# Phase Y research plan: the content-validation bottleneck

Phase X removed the duplicate validation pass; Phase X1 proved that removal sound and measured what
is left. This is a *plan*, not an implementation. No Phase Y production change is contained here,
and none is allowed until Phase X is merged and post-merge `main` CI is verified.

## 1. What is left to attack

One warm HIT of the compiler workload, measured on this host with `TRACEJIT_GUARD_PROFILE=1`
(profiler on, so ~3.7 % pessimistic):

| Component | Time | Share of the hit |
| --- | --- | --- |
| content hashing (57 guards, 107,160,458 bytes, 1737 `read`s) | 48.343 ms | ~61 % |
| other validation work (interpretation, environment, preconditions) | 3.1 ms | ~4 % |
| metadata (`stat` 0.599, `open` 0.374, `readlink` 0.115, access 0.099) | 1.19 ms | ~1.5 % |
| SQLite query + record decode | 6.38 ms | ~8 % |
| output restore (stage, verify, rename) | 2.95 ms | ~4 % |
| identity, CLI, process startup, presentation | ~5.5 ms | ~7 % |
| process exec, dynamic loading, harness wrapper | ~10 ms | ~13 % |
| **total warm hit (paired A/B median, profiler off)** | **79.2 ms** | |

The multiplicity is the interesting part: 107.2 MB is hashed for 43.4 MB of distinct content
because `cc1` appears three times (`ExecutableHash` + two `ControlledRuntime` observations),
`gcc-13` three times, `as` twice. Phase X rejected sharing one digest per path *within* a pass
because a same-size rewrite inside one timestamp tick leaves `mtime`, `ctime` and `size` identical —
that counterexample is a permanent regression, and any Phase Y design has to answer it directly.

## 2. Mechanism research

### A. Kernel-enforced immutability

| Mechanism | What it proves | What it does not | Availability |
| --- | --- | --- | --- |
| **fs-verity** | The file's Merkle root (`FS_IOC_MEASURE_VERITY`) and every read is verified by the kernel; the file becomes read-only when verity is enabled; a mismatch fails with `EIO`/`SIGBUS` | Not that the digest is the *expected* one — that needs a pinned value or a signature (`fs.verity.require_signatures`, `.fs-verity` keyring). A privileged writer cannot modify bytes without breaking reads, but it can *disable* verity only by rewriting inodes on a filesystem where it has raw access | Kernel ≥ 5.4 with `CONFIG_FS_VERITY`; ext4 (verity feature), f2fs, btrfs ≥ 5.15. **XFS is not supported** (patches still in flight); enabling on ext4 requires `tune2fs -O verity` on an unmounted filesystem, and enabling per file requires no writer open (`ETXTBSY`) |
| **`FS_IMMUTABLE_FL`** | Writes, truncate, rename, unlink, link and metadata changes are refused, even against most writers | Any process with `CAP_LINUX_IMMUTABLE` can clear the flag and rewrite the file; it is not a content identity, only a stability promise | Universal on ext4/xfs/btrfs, but setting it on system binaries is a root action |
| **Read-only mount / ro bind mount** | Writes to the mount are refused | Requires privileges; root can remount; per-mount, not per-file | Universal |
| **File seals (`memfd`)** | `F_SEAL_WRITE`/`F_SEAL_FUTURE_WRITE` make the mapping immutable | Only for `memfd`, not for files on disk, so not applicable to `/usr/bin/cc1` | memfd only |
| **Content-addressed installs (Nix store, ostree, verity container images)** | The path *is* the digest, and the store is read-only | Depends on the user's installation method; not the default on Ubuntu/Fedora developer machines | Nix, ostree, containerd verity |

Threat model each mechanism *does* address, for TraceJIT: an unrelated process (build system,
editor, another user's job) rewriting a compiler binary between two compiles, or an attacker who can
write to the file but not to the kernel or the filesystem's metadata. What none of them addresses:
an attacker who can rewrite the file *and* the expectation TraceJIT holds about it (that is a
different trust root — signatures), or a filesystem-level rollback to an older but internally
consistent state.

### B. Validated immutable-object registry

The shape that can be justified: per identity `(device, inode, size, mtime, ctime, nlink,
mount_id)`, store `(fsverity_digest, full_blake3)`. On a HIT, re-read the *witness* (the same
`statx` fields plus `FS_IOC_MEASURE_VERITY`) and reuse the stored full digest only if the witness is
identical **and** the file is verity-enabled **and** the measure ioctl returns the stored root.
That last clause is what the Phase X counterexample lacked: a same-tick rewrite cannot change the
Merkle root without breaking verity, and if verity is disabled the ioctl fails and the registry
falls back to full hashing. Replacement detection is the inode witness plus the verity root;
explicit invalidation is the digest mismatch. A pathname plus timestamp is never sufficient, and a
registry entry whose file is not verity-enabled is never used.

Cost: one `statx` (~2 µs) plus one ioctl (~5–20 µs) per content guard instead of reading 1.9–32 MB.
Expected saving on the compiler workload: up to 48 ms of the 79 ms hit, i.e. a further ~2.5× on top
of Phase X, bounded below by §5.

The registry's real constraint is **admission**: TraceJIT cannot enable fs-verity on
`/usr/lib/gcc/.../cc1` or `/usr/bin/gcc-13` on a developer machine. It can only *observe* that a
file is verity-enabled (upstream distribution images, verity-protected container layers, Nix-style
stores with enforced read-only mounts). So the mechanism is a fast path for environments that
already provide the invariant, not a universal replacement for hashing.

### C. Trust boundaries (kept as separate contracts)

| Tier | What is verified per HIT | Contract name | Honest claim |
| --- | --- | --- | --- |
| 1. Strict | full content hash of every content dependency | `tracejit.strict-hash.v1` (today) | native-equivalent |
| 2. Kernel-immutable | witness + `FS_IOC_MEASURE_VERITY` against a pinned digest | `tracejit.verity-immutable.v1` (proposed) | native-equivalent **given** the kernel's verity guarantee and a trusted pin |
| 3. User-declared immutable | nothing per HIT; the user asserts the path cannot change | `tracejit.declared-immutable.v1` (proposed) | reproducible under an explicit user contract; **weaker** |
| 4. Metadata only | `statx` witness only | never shipped as a reuse contract | refused |

Tier 3 must never be reported as Strict, must be opt-in per path, and must appear in `reasons` and
in the JSON `contract` field. Tier 4 is listed here only to be excluded: it is the Phase X
counterexample.

### D. Alternative workload architecture

Whole-command memoization pays the full hash cost per command. Pipelines and deterministic batch jobs
do not necessarily: a pipeline stage that consumes an output produced moments earlier could be
validated against the producing record instead of re-hashing the bytes, if the producer and consumer
share a session. That is a real architectural change (session identity, cross-invocation
bookkeeping) and its saving is workload-dependent; it is ranked below the immutability work because
the compiler workload — the one with the largest measured win — is a sequence of independent
`cc` invocations.

### E. Lower bound

Fundamental to the current contract, measured here: process exec + dynamic loading ≈ 8–12 ms
(visible in the `true` workload: 11.1 ms for a command that does nothing), SQLite lookup + decode
≈ 6.4 ms (could be reduced, not eliminated), restore of the recorded outputs ≈ 3.0 ms, stdio replay
≈ 0.03 ms. Implementation artifacts: 48.3 ms of hashing (avoidable *only* with an invariant), 1.2 ms
of metadata, ~3.1 ms of interpreter overhead.

So a hit with a fully trusted content identity lands near **25–30 ms** on this host — roughly 2.6×
faster than the Phase X candidate and 4.5× faster than the two-pass baseline — and the remaining
floor is dominated by process startup and SQLite. No design in this plan can go below that without
changing the process model (daemon, shared memory), which is out of scope and out of contract.

## 3. Ranked hypotheses

| # | Hypothesis | Expected gain (compiler hit) | Correctness risk | Kernel/OS availability | Implementation cost | Testability |
| --- | --- | --- | --- | --- | --- | --- |
| **H1** | fs-verity fast path for content guards: witness + measure ioctl against a pinned digest; full hash elsewhere | up to −48 ms (−60 %) | **Medium**: requires a trusted pin and a correct "verity still enabled" check; a bug that trusts a stale pin is a false HIT | ext4 (feature flag), f2fs, btrfs ≥ 5.15; **not XFS**; `CONFIG_FS_VERITY`; observation only, enabling needs root | Medium-high (new capability probe, guard variant, pinned-digest storage, fallback) | High: can build verity fixtures on ext4 in a loop-mounted image; adversarial suite already exists for content guards |
| **H2** | Intra-pass digest dedup **only for files proven kernel-immutable** (combines with H1 to cut 107.2 MB → 43.4 MB) | −5 to −8 ms beyond H1 | Low **given** H1's invariant; the Phase X counterexample is exactly what this cannot do without it | as H1 | Low (a per-pass map keyed by verity digest) | High: the existing counterexample test becomes the negative control |
| **H3** | Explicit user-declared immutable inputs (`TRACEJIT_ASSUME_IMMUTABLE`), separate contract, opt-in | −48 ms when declared | Medium-high but **explicit**: the user owns the invariant | universal | Low-medium (contract plumbing, reporting, docs) | High: refusal paths and reporting are mechanical; no kernel dependency |
| **H4** | Session-aware pipeline validation (validate a consumer against its producer's record) | workload-dependent, possibly −30 ms for pipelines | High (new cross-invocation state machine) | universal | High | Hard: needs a new model-check target and session-level fuzzing |
| **H5** | Reduce the residual non-hash costs (SQLite `prepare_cached` already used; investigate record decode 3.5 ms) | −3 to −5 ms | Low | universal | Low | High |

Recommended order: **H5 (cheap, safe, do first) → H1 (the real prize, capability-gated) → H2 (rides
on H1) → H3 (only if users ask for an explicit weaker contract) → H4 (research only)**.

Each of H1–H3 must ship with: a capability probe reported by `tracejit doctor`; a named contract in
`RunReport.contract`; a refusal test for every precondition (not verity-enabled, digest mismatch,
pin missing, filesystem unsupported); a permanent regression for the Phase X same-tick
counterexample; and a benchmark that reports the profiler's overhead.

## 4. Entry criteria for Phase Y implementation

1. PR #41 merged and post-merge `main` CI green on the exact merge commit.
2. `docs/PHASE_X1_AUDIT.md` assumptions A1–A7 still hold after any new guard kind is added.
3. A verity-enabled fixture filesystem exists in CI (loop-mounted ext4 image) so H1's fast path and
   its refusal paths are both exercised, not simulated.
4. The benchmark harness reports profiler-on and profiler-off numbers for every claim.

## 5. Explicit non-goals

* No timestamp-only or size-only reuse of a previous digest, in any contract, ever.
* No shared digest within a pass for a file that is not kernel-immutable.
* No automatic enabling of fs-verity on system paths, and no elevation to do it.
* No daemon or long-lived process model in this phase.
* No change to the stored record format until a fast path is proven to pay for the version bump.

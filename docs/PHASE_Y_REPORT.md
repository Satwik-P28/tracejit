# Phase Y report: kernel-verified content identity and the hashing bottleneck

The question this phase had to answer: **can a warm hit stop reading 105 MB of compiler binaries on
the strength of something cheaper than a full content hash, without weakening
`tracejit.strict-hash.v1`?**

The answer, with the evidence below, is a qualified **no — not promotable today**, for two
independent reasons:

1. **The mechanism is sound but the environment is absent.** fs-verity is the only Linux mechanism
   that is a per-file, constant-time, unprivileged-to-observe *content identity*. On this host —
   and on a stock ext4 developer machine — it does not exist: the kernel is built without
   `CONFIG_FS_VERITY` and the root filesystem was not created with the `verity` feature.
2. **The workload that would benefit can no longer be re-measured here.** The sandbox image moved
   from the audited glibc `2.39-0ubuntu8.9` to `2.39-0ubuntu8.12`, so the `allocator-entropy-v1`
   admission correctly refuses the compiler's allocator probe and the compiler workload is
   `NONDETERMINISTIC` on this host. All 48 invocations of the compiler session missed.

So this phase delivers a proven design, a real refusal-path implementation, a reproducible
capability probe, an adversarial suite, a quantified cost ledger — and **no production
optimization**. Nothing was merged into `main`, and no release was published.

## 1. Commits

| | |
| --- | --- |
| Starting `main` | `6bab00bff96f6b461b65874ba3152178f8fea79a` (merge of PR #41) |
| Post-merge `main` CI | run **#263**, `success`, on `6bab00b` (verified before any work) |
| Research branch | `research/phase-y`, created at `6bab00b` |
| Branch CI | run **#264** on `da48bae`: **success**, 14/14 steps (formatting, clippy, tests, release build, version consistency, doctor, Linux integration, real-world census, demo) |
| Production-behaviour diff | one new guard variant + one new `doctor` line, both inert without fs-verity |
| Merged into `main` | **nothing**; promotion gate failed (see §9) |
| Release | none; v0.3 not published |

## 2. What the hashing cost actually is, per file

Phase X1's profile gave the aggregate: 57 content guards, 107,160,458 bytes, 48.343 ms of a 79.246 ms
warm hit. Phase Y needed the per-file ledger, so `benchmarks/phase_y/attribution.py` reads a real
recorded execution (`tracejit explain --json`), collects **every guard kind whose validation reads a
file and compares a digest** — `FileHash`, `ExecutableHash`, `ControlledRuntime` (hashes the runtime
binary), `ControlledEntropy` (hashes the issuing library), `VerityContentIdentity` — and joins it
with `stat`.

One `cc -O2 -c unit.c` execution, this host, 2026-11-23:

| File | Observations | Bytes each | Bytes total | Share of content bytes |
| --- | --- | --- | --- | --- |
| `/usr/libexec/gcc/x86_64-linux-gnu/13/cc1` | **3** | 30,487,984 | 91,463,952 | **87.1 %** |
| `/usr/bin/x86_64-linux-gnu-gcc-13` | **3** | 1,023,032 | 3,069,096 | 2.9 % |
| `/lib/x86_64-linux-gnu/libc.so.6` | 1 | 2,129,424 | 2,129,424 | 2.0 % |
| `/lib/x86_64-linux-gnu/libisl.so.23` | 1 | 1,863,352 | 1,863,352 | 1.8 % |
| `/usr/bin/x86_64-linux-gnu-as` | **2** | 745,768 | 1,491,536 | 1.4 % |
| `/lib/x86_64-linux-gnu/libbfd-2.42-system.so` | 1 | 1,479,888 | 1,479,888 | 1.4 % |
| … 50 more (headers, `libm`, `libmpfr`, `libzstd`, `unit.c`, …) | | | ≈ 3.5 MB | 3.4 % |
| **total** | **56 guards** | | **105,031,035** | |

| Property | Value |
| --- | --- |
| Content guards | 56 (Phase X1 measured 57 on an equal workload; the record differs by one header) |
| Bytes hashed | 105,031,035 (Phase X1: 107,160,458) |
| Distinct bytes **by path** | 41,263,235 |
| Distinct bytes **by inode** | 41,263,235 — every repeated path is the same inode, so this is not aliasing |
| **Redundancy factor** | **2.545×** |
| Derived content cost at the profiled 2.217 GB/s | **47.4 ms** (Phase X1 measured 48.343 ms of content time) |

**The finding that shapes the rest of the phase.** The redundancy is real but it is *one file*:
`cc1` is hashed three times per pass — once as the child executable, twice as the `ControlledRuntime`
subject of two runtime observations — and those three reads are 87 % of all content bytes. Hashing
`cc1` once instead of three times would cut content bytes by 2.545× on its own. That is exactly the
operation Phase X rejected, because a same-size rewrite inside one timestamp tick preserves `mtime`,
`ctime` and `size`; a digest computed at `t_a` cannot answer a guard at `t_b > t_a`. Phase Y
re-derived that counterexample's status rather than assuming it (§7).

## 3. Verified host capability

Reproducible: `python3 scripts/phase_y_verity_probe.py --json-out benchmarks/results/phase_y/verity-probe.json`.
Full matrix and primary sources: [`docs/VERITY_CAPABILITY_MATRIX.md`](VERITY_CAPABILITY_MATRIX.md).

| Fact | Value |
| --- | --- |
| Kernel / distro | `6.1.102`, Ubuntu 24.04.5, x86_64 |
| `CONFIG_FS_VERITY` | **not set** (`/boot/config-6.1.102`) |
| Root filesystem | ext4, `rw,relatime`, `/dev/vda` |
| `FS_IOC_MEASURE_VERITY` (exact `_IOWR('f',134,4)`) | `EOPNOTSUPP` (95) |
| `FS_IOC_ENABLE_VERITY` (exact 128-byte arg) | `EOPNOTSUPP` (95) |
| `FS_IOC_MEASURE_VERITY` with a wrong `_IOC_SIZE` | `ENOTTY` (25) — same kernel, same file |
| Capabilities | `CapEff: 0`, `NoNewPrivs: 1`, no `sudo` |
| User namespaces | permitted; but ext4 is not `FS_USERNS_MOUNT`, so no loop-mounted verity image |
| `/dev/kvm` | present, group-restricted, unusable by this user |
| qemu / firecracker | absent; no apt package lists; installing needs root |

### Whether fs-verity was actually supported and tested

**Supported: no. Tested against a real kernel: yes, the refusal path; the admission path only
against an injected measurement.** Concretely:

* Every failure mode the design depends on *was* exercised on the real kernel: `measure()` on a
  normal file returns `Unavailable`, a verity guard falls back to the full hash, and the fallback
  still refuses changed content (`a_verity_guard_without_kernel_support_hashes_the_file`,
  `a_verity_pair_falls_back_together`, `an_executable_verity_guard_still_checks_permissions`).
* The admission path — measurement equals pin ⇒ `Proven` without reading — is exercised by the pure
  decision function over the whole input space, not by a kernel.
* No verity *speedup* is claimed anywhere in this report, because none was measured.

**Erratum found by the probe.** The documentation says an unconfigured kernel returns `EOPNOTSUPP`
and a non-implementing filesystem returns `ENOTTY`. On this host the correctly-numbered ioctl reaches
ext4's `fsverity_ioctl_measure()` stub and returns `EOPNOTSUPP`, while the *same* request with a
wrong `_IOC_SIZE` misses the compiled-in case and returns `ENOTTY`. A classifier keyed on one errno
would misread a missing kernel feature as an I/O error. `is_unavailable_errno` therefore accepts
`ENODATA`, `ENOTTY`, `EOPNOTSUPP`, `ENOPKG` and `EINVAL`, and only `Proven` ever skips the hash.

### The reproduced baseline, and why it is not a warm-hit baseline

Phase X1's compiler warm-hit baseline **could not be reproduced**. The image's glibc moved from the
audited `2.39-0ubuntu8.9` (build id `a4a7992a…ea65`) to `2.39-0ubuntu8.12` (build id
`8cebda42d140fc2b09639f8b13a5d5f2e617ef09`). The `allocator-entropy-v1` admission is a build-id
profile match, so the compiler's allocator `getrandom` is no longer absorbed, the execution is
classified `NONDETERMINISTIC`, and reuse is refused:

```text
cache          MISS
classified     NONDETERMINISTIC
reuse disabled: process read randomness via getrandom
```

That is the product behaving correctly, and it is independent evidence for mechanism (a) of the
Phase X1 §8 CI question: the pinned glibc profile *does* go stale in practice, and when it does, the
compiler workload cannot reuse at all. It is not the same failure as CI run #259 (an integration
test on an audited runner), so §8 of the Phase X1 audit stays open — but the drift is now observed
rather than hypothesised.

Consequence: content-cost attribution (§2) uses the **recorded guard list**, which is written
regardless of classification, and end-to-end reuse timing (§6) uses workloads that still reuse.

**The drift is not local.** CI run #264's own annotation reports
`ldd (Ubuntu GLIBC 2.39-0ubuntu8.12) 2.39 build_id=8cebda42d140fc2b09639f8b13a5d5f2e617ef09` — the
same build as this sandbox — and the run still passed, because Phase X1 made the two contract tests
assert the documented refusal on an unaudited runtime instead of asserting a HIT. That fix is the
only reason the `Tests` step is green on today's runner; without it, run #264 would have failed like
#254. The cost is coverage: **no current CI runner exercises the `allocator-entropy-v1` compiler
reuse path at all**, so that contract's happy path is now tested nowhere. Phase X1 §8's mechanism
(a) is therefore confirmed and universal, while its open question (#259's unnamed integration
failure on an *audited* runner) remains open for the same reason as before.

## 4. Design: `VerityContentIdentity`, and the correctness argument

`crates/tracejit-guards/src/verity.rs`, plus `Guard::VerityContentIdentity { path, expected, verity,
executable }`.

### 4.1 What is pinned

At record time the guard carries **both** digests for the same bytes:

| Field | Meaning |
| --- | --- |
| `expected: Hash` | BLAKE3 of the file, exactly as `FileHash` records today |
| `verity: VerityPin { algorithm, digest }` | the fs-verity **file digest the kernel reported**, opaque bytes |

TraceJIT never computes an fs-verity digest. It only stores what `FS_IOC_MEASURE_VERITY` returned
and later compares the kernel's answer with it. There is no second implementation of the Merkle
layout, no assumption about salt/block size/algorithm numbering, and a future algorithm is compared
as opaque bytes instead of failing to parse.

### 4.2 The pin is taken before the read, deliberately

`pin_before_read` measures, then the caller hashes. Ordering matters:

* Measure succeeds ⇒ verity was already enabled ⇒ every subsequent `read` is verified by the kernel
  against the Merkle tree that the digest describes ⇒ the BLAKE3 we record is the digest *of the
  content whose Merkle root we pinned* ⇒ content can no longer change in place.
* Measuring *after* the read would leave a window: the content could be replaced and verity enabled
  over the replacement, leaving a pin for the new bytes next to a hash of the old ones. That window
  would be a genuine false-HIT generator, so the ordering is part of the contract, not an
  implementation detail.

### 4.3 The admission rule

`decide(pin, outcome)` is pure and total:

| Measurement | Verdict | Effect on the hit |
| --- | --- | --- |
| same algorithm, same length, **equal bytes** | `Proven` | content identity holds; the file is not read |
| same algorithm, same length, different bytes | `Contradicted` | **guard fails, no read** |
| different algorithm or length | `FallBackToHash` | digests are incomparable; nothing proven |
| `ENODATA`, `ENOTTY`, `EOPNOTSUPP`, `ENOPKG`, `EINVAL` | `FallBackToHash` | no kernel answer exists |
| any other ioctl failure / malformed answer | `FallBackToHash` | an unexpected failure is never agreement |

`FallBackToHash` means *the existing Strict behaviour*: read the file, compare BLAKE3. The guard is
an accelerator for a predicate that is still fully checked wherever the kernel cannot speak. It is
never a metadata-only acceptance — that is the one thing the design forbids, and it is pinned by
`a_verity_guard_without_kernel_support_hashes_the_file` (identical metadata, changed content,
fabricated pin ⇒ refusal).

### 4.4 Formal argument

Let `C` be the traced content of a dependency, `b = BLAKE3(C)`, `v = fsverity_digest(C)`, and let a
record carry the pair `(b, v)` produced under §4.2's ordering. At validation time, on an opened
descriptor `fd` for the live file `C'`, `M(fd)` is the kernel's measurement.

**Assumptions.**

* **V1 (trace-time binding).** `(b, v)` describe the same bytes: the measurement preceded the read,
  and verity was already enabled, so the read was kernel-verified against `v`.
* **V2 (kernel contract).** When `FS_IOC_MEASURE_VERITY` returns digest `d` for an inode, every read
  of that inode is verified against the Merkle tree whose descriptor hashes to `d`, and a mismatch
  fails the read (`EIO`/`SIGBUS`). This is the documented fs-verity guarantee; it is the one thing
  this phase could not test on real hardware.
* **V3 (collision resistance).** The fs-verity digest construction (hash of a descriptor containing
  the Merkle root, data size, algorithm, log₂ block size, salt) is collision-resistant: two different
  contents producing the same `(algorithm, digest)` is infeasible.
* **V4 (constant-time independence).** `M` does not read the data, so it cannot itself be influenced
  by the data it is meant to describe.

**Claim.** If `M(fd) = v` with the same algorithm, then `C' = C`.

*Proof.* By V2 and V4, `M(fd)` is the fs-verity digest the kernel is enforcing for `fd`'s inode. It
equals `v`. By V1, `v` is the digest of `C`. So `C` and `C'` have the same digest, and by V3 they are
the same content. ∎

**Claim (composition).** A hit accepted with a `Proven` verity guard is observationally equivalent to
a native execution.

*Proof.* `C' = C` for every verity-proven dependency. Every other guard is unchanged and is still
evaluated against live state (Phase X1 A1–A7 untouched). The metadata half of the pair is still
compared. The restore is a function of the recorded outputs. Hence Phase X1's theorem applies
verbatim. ∎

**What `Contradicted` is allowed to do, and why.** A different digest with the same algorithm and
length means `C' ≠ C` by V3, so the guard may refuse without reading the file. This is the only place
where a measurement shortens the work by *rejecting*; it cannot produce a false HIT.

**What this does not prove.** It does not prove that verity is *enabled* — only the measurement
result does. A file that lost verity (restored from a backup, copied) fails `M` and takes the hash
path. It does not prove the *path* still names the measured inode after validation: pathname
replacement inside the restore window stays the documented V1 limitation. It does not make the
digest an authentication statement: the pin is TraceJIT's own, so no signature, keyring or
`fs-verity.require_signatures` is needed — and equally, a hostile party who can rewrite *both* the
file and TraceJIT's cache is out of scope, exactly as with a BLAKE3 pin today.

## 5. Adversarial falsification

`crates/tracejit-guards/src/phase_y_tests.rs` (12 tests). "Real" = exercised against this kernel;
"pure" = exercised against the decision function with injected measurements.

| Attack | Mechanism | Result |
| --- | --- | --- |
| Same-size same-timestamp modification | pin mismatch, same algorithm | `Contradicted` ⇒ refuse without reading (pure) |
| One-bit flip in a pinned digest | identical | `Contradicted` (pure) |
| Atomic pathname replacement | replacement inode has no verity | `ENODATA` ⇒ `FallBackToHash` ⇒ BLAKE3 decides (real fallback + pure) |
| Hardlink aliasing | same inode ⇒ same digest | no new acceptance surface; the metadata half still compares link count and `ctime` (design) |
| Symlink swap | symlink resolution happens at `open`, before `measure` | unchanged from today: the hash guard also resolves the path |
| File deletion and recreation | no verity on the new inode | `ENODATA` ⇒ fallback ⇒ BLAKE3 decides (pure) |
| Different files with the same size | digest differs | `Contradicted` (pure) |
| Cross-filesystem replacement | destination fs has no verity | `EOPNOTSUPP`/`ENOTTY` ⇒ fallback (pure) |
| Mount namespace change | path resolution differs before `open` | guarded by the existing namespace guards; unchanged |
| Permission change only | metadata half of the pair | still compared; executable bit still checked (`an_executable_verity_guard_still_checks_permissions`, real) |
| Missing verity measurement | `ENODATA` | fallback, never acceptance (real on this host) |
| Unsupported digest algorithm | algorithm mismatch | fallback, never acceptance (pure) |
| Future/unknown algorithm number | opaque byte comparison | equal ⇒ proven, different ⇒ contradicted (pure) |
| Corrupted cache record | malformed hex digest | record rejected at decode, candidate skipped (`a_malformed_digest_field_is_rejected`) |
| Stale cache candidate | pin belongs to older content | `Contradicted` (pure) |
| Concurrent mutation | verity blocks in-place writes; path replacement is the V1 window | documented, unchanged |
| Executable substitution | replacement lacks the pin | fallback ⇒ BLAKE3 + executable check (real) |
| File-descriptor reuse | measurement is on the descriptor the pair already opened and `fstat`s | same-descriptor semantics preserved |
| Cache restart | pins live in the record, not in memory | `a_verity_record_round_trips_its_digest` |
| Crash recovery | restore-intent machinery untouched | `phase_k4_*` PASS |
| Phase W1 rename-source counterexample | unaffected guards | `rename_source_bytes_are_an_input_even_when_the_source_is_recreated` PASS |
| Phase X same-timestamp digest sharing | **not reintroduced** | `phase_x_tests` PASS |

No incorrect HIT was produced. Differential fuzz (seed 29, 120 cases) against native output:
`incorrect_hits = 0`.

## 6. Benchmark

Four arms were required. On this host two of them do not exist:

| Arm | Status |
| --- | --- |
| **A. Strict full hashing** | measured |
| **B. Verity-backed validation** | **not measurable** — no fs-verity on this host (kernel or superblock) |
| **C. Verity + intra-pass sharing** | **not measurable**, and see §7: subsumed by B |
| **D. Unsupported-verification fallback** | measured, and identical to A by construction and by test |

### 6.1 No-regression (A vs D), paired and interleaved

`benchmarks/phase_x/workloads.py`, 20 rounds, `main` @ `6bab00b` (`/tmp/tj-main`, built from a clean
worktree) versus this branch. Both arms report `hit` in every measured round.

| Workload | baseline (main) | phase-y | ratio |
| --- | --- | --- | --- |
| `etl` | 10.893 ms | 11.040 ms | 0.987× |
| `true` | 8.430 ms | 8.463 ms | 0.996× |

The branch is performance-neutral: the guard variant is never constructed, so the hit path is the
same instruction stream. The 1.3 % / 0.4 % spread is the harness's run-to-run noise (the same
workloads moved in the opposite direction between Phase X1 arms).

### 6.2 Cost of the mechanism, measured where it can be

| Quantity | Value | How |
| --- | --- | --- |
| One failing `measure()` in Rust | **493 ns** | `measure_call_cost`, 100 000 iterations, release |
| Fallback overhead if a recorded pin stops being measurable | 493 ns × 56 guards ≈ **27.6 µs** per hit | derived |
| BLAKE3 throughput implied by the Phase X1 profile | 2.217 GB/s | 107,160,458 B / 48.343 ms |
| Content validation on this record | 105,031,035 B ⇒ **47.4 ms** derived, 48.343 ms measured by Phase X1 | §2 |

The 493 ns is the honest cost of *not* having the feature: even if every content guard carried a
dead pin, the hit would pay 28 µs to discover it. That is why the fallback is a viable design rather
than a hazard — but it is also why the fallback is not a strategy: it pays 28 µs to reach the same
47 ms of hashing.

### 6.3 The ceiling, derived and labelled as derived

Phase X1 measured a 79.246 ms compiler warm hit with 48.343 ms of content time. Replace the content
time with 56 measurements (56 × 493 ns ≈ 28 µs) and the hit lands at **≈ 31.9 ms**, i.e. **2.49×**
faster than Phase X1's single-pass candidate and **3.97×** faster than the two-pass baseline.

This is arithmetic on two measured components, **not a measurement of arm B**, and it is valid only
while all of the following hold: fs-verity is present; every one of the 56 files is verity-enabled;
the compiler workload can reuse at all (it cannot, today, for an unrelated reason); and the numbers
are internally consistent — the 79.246 ms hit and this host's 105 MB record come from different
images of the same machine class. It is a bound on the prize, not a result.

### 6.4 End-to-end sessions

48 invocations, 3 units, edits at rounds 7 and 12 (`benchmarks/phase_w/session.py`):

| Arm | Total | Outputs match native | Cache decisions |
| --- | --- | --- | --- |
| native `cc` | 24.373 s | — | — |
| `main` @ `6bab00b` | 33.479 s | true | 48 miss |
| `research/phase-y` | 33.824 s | true | 48 miss |

**Zero hits on both TraceJIT arms**, because of the glibc build-id drift in §3. The session therefore
measures trace overhead (≈ 9 s over 48 invocations) and proves output fidelity, and it says nothing
about reuse latency. The 1.0 % difference between the arms is noise. Phase X1's 27-invocation
(8.398 → 6.660 s) and 48-invocation (12.442 → 10.595 s) comparisons remain the last valid
measurements of this workload and could not be reproduced or extended here.

### 6.5 Bytes and operations saved — measured versus hypothetical

| | Strict today | With verity (hypothetical) |
| --- | --- | --- |
| Bytes read + hashed per hit | 105,031,035 | 0 |
| `read` syscalls (64 KiB buffer) | ≈ 1 600 | 0 |
| `open` for content | 56 | 56 (measurement needs the descriptor) |
| `FS_IOC_MEASURE_VERITY` calls | 0 | 56 |
| Content-validation time | 47.4–48.3 ms | unmeasured; 28 µs of ioctl at this host's observed failure cost |

## 7. Hypothesis ledger

Full table with reasoning: `docs/PHASE_Y_LEDGER.md`. Summary:

| # | Hypothesis | Verdict |
| --- | --- | --- |
| H1 | fs-verity fast path for content guards | **Design accepted, promotion rejected** — sound on paper, unusable here, unmeasurable |
| H2 | Intra-pass digest dedup for verity files | **Rejected as valueless** — subsumed by H1: once hashing is gone, dedup saves repeated *ioctls* (µs), not megabytes |
| H2′ | Intra-pass dedup *without* verity | **Rejected as unsound** — Phase X's same-tick counterexample still applies, and it is 87 % of the bytes, so it is the tempting one |
| H3 | User-declared immutable inputs | **Not implemented** — a weaker contract with no proof; must never be reported as Strict |
| H4 | Session-aware pipeline validation | **Not attempted** — new cross-invocation state machine, out of phase |
| H5 | Residual non-hash costs | **Deferred** — nothing in Phase Y changed them |

## 8. Verification run on this host

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace --no-fail-fast` | **253 passed, 0 failed**, 1 ignored (manual measurement) |
| `linux_integration`, `--test-threads=1` | 75/75 |
| `linux_integration`, `--test-threads=2 / 4 / 8` | 75/75 each |
| `cargo build --workspace --release` | pass |
| `cargo audit` | clean, 110 dependencies |
| State-machine model check | PASS (`reuse_hit` 0 violations, `restore_crash` 0, `restore_intent` 0) |
| Restore fault injection | soft-fail retrace PASS, hard-kill recovery PASS |
| Differential fuzz, seed 29 | 120/120 ok, **0 incorrect hits** |
| Phase W1 rename-source regression | pass (in the 75) |
| Phase X same-timestamp regression | pass (in the 53 guard tests) |
| Malformed record / corrupt CAS | pass |
| Capability probe | ran; `fs_verity_supported_here: false` |
| Real-world compatibility census | ran in CI on this head (`census.py --runs 3 --warmups 1`, step success); not re-run locally, and unchanged by this phase |

Skipped or unsupported: arm B/C latency (no fs-verity), the compiler warm-hit baseline (glibc
drift), and any kernel-level assertion about verity enforcement (no verity-capable kernel reachable).

## 9. Promotion gate

| # | Requirement | Verdict |
| --- | --- | --- |
| 1 | Kernel guarantees precisely documented | **pass** — matrix with primary sources, including the errno erratum |
| 2 | Cannot introduce an incorrect HIT within its contract | **pass by argument** (§4.4), *not* by kernel test |
| 3 | Passes independent adversarial verification | **partial** — refusal paths on the real kernel, admission paths by injection |
| 4 | Produces a meaningful end-to-end performance improvement | **fail** — unmeasurable here; derived bound only |
| 5 | Applicability measured on realistic workloads | **fail** — applicability is 0 on this host and on stock ext4 developer machines |
| 6 | Unsupported environments keep safe behaviour | **pass** — measured: identical behaviour, no-regression 0.987×/0.996× |
| 7 | No unacceptable system modifications | **pass** — observation only, no elevation, no file changes |
| 8 | Maintainable and understandable | **pass** — one pure decision function, 12 tests, one capability line in `doctor` |

**Verdict: not promotable.** Requirements 4 and 5 cannot be satisfied on any machine reachable from
this phase. Requirements 1, 2, 6, 7, 8 are satisfied; 3 is satisfied for everything the host could
exercise.

## 10. What would change the verdict

1. A CI runner with a verity-formatted ext4 image (created with `mke2fs -O verity`, mounted from a
   loop device) and a `CONFIG_FS_VERITY=y` kernel. That makes arm B measurable end-to-end and turns
   gate 3 from "by injection" into "by kernel". `sites_prepare_next`-style plumbing is irrelevant
   here: this is a CI-image change, not a code change.
2. A workload whose dependencies are actually verity-enabled. Compiler binaries are not, on any
   mainstream distribution; distribution images built with ostree or with `mkosi`'s verity support
   are the realistic candidates, and adopting one is a user decision, not a TraceJIT one.
3. Or: a *different* mechanism that answers content identity for ordinary writable files. Nothing in
   the capability matrix does. That is the honest state of the art.

## 11. Deliverables

| Path | What |
| --- | --- |
| `docs/PHASE_Y_REPORT.md` | this report |
| `docs/VERITY_CAPABILITY_MATRIX.md` | 10-mechanism matrix, primary sources, measured host capability |
| `docs/PHASE_Y_LEDGER.md` | accepted/rejected hypothesis ledger with reasons |
| `scripts/phase_y_verity_probe.py` | reproducible capability probe (disposable files only) |
| `benchmarks/results/phase_y/verity-probe.json` | raw probe output for this host |
| `benchmarks/phase_y/attribution.py` | per-file content-cost harness |
| `benchmarks/results/phase_y/attribution.json` | raw per-guard, per-path, per-inode ledger |
| `benchmarks/results/phase_y/workloads.json` | no-regression A/D measurement |
| `benchmarks/results/phase_y/session-48.json` | 48-invocation session (0 hits, documented) |
| `benchmarks/results/phase_y/fuzz-29/` | differential fuzz output |
| `crates/tracejit-guards/src/verity.rs` | measurement, pure decision, capability probe |
| `crates/tracejit-guards/src/phase_y_tests.rs` | 12 adversarial regressions + 1 manual measurement |
| `crates/tracejit-guards/src/lib.rs` | `Guard::VerityContentIdentity` and its validation |
| `crates/tracejit-core/src/lib.rs`, `crates/tracejit-cli/src/main.rs` | `doctor` capability line |

## 12. Limitations

1. **No verity-capable kernel was reachable**, so V2 (the kernel's enforcement guarantee) is taken
   from the documentation, not verified here. Every claim that depends on it is marked as such.
2. **The compiler warm-hit baseline could not be reproduced** on this image because the audited
   glibc profile went stale; the 79.246 ms and 48.343 ms figures are Phase X1's, and the 47.4 ms is
   this phase's derived equivalent.
3. **Record-time admission is not wired into the tracer.** `pin_before_read` exists and is tested,
   but no call site in `crates/tracejit-trace` uses it, because there is no host on which the
   resulting pins could be validated. Wiring it is one call per `hash_file` site in
   `InputDependency::{File,Executable}` construction; doing it blind would ship untested kernel-facing
   behaviour.
4. **`cc1` is hashed three times and that remains the single largest cost.** Phase Y did not fix it,
   because the only sound fix is the invariant this host lacks.
5. **The probe cannot distinguish "kernel not configured" from "superblock lacks the feature"** on a
   host where `CONFIG_FS_VERITY=n`, since both surface as `EOPNOTSUPP`; the report says which is
   known (`/boot/config`) and which is inferred.

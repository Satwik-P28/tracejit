# Phase Y hypothesis ledger

Every hypothesis this phase considered, what it would buy, and why it was accepted or rejected.
"Rejected" is a result: the next phase should not re-open an item marked *settled* without new
evidence.

Costs are per compiler warm hit, from §2 of [`docs/PHASE_Y_REPORT.md`](PHASE_Y_REPORT.md):
105,031,035 content bytes over 56 guards, 2.545× redundant, ≈ 47.4 ms of hashing.

| # | Hypothesis | Gain | Correctness | Availability | Cost | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **H1** | **fs-verity fast path**: pin the kernel's `FS_IOC_MEASURE_VERITY` digest at trace time; at validation compare the measurement, fall back to the full hash whenever it cannot answer | −47 ms (to ≈ 30.9 ms, 2.56× over Phase X) | sound under V1–V4 (§4.4); a false HIT needs a SHA-256/512 collision or a kernel verity bug | **none on this host** (`CONFIG_FS_VERITY` unset, ext4 without the feature); needs a verity-formatted fs, which is a root/mkfs-time decision | medium: guard variant + pure decision + probe + fallback | **design accepted, promotion rejected** (gate 4/5) |
| **H2** | **Intra-pass sharing of one pinned measurement** across the 3 `cc1` guards | with H1: ≈ 0 (2 fewer ioctls ≈ 1 µs). Without H1: 2.545× fewer bytes, ≈ −28.7 ms | sound *given* H1's invariant: sharing a measurement is safe when the content cannot change between the two uses | as H1 | low (a per-pass map keyed by `(dev, ino, pin)`) | **rejected as valueless** — H1 removes the hashing that sharing would have saved |
| **H2′** | **Intra-pass digest sharing without verity** (hash once, reuse the digest for later guards) | 2.545× fewer bytes, ≈ −28.7 ms — the largest single available win | **unsound**: a same-size rewrite inside one filesystem timestamp tick preserves `mtime`, `ctime` and `size`, so a digest from `t_a` cannot answer a guard at `t_b > t_a`. Permanent regression `phase_x_tests` | universal | low | **rejected, settled by Phase X** — and this phase re-derived it rather than assuming it |
| **H3** | **User-declared immutable inputs** (`TRACEJIT_ASSUME_IMMUTABLE`) | −47 ms when declared | no proof at all: the user asserts an invariant. Must be a separately named contract, opt-in, never reported as Strict | universal | medium (contract plumbing, reporting, per-path opt-in) | **not implemented** — an attractive number attached to zero evidence, and it would put a weaker contract one flag away from Strict |
| **H4** | **Session-aware pipeline validation** (a consumer validated against its producer's record) | workload-dependent | high: new cross-invocation state machine, new model-check target | universal | high | **not attempted** — out of scope for a phase about hashing |
| **H5** | **Residual non-hash costs** (SQLite lookup + decode ≈ 6.4 ms, restore ≈ 3.0 ms, interpreter ≈ 3.1 ms) | −3 to −6 ms | low | universal | low | **deferred** — untouched by this phase, and the plan's original "do first" ordering was superseded by the discovery that the compiler workload cannot reuse at all here |
| **H6** | **Parallel BLAKE3** across threads for the 105 MB | wall-clock only; bytes unchanged | none — same bytes, same digest | universal | needs a new dependency (`blake3/rayon`) and a thread pool in a tool whose hit is 79 ms | **rejected as out of scope** — it does not reduce hashing, it hides it, and it adds a dependency to a 10 MB-RSS process |
| **H7** | **`FS_IMMUTABLE_FL`** on dependencies | −47 ms if it were set | no identity: a root writer can clear the flag and rewrite | needs `CAP_LINUX_IMMUTABLE` to set, i.e. root, and it changes the user's files | high | **rejected** — a weaker guarantee than a hash, at a higher privilege cost than verity |
| **H8** | **Read-only bind mount / namespace** around dependencies | −47 ms | no identity: a second writable mount bypasses it | root to mount | high | **rejected** |
| **H9** | **`memfd` seals** | none for real binaries | identity, but only for `memfd` objects with no pathname | cannot hold `/usr/bin/cc1` | — | **rejected as inapplicable** |
| **H10** | **dm-verity** | −47 ms | identity of a whole block device, not a file | root, a dedicated device, a key policy | very high | **rejected** — cannot be applied to files on a writable root filesystem |
| **H11** | **IMA appraisal** | −47 ms | authentication against a machine-wide policy, not per-file identity | root, policy, keyring, xattrs | high, machine-wide | **rejected** |
| **H12** | **Content-addressed toolchains** (Nix, ostree, verity container images) | −47 ms where adopted | identity by construction | the user must have adopted the installation method | adoption cost, not code | **rejected for this phase, recorded as the only realistic route to H1** — a distribution-image decision, not a TraceJIT one |
| **H13** | **Trust the allocator-entropy profile** to keep compiler reuse alive | n/a | n/a | **it went stale on this image** (glibc 8.9 → 8.12) | — | **confirmed risk, not a Phase Y item** — observed evidence for Phase X1 §8 mechanism (a) |

## Settled negative results

1. **No sound way exists, with the mechanisms available here, to reduce repeated dependency hashing
   for ordinary writable files.** The 2.545× redundancy in the compiler workload is reachable only
   with an invariant that ordinary developer machines do not provide.
2. **Metadata is never enough**, in any contract: `mtime`/`ctime`/`size` are equal across a
   same-tick rewrite. Every rejected hypothesis above that promised a win cheaply relied on metadata
   or on a policy rather than on content identity.
3. **A failing measurement is cheap** (493 ns), so the fallback is a safe design — but it is not a
   strategy, because it reaches the same 47 ms of hashing.

## Open questions the ledger hands forward

1. Is there a verity-formatted filesystem in any CI environment this project can use? If yes, H1
   becomes measurable and gate 3 becomes a kernel test.
2. Do any real workloads of interest run on ostree/verity images (Silverblue, CoreOS, mkosi-built
   images, Android host-side tooling)? If yes, H1's applicability is > 0 for those users.
3. Is the 493 ns measurement cost dominated by the `ENOTTY`/`EOPNOTSUPP` path rather than by a real
   xattr read? Only a verity host can answer that, and it changes the size of H1's win by
   microseconds, not milliseconds.

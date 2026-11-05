# TraceJIT execution state

Updated at the Phase 2G worktree (base `6941443`, branch `verify/phase1-5`, uncommitted at the time
of writing). This file is the resume point: what is done, what is measured, and what is blocked.

## Phase status

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 2A.1 | Executable identity cannot file a profile under the wrong identity | **PARTIAL PASS** — re-hashed immediately before exec, fails closed; the final window remains open | `PHASE2_EXEC_IDENTITY.md` |
| 2A.2 | Landlock + seccomp `PROVEN` path executed | **BLOCKED** — no Landlock on this host (`ENOSYS`, LSM `capability,selinux`) | `PHASE1_5_SECURITY_REPORT.md` |
| 2A.3 | Restoration crash consistency | **ACCEPTED LIMITATION** — not atomic; recovery by re-execution | `PHASE1_5_INDEPENDENT_REVIEW.md` |
| 2B.2 | Permission checks guardable | **PASS** — replayed under the recorded credential identity, or refused | `PHASE2B_ACCESS_SOUNDNESS.md` |
| 2B | Descriptor and pipe model | **PASS for soundness, FAIL for reach** | `PHASE2C_PIPE_SOUNDNESS.md` |
| 2C | First real-world workload reused | **PASS** — `gzip -9 -c`, 20/20 hits, invalidation verified | `PHASE2C_FIRST_REALWORLD_HIT.md` |
| 2D.1 | Timestamp invalidation defect explained | **WRONG, corrected in 2E** — the dependency was never an `atime` or a `stat` | `PHASE2D_ATIME_ANALYSIS.md` |
| 2D.2 | Fixed direct-execution compatibility suite | **PASS** — 16 workloads, fixed denominator | `PHASE2D_DIRECT_COMPATIBILITY.md` |
| 2D.3 | Certified effect noninterference | **ASSESSED, NOT IMPLEMENTED** | `PHASE2D_NONINTERFERENCE_RESEARCH.md` |
| 2E.1 | Directory dependency traced to its origin | **PASS** — a real `openat(... O_DIRECTORY)` by the command, recorded as a metadata read | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2E.2 | Typed directory provenance and production fix | **PASS** — `DirectoryOpened` effect/dependency/guard | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2E.3 | Ordinary output placement no longer invalidates | **PASS** — 0% invalidation in 8/8 benchmark cells | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2F.0 | Independent `DirectoryOpened` audit | **PASS with defects fixed** — credential binding, `O_PATH` access mode, `..` through symlinks | `PHASE2F_DIRECTORY_GUARD_AUDIT.md` |
| 2F.1 | Sound `statfs`/`fstatfs` model | **PASS** — all 120 bytes, same call shape, namespace + credential bound | `PHASE2F_STATFS_AND_DESCRIPTORS.md` |
| 2F.2 | Safe inherited descriptor inputs | **PARTIAL PASS** — regular files modelled; pipes/sockets/TTYs/anonymous refused | `PHASE2F_STATFS_AND_DESCRIPTORS.md` §5–6 |
| 2F.3 | Sound directory enumeration | **PASS (bounded)** — exact per-call byte stream; refuses non-zero offset and >1 MiB | `PHASE2F_DIRECTORY_ENUMERATION.md` |
| 2F.4 | Two additional reusable categories | **FAIL** — 1 of 16 direct, 0 of 9 census | `PHASE2F_COMPATIBILITY.md` §4 |
| 2G.A | Path-resolution adversarial audit | **PASS after fix** — confirmed false hit in `be94f38`, removed; regression tests fail on the defective build | `PHASE2G_PATH_RESOLUTION.md` |
| 2G.B | Forensic identification of allocator randomness | **PASS** — glibc `tcache_key_initialize` via `ptmalloc_init`, call site, build IDs, tunables, static variant; musl **BLOCKED** | `PHASE2G_ALLOCATOR_ENTROPY.md` |
| 2G.C | Two explicit execution contracts | **PASS** — native unchanged; `tracejit.allocator-entropy.v1` specified with admission conditions, recorded evidence and non-equivalence statement | `PHASE2G_EXECUTION_CONTRACTS.md` |
| 2G.D | Controlled-mode prototype on real workloads | **PASS (narrow)** — `sed`, `tr`, `base64`, `wc` verified; `gzip`, `bzip2`, `md5sum` also reuse under the contract | `PHASE2G_COMPATIBILITY.md` |
| 2G.E | Adversarial correctness testing | **PASS** — application randomness refused, tampered runtime/contract/value/shape refused, mode mixing impossible, input/env changes invalidate | `PHASE2G_EXECUTION_CONTRACTS.md` §"Verified by tests" |
| 2G.F | Two fixed suites, both modes, two sessions + workflow | **PASS** — native 1/16, 0/9; controlled 7/16 and 6/16, 0/9; 16/16 and 9/9 equivalence; workflow 14.74x | `PHASE2G_COMPATIBILITY.md` |
| 2D.6 | `PROVEN` enforcement | **BLOCKED** — never executed on any host | — |
| 3 | Performance engineering | **NOT STARTED** — controlled mode is a prerequisite, now measurable | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **NOT ESTABLISHED** — the contract is a mechanism, not a verified contribution | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild/clang on this host | — |

## Latest verified test results

`cargo test --workspace` **105 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 30 Linux
integration + 7 core + 5 effects + 25 guards + 4 sandbox + 13 trace), with `fmt --check` and
`clippy -D warnings` clean, at the Phase 2G worktree.

## Latest measured results (Phase 2G, two sessions per mode)

- **Direct suite** (16 workloads): native **1/16** (`gzip`); controlled **7/16** (session A:
  `gzip`, `bzip2`, `sed`, `tr`, `base64`, `md5sum`, `wc`) and **6/16** (session B, `tr` missed
  because its stdin read changed `atime` in the remembered identity). Output equivalence 16/16.
- **Census** (nine workloads, 3 runs + 1 warmup): **0/9** in native *and* controlled mode, both
  sessions, 9/9 output equivalence; blockers are the shell's clocks, PIDs and sockets, not the
  allocator key.
- **gzip** direct 28.61/28.66 ms, cached 3.87/3.88 ms, cold 47.36/40.56 ms, **7.39x/7.39x**,
  0.76/0.48 hits to repay. **bzip2** 17.55/17.62 → 4.28/4.34 ms, **4.10x/4.06x**, 1.27/1.28.
- **Small filters are losses on a hit**: `sed` 0.69x, `tr` 0.25x, `base64` 0.30x, `md5sum` 0.30x,
  `wc` 0.21x, because a hit costs 4–6 ms. Positive savings need ≥ ~10 ms of native work.
- **Workflow** (5.416 MB, `sed` → `wc -c` → `md5sum` → `gzip -9 -c`, 5 reps): 645.62 → 43.80 ms,
  **14.74x**, about 602 ms saved per iteration; every step a hit with direct-equal bytes.
- **Contract differential check**: 4/4 reusable and fully verified (`sed`, `tr`, `base64`, `wc`).

## Open correctness risks

1. **The contract is narrow, not general determinism.** It controls only a shared runtime library's
   8-byte `GRND_NONBLOCK` probe. Clocks, PIDs, `sysinfo`, `sched_getaffinity`, application
   randomness, `/proc/self/maps` and network remain refused.
2. **Validation-to-restore TOCTOU** remains for every guard; the false-hit defect was about recorded
   evidence, not this window.
3. **Symlinked output ancestors are refused**; restoration through a repointable path would be unsafe.
4. **Mount-namespace changes** are only bound by `statfs`/enumeration dependencies; `unshare -m` is
   not permitted here, so the path case is untested (BLOCKED).
5. **`tr`'s stdin `atime` in the runtime identity** turns some hits into misses across sessions; a
   reach, not a soundness, limitation.
6. **musl and static-musl variants were not tested** (no toolchain); static glibc still emits the
   probe and is excluded by the contract's module rule.
7. **`PROVEN` has never been executed**; the contract is explicitly not a sandbox and makes no
   isolation claim.
8. **Restoration is not crash-atomic**; re-execution repairs it.

## Next executable actions

1. Decide whether to exclude `atime` from the inherited-stdin identity so `tr` and similar filters
   reuse reliably, with a test that a content change still invalidates.
2. Model `/proc/self/maps` for `grep`, or keep it refused.
3. Decide the `getrusage` question explicitly: an opt-in, recorded, falsifiable certificate, or keep
   compilers refused.
4. Test a musl toolchain and a fully static program to complete the allocator-entropy matrix.
5. Landlock-capable CI job for the `PROVEN` gate.

# TraceJIT execution state

Updated at the Phase 2F tip (commits `5db741f`, `be94f38`) on branch `verify/phase1-5`. This file is
the resume point: what is done, what is measured, and what is blocked.

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
| 2E.2 | Typed directory provenance and production fix | **PASS** — `DirectoryOpened` effect/dependency/guard; timestamps excluded, identity and openability compared | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2E.3 | Ordinary output placement no longer invalidates | **PASS** — 0% invalidation in 8/8 benchmark cells | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2F.0 | Independent `DirectoryOpened` audit | **PASS with defects fixed** — credential binding, `O_PATH` access mode, `..` through symlinks | `PHASE2F_DIRECTORY_GUARD_AUDIT.md` |
| 2F.1 | Sound `statfs`/`fstatfs` model | **PASS** — all 120 bytes, same call shape, namespace + credential bound; adversarial capacity change invalidates | `PHASE2F_STATFS_AND_DESCRIPTORS.md` |
| 2F.2 | Safe inherited descriptor inputs | **PARTIAL PASS** — regular files modelled (hash, offsets); pipes/sockets/TTYs/anonymous still refused | `PHASE2F_STATFS_AND_DESCRIPTORS.md` §5–6 |
| 2F.3 | Sound directory enumeration | **PASS (bounded)** — exact per-call byte stream; refuses non-zero offset and >1 MiB | `PHASE2F_DIRECTORY_ENUMERATION.md` |
| 2F.4 | Two additional reusable categories | **FAIL** — 1 of 16 direct, 0 of 9 census; all candidates blocked by allocator `getrandom` | `PHASE2F_COMPATIBILITY.md` §4 |
| 2D.6 | `PROVEN` enforcement | **BLOCKED** — never executed on any host | — |
| 3 | Performance engineering | **NOT STARTED** — one reusable workload is too narrow to tune against | `PHASE2F_COMPATIBILITY.md` §9 |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **NOT ESTABLISHED** — no mechanism or comparison exists | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild/clang on this host | — |

## Latest verified test results

`cargo test --workspace` **100 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 26 Linux
integration + 7 core + 5 effects + 24 guards + 4 sandbox + 13 trace), with `fmt --check` and
`clippy -D warnings` clean, at `be94f38`.

## Latest measured results (`be94f38`, two clean-tree sessions)

- **Direct suite** (16 workloads, 5 runs): **1 of 16 reused** (`gzip`), **16 of 16** output
  equivalent, PASS in both sessions.
- **Census** (nine workloads, unchanged denominator, 3 runs + 1 warmup): **0 of 9**, 9 refused,
  0 execution failures, 9/9 output equivalent, in both sessions.
- **gzip** `-9 -c` on a 20 000-line input: direct 28.89 / 29.00 ms (p95 29.16 / 29.03), warm
  4.33 / 4.06 ms (p95 7.23 / 6.96), cold 40.79 / 42.49 ms, **6.67x / 7.14x**, **0.48 / 0.54 hits**
  to repay the trace.
- No other workload reached `Reused`, so no other timing is reported.

`statfs`, enumeration and stdin refusals are gone from the chains: `sed` and `tar` now stop at
`getrandom`, `tr` at `getrandom` after a recorded regular-file stdin dependency, and `nm` at
`getrandom` plus `prlimit64` after four enumerated plugin directories.

## Open correctness risks

1. **glibc allocator `getrandom` refuses essentially every dynamically linked tool.** About 50
   surveyed, including `sed`, `tar`, `tr`, `nm`, `ar`, `grep`, `sort`, `perl`, `make`, `zip` and
   `gcc`. The call sits in `malloc` via `setlocale`; disabling tcache does not remove it. No model
   exists; ignoring it would be a forbidden global whitelist.
2. **`/proc/self/maps`** still refuses `grep`; process memory identity is unmodelled.
3. **`getrusage`** still refuses compilers and assemblers; per-run consumption is unguardable.
4. **Enumeration is bounded** at 1 MiB and refuses a non-zero start offset; large trees fall back to
   direct execution.
5. **Mount-namespace changes after a path open** are not modelled by path guards; `statfs` and
   enumeration bind namespace identity.
6. **Every guard has a validation-to-restore TOCTOU window**; the executable re-hash narrows one.
7. **Restoration is not crash-atomic**; re-execution repairs it.
8. **`PROVEN` has never been executed**; no enforcement claim is made anywhere.

## Next executable actions

1. Test a workload class that avoids glibc's allocator entropy — a static or musl binary, or a
   direct-syscall tool — end to end, to see whether a second reusable category is reachable at all.
2. If that succeeds, profile the ~4 ms hit path across the new categories before choosing between
   faster validation, lower ptrace overhead and cache-admission changes (Phase 3).
3. Model `/proc/self/maps` for `grep` (process memory identity), or keep it refused.
4. Decide the `getrusage` question explicitly: an opt-in, recorded, falsifiable certificate, or keep
   compilers refused. Never a global whitelist.
5. Landlock-capable CI job for the `PROVEN` gate.

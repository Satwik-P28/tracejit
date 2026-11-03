# TraceJIT execution state

Updated at the Phase 2E tip on branch `verify/phase1-5`. This file is the resume point: what is done,
what is measured, and what is blocked.

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
| 2E.3 | Ordinary output placement no longer invalidates | **PASS** — 0% invalidation in 8/8 benchmark cells; 83% invalidation on the baseline for the same sequence | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2E.4 | Two additional reusable categories | **FAIL** — 1 of 16 in the direct suite, 0 of 9 in the census | `PHASE2E_DIRECTORY_DEPENDENCY.md` §7 |
| 2D.6 | `PROVEN` enforcement | **BLOCKED** — unchanged; never executed on any host | — |
| 3 | Performance engineering | **NOT STARTED** — the hit path has not been profiled | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **NOT ESTABLISHED** — mechanism and evidence do not exist | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild/clang on this host | — |

## Latest verified test results

`cargo test --workspace` **95 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 26 Linux
integration + 7 core + 5 effects + 19 guards + 4 sandbox + 13 trace), with `fmt --check` and
`clippy -D warnings` clean.

## Latest measured results

- **Ordinary gzip use**, 6 MB and 480 kB, 15 runs, two sessions: output written beside the input is
  now as cheap as an isolated directory — 0% invalidation, 15/15 hits, 5.86–12.04 ms warm against
  112–1494 ms direct (18.6–147x), every cell repaying the trace within 0.42 hits.
- **Baseline `0ccf181`**, same sequence: 83% invalidation, 1/6 hits, 138.21 ms and 1548.51 ms warm —
  slower than running the command directly (0.82x and 0.96x).
- **Direct suite**, two sessions, 3 runs: **1 of 16 reused** (`gzip`), **16 of 16** output equivalent.
- **Fixed census** (nine workloads, unchanged denominator): **0 of 9**, 9 of 9 output equivalent,
  0 execution failures.
- **Synthetic C ETL** at `9571772`: baseline 8.366 ms, cold 21.089 ms, hit 4.043 ms, 2.069x.

## Open correctness risks

1. **Directory enumeration is refused, not guarded.** `getdents64` used to be silently ignored, which
   was unsound; it now fails closed. A real entry-set dependency is unimplemented.
2. **`getrusage` blocks every compiler and assembler.** Deliberately unadmitted; the value reaches no
   output for the tested inputs, but per-run consumption cannot be guarded.
3. **Unmodelled `statfs`, `/proc/self/maps`, inherited descriptor reads** refuse `tar`, `sed`, `grep`
   and `tr`.
4. **Every guard has a validation-to-restore TOCTOU window**; the executable re-hash narrows one.
5. **Restoration is not crash-atomic**; re-execution repairs it.
6. **`PROVEN` has never been executed**; no enforcement claim is made anywhere.

## Next executable actions

1. Model `statfs` so `tar` and `sed` can be re-evaluated — the cheapest route to another category.
2. Implement a directory enumeration dependency (entry-set digest) instead of refusing it.
3. Profile the ~6–10 ms hit path (Phase 3) before optimising it; the added directory guard is below
   this VM's measurement floor.
4. Landlock-capable CI job for the `PROVEN` gate.
5. Decide the `getrusage` question explicitly: an opt-in, recorded, falsifiable certificate, or keep
   compilers refused. Never a global whitelist.

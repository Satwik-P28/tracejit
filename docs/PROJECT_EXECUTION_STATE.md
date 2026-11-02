# TraceJIT execution state

Updated at commit `bd59a0e` on branch `verify/phase1-5` (Phase 2C work is in the working tree below).
This file is the resume point: what is done, what is measured, and what is blocked.

## Phase status

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 2A.1 | Executable identity cannot file a profile under the wrong identity | **PARTIAL PASS** — re-hashed immediately before exec, fails closed; the final window remains open | `PHASE2_EXEC_IDENTITY.md` |
| 2A.2 | Landlock + seccomp `PROVEN` path executed | **BLOCKED** — no Landlock on this host (`ENOSYS`, LSM `capability,selinux`) | `PHASE1_5_SECURITY_REPORT.md` |
| 2A.3 | Restoration crash consistency | **ACCEPTED LIMITATION** — not atomic; recovery by re-execution | `PHASE1_5_INDEPENDENT_REVIEW.md` |
| 2B.2 | Permission checks guardable | **PASS** — replayed under the recorded credential identity, or refused | `PHASE2B_ACCESS_SOUNDNESS.md` |
| 2B | Descriptor and pipe model | **PASS for soundness, FAIL for reach** | `PHASE2B_DESCRIPTOR_MODEL.md`, `PHASE2C_PIPE_SOUNDNESS.md` |
| 2C | First real-world workload reused | **PASS** — `gzip -9 -c`, 20/20 hits, 23.7x, invalidation verified | `PHASE2C_FIRST_REALWORLD_HIT.md` |
| 2C | Compiler workload reused | **FAIL (analysed)** — sole blocker is one `getrusage(RUSAGE_SELF)` in `as`; not admitted | `PHASE2C_GETRUSAGE_ANALYSIS.md` |
| 2B | Three reusable real workload categories | **FAIL** — census still 0 of 9 | `PHASE2B_CENSUS_DELTA.md` |
| 3 | Performance engineering | **NOT STARTED** — the hit path has not been profiled | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **BLOCKED** — no prior-art review or ablation was produced | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild on this host | — |

## Latest verified test results

`cargo fmt --all -- --check` clean, `cargo clippy --workspace --all-targets --all-features -D
warnings` clean, `cargo test --workspace` **87 passed, 0 failed** across 8 suites (16 cache + 5 CLI +
25 Linux integration + 7 core + 5 effects + 12 guards + 4 sandbox + 13 trace). The integration suite
now includes `real_gzip_workload_is_reused_and_invalidated`, which asserts classification, byte
equality with a direct run, a `Reused` decision, deoptimization on content change, correct new bytes,
and reusability afterwards.

## Latest measured results

- **Direct-invocation suite** (`benchmarks/realworld/direct_suite.py`, `RESULT direct-suite PASS`):
  `gzip` Guarded/eligible, `sort` Unknown (clone semantics), `base64`/`md5sum`/`tr`/`wc`
  Nondeterministic (`getrandom`). gzip timing: direct 258.19 ms median (p95 261.28), cached 10.90 ms
  (p95 15.35), cold 458.95 ms, **23.68x**, 247.29 ms saved, **1.81** hits to repay. Artifact:
  `benchmarks/results/phase2c/direct-suite/direct-suite.json`.
- **Fixed census** (nine workloads, unchanged): **0 of 9 eligible**, 9/9 output equivalence.
  Blockers: interpreter clock/randomness/pid, pipe short-read-then-more, `fstat` on a pipe,
  `getrusage` (two compiler workloads), `epoll_create1`.
- **Synthetic C ETL** at `9571772`: baseline 8.366 ms, cold 21.089 ms, hit 4.043 ms, 2.069x.

## Known safety limitations

- Restoration is not crash-atomic; re-execution repairs it.
- Every guard has a validation-to-restore TOCTOU window.
- The executable re-hash narrows, but does not close, the replace-before-exec window.
- `PROVEN` has never been executed on any host; no enforcement claim is made.
- Pipe reuse rests on a packetisation argument: sound for programs whose output is a function of the
  byte stream, which is what condition 2 makes observable. Streaming pipelines are refused.
- An input whose mtime is in the future (or a `strictatime` mount) was observed to keep an execution
  deoptimizing on every run. Cause not established; recorded as an open defect, not a passing test.
- `fstat` on a pipe, `epoll`, `eventfd`, `SCM_RIGHTS`, `/dev/null` outputs and `getrusage` remain
  unmodelled and fail closed.

## Next executable actions

1. Diagnose the future-mtime deopt loop above; it is a repeated-execution bug that costs every edit one
   extra run.
2. Decide the `getrusage` question explicitly: either a documented, opt-in non-interference profile
   with its own contract, or keep compilers refused. Do not whitelist globally.
3. `epoll_create1` modelling for the Pillow workload, which is otherwise only blocked by interpreter
   randomness.
4. Profile the 10.9 ms hit (Phase 3) before optimising it.
5. Landlock-capable CI job for the `PROVEN` gate.

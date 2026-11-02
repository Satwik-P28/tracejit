# TraceJIT execution state

Updated at the Phase 2D tip on branch `verify/phase1-5`. This file is the resume point: what is done,
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
| 2D.1 | Timestamp invalidation defect explained | **PASS (explained, not fixed)** — the invalidation is a directory `mtime`/`ctime` dependency, not the input's atime; fix scoped, recording site not located | `PHASE2D_ATIME_ANALYSIS.md` |
| 2D.2 | Fixed direct-execution compatibility suite | **PASS** — 16 workloads, fixed denominator, 1 reused, 16/16 output equivalence | `PHASE2D_DIRECT_COMPATIBILITY.md` |
| 2D.3 | Certified effect noninterference | **ASSESSED, NOT IMPLEMENTED** — prior art surveyed; no mechanism exists yet, so no research claim is made | `PHASE2D_NONINTERFERENCE_RESEARCH.md` |
| 2D.4 | Two additional reusable workload categories | **FAIL** — 1 of 16 in the direct suite (gzip); 0 of 9 in the unchanged census | `PHASE2D_DIRECT_COMPATIBILITY.md` |
| 2D.5 | Two-session benchmark validation | **PASS** — 7.16x / 6.89x, 0.70 / 0.74 hits to repay | `PHASE2D_REALWORLD_BENCHMARKS.md` |
| 2D.6 | `PROVEN` enforcement | **BLOCKED** — unchanged; never executed on any host | — |
| 3 | Performance engineering | **NOT STARTED** — the hit path has not been profiled | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **NOT ESTABLISHED** — mechanism and evidence do not exist | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild/clang on this host | — |

## Latest verified test results

`cargo test --workspace` **87 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 25 Linux
integration + 7 core + 5 effects + 12 guards + 4 sandbox + 13 trace), with `fmt --check` and
`clippy -D warnings` clean. No production code changed in Phase 2D; only the benchmark script, tests
from earlier phases and documentation.

## Latest measured results

- **Direct suite** (`benchmarks/realworld/direct_suite.py`, 16 workloads, both sessions
  `RESULT direct-suite PASS`): **1/16 reused** (gzip), **16/16** traced output equal to a direct run.
  Refusals: `getrandom` (bzip2, xz, sort, base64, md5sum, wc, jq, python, strip), `statfs` (tar, sed),
  `/proc/self/maps` (grep), inherited descriptor read (tr), `getrusage` (gcc, as).
- **gzip timing**, two sessions, 480 KB input: direct 28.84/28.78 ms, cached 4.03/4.18 ms, cold
  46.26/47.10 ms, **7.16x/6.89x**, **0.70/0.74 hits to repay**. Only valid while the input's parent
  directory is unchanged.
- **Fixed census** (nine workloads, unchanged denominator): **0 of 9**, 9/9 output equivalence.
- **Synthetic C ETL** at `9571772`: baseline 8.366 ms, cold 21.089 ms, hit 4.043 ms, 2.069x.

## Open correctness risks

See `PHASE2D_REMAINING_CORRECTNESS_RISKS.md`. The most valuable is the directory metadata
over-approximation: it is conservative, but it defeats reuse whenever a command writes beside its
input, which is the normal pattern. Second is the unmodelled `getrusage` that blocks every compiler
and assembler invocation.

## Known safety limitations

- Restoration is not crash-atomic; re-execution repairs it.
- Every guard has a validation-to-restore TOCTOU window; the executable re-hash narrows one of them.
- `PROVEN` has never been executed; no enforcement claim is made anywhere.
- Pipe reuse rests on a packetisation argument; streaming pipelines are refused.
- `fstat` on a pipe, `epoll`, `eventfd`, `SCM_RIGHTS`, `/dev/null` outputs, `statfs` and `getrusage`
  remain unmodelled and fail closed.

## Next executable actions

1. Locate the parent-directory snapshot site and give resolution-time directory dependencies an
   identity-only comparison, keeping full fingerprints for genuine directory `stat` calls. This is
   the single highest-value fix: it restores reuse for outputs written beside inputs.
2. Decide the `getrusage` question explicitly: an opt-in, recorded, falsifiable inert-read
   certificate, or keep compilers refused. Never a global whitelist.
3. Model `statfs` so `tar` and `sed` can be re-evaluated, and reconsider inherited-descriptor reads
   for `tr`.
4. Profile the ~4 ms hit path (Phase 3) before optimising it.
5. Landlock-capable CI job for the `PROVEN` gate.

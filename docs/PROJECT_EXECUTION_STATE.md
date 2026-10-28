# TraceJIT execution state

Updated at commit `2edbf0d` on branch `verify/phase1-5`. This file is the resume point: it records
what is done, what is measured, and what is blocked, so no phase has to be re-derived.

## Phase status

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 2A.1 | Executable identity cannot file a profile under the wrong identity | **PARTIAL PASS** — re-verified immediately before exec, fails closed; the final window remains open | `docs/audits/PHASE2_EXEC_IDENTITY.md` |
| 2A.2 | Landlock + seccomp `PROVEN` path executed | **BLOCKED** — host has no Landlock (`landlock_create_ruleset` → `ENOSYS`, LSM list `capability,selinux`) | `PHASE1_5_SECURITY_REPORT.md` |
| 2A.3 | Restoration crash consistency | **ACCEPTED LIMITATION** — not atomic; recovery by re-execution | `PHASE1_5_INDEPENDENT_REVIEW.md` |
| 2B.2 | Permission checks guardable | **PASS** — recorded and replayed exactly, or refused | `docs/audits/PHASE2_ACCESS_PREDICATES.md` |
| 2B | Three reusable real workload categories | **FAIL** — 0 of 9 eligible, unchanged | `docs/audits/PHASE2_CENSUS_DELTA.md` |
| 3 | Performance engineering | **NOT STARTED** — no measurement of this tree | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **BLOCKED** — prior-art review and experiments cannot be produced responsibly without a full research pass | — |
| 6 | Competitive benchmarking | **BLOCKED** — needs Firebuild/ccache/Incr installed and a holdout suite | — |

## Latest verified test results

`cargo fmt --all -- --check` clean, `cargo clippy --workspace --all-targets --all-features -D
warnings` clean, `cargo test --workspace` **77 passed, 0 failed** across 8 suites (16 unit + 5 + 24
Linux integration + 7 + 5 + 10 + 4 + 6). The integration suite includes the 47-case classification
table, the guarded hit/deopt/restore path, the Phase 1.5 script-path test, and the new access
predicate test.

## Latest measured results

Compatibility census at `2edbf0d` (`--runs 3 --warmups 1`, nine fixed workloads): 9 attempted, 0
missing tools, 0 execution failures, **9/9 output equivalence PASS**, **0/9 eligible**, 0 hits.
Top blocker is now `unclassified_descriptor` (4 workloads, 11 occurrences); `access` checks are
gone (was 4 workloads, 28 occurrences).

Benchmarks: **NOT RE-RUN for this commit.** The Phase 1.5 numbers (baseline 8.34 ms, cold 19.0 ms,
hit 3.97 ms, 2.10x) describe the tree *before* these changes and must not be quoted for `2edbf0d`.
The hit path for workloads that record no permission checks is unchanged in code, but that is an
argument, not a measurement. Command to produce the missing data:

```bash
python3 benchmarks/harness/benchmark.py --runs 50 --warmups 10 \
  --output-dir benchmarks/results/phase2/native
```

## Known safety limitations

- Restoration is not crash-atomic: a kill between renames leaves a mixed workspace plus stray
  files. Re-execution repairs it. No journal, no directory `fsync`.
- Every guard has a validation-to-restore TOCTOU window.
- The executable re-hash narrows, but does not close, the replace-before-exec window.
- `PROVEN` has never been exercised on any host.
- Cache ownership marker is unauthenticated; a wrong-type directory is adopted harmlessly because
  the root is allow-listed first.

## Next executable actions

1. Descriptor identity: give fds that are neither files nor sockets a modelled state (pipe,
   epoll, eventfd). Covers `unclassified_descriptor`, `fstat`, `epoll_create1` — 6 of the 11
   remaining blocker occurrences — and is a correctness gap in its own right.
2. Internal-pipe modelling for `pipe2`, on top of (1). Required for the shell pipeline and compiler
   driver workloads.
3. Re-run the benchmark suites at the new commit and record two independent sessions.
4. Add a `build(ci)` job on a Landlock-capable kernel to execute the `PROVEN` gate.

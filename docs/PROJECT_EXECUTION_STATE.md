# TraceJIT execution state

Updated at commit `b57bc7f` on branch `verify/phase1-5`. This file is the resume point: what is done,
what is measured, and what is blocked, so no phase has to be re-derived.

## Phase status

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 2A.1 | Executable identity cannot file a profile under the wrong identity | **PARTIAL PASS** — re-verified immediately before exec, fails closed; the final window remains open | `docs/audits/PHASE2_EXEC_IDENTITY.md` |
| 2A.2 | Landlock + seccomp `PROVEN` path executed | **BLOCKED** — host has no Landlock (`ENOSYS`, LSM list `capability,selinux`) | `docs/audits/PHASE1_5_SECURITY_REPORT.md` |
| 2A.3 | Restoration crash consistency | **ACCEPTED LIMITATION** — not atomic; recovery by re-execution | `docs/audits/PHASE1_5_INDEPENDENT_REVIEW.md` |
| 2B.2 | Permission checks guardable | **PASS** — replayed under the recorded credential identity, or refused | `docs/audits/PHASE2B_ACCESS_SOUNDNESS.md` |
| Priority 0 | Soundness audit of the access mechanism | **PASS** — three high-severity defects found and fixed (`A1` credentials, `A2` `AT_EMPTY_PATH`, `A3` lexical `..`) | `docs/audits/PHASE2B_ACCESS_SOUNDNESS.md` |
| Priority 1 | Descriptor and pipe model | **PASS for soundness, FAIL for reach** — pipes are modelled, `pipe2`/`unclassified_descriptor` gone, but streaming pipelines stay refused | `docs/audits/PHASE2B_DESCRIPTOR_MODEL.md` |
| 2B | Three reusable real workload categories | **FAIL** — 0 of 9 eligible | `docs/audits/PHASE2B_CENSUS_DELTA.md` |
| 3 | Performance engineering | **NOT STARTED** — no measurement of this tree | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **BLOCKED** — a prior-art review and ablation study cannot be produced responsibly in the remaining budget | — |
| 6 | Competitive benchmarking | **BLOCKED** — needs Firebuild/ccache/Incr installed and a holdout suite | — |

## Latest verified test results

`cargo fmt --all -- --check` clean, `cargo clippy --workspace --all-targets --all-features -D
warnings` clean, `cargo test --workspace` **86 passed, 0 failed** across 8 suites (16 cache + 5 CLI +
24 Linux integration + 7 core + 5 effects + 12 guards + 4 sandbox + 13 trace). The integration suite
includes the classification table (`tests/fixtures/cases.json`, now with `pipe_roundtrip` and
`pipe_short_read`), the guarded hit/deopt/restore path, the Phase 1.5 script-path test, and the
access-predicate test.

## Latest measured results

Compatibility census at `b57bc7f` (nine fixed workloads, same denominator as Phase 1): 9 attempted,
0 missing tools, 0 execution failures, **9/9 output equivalence PASS**, **0/9 eligible**, 0 hits.
`pipe2` and `unclassified_descriptor` no longer appear anywhere in the ranking. What remains:
`clock` (4 workloads), `randomness` (4), `process_identity` (3), pipe short-read-then-more (3),
`fstat` on a pipe (2), `getrusage` (2), `epoll_create1` (1), `/dev/null` as output (1).

Benchmarks: **NOT RE-RUN for this commit.** The Phase 1.5 numbers (baseline 8.34 ms, cold 19.0 ms,
hit 3.97 ms, 2.10x) describe an earlier tree and must not be quoted here. Command:

```bash
python3 benchmarks/harness/benchmark.py --runs 50 --warmups 10 \
  --output-dir benchmarks/results/phase2b/native
```

## Known safety limitations

- Restoration is not crash-atomic: a kill between renames leaves a mixed workspace plus stray files.
  Re-execution repairs it. No journal, no directory `fsync`.
- Every guard has a validation-to-restore TOCTOU window.
- The executable re-hash narrows, but does not close, the replace-before-exec window.
- `PROVEN` has never been exercised on any host.
- Cache ownership marker is unauthenticated.
- Pipe reuse rests on a packetisation argument, not a proof of program behaviour: it is sound only
  for programs whose output is a function of the byte stream rather than of chunk boundaries, and the
  tracer enforces the observable part of that condition (single writer, no short-read-then-more, no
  partial transfer). A program that reads one byte at a time and *also* completes its stream before
  more data arrives would still pass; the condition checked is the one that makes the read sequence
  reproducible.
- `fstat` on a pipe, `epoll`, `eventfd`, `SCM_RIGHTS` descriptor passing and `/dev/null` outputs are
  unmodelled and fail closed.

## Next executable actions

1. `/dev/null` as a modelled output sink and `close(-1)` — cheapest sound gaps, but they change no
   workload on their own (documented in `PHASE2B_CENSUS_DELTA.md`).
2. `getrusage`: decide whether an observation that is nondeterministic *and* provably unrelated to
   output can be recorded rather than refused. Needs evidence per workload, not a table entry.
3. Interpreter determinism model for CPython and `awk` startup — the only route to the three
   interpreter workloads.
4. Per-process reuse for streaming pipelines, which is the only route to the shell and `groff`
   workloads and is an architectural change, not a syscall model.
5. Run the benchmark suites at the current commit; record two independent sessions.
6. Add a CI job on a Landlock-capable kernel to execute the `PROVEN` gate.

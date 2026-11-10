# TraceJIT Competitive Benchmarks

## Claim boundary

TraceJIT is a transparent command cache. A correct incremental build system or content-addressed cache
knows more about the workflow than TraceJIT does and can skip the command entirely. The current claim is
limited to workloads where that graph is absent or the output is missing/suspect.

## Phase 2T retained negative

Three sessions, five arms, 2.8 MB × 3 assets, bzip2 output creation inside each timed command. Medians:

| Scenario | Native | TraceJIT | Make | Ninja | Content cache |
| --- | ---: | ---: | ---: | ---: | ---: |
| First build | 430.00 ms | 669.07 ms | 425.66 ms | 436.50 ms | 495.54 ms |
| Identical rerun | 433.68 ms | 678.59 ms | 2.63 ms | 2.82 ms | 60.22 ms |
| Input edit, mtime preserved | 423.57 ms | 240.50 ms | 2.87 ms stale | 2.89 ms stale | 197.59 ms |
| Corrupted output | 428.88 ms | 437.08 ms | 2.65 ms stale | 2.91 ms stale | 51.62 ms |
| Five sessions | 2142.60 ms | 2445.11 ms | 800.41 ms | 835.88 ms | 1071.34 ms |

Make/Ninja are far cheaper on an unchanged rerun. TraceJIT is correct on the preserved-mtime edit and
the corrupted output where mtime-based tools retain stale bytes, and it preserves native output metadata
where the baseline's `touch`/write path does not. That is a correctness and discovery difference, not a
speed win.

Raw: `benchmarks/results/phase2t/incremental.json`; method:
`benchmarks/repos/phase2t_incremental.py`.

## Phase 3A A/B/A measurement

Five fresh sessions per arm. Input one -> input two -> input one.

| Arm | Third decision | Median wall | Median report runtime |
| --- | --- | ---: | ---: |
| Current candidate index | `Reused` 5/5 | 13.841662 ms | 3,854,780 ns |
| Pre-change binary | `Executed` 5/5 | 20.572657 ms | 5,258,884 ns |

The fixture is `tests/fixtures/fixture_driver.c:plain_file_read`; raw JSON is
`benchmarks/results/phase3a/candidate-reuse.json`; harness is
`benchmarks/repos/candidate_reuse.py`.

This is a microbenchmark of candidate retention, not a general workload result. It excludes multi-stage
builds, large dependency hashing, parallel execution, and a build-system baseline.

## Real-project recurrence (Phase 2T, retained for context)

Warm recurrence on installed projects:

- jQuery 28.68 -> 10.63 ms; Expat 8.45 -> 7.29 ms; Socat 15.15 -> 8.41 ms.
- Three `Reused` decisions in each workflow, all output bytes correct.
- These are warm-hit rates. Cold trace costs were 59.72, 34.33, and 44.94 ms respectively, so a
  three-command recurrence does not necessarily recover the trace.

Raw: `benchmarks/results/phase2t/real_workflows.json`.

## Methodology obligations for future runs

- Record exact binary hash, commit, kernel, compiler, and fixture.
- Include misses, refusals, cold trace, restoration, and output writes in session time.
- Keep negative and stale-baseline results.
- Do not use repeat loops as a stand-in for ordinary developer behavior.
- Balance arm order where practical; the A/B/A harness alternates binary order by session.
- Do not compare a warm hit against a native command that has different output semantics without
  disclosing the difference.

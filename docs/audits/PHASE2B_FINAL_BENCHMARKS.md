# Current-commit performance baseline

Measured commit: `9571772f8a7f004f2c40a080cd38c6e1e30cdf9b` (documentation only; the code under test
is identical to `b57bc7f`). Working tree clean at measurement time, as recorded by the harness.

Host: Linux 6.1.102, x86-64, 2 vCPU virtual machine, `ext4`/`tmpfs` scratch. Single session, no other
benchmark running. Raw samples: `benchmarks/results/phase2b/native/latest.json`; harness summary
`latest.md`; the harness also saved `explain-cache-hit.txt` and `explain-deopt.txt` for the same run.

Command:

```bash
python3 benchmarks/harness/benchmark.py --runs 50 --warmups 10 \
  --output-dir benchmarks/results/phase2b/native
```

## Results (C ETL workload, 50 recorded runs, 10 warmups)

| Condition | Median | p95 | Minimum | Maximum | Std dev |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct baseline | 8.366 ms | 8.491 ms | 8.301 ms | 9.064 ms | 0.112 ms |
| Traced cold (fresh cache) | 21.089 ms | 33.461 ms | 20.082 ms | 37.002 ms | 4.245 ms |
| Guard validation | 1.671 ms | 2.322 ms | 1.482 ms | 2.895 ms | 0.256 ms |
| Cached end-to-end | 4.043 ms | 4.512 ms | 3.902 ms | 4.644 ms | 0.176 ms |

- Cache-hit speedup: **2.069x**
- Median time saved per hit: **4.323 ms**
- Tracing overhead on a cold run: **152.1%** (21.089 ms versus 8.366 ms)
- Hits needed to repay one cold trace: `(21.089 - 4.043) / (8.366 - 4.043)` ≈ **4.0**
- Output equivalence: **PASS**. Mutation/deoptimization check: **PASS**.

## Comparison with Phase 1.5 — different commit, so not a regression claim

| Metric | Phase 1.5 (`9b47a9a` era, two sessions) | This commit |
| --- | --- | --- |
| Baseline median | 8.3414 / 8.3508 ms | 8.366 ms |
| Cold traced median | 19.0236 / 18.5066 ms | 21.089 ms |
| Cache-hit median | 3.9715 / 3.9912 ms | 4.043 ms |
| Speedup | 2.1003x / 2.0923x | 2.069x |

The cache hit is 1.8% slower and the cold trace 11% slower than the Phase 1.5 sessions. Neither is
attributed to this phase's changes:

- The hit path for a workload with no permission checks and no pipes is unchanged in code. `c-etl`
  performs neither.
- The cold-trace difference is inside the noise this session actually shows: the cold sample's own
  standard deviation is 4.245 ms and its range spans 20.08–37.00 ms. Phase 1.5's two sessions
  differed by 2.7% from each other; this session's variance is far larger, so it cannot separate a
  3 ms shift from host noise.
- CPU frequency, neighbour activity and warm page cache were not controlled.

A second independent session is required before any statement about a performance change at this
commit. **Do not claim a regression or an improvement from one session.**

## What these numbers do and do not say

They say the machinery still works on the workload it was built for: a repeated short command is
~2x faster through the cache, and the break-even point is about four hits.

They do not say anything about the real developer workloads, because **none of the nine census
workloads is eligible** (see `PHASE2B_CENSUS_DELTA.md`). A 2.07x speedup on a workload that refuses
five of nine real commands is not evidence of practical acceleration.

The measured hit floor remains ~4 ms. It is dominated by process startup, record decoding, SQLite
lookup and guard validation rather than by output restoration; guard validation alone is 1.671 ms of
the 4.043 ms.

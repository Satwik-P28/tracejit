# Benchmarks

## Start here: real-world corpus (Phase AA, current `main`)

`benchmarks/realworld_v2/` is the maintained benchmark package. It measures 59
workloads across 12 families in three frozen splits, under three execution
policies, with randomized paired sampling, bootstrap intervals, raw nanosecond
samples, an independent whole-workspace oracle, and a results schema that
`validate.py` enforces.

```bash
./benchmarks/realworld_v2/run.sh          # full run into benchmarks/results/phaseaa/
AA_MODE=smoke ./benchmarks/realworld_v2/run.sh
```

Rules the package enforces, and the older harnesses did not:

- Eligibility is reported per (environment tier, execution contract) cell. Tier A
  (strict native) and tier C (declared adaptation) are never summed; native rows
  are never averaged with `allocator-entropy-v1` or `compiler-runtime-v1` rows.
- A sample counts as a HIT only when TraceJIT reports `kind = "Reused"` for that
  invocation. A deoptimisation is a miss.
- A `Reused` decision whose independent oracle observation differs from native is
  an incorrect hit and fails the run.
- Missing tools, refusals and harness errors stay in the report with their own
  status. Nothing is filtered out of the count.

Current result on `main`: 1/49 strict-native eligible, 10/49 under
`allocator-entropy-v1`, 17/49 under `compiler-runtime-v1`, 0/5 adapted
workloads. Four workloads have positive cumulative savings, eight are slower
than native, and there are zero incorrect hits. Protocol:
[docs/REAL_WORLD_BENCHMARK_PROTOCOL.md](docs/REAL_WORLD_BENCHMARK_PROTOCOL.md).
Report: [docs/PHASE_AA_REPORT.md](docs/PHASE_AA_REPORT.md).

## Historical results (do not use as current claims)

The short-command loss remains [benchmarks/results/latest.md](benchmarks/results/latest.md), from commit `63e33638709aacfaed896ab587435e64c0ecea62` (v0.1.0 era). TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands; the Phase AA corpus re-measures that floor on `main`.

Warm-HIT destination-match restore skip was **evaluated and withdrawn** (final stabilization PR3 / #35). A synthetic back-to-back loop with no consumer of outputs can look like ~5 ms → ~3 ms; under `relatime`, reading outputs between runs yields **0% skip** because recorded atime is part of Obs and must match. See [benchmarks/results/final_stab_pr3/compare.md](benchmarks/results/final_stab_pr3/compare.md) and `skip_rate_study.json`. Do not cite the synthetic skip delta as a product result.

**Final mandate §4 package** (measuring commit `4ffde9a`, product ≡ `ed3bd39`/`7b9e7ca`): [benchmarks/results/final_stab_pr3/mandate_s4/SUMMARY.md](benchmarks/results/final_stab_pr3/mandate_s4/SUMMARY.md) — C transform, short floor, gzip, ETL, session, concurrency, warm/cold/direct/auto, census. Warm-HIT phase breakdown: [warm_hit_profile_breakdown.md](benchmarks/results/final_stab_pr3/warm_hit_profile_breakdown.md). PR4 gate logs: [final_stab_pr4/gates/](benchmarks/results/final_stab_pr4/gates/).

**Historical, v0.1.0.** The 312.913 ms to 3.972 ms result is the synthetic `c-transform` workload: it folds `benchmarks/workloads/c-transform/numbers.txt` and then runs 250,000,000 extra mix rounds (`EXTRA_ROUNDS` in `main.c`). It is a controlled CPU-bound command with a real file input and a real output file. It is not a compiler, an ETL job from production, or evidence that other commands scale the same way.

The duration sweep and later hit-path measurement are [benchmarks/results/break-even.md](benchmarks/results/break-even.md). The pre-optimization profile is [benchmarks/results/overhead-before.md](benchmarks/results/overhead-before.md). Do not replace those files by hand. `./scripts/benchmark.sh` refreshes only `latest.json` and `latest.md`. The sweep is `python3 benchmarks/harness/break_even.py --runs 30 --warmups 5`.

`./scripts/benchmark.sh` builds the release binary and generates JSON containing
the commit, kernel, CPU model, total memory, filesystem type and capacity, workload
hash, command, cache state, run count, median, and p95. Timed groups use
`benchmarks/workloads/c-etl`, a small C program that reads the committed CSV files
and does not call the clock, `getrandom`, or process-id syscalls. CPython is
analyzed in the same run and recorded as a refusal when it calls `gettid` or
`getrandom`; those samples are not cache-hit timings. The timed groups are:

1. untraced baseline
2. traced execution
3. end-to-end cached execution, including guard checks and restoration

The harness fixes `PYTHONHASHSEED=0` because an otherwise unseeded Python runtime
is allowed to call `getrandom`, which TraceJIT correctly classifies as
`NONDETERMINISTIC`. It sets `PYTHONDONTWRITEBYTECODE=1` so interpreter cache files
do not become workload outputs. It also sets
`GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and `MALLOC_ARENA_MAX=1` so glibc does
not draw allocator entropy or query the CPU count while sizing arenas. The
workload does not import hashlib, because OpenSSL initialization calls
`getrandom`. These are explicit workload settings. The classifier still refuses
any observed `getrandom`, clock, or unguarded kernel-state syscall. Results must
not be copied into README without retaining the generated JSON and exact commit.
The harness aborts if any sample in the cached group is not reported as `Reused`.

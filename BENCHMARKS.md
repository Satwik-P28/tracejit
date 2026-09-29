# Benchmarks

The short-command loss remains [benchmarks/results/latest.md](benchmarks/results/latest.md), from commit `63e33638709aacfaed896ab587435e64c0ecea62`. TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands.

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

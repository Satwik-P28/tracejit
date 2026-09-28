# Benchmarks

TraceJIT does not publish benchmark results in this repository yet.

`./scripts/benchmark.sh` builds the release binary and generates JSON containing
the commit, kernel, CPU model, total memory, filesystem type and capacity, workload
hash, command, cache state, run count, median, and p95. It reports these groups
separately:

1. untraced baseline
2. traced execution
3. end-to-end cached execution, including guard checks and restoration

The harness fixes `PYTHONHASHSEED=0` because an otherwise unseeded Python runtime
is allowed to call `getrandom`, which TraceJIT correctly classifies as
`NONDETERMINISTIC`. It sets `PYTHONDONTWRITEBYTECODE=1` so interpreter cache files
do not become workload outputs. Results must not be copied into README without
retaining the generated JSON and exact commit. The harness aborts if any sample in
the cached group is not reported as `Reused`.

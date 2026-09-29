# Benchmark harness

Build and run the harness on Linux x86_64:

```bash
./scripts/benchmark.sh --runs 30 --warmups 5
```

The harness sets `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`,
`GLIBC_TUNABLES=glibc.malloc.tcache_count=0`, and `MALLOC_ARENA_MAX=1`. It uses a
fresh TraceJIT cache for every cold sample and a separate stable cache for
guarded hits. It records baseline,
traced-cold, internal guard/restore, and end-to-end cached timings. It also checks
exit status, captured streams, output hashes, reversible input invalidation, and
the corresponding `tracejit explain` records. Results are written to
`benchmarks/results/latest.json` and `benchmarks/results/latest.md`.

Timed runs use `benchmarks/workloads/c-etl`. It reads the committed CSV inputs,
observes its current working directory and `TRACEJIT_REPORT_REGION`, performs a
fixed integer mix, and writes `output/report.json`. It uses no external service.
The Python ETL is analyzed in the same invocation and kept as a refusal record
when CPython calls `gettid` or `getrandom`.

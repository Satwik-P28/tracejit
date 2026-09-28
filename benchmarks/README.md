# Benchmark harness

Build and run the harness on Linux x86_64:

```bash
./scripts/benchmark.sh --runs 30 --warmups 5
```

The harness sets `PYTHONHASHSEED=0`, uses a fresh TraceJIT cache for every cold
sample, and uses a separate stable cache for guarded hits. It records baseline,
traced-cold, internal guard/restore, and end-to-end cached timings. It also checks
exit status, captured streams, output hashes, reversible input invalidation, and
the corresponding `tracejit explain` records. Results are written to
`benchmarks/results/latest.json` and `benchmarks/results/latest.md`.

The Python ETL workload reads committed CSV inputs, observes its current working
directory and `TRACEJIT_REPORT_REGION`, performs deterministic CPU work, and writes
`output/report.json`. It uses no external service.

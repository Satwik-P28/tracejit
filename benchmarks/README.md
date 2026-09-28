# Benchmark harness

Build and run the harness on Linux x86_64:

```bash
./scripts/benchmark.sh --runs 7
```

The harness sets `PYTHONHASHSEED=0`, uses an isolated TraceJIT cache, measures the
untraced workload, tracing path, and end-to-end cached path separately, and emits
JSON. It does not edit the README or publish a result automatically. Preserve the
JSON alongside the exact commit when reporting numbers. The cached group is
accepted only when every measured invocation reports `Reused`.

The Python ETL workload reads committed CSV inputs, observes its current working
directory and `TRACEJIT_REPORT_REGION`, performs deterministic CPU work, and writes
`output/report.json`. It uses no external service.

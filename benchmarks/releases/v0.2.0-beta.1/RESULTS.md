# TraceJIT 0.2.0-beta.1 release benchmarks

Commit: `cdb307be9160b93318603005373a0a9f69b84219`  
Binary SHA-256: `5a1100c5fd92dd7f2593451932d1ba93a2bd1f83d8681bb18861a4bc246db990`  
Runs per condition: 20, warmups: 3  
Generated: 2026-11-17T22:37:40Z

Raw per-scenario JSON is in this directory. All samples are wall-clock
process times measured with `time.perf_counter_ns`. Confidences are
percentile bootstrap 95% intervals for the median.

| Scenario | Kind | Condition | Median | p95 | 95% CI (median) | Runs |
| --- | --- | --- | ---: | ---: | --- | ---: |
| cpu_transform | synthetic | direct | 333.103 ms | 369.034 ms | 330.591–359.719 ms | 20 |
| cpu_transform | synthetic | cold_trace | 374.616 ms | 409.539 ms | 361.794–384.686 ms | 20 |
| cpu_transform | synthetic | warm_hit | 8.839 ms | 10.559 ms | 8.691–9.937 ms | 20 |
| short_command | synthetic | direct | 0.826 ms | 0.863 ms | 0.820–0.835 ms | 20 |
| short_command | synthetic | warm_hit | 6.408 ms | 7.498 ms | 6.341–6.819 ms | 20 |
| compression | controlled | direct | 117.237 ms | 144.897 ms | 116.438–119.054 ms | 20 |
| compression | controlled | cold_trace | 428.127 ms | 525.813 ms | 412.132–434.839 ms | 20 |
| compression | controlled | warm_hit | 289.334 ms | 314.686 ms | 263.295–294.632 ms | 20 |
| etl_session | controlled | direct | 89.029 ms | 115.430 ms | 88.681–92.094 ms | 20 |
| etl_session | controlled | tracejit | 125.349 ms | 161.736 ms | 118.581–135.922 ms | 20 |
| large_restore | synthetic | direct | 142.829 ms | 162.261 ms | 137.764–151.598 ms | 10 |
| large_restore | synthetic | cold_trace | 588.896 ms | 615.320 ms | 565.681–602.314 ms | 10 |
| large_restore | synthetic | warm_hit | 193.251 ms | 220.113 ms | 190.388–201.364 ms | 10 |
| cache_invalidation | controlled | direct_after_mutation | 15.686 ms | 41.994 ms | 10.180–21.322 ms | 10 |
| cache_invalidation | controlled | tracejit_after_mutation | 31.616 ms | 41.590 ms | 27.402–35.523 ms | 10 |
| concurrency | controlled | cold_8_concurrent | 72.440 ms | 116.454 ms | 53.711–116.454 ms | 5 |
| concurrency | controlled | warm_8_concurrent | 22.125 ms | 22.980 ms | 20.967–22.980 ms | 5 |
| compatibility_census | real-world | (no timed conditions) | — | — | — | 0 |
| make_ninja_competitive | real-world | (no timed conditions) | — | — | — | 0 |

## Scenario notes and refusals

### cpu_transform

Committed C transform: folds numbers.txt, then 250,000,000 fixed mix rounds.
- Output report.txt is identical across direct, traced, and reused runs.

### short_command

/bin/true: the fixed cost of a warm hit with no useful work to save.
- A warm hit that costs more than the command itself is a documented loss.

### compression

gzip -9 -n -c over a deterministic 4 MiB file; compressed bytes are captured stdout.
- probe_cold_ns=671530796
- probe_warm_ns=292982349

### etl_session

10 sequential runs of the committed C ETL, direct versus one trace plus nine hits.
- Session totals include every process launch; a hit that costs more than the command loses.

### large_restore

64 MiB deterministic output file. Warm hits pay output materialisation and fsync.
- Output SHA-256 is verified after every warm hit before the sample is accepted.

### cache_invalidation

sales.csv is mutated after priming. TraceJIT must deoptimise and recompute, never reuse.
- Every measured run was required to report cache_decision=Deoptimized.

### concurrency

Eight simultaneous /bin/true invocations sharing one cache, cold and warm.
- All eight processes must exit 0; warm batches must all report Reused.

### compatibility_census

Unmodified real-world command census (eligibility, refusals, hits).
- Raw harness output is in the adjacent log and JSON files.
- exit_status=0

### make_ninja_competitive

Make/Ninja/plain-CAS comparison on a rebuild workload; missing tools are skipped, not scored.
- Raw harness output is in the adjacent log and JSON files.
- exit_status=0

## Reading these numbers

- Synthetic scenarios are committed workloads built for this repository.
- Controlled scenarios add fixed environment settings so glibc and CPython do not draw entropy.
- Real-world scenarios run unmodified third-party tools.
- Negative results (warm losses, refusals, weak eligibility) are kept, not filtered.
- These results apply to this commit and this host only.

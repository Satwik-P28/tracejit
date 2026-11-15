# Mandate §4 snapshot

commit `4ffde9aa82ba91b4f71a587d5c8acb3136ad96a7`

## Hit floor / ETL-like
- direct: median 0.337 ms p95 0.696 ms n=30 ci=[330782, 350833]
## C transform throughput
- direct: median 32.524 ms p95 33.087 ms ci=[32481096, 32568869]
## Session
- tracejit cumulative 177.046 ms direct 35.452 ms kinds={'Executed': 1, 'Reused': 30}
## Concurrency
- keys=['all_success', 'kind_counts', 'results', 'wall_ns', 'workers']
## Short + compression
- true_direct: median 0.351 ms p95 0.610 ms ci=[317606, 364017]
- true_cold: median 4.544 ms p95 6.058 ms ci=[4122805, 5183266]
- true_warm: median 4.475 ms p95 5.236 ms ci=[4207541, 4699607]
- gzip64k_direct: median 0.847 ms p95 0.960 ms ci=[716091, 878141]
- gzip64k_cold: median 4.686 ms p95 6.329 ms ci=[4217139, 5046993]
- gzip64k_warm: median 4.805 ms p95 6.306 ms ci=[4141254, 5317839]
## Harness ETL
- baseline 1.374 ms cached 4.430 ms traced_cold 8.289 ms
## Census
- eligibility 0.03125 reused 1/32

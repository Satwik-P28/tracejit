# Mandate §4 snapshot

Measured on tip `4ffde9a` (product ≡ `ed3bd39`); packaging commit may follow.  
Nothing deferred to PR4. Raw JSON under this directory.

## C transform (`final_p1/e2e.json` throughput)

| Mode | Median ms | p95 ms | 95% CI median ns |
| --- | ---: | ---: | --- |
| direct | 32.524 | 33.087 | [32481096, 32568869] |
| cold_trace | 43.676 | 46.988 | [42387140, 44311846] |
| warm_hit | 5.303 | 6.477 | [4881492, 5796698] |
| auto | 7.061 | 8.297 | [5178544, 7559605] |

## Short-command `/bin/true` (`short_and_compression.json`)

| Mode | Median ms | p95 ms | 95% CI median ns |
| --- | ---: | ---: | --- |
| direct | 0.351 | 0.610 | [317606, 364017] |
| cold | 4.544 | 6.058 | [4122805, 5183266] |
| warm | 4.475 | 5.236 | [4207541, 4699607] |

## Compression gzip 64KiB

| Mode | Median ms | p95 ms | 95% CI median ns |
| --- | ---: | ---: | --- |
| direct | 0.847 | 0.960 | [716091, 878141] |
| cold | 4.686 | 6.329 | [4217139, 5046993] |
| warm (Reused) | 4.805 | 6.306 | [4141254, 5317839] |

## ETL hit floor + harness

| Mode | Median ms | p95 ms | 95% CI median ns |
| --- | ---: | ---: | --- |
| direct | 0.337 | 0.696 | [330782, 350833] |
| cold_trace | 7.783 | 10.457 | [7517221, 8578051] |
| warm_hit | 4.332 | 6.275 | [3893579, 4610234] |
| auto | 3.252 | 4.836 | [3072265, 3390729] |

Harness ETL (`harness_etl/latest.json`): baseline 1.374 ms, traced_cold 8.289 ms, cached 4.430 ms.

## Session / concurrency / census

- Session: TraceJIT cumulative 177.046 ms vs direct 35.452 ms; kinds Executed=1 Reused=30
- Concurrency: `e2e.json` section9.concurrency
- Census: eligibility **1/32** (`census/census.json`)

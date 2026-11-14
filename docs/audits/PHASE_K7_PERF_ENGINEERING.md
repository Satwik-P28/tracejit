# Phase K7 — Professional performance engineering

Date: 2026-11-14  
Base: `f148228` (post K5)  
Branch: `cursor/phase-k7-perf-prepare-cached-7fee`

## Method

Harness: `scripts/phase_k7_perf_micro.py`  
Shapes: `c-etl`, `plain_file_read`  
Protocol: release binary, 5 warmups + 30 runs, phase timing on, inherited fds >2 closed.

Raw: `benchmarks/results/phase_k7/{before,after,compare}.md|json`

## Attempted / shipped levers

| Lever | Obs safety | Result |
| --- | --- | --- |
| SQLite `prepare_cached` on candidate query | unchanged | No significant wall win alone; kept as hygiene |
| Staging `sync_data` instead of `sync_all` | Obs unchanged; data sync retained; CAS puts still `sync_all` | Small measured warm win on `plain_file_read` (−0.208 ms wall, −0.139 ms cas_restore) |
| Drop staging sync entirely | durability | **Rejected** (Phase F) |
| Daemon / skip process startup | architecture | **Not pursued** (prior reject) |

## Measured before → after (this host)

| Shape | Warm wall ms | cas_restore ms |
| --- | ---: | ---: |
| c-etl | 3.849 → 3.794 | 1.030 → 1.019 |
| plain_file_read | 3.988 → 3.780 | 1.177 → 1.038 |

## Non-claims

- Does not make short ETL faster than direct execution.
- Does not invent benchmark numbers; see JSON artifacts.
- Does not weaken guard/CAS content verification.

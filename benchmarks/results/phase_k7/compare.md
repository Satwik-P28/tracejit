# Phase K7 before/after

- Before commit: `f148228a66c76784e3e36576c9eaf8602b21a23e` binary `59de7a6194fc4405…`
- After label: `after-sync-data` binary `164a7c0b0007b187…`
- Host: Linux-6.12.113+-x86_64-with-glibc2.39, cpus=4
- Method: 5 warmups + 30 runs; `TRACEJIT_PHASE_TIMING`; fds >2 closed before exec
- Raw: `before.json`, `after.json`

| Shape | Warm wall before ms | Warm wall after ms | Δ wall | cas_restore before | cas_restore after | Δ cas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| c-etl | 3.849 | 3.794 | -0.055 | 1.030 | 1.019 | -0.011 |
| plain_file_read | 3.988 | 3.780 | -0.208 | 1.177 | 1.038 | -0.139 |

## Changes under test

1. `prepare_cached` for the hit-path candidate SQL (alone: no significant wall win; kept as hygiene).
2. Staging restore uses `sync_data` instead of `sync_all` (data durability retained; temp inode metadata not part of Obs). CAS `put_bytes` still uses `sync_all`.

## Notes

- Numbers measured on this host; not invented.
- Short-ETL remains a net loss vs direct baseline (see `benchmarks/results/latest.md`).
- Dropping staging sync entirely remains **rejected** (Phase F durability).
- Process startup still dominates short warm hits.

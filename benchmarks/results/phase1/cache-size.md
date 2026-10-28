# Cache size for one saved execution

Measured on the Phase 1 host at commit `6358522e2eee7b8aa7f59acca88e061f72166d8e`
plus the Phase 1 fixes, after one cold trace of `benchmarks/workloads/c-etl/etl`
followed by one cache hit (`TRACEJIT_CACHE_DIR` pointed at a fresh directory).

| Item | Bytes |
| --- | ---: |
| Total on disk (6 files) | **77,104** |
| `db.sqlite3` (SQLite metadata plus the record row) | 53,248 |
| `executions/<id>.json` (stored record: effects, guards, identity) | 23,580 |
| `objects/` total (content-addressed blobs) | 21,258 |
| — the workload's `report.json` output | 21,212 |
| — captured stdout | 46 |
| — captured stderr (empty) | 0 |
| `.tracejit-cache-v1` ownership marker | 18 |

Notes:

- The record is dominated by per-execution metadata (SQLite page allocation plus
  the stored effect/guard JSON), not by output bytes: this is a small command
  whose output is 21 KB.
- Output bytes are stored once, content-addressed. Two identical executions
  therefore do not double the blob footprint.
- Output-restoration cost is the `CAS restore` phase of the hit path: median
  **0.910 ms** of a 4.0 ms cache hit on this host. The full phase table is in
  [PHASE1_BENCHMARK_REPORT.md](../../../docs/audits/PHASE1_BENCHMARK_REPORT.md).

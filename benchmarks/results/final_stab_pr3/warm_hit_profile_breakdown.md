# Warm-HIT phase breakdown (final tip)

Commit: `4ffde9aa82ba91b4f71a587d5c8acb3136ad96a7` (product crates ≡ `ed3bd39`).  
Shape: c-etl warm HIT, 5 warmups + 40 runs, fds >2 closed, `TRACEJIT_PHASE_TIMING`.  
Raw: `warm_hit_phase_breakdown.json`.

Wall median **4.619 ms**, p95 **see JSON**.  
`process_startup_ns` is `/proc` starttime–based and **CLK_TCK-quantized** — not trustworthy below ~10 ms; exclude it when ranking in-process work.

## Where the time goes (median ms)

| Phase | Median ms | Role |
| --- | ---: | --- |
| cas_restore | 1.163 | Stage CAS→temp, content hash, `sync_data`, parent dir sync, restore-intent, rename |
| guard_validation | 0.430 | First `validate_all` (hashing inputs). A second TOCTOU recheck runs before restore; timed into wall, not a separate field |
| sqlite_query | 0.173 | Candidate lookup |
| record_decode | 0.134 | Decode stored execution |
| sqlite_schema | 0.109 | `PRAGMA user_version` (init skipped when current) |
| identity_prepare | 0.085 | Executable hash + runtime identity |
| sqlite_open | 0.078 | Open DB connection |
| cli_parse | 0.077 | CLI |
| present | 0.022 | Report presentation |
| stdio_replay | 0.008 | Load stdout/stderr CAS objects |
| cache_prepare | 0.007 | Cache root prep |
| lookup_key | 0.004 | Lookup key |
| decision_persist | 0.0 | Admission sample (always mode: none) |
| process_startup | ~6.2* | Coarse proc tick — **do not rank** |

\*Attributed in-process (ex-startup) ≈ **2.29 ms**.

## Candidate optimizations (none landed)

| Candidate | Low-risk? | Measurable? | Verdict |
| --- | --- | --- | --- |
| Skip restore when destinations match (incl. atime) | Yes for Obs *if* atime kept | Yes | **Withdrawn**: 0% skip when outputs are consumed under `relatime` (`skip_rate_study.json`) |
| Drop / weaken staging `sync_data` or intent sync | **No** (durability) | Yes | Rejected (Phase F / K7) |
| Skip restore-intent for single-file | **No** (HIT-refuse after hard-kill semantics) | Yes | Rejected |
| Skip or weaken pre-restore guard recheck | **No** (safety ordering) | Yes | Rejected |
| SQLite `synchronous=NORMAL` / drop WAL FULL | **No** (durability) | Yes | Rejected |
| Daemon / persistent SQLite connection | Architecture change | Yes | Out of V1 scope |
| Parallelize guard hashing | Medium (ordering/races) | Maybe | Not landed; complexity vs ~0.4 ms |
| Larger restore copy buffer / `copy_file_range` | Yes | Only large payloads | Not landed: ETL objects are tiny; cost is fsync/intent |
| Cache `PRAGMA user_version` in-process | Yes | ~0.1 ms | Insignificant vs wall; not landed |
| Compact JSON / avoid admission on always | Already done historically | — | No further change |

**Outcome: no safe, material optimization found** on the warm-HIT path that preserves Obs, durability, and guard ordering. The floor remains process overhead + mandatory restore sync + guards.

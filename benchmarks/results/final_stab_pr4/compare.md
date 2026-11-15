# Final stabilization PR3: warm-hit profile (measurement only)

Host: Linux 6.12.113+ x86_64, 4 CPUs, glibc 2.39.  
Tip: `4ffde9aa82ba91b4f71a587d5c8acb3136ad96a7`.  
`git diff ed3bd39..4ffde9a -- crates/` → **empty** (no product code change).

## Decision

Destination-match restore skip was **evaluated and withdrawn**. Keep the skip-rate study as a **negative result**. Do not present synthetic no-consumer timings as a product improvement.

## crates/ diff

```
$ git diff ed3bd39..4ffde9a --stat -- crates/
(empty)
```

## Skip-rate negative result (`skip_rate_study.json`)

| Scenario | Consume output between HITs? | Skips | Full | Skip rate |
| --- | --- | ---: | ---: | ---: |
| c-etl back-to-back | no | 40 | 0 | 1.00 |
| c-etl consume `report.json` | yes | 0 | 40 | **0.00** |
| plain back-to-back | no | 40 | 0 | 1.00 |
| plain consume | yes | 0 | 40 | **0.00** |
| session-like ETL consume | yes | 0 | 30 | **0.00** |

Atime remains part of Obs; comparison was not relaxed.

## Warm-HIT profile (final tip)

See `warm_hit_profile_breakdown.md` + `warm_hit_phase_breakdown.json`.  
Largest attributable costs: **cas_restore ~1.16 ms**, **guard_validation ~0.43 ms**, SQLite query/decode ~0.3 ms.  
**No safe optimization landed.**

## Three scenarios on tip after drop (`three_scenario_after_drop.json`)

Full restore always (n=40): matching wall median 5.260 ms; deleted 6.219 ms; diverged small 4.134 ms; diverged 2 MiB 4.217 ms.

## Withdrawn probe artifacts (not product claims)

Renamed under `withdrawn_skip_probe_*` (phase_k7 / warm profile / harness / census taken while skip was enabled). Use only as evidence the opt was tried.

## Mandate §4 benches

Fresh package on tip: `mandate_s4/` (see that directory’s `PROVENANCE.json`).

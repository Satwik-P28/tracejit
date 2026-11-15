# Final stabilization PR3: warm-hit profile (opt withdrawn)

Host: Linux 6.12.113+ x86_64, 4 CPUs, glibc 2.39.

## Decision

**The destination-match restore skip was withdrawn.** It only fired in synthetic
back-to-back warm HIT loops where nothing reads outputs between runs. Under
default Linux `relatime`, any consumer read after a restore advances atime when
`atime <= mtime` (the post-restore case). Obs and full restore both treat recorded
atime as part of v2 metadata, so the skip must compare atime; relaxing that would
make skip ≠ full restore. Measured skip rate with output consumption: **0/40**.

Do **not** cite 5.2 ms → 3.4 ms as a product win. That delta is the synthetic
no-consumer loop only (`skip_rate_study.json` scenario `c-etl-back-to-back`).

PR3 deliverable after withdrawal: profile + skip-rate study + before benches on
`ed3bd39`, tip restored to full-restore behavior (same as `ed3bd39` restore path).

## Provenance

| Artifact | Commit / binary |
| --- | --- |
| `phase_k7_before.json`, `warm_hit_profile_before.json`, `harness_before/`, `census_before/` | `ed3bd39` |
| `skip_rate_study.json` (probe **with** skip) | working tree on `7b0abf9` + skip WIP; see file |
| `three_scenario_after_drop.json` | tip after skip removed (binary SHA matches `ed3bd39` release) |
| `phase_k7_after.json` / harness_after | **historical probe with skip — not a claimed product result** |

## Skip rate (same machine, n=40 unless noted)

| Scenario | Consume output between HITs? | Skips | Full restores | Skip rate | Warm wall median ms |
| --- | --- | ---: | ---: | ---: | ---: |
| c-etl back-to-back | no | 40 | 0 | 1.00 | 3.309 |
| c-etl consume `report.json` | yes | 0 | 40 | 0.00 | 4.032 |
| plain back-to-back | no | 40 | 0 | 1.00 | 3.315 |
| plain consume outputs | yes | 0 | 40 | 0.00 | 4.087 |
| session-like ETL consume | yes | 0 | 30 | 0.00 | 4.836 |

Classification: `cas_restore_ns < 200_000` ⇒ skip. Raw: `skip_rate_study.json`.

## Three scenarios after drop (full restore always) — `three_scenario_after_drop.json`

| Scenario | n | Warm wall median ms | p95 ms | cas_restore median ns |
| --- | ---: | ---: | ---: | ---: |
| outputs present & matching | 40 | 5.260 | 7.055 | 1_872_162 |
| outputs deleted | 40 | 6.219 | 7.166 | 2_839_471 |
| outputs diverged (small) | 40 | 4.134 | 5.694 | 900_312 |
| outputs diverged (2 MiB) | 40 | 4.217 | 6.533 | 963_048 |

Headline for matching warm HIT remains the ~5 ms full-restore floor on this host, not the withdrawn 3.4 ms skip figure.

## Atime / Obs (why we did not relax the comparison)

- Full restore sets mode, uid, gid, atime, mtime from the v2 artifact (`stage_output`).
- `INVARIANTS.yaml` Obs includes `regular_file_output_metadata_v2_when_present`.
- Skip that ignored atime would leave a post-read atime while full restore would reset it → distinguishable under Obs.
- Therefore atime stays required for any skip; with relatime + consumers, skip rate is ~0 → **drop**.

## Census

Before `ed3bd39` and after-with-skip probe both 1/32 eligible; restore path does not change classification. Tip after drop: same classifier.

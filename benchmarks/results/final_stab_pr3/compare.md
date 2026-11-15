# Final stabilization PR3: warm-hit before/after

Host: Linux 6.12.113+ x86_64, 4 CPUs, glibc 2.39.  
Method: release binary; `TRACEJIT_PHASE_TIMING`; fds >2 closed for phase_k7; official `scripts/benchmark.sh`; `benchmarks/realworld/census.py`.

**Do not treat numbers from other commits as fresh.** Each artifact records its `commit` field.

| Arm | Commit | Binary role |
| --- | --- | --- |
| Before | `ed3bd39fabd2c809a25059740ccc553b935b9039` | main tip after #34 (audit) |
| After | `5c50d111b0c567863163a1d49023cb2bb12d34a9` | skip-restore when destinations already match |

Raw JSON: `phase_k7_{before,after}.json`, `warm_hit_profile_{before,after}.json`, `harness_{before,after}/latest.json`, `census_{before,after}/census.json`, `PROVENANCE.json`.

## Profile (c-etl warm HIT phase medians, ms)

| Phase | Before (`ed3bd39`) | After (`5c50d11`) |
| --- | ---: | ---: |
| warm wall | 5.601 | 3.381 |
| cas_restore | 2.103 | 0.031 |
| guard_validation | 0.432 | 0.424 |
| sqlite_query | 0.178 | 0.164 |
| record_decode | 0.133 | 0.132 |

Largest measured warm cost before the change was `cas_restore` (staging + `sync_data` + restore-intent + rename) on destinations that already matched the CAS object.

## phase_k7 microbench (5 warmups + 30 runs)

| Shape | Warm wall before ms | Warm wall after ms | cas_restore before | cas_restore after |
| --- | ---: | ---: | ---: | ---: |
| c-etl | 5.219 | 3.409 | 1.861 | 0.031 |
| plain_file_read | 5.475 | 3.392 | 1.996 | 0.027 |

## Official harness (`benchmarks/workloads/c-etl`)

| Metric | Before (`ed3bd39`) | After (`5c50d11`) |
| --- | ---: | ---: |
| cached median ns | 5_004_024 | 2_900_365 |
| guard_check median ns | 3_130_513 | 1_090_955 |
| baseline median ns | 1_369_003 | 1_439_502 |
| output_equivalent | PASS | PASS |

## Census (native `admission=always`)

| | Before | After |
| --- | ---: | ---: |
| eligibility_rate | 0.03125 (1/32) | 0.03125 (1/32) |
| reused | 1 | 1 |
| refused | 30 | 30 |

Eligibility unchanged (expected: restore fast path does not alter classification).

## Change under test

When every `OutputArtifact` already matches on-disk content (BLAKE3 via `O_NOATIME`) and metadata (mode/uid/gid/atime/mtime), `restore_outputs` returns without staging, parent fsync, restore-intent, or rename. Shape validation still runs; mismatch or `O_NOATIME` denial falls through to the existing durable path. CAS puts still `sync_all`; divergent destinations still full-restore.

Rejected for this PR: dropping staging sync, weakening guards, or skipping content verification.

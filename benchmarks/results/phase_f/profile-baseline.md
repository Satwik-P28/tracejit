# Phase F profile (baseline)

Commit `5e94d4c58d11a80fd5ac03d58b7564afc4638ec0` · binary `d22e0db2fa561127` · 5 warmups + 30 runs.

## Host tooling

- perf available: `False`
- strace available: `False`
- perf_event_paranoid: `2`
- PMU devices: `breakpoint, kprobe, msr, power, software, tracepoint, uprobe`
- hardware cpu PMU present: `False`

## Wall times

| Shape | cold ms | warm median | warm p95 | all reused |
| --- | ---: | ---: | ---: | --- |
| c-etl | 9.713 | 2.272 | 4.087 | True |
| plain_file_read | 12.557 | 3.499 | 5.646 | True |
| bin_true | 9.851 | 2.39 | 4.218 | True |

## Phase rank (warm median ms)

### c-etl

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.548 | 0.8345 |
| guard_validation_ns | 0.456 | 0.0686 |
| sqlite_query_ns | 0.13 | 0.0196 |
| record_decode_ns | 0.128 | 0.0193 |
| sqlite_schema_ns | 0.096 | 0.0144 |
| identity_prepare_ns | 0.093 | 0.014 |
| sqlite_open_ns | 0.072 | 0.0108 |
| cli_parse_ns | 0.071 | 0.0107 |
| present_ns | 0.022 | 0.0033 |
| lookup_key_ns | 0.014 | 0.0021 |
| cache_prepare_ns | 0.009 | 0.0014 |
| stdio_replay_ns | 0.009 | 0.0014 |

### plain_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 6.243 | 0.7619 |
| cas_restore_ns | 0.744 | 0.0908 |
| guard_validation_ns | 0.497 | 0.0607 |
| sqlite_query_ns | 0.152 | 0.0186 |
| record_decode_ns | 0.139 | 0.017 |
| identity_prepare_ns | 0.103 | 0.0126 |
| sqlite_schema_ns | 0.102 | 0.0124 |
| cli_parse_ns | 0.078 | 0.0095 |
| sqlite_open_ns | 0.076 | 0.0093 |
| present_ns | 0.026 | 0.0032 |
| lookup_key_ns | 0.017 | 0.0021 |
| stdio_replay_ns | 0.009 | 0.0011 |
| cache_prepare_ns | 0.008 | 0.001 |

### bin_true

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.569 | 0.8341 |
| guard_validation_ns | 0.468 | 0.0701 |
| sqlite_query_ns | 0.136 | 0.0204 |
| record_decode_ns | 0.12 | 0.018 |
| sqlite_schema_ns | 0.097 | 0.0145 |
| identity_prepare_ns | 0.093 | 0.0139 |
| cli_parse_ns | 0.072 | 0.0108 |
| sqlite_open_ns | 0.065 | 0.0097 |
| present_ns | 0.025 | 0.0037 |
| lookup_key_ns | 0.014 | 0.0021 |
| cache_prepare_ns | 0.009 | 0.0013 |
| stdio_replay_ns | 0.009 | 0.0013 |


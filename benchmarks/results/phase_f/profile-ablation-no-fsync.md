# Phase F profile (ablation-no-fsync)

Commit `780174869afa02a2587d76d7ac244d3595d5a034` · binary `3121b0f67f6f7f9a` · 3 warmups + 20 runs.

## Host tooling

- perf available: `False`
- strace available: `False`
- perf_event_paranoid: `2`
- PMU devices: `breakpoint, kprobe, msr, power, software, tracepoint, uprobe`
- hardware cpu PMU present: `False`

## Wall times

| Shape | cold ms | warm median | warm p95 | all reused |
| --- | ---: | ---: | ---: | --- |
| c-etl | 13.804 | 2.356 | 2.647 | True |
| plain_file_read | 16.323 | 2.417 | 2.66 | True |
| large_file_read | 68.209 | 12.182 | 13.46 | True |
| bin_true | 12.318 | 2.256 | 2.498 | True |

## Phase rank (warm median ms)

### c-etl

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.966 | 0.8458 |
| guard_validation_ns | 0.422 | 0.0598 |
| sqlite_query_ns | 0.134 | 0.019 |
| record_decode_ns | 0.129 | 0.0183 |
| identity_prepare_ns | 0.111 | 0.0157 |
| sqlite_schema_ns | 0.101 | 0.0143 |
| sqlite_open_ns | 0.076 | 0.0108 |
| cli_parse_ns | 0.075 | 0.0106 |
| present_ns | 0.021 | 0.003 |
| cache_prepare_ns | 0.008 | 0.0011 |
| stdio_replay_ns | 0.008 | 0.0011 |
| lookup_key_ns | 0.003 | 0.0004 |

### plain_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.902 | 0.8253 |
| guard_validation_ns | 0.434 | 0.0607 |
| record_decode_ns | 0.135 | 0.0189 |
| sqlite_query_ns | 0.135 | 0.0189 |
| cas_restore_ns | 0.134 | 0.0187 |
| identity_prepare_ns | 0.114 | 0.0159 |
| sqlite_schema_ns | 0.099 | 0.0138 |
| sqlite_open_ns | 0.082 | 0.0115 |
| cli_parse_ns | 0.077 | 0.0108 |
| present_ns | 0.022 | 0.0031 |
| cache_prepare_ns | 0.007 | 0.001 |
| stdio_replay_ns | 0.007 | 0.001 |
| lookup_key_ns | 0.003 | 0.0004 |

### large_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| cas_restore_ns | 7.627 | 0.4746 |
| process_startup_ns | 5.504 | 0.3425 |
| guard_validation_ns | 1.433 | 0.0892 |
| record_decode_ns | 0.532 | 0.0331 |
| sqlite_query_ns | 0.51 | 0.0317 |
| identity_prepare_ns | 0.124 | 0.0077 |
| sqlite_schema_ns | 0.108 | 0.0067 |
| sqlite_open_ns | 0.092 | 0.0057 |
| cli_parse_ns | 0.086 | 0.0054 |
| present_ns | 0.033 | 0.0021 |
| cache_prepare_ns | 0.008 | 0.0005 |
| stdio_replay_ns | 0.008 | 0.0005 |
| lookup_key_ns | 0.004 | 0.0002 |

### bin_true

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.982 | 0.8542 |
| guard_validation_ns | 0.429 | 0.0613 |
| sqlite_query_ns | 0.122 | 0.0174 |
| record_decode_ns | 0.113 | 0.0161 |
| identity_prepare_ns | 0.095 | 0.0136 |
| sqlite_schema_ns | 0.092 | 0.0131 |
| cli_parse_ns | 0.068 | 0.0097 |
| sqlite_open_ns | 0.06 | 0.0086 |
| present_ns | 0.024 | 0.0034 |
| stdio_replay_ns | 0.008 | 0.0011 |
| cache_prepare_ns | 0.007 | 0.001 |
| lookup_key_ns | 0.003 | 0.0004 |


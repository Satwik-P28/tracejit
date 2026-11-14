# Phase F profile (after-opts)

Commit `780174869afa02a2587d76d7ac244d3595d5a034` · binary `a00efdaec19ea98b` · 5 warmups + 30 runs.

## Host tooling

- perf available: `False`
- strace available: `False`
- perf_event_paranoid: `2`
- PMU devices: `breakpoint, kprobe, msr, power, software, tracepoint, uprobe`
- hardware cpu PMU present: `False`

## Wall times

| Shape | cold ms | warm median | warm p95 | all reused |
| --- | ---: | ---: | ---: | --- |
| c-etl | 13.292 | 2.328 | 2.435 | True |
| plain_file_read | 11.483 | 3.494 | 4.055 | True |
| large_file_read | 64.061 | 9.748 | 13.685 | True |
| bin_true | 9.22 | 2.155 | 2.399 | True |

## Phase rank (warm median ms)

### c-etl

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 6.193 | 0.8533 |
| guard_validation_ns | 0.432 | 0.0595 |
| sqlite_query_ns | 0.128 | 0.0176 |
| record_decode_ns | 0.123 | 0.0169 |
| identity_prepare_ns | 0.107 | 0.0147 |
| sqlite_schema_ns | 0.091 | 0.0125 |
| cli_parse_ns | 0.073 | 0.0101 |
| sqlite_open_ns | 0.07 | 0.0096 |
| present_ns | 0.022 | 0.003 |
| cache_prepare_ns | 0.008 | 0.0011 |
| stdio_replay_ns | 0.008 | 0.0011 |
| lookup_key_ns | 0.003 | 0.0004 |

### plain_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.572 | 0.7122 |
| cas_restore_ns | 1.128 | 0.1442 |
| guard_validation_ns | 0.451 | 0.0576 |
| sqlite_query_ns | 0.136 | 0.0174 |
| record_decode_ns | 0.131 | 0.0167 |
| identity_prepare_ns | 0.111 | 0.0142 |
| sqlite_schema_ns | 0.099 | 0.0127 |
| sqlite_open_ns | 0.079 | 0.0101 |
| cli_parse_ns | 0.077 | 0.0098 |
| present_ns | 0.02 | 0.0026 |
| cache_prepare_ns | 0.008 | 0.001 |
| stdio_replay_ns | 0.008 | 0.001 |
| lookup_key_ns | 0.004 | 0.0005 |

### large_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| cas_restore_ns | 5.947 | 0.4867 |
| process_startup_ns | 3.522 | 0.2883 |
| guard_validation_ns | 1.375 | 0.1125 |
| record_decode_ns | 0.522 | 0.0427 |
| sqlite_query_ns | 0.447 | 0.0366 |
| identity_prepare_ns | 0.107 | 0.0088 |
| sqlite_schema_ns | 0.098 | 0.008 |
| sqlite_open_ns | 0.075 | 0.0061 |
| cli_parse_ns | 0.073 | 0.006 |
| present_ns | 0.032 | 0.0026 |
| cache_prepare_ns | 0.008 | 0.0007 |
| stdio_replay_ns | 0.008 | 0.0007 |
| lookup_key_ns | 0.004 | 0.0003 |

### bin_true

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.463 | 0.8476 |
| guard_validation_ns | 0.418 | 0.0649 |
| sqlite_query_ns | 0.117 | 0.0182 |
| record_decode_ns | 0.109 | 0.0169 |
| identity_prepare_ns | 0.093 | 0.0144 |
| sqlite_schema_ns | 0.085 | 0.0132 |
| cli_parse_ns | 0.064 | 0.0099 |
| sqlite_open_ns | 0.056 | 0.0087 |
| present_ns | 0.022 | 0.0034 |
| stdio_replay_ns | 0.008 | 0.0012 |
| cache_prepare_ns | 0.007 | 0.0011 |
| lookup_key_ns | 0.003 | 0.0005 |


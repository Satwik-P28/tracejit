# Phase F profile (baseline-7801748)

Commit `780174869afa02a2587d76d7ac244d3595d5a034` · binary `d22e0db2fa561127` · 5 warmups + 30 runs.

## Host tooling

- perf available: `False`
- strace available: `False`
- perf_event_paranoid: `2`
- PMU devices: `breakpoint, kprobe, msr, power, software, tracepoint, uprobe`
- hardware cpu PMU present: `False`

## Wall times

| Shape | cold ms | warm median | warm p95 | all reused |
| --- | ---: | ---: | ---: | --- |
| c-etl | 16.766 | 2.401 | 2.637 | True |
| plain_file_read | 12.61 | 3.659 | 4.351 | True |
| large_file_read | 84.314 | 14.591 | 16.99 | True |
| bin_true | 7.484 | 2.115 | 2.337 | True |

## Phase rank (warm median ms)

### c-etl

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.505 | 0.8328 |
| guard_validation_ns | 0.438 | 0.0663 |
| sqlite_query_ns | 0.134 | 0.0203 |
| record_decode_ns | 0.13 | 0.0197 |
| identity_prepare_ns | 0.099 | 0.015 |
| sqlite_schema_ns | 0.099 | 0.015 |
| sqlite_open_ns | 0.076 | 0.0115 |
| cli_parse_ns | 0.073 | 0.011 |
| present_ns | 0.023 | 0.0035 |
| lookup_key_ns | 0.016 | 0.0024 |
| stdio_replay_ns | 0.009 | 0.0014 |
| cache_prepare_ns | 0.008 | 0.0012 |

### plain_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 6.072 | 0.7199 |
| cas_restore_ns | 1.169 | 0.1386 |
| guard_validation_ns | 0.452 | 0.0536 |
| sqlite_query_ns | 0.155 | 0.0184 |
| record_decode_ns | 0.139 | 0.0165 |
| identity_prepare_ns | 0.112 | 0.0133 |
| sqlite_schema_ns | 0.106 | 0.0126 |
| sqlite_open_ns | 0.086 | 0.0102 |
| cli_parse_ns | 0.084 | 0.01 |
| present_ns | 0.024 | 0.0028 |
| lookup_key_ns | 0.018 | 0.0021 |
| stdio_replay_ns | 0.009 | 0.0011 |
| cache_prepare_ns | 0.008 | 0.0009 |

### large_file_read

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| cas_restore_ns | 9.98 | 0.5301 |
| process_startup_ns | 5.817 | 0.309 |
| guard_validation_ns | 1.405 | 0.0746 |
| sqlite_query_ns | 0.627 | 0.0333 |
| record_decode_ns | 0.57 | 0.0303 |
| sqlite_schema_ns | 0.103 | 0.0055 |
| identity_prepare_ns | 0.101 | 0.0054 |
| sqlite_open_ns | 0.08 | 0.0042 |
| cli_parse_ns | 0.078 | 0.0041 |
| present_ns | 0.033 | 0.0018 |
| lookup_key_ns | 0.014 | 0.0007 |
| stdio_replay_ns | 0.009 | 0.0005 |
| cache_prepare_ns | 0.008 | 0.0004 |

### bin_true

| Phase | median ms | share of summed phases |
| --- | ---: | ---: |
| process_startup_ns | 5.624 | 0.8453 |
| guard_validation_ns | 0.434 | 0.0652 |
| sqlite_query_ns | 0.126 | 0.0189 |
| record_decode_ns | 0.114 | 0.0171 |
| sqlite_schema_ns | 0.09 | 0.0135 |
| identity_prepare_ns | 0.086 | 0.0129 |
| cli_parse_ns | 0.066 | 0.0099 |
| sqlite_open_ns | 0.064 | 0.0096 |
| present_ns | 0.021 | 0.0032 |
| lookup_key_ns | 0.013 | 0.002 |
| stdio_replay_ns | 0.008 | 0.0012 |
| cache_prepare_ns | 0.007 | 0.0011 |


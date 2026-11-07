# Warm-hit latency profile

Binary `b0576fb19473ab15` · 25 interleaved warm runs per shape.

| Shape | cold ms | median ms | min ms | p95 ms | sum of phases ms |
| --- | --- | --- | --- | --- | --- |
| native_file | 254.902 | 250.215 | 241.562 | 259.932 | 0 |
| native_devnull | 250.012 | 254.084 | 247.701 | 261.415 | 0 |
| tracejit_file | 309.566 | 17.408 | 13.507 | 21.007 | 18.169 |
| tracejit_devnull | 308.785 | 14.076 | 11.664 | 25.596 | 16.005 |
| tracejit_json | 404.969 | 85.235 | 76.175 | 93.166 | 84.75 |
| tracejit_make | 310.904 | 2.809 | 2.268 | 3.396 | 0 |
| native_make | 2.809 | 2.332 | 1.898 | 3.091 | 0 |
| tracejit_true | 19.023 | 14.34 | 13.441 | 17.695 | 11.593 |

## Median phases (ms)

| Shape | cache_prepare_ns | cas_restore_ns | cli_parse_ns | decision_persist_ns | guard_validation_ns | identity_prepare_ns | lookup_key_ns | present_ns | process_startup_ns | record_decode_ns | sqlite_open_ns | sqlite_query_ns | sqlite_schema_ns | stdio_replay_ns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| native_file |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| native_devnull |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| tracejit_file | 0.024 | 0.001 | 0.128 | 2.825 | 4.614 | 0.223 | 0.011 | 1.487 | 6.284 | 0.249 | 0.188 | 0.113 | 0.468 | 1.554 |
| tracejit_devnull | 0.023 | 0.001 | 0.109 | 2.353 | 4.479 | 0.205 | 0.009 | 0.04 | 6.365 | 0.226 | 0.161 | 0.092 | 0.368 | 1.574 |
| tracejit_json | 0.023 | 0.001 | 0.108 | 2.577 | 4.459 | 0.207 | 0.009 | 69.926 | 5.089 | 0.223 | 0.165 | 0.097 | 0.374 | 1.492 |
| tracejit_make |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| native_make |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| tracejit_true | 0.025 | 0.001 | 0.121 | 2.408 | 1.115 | 0.171 | 0.011 | 0.041 | 6.726 | 0.225 | 0.189 | 0.101 | 0.435 | 0.024 |

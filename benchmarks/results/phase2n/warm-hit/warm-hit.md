# Warm-hit latency profile

Binary `eb11091e8d2037b4` · 25 interleaved warm runs per shape.

| Shape | cold ms | median ms | min ms | p95 ms | sum of phases ms |
| --- | --- | --- | --- | --- | --- |
| native_file | 250.65 | 251.668 | 240.372 | 271.208 | 0 |
| native_devnull | 248.124 | 251.349 | 247.142 | 268.3 | 0 |
| tracejit_file | 314.838 | 12.789 | 10.364 | 20.39 | 15.21 |
| tracejit_devnull | 308.306 | 10.39 | 8.293 | 16.384 | 14.123 |
| tracejit_json | 360.173 | 61.856 | 54.64 | 77.031 | 63.453 |
| tracejit_make | 318.21 | 17.736 | 14.656 | 27.098 | 18.742 |
| native_make | 256.668 | 258.91 | 244.492 | 278.099 | 0 |
| tracejit_true | 23.941 | 5.296 | 4.352 | 8.11 | 9.58 |

## Median phases (ms)

| Shape | cache_prepare_ns | cas_restore_ns | cli_parse_ns | decision_persist_ns | guard_validation_ns | identity_prepare_ns | lookup_key_ns | present_ns | process_startup_ns | record_decode_ns | sqlite_open_ns | sqlite_query_ns | sqlite_schema_ns | stdio_replay_ns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| native_file |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| native_devnull |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| tracejit_file | 0.027 | 0.001 | 0.155 | 0.0 | 4.969 | 0.246 | 0.012 | 1.44 | 5.774 | 0.248 | 0.217 | 0.223 | 0.377 | 1.521 |
| tracejit_devnull | 0.025 | 0.001 | 0.131 | 0.0 | 4.817 | 0.214 | 0.011 | 0.024 | 6.638 | 0.211 | 0.189 | 0.203 | 0.316 | 1.343 |
| tracejit_json | 0.025 | 0.001 | 0.122 | 0.0 | 5.141 | 0.23 | 0.01 | 49.636 | 5.889 | 0.238 | 0.183 | 0.19 | 0.289 | 1.499 |
| tracejit_make | 0.028 | 0.001 | 0.148 | 0.0 | 5.228 | 0.257 | 0.013 | 1.523 | 8.904 | 0.271 | 0.216 | 0.232 | 0.355 | 1.566 |
| native_make |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| tracejit_true | 0.028 | 0.001 | 0.141 | 0.0 | 1.151 | 0.186 | 0.012 | 0.026 | 6.988 | 0.236 | 0.219 | 0.206 | 0.362 | 0.024 |

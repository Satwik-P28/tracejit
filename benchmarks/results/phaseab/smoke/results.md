# TraceJIT Phase AA real-world benchmark

Schema `tracejit.realworld.results/v1` · commit `fd6d0041ae731784c5e9453bff8accca96791ca1` · binary `d2f6173562e940e4`

Eligibility is reported per environment tier and execution policy. Tier A (strict native) and tier C (declared adaptation) are never summed, and native-contract rows are never averaged with `allocator-entropy-v1` rows.

## Eligibility

| Tier / policy | Workloads | Attempted | Reused | Refused | Other | Rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A/compiler-runtime-v1 | 19 | 19 | 9 | 10 | 0 | 0.474 |
| A/native | 19 | 19 | 1 | 18 | 0 | 0.053 |
| C/compiler-runtime-v1 | 2 | 1 | 0 | 1 | 0 | 0.000 |
| C/native | 2 | 1 | 0 | 1 | 0 | 0.000 |

## Workloads

| Workload | Family | Tier | Policy | Status | Decision | Direct median | Warm median | Cold median | Break-even | Assessment |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `awk-reduce` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `awk-reduce` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `c-numeric-integration` | scientific | A | compiler-runtime-v1 | reused | Executed | 345.433 ms | 9.413 ms | 370.634 ms | 1 | clear_win |
| `c-numeric-integration` | scientific | A | native | refused | Executed | - | - | - | - | ineligible |
| `cppcheck-project` | analysis | C | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `cppcheck-project` | analysis | C | native | tool_unavailable | - | - | - | - | - | unavailable |
| `fs-delete-recreate` | filesystem | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-delete-recreate` | filesystem | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-heavy-tu` | compiler | A | compiler-runtime-v1 | reused | Executed | 508.726 ms | 68.650 ms | 810.782 ms | 1 | clear_win |
| `gcc-cc-heavy-tu` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-small-tu` | compiler | A | compiler-runtime-v1 | reused | Executed | 75.069 ms | 60.207 ms | 257.727 ms | 13 | marginal_win |
| `gcc-cc-small-tu` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-fanalyzer` | analysis | A | compiler-runtime-v1 | reused | Executed | 21.993 ms | 60.445 ms | 171.670 ms | - | loss |
| `gcc-fanalyzer` | analysis | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gzip-6-stdout` | compression | A | compiler-runtime-v1 | reused | Executed | 5.796 ms | 5.474 ms | 29.845 ms | 75 | indistinguishable |
| `gzip-6-stdout` | compression | A | native | reused | Executed | 5.585 ms | 6.295 ms | 35.537 ms | - | indistinguishable |
| `gzip-9-file` | compression | A | compiler-runtime-v1 | reused | Executed | - | - | - | - | ineligible |
| `gzip-9-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `jq-sum` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `jq-sum` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `make-build` | build | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-build` | build | A | native | refused | Executed | - | - | - | - | ineligible |
| `make-clean` | build | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-clean` | build | A | native | refused | Executed | - | - | - | - | ineligible |
| `node-compute` | tooling | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `node-compute` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `objcopy-strip` | tooling | A | compiler-runtime-v1 | reused | Executed | - | - | - | - | ineligible |
| `objcopy-strip` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `py-compile` | analysis | C | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `py-compile` | analysis | C | native | refused | Executed | - | - | - | - | ineligible |
| `sed-substitute-file` | data | A | compiler-runtime-v1 | reused | Executed | 8.841 ms | 11.085 ms | 66.012 ms | - | loss |
| `sed-substitute-file` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `sort-lines` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `sort-lines` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | native | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `zlib-compile-adler32` | real-project | A | compiler-runtime-v1 | reused | Executed | 87.236 ms | 66.940 ms | 321.168 ms | 12 | marginal_win |
| `zlib-compile-adler32` | real-project | A | native | refused | Executed | - | - | - | - | ineligible |

## Negative results

- `awk-reduce` (compiler-runtime-v1): **refused** — process read system clock: realtime; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `awk-reduce` (native): **refused** — process read randomness via getrandom; process read system clock: realtime
- `c-numeric-integration` (native): **refused** — process read randomness via getrandom
- `cppcheck-project` (compiler-runtime-v1): **tool_unavailable** — {'tool': 'cppcheck', 'path': None, 'note': 'not an eligibility measurement'}
- `cppcheck-project` (native): **tool_unavailable** — {'tool': 'cppcheck', 'path': None, 'note': 'not an eligibility measurement'}
- `fs-delete-recreate` (compiler-runtime-v1): **refused** — failed filesystem effect is not guardable: /tmp/ab-smoke/qualify/fs-delete-recreate__compiler-runtime-v1/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-delete-recreate` (native): **refused** — failed filesystem effect is not guardable: /tmp/ab-smoke/qualify/fs-delete-recreate__native/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `gcc-cc-heavy-tu` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff11aacfd0, 0x7fff11aad568, 0x7fff11aad120, 0x0, 0x7f86888c7380]
- `gcc-cc-small-tu` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffef0aaf690, 0x7ffef0aafc28, 0x7ffef0aaf7e0, 0x0, 0x7f28801fb380]
- `gcc-fanalyzer` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd672fb720, 0x7ffd672fbcb8, 0x7ffd672fb870, 0x0, 0x7fb77ab62380]
- `gcc-multi-tu-link` (compiler-runtime-v1): **refused** — failed filesystem effect is not guardable: /tmp/ccfHVLUa.o (errno 17); unmodeled successful syscall 98: getrusage outside the audited compiler profile; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-multi-tu-link` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff6677bc20, 0x7fff6677c1a8, 0x7fff6677bd70, 0x0, 0x7f1fd6b5a380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff93998a10, 0x7fff93998f98, 0x7fff93998b60, 0x0, 0x7f7b71c69380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff657a7d20, 0x7fff657a81f8, 0x7fff657a7c50, 0x0, 0x7f511a80c380]
- `gzip-9-file` (native): **refused** — process read randomness via getrandom
- `jq-sum` (compiler-runtime-v1): **refused** — process read randomness via getrandom; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `jq-sum` (native): **refused** — process read randomness via getrandom
- `make-build` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-build` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `node-compute` (compiler-runtime-v1): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffcfdcee300, 0x7ffcfdcee2d0, 0x7f8c188f5b5b, 0x7f8c18a04b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-compute` (native): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffd1a960b30, 0x7ffd1a960b00, 0x7f8b4def5b5b, 0x7f8b4e004b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `objcopy-strip` (native): **refused** — process read randomness via getrandom
- `py-compile` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compile` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `sed-substitute-file` (native): **refused** — process read randomness via getrandom
- `sort-lines` (compiler-runtime-v1): **refused** — process read system information via sched_getaffinity; process read system information via prlimit64; process read system information via sysinfo
- `sort-lines` (native): **refused** — process read randomness via getrandom; process read system information via sched_getaffinity; process read system information via prlimit64
- `tar-create` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `tar-create` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-0-file` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-0-file` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `zlib-compile-adler32` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc031e9be0, 0x7ffc031ea178, 0x7ffc031e9d30, 0x0, 0x7facc3e8f380]


# TraceJIT Phase AA real-world benchmark

Schema `tracejit.realworld.results/v1` · commit `ae884c59320b1ee37ac2d0ae8af24eae98f26241` · binary `daca8b0dc9fda100`

Eligibility is reported per environment tier and execution policy. Tier A (strict native) and tier C (declared adaptation) are never summed, and native-contract rows are never averaged with `allocator-entropy-v1` rows.

## Eligibility

| Tier / policy | Workloads | Attempted | Reused | Refused | Other | Rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A/compiler-runtime-v1 | 19 | 19 | 8 | 11 | 0 | 0.421 |
| A/native | 19 | 19 | 1 | 18 | 0 | 0.053 |
| C/compiler-runtime-v1 | 2 | 1 | 0 | 1 | 0 | 0.000 |
| C/native | 2 | 1 | 0 | 1 | 0 | 0.000 |

## Workloads

| Workload | Family | Tier | Policy | Status | Decision | Direct median | Warm median | Cold median | Break-even | Assessment |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `awk-reduce` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `awk-reduce` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `c-numeric-integration` | scientific | A | compiler-runtime-v1 | reused | Executed | 335.595 ms | 12.177 ms | 364.233 ms | 1 | clear_win |
| `c-numeric-integration` | scientific | A | native | refused | Executed | - | - | - | - | ineligible |
| `cppcheck-project` | analysis | C | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `cppcheck-project` | analysis | C | native | tool_unavailable | - | - | - | - | - | unavailable |
| `fs-delete-recreate` | filesystem | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-delete-recreate` | filesystem | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-heavy-tu` | compiler | A | compiler-runtime-v1 | reused | Executed | 466.623 ms | 64.972 ms | 736.876 ms | 1 | clear_win |
| `gcc-cc-heavy-tu` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-small-tu` | compiler | A | compiler-runtime-v1 | reused | Executed | 72.671 ms | 65.620 ms | 195.260 ms | 18 | marginal_win |
| `gcc-cc-small-tu` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-fanalyzer` | analysis | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-fanalyzer` | analysis | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gzip-6-stdout` | compression | A | compiler-runtime-v1 | reused | Executed | 5.986 ms | 6.976 ms | 27.907 ms | - | loss |
| `gzip-6-stdout` | compression | A | native | reused | Executed | 6.795 ms | 8.379 ms | 32.438 ms | - | loss |
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
| `sed-substitute-file` | data | A | compiler-runtime-v1 | reused | Executed | 9.117 ms | 13.396 ms | 53.643 ms | - | loss |
| `sed-substitute-file` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `sort-lines` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `sort-lines` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | native | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `zlib-compile-adler32` | real-project | A | compiler-runtime-v1 | reused | Executed | 92.057 ms | 70.361 ms | 328.248 ms | 11 | marginal_win |
| `zlib-compile-adler32` | real-project | A | native | refused | Executed | - | - | - | - | ineligible |

## Negative results

- `awk-reduce` (compiler-runtime-v1): **refused** — process read system clock: realtime; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `awk-reduce` (native): **refused** — process read randomness via getrandom; process read system clock: realtime
- `c-numeric-integration` (native): **refused** — process read randomness via getrandom
- `cppcheck-project` (compiler-runtime-v1): **tool_unavailable** — {'tool': 'cppcheck', 'path': None, 'note': 'not an eligibility measurement'}
- `cppcheck-project` (native): **tool_unavailable** — {'tool': 'cppcheck', 'path': None, 'note': 'not an eligibility measurement'}
- `fs-delete-recreate` (compiler-runtime-v1): **refused** — failed filesystem effect is not guardable: /tmp/aa1-scratch/qualify/fs-delete-recreate__compiler-runtime-v1/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-delete-recreate` (native): **refused** — failed filesystem effect is not guardable: /tmp/aa1-scratch/qualify/fs-delete-recreate__native/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `gcc-cc-heavy-tu` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff86c9fe60, 0x7fff86ca03f8, 0x7fff86c9ffb0, 0x0, 0x7f6d3646c380]
- `gcc-cc-small-tu` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc4c2687e0, 0x7ffc4c268d78, 0x7ffc4c268930, 0x0, 0x7f04d4f7a380]
- `gcc-fanalyzer` (compiler-runtime-v1): **refused** — process read randomness via getrandom; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-fanalyzer` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff484c77f0, 0x7fff484c7d88, 0x7fff484c7940, 0x0, 0x7fbf05e17380]
- `gcc-multi-tu-link` (compiler-runtime-v1): **refused** — failed filesystem effect is not guardable: /tmp/cc1yQx7P.o (errno 17); unmodeled successful syscall 98: getrusage outside the audited compiler profile; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-multi-tu-link` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe524979a0, 0x7ffe52497f28, 0x7ffe52497af0, 0x0, 0x7f0524583380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd425c5be0, 0x7ffd425c6168, 0x7ffd425c5d30, 0x0, 0x7fda43e5f380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcd343d290, 0x7ffcd343d768, 0x7ffcd343d1c0, 0x0, 0x7f5c84b7a380]
- `gzip-9-file` (native): **refused** — process read randomness via getrandom
- `jq-sum` (compiler-runtime-v1): **refused** — process read randomness via getrandom; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `jq-sum` (native): **refused** — process read randomness via getrandom
- `make-build` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-build` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `node-compute` (compiler-runtime-v1): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffdc06d5c40, 0x7ffdc06d5c10, 0x7fec21ef5b5b, 0x7fec22004b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-compute` (native): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffffc87db10, 0x7ffffc87dae0, 0x7fc2ef4f5b5b, 0x7fc2ef604b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
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
- `zlib-compile-adler32` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe20c673e0, 0x7ffe20c67978, 0x7ffe20c67530, 0x0, 0x7fc243d5e380]


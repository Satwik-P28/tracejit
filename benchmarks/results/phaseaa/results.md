# TraceJIT Phase AA real-world benchmark

Schema `tracejit.realworld.results/v1` · commit `0c8f0d401b2396994016f2bd27a31e3e6dc12e9d` · binary `7b79883f92a5721c`

Eligibility is reported per environment tier and execution policy. Tier A (strict native) and tier C (declared adaptation) are never summed, and native-contract rows are never averaged with `allocator-entropy-v1` rows.

## Eligibility

| Tier / policy | Workloads | Attempted | Reused | Refused | Other | Rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A/allocator-entropy-v1 | 50 | 49 | 10 | 37 | 2 | 0.204 |
| A/compiler-runtime-v1 | 50 | 49 | 17 | 30 | 2 | 0.347 |
| A/native | 50 | 49 | 1 | 47 | 1 | 0.020 |
| C/allocator-entropy-v1 | 9 | 5 | 0 | 5 | 0 | 0.000 |
| C/compiler-runtime-v1 | 9 | 5 | 0 | 5 | 0 | 0.000 |
| C/native | 9 | 5 | 0 | 5 | 0 | 0.000 |

## Workloads

| Workload | Family | Tier | Policy | Status | Decision | Direct median | Warm median | Cold median | Break-even | Assessment |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `awk-float-reduce` | scientific | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `awk-float-reduce` | scientific | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `awk-float-reduce` | scientific | A | native | refused | Executed | - | - | - | - | ineligible |
| `awk-reduce` | data | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `awk-reduce` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `awk-reduce` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `bzip2-9-file` | compression | A | allocator-entropy-v1 | reused | Executed | - | - | - | - | ineligible |
| `bzip2-9-file` | compression | A | compiler-runtime-v1 | reused | Executed | - | - | - | - | ineligible |
| `bzip2-9-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `c-numeric-integration` | scientific | A | allocator-entropy-v1 | reused | Executed | 344.884 ms | 11.444 ms | 384.155 ms | 1 | clear_win |
| `c-numeric-integration` | scientific | A | compiler-runtime-v1 | reused | Executed | 355.944 ms | 14.493 ms | 379.406 ms | 1 | clear_win |
| `c-numeric-integration` | scientific | A | native | refused | Executed | - | - | - | - | ineligible |
| `cppcheck-project` | analysis | C | allocator-entropy-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `cppcheck-project` | analysis | C | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `cppcheck-project` | analysis | C | native | tool_unavailable | - | - | - | - | - | unavailable |
| `cut-columns` | data | A | allocator-entropy-v1 | reused | Executed | 3.581 ms | 24.113 ms | 49.472 ms | - | loss |
| `cut-columns` | data | A | compiler-runtime-v1 | reused | Executed | 3.306 ms | 21.085 ms | 43.420 ms | - | loss |
| `cut-columns` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `fs-chmod-output` | filesystem | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-chmod-output` | filesystem | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-chmod-output` | filesystem | A | native | refused | Executed | - | - | - | - | ineligible |
| `fs-delete-recreate` | filesystem | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-delete-recreate` | filesystem | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-delete-recreate` | filesystem | A | native | refused | Executed | - | - | - | - | ineligible |
| `fs-hardlink-alias` | filesystem | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-hardlink-alias` | filesystem | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-hardlink-alias` | filesystem | A | native | refused | Executed | - | - | - | - | ineligible |
| `fs-identical-rewrite` | filesystem | A | allocator-entropy-v1 | eligible_but_no_hit | Executed | - | - | - | - | ineligible |
| `fs-identical-rewrite` | filesystem | A | compiler-runtime-v1 | eligible_but_no_hit | Executed | - | - | - | - | ineligible |
| `fs-identical-rewrite` | filesystem | A | native | eligible_but_no_hit | Executed | - | - | - | - | ineligible |
| `fs-symlink-input` | filesystem | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-symlink-input` | filesystem | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `fs-symlink-input` | filesystem | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-heavy-tu` | compiler | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-heavy-tu` | compiler | A | compiler-runtime-v1 | reused | Executed | 610.111 ms | 86.346 ms | 806.314 ms | 1 | clear_win |
| `gcc-cc-heavy-tu` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-small-tu` | compiler | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-small-tu` | compiler | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-cc-small-tu` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-cpp-preprocess` | compiler | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-cpp-preprocess` | compiler | A | compiler-runtime-v1 | reused | Executed | 16.461 ms | 68.939 ms | 195.653 ms | - | loss |
| `gcc-cpp-preprocess` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-fanalyzer` | analysis | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-fanalyzer` | analysis | A | compiler-runtime-v1 | reused | Executed | 26.717 ms | 72.222 ms | 202.772 ms | - | loss |
| `gcc-fanalyzer` | analysis | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-link-only` | linker | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-link-only` | linker | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-link-only` | linker | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-multi-tu-link` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-noopt-compile` | compiler | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-noopt-compile` | compiler | A | compiler-runtime-v1 | reused | Executed | 73.281 ms | 70.984 ms | 365.457 ms | 128 | indistinguishable |
| `gcc-noopt-compile` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-static-archive` | archiver | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-static-archive` | archiver | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-static-archive` | archiver | A | native | refused | Executed | - | - | - | - | ineligible |
| `gcc-syntax-only` | compiler | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gcc-syntax-only` | compiler | A | compiler-runtime-v1 | reused | Executed | 29.318 ms | 73.318 ms | 261.092 ms | - | loss |
| `gcc-syntax-only` | compiler | A | native | refused | Executed | - | - | - | - | ineligible |
| `gzip-6-stdout` | compression | A | allocator-entropy-v1 | reused | Executed | 7.290 ms | 17.125 ms | 33.637 ms | - | loss |
| `gzip-6-stdout` | compression | A | compiler-runtime-v1 | reused | Executed | 6.616 ms | 13.136 ms | 46.923 ms | - | loss |
| `gzip-6-stdout` | compression | A | native | reused | Executed | 6.186 ms | 13.409 ms | 40.178 ms | - | loss |
| `gzip-9-file` | compression | A | allocator-entropy-v1 | reused | Executed | - | - | - | - | ineligible |
| `gzip-9-file` | compression | A | compiler-runtime-v1 | reused | Executed | - | - | - | - | ineligible |
| `gzip-9-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `gzip-roundtrip` | compression | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `gzip-roundtrip` | compression | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `gzip-roundtrip` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `jq-sum` | data | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `jq-sum` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `jq-sum` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `jq-transform-file` | data | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `jq-transform-file` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `jq-transform-file` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `make-build` | build | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-build` | build | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-build` | build | A | native | refused | Executed | - | - | - | - | ineligible |
| `make-clean` | build | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-clean` | build | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-clean` | build | A | native | refused | Executed | - | - | - | - | ineligible |
| `make-header-change` | build | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-header-change` | build | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-header-change` | build | A | native | refused | Executed | - | - | - | - | ineligible |
| `make-incremental-noop` | build | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-incremental-noop` | build | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `make-incremental-noop` | build | A | native | refused | Executed | - | - | - | - | ineligible |
| `nm-symbols` | tooling | A | allocator-entropy-v1 | eligible_but_no_hit | Executed | - | - | - | - | ineligible |
| `nm-symbols` | tooling | A | compiler-runtime-v1 | eligible_but_no_hit | Executed | - | - | - | - | ineligible |
| `nm-symbols` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `node-compute` | tooling | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `node-compute` | tooling | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `node-compute` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `node-script-file` | tooling | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `node-script-file` | tooling | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `node-script-file` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `numpy-matmul` | scientific | C | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `numpy-matmul` | scientific | C | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `numpy-matmul` | scientific | C | native | refused | Executed | - | - | - | - | ineligible |
| `objcopy-strip` | tooling | A | allocator-entropy-v1 | reused | Executed | - | - | - | - | ineligible |
| `objcopy-strip` | tooling | A | compiler-runtime-v1 | reused | Executed | - | - | - | - | ineligible |
| `objcopy-strip` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `objdump-disassemble` | tooling | A | allocator-entropy-v1 | reused | Executed | 4.446 ms | 17.418 ms | 53.751 ms | - | loss |
| `objdump-disassemble` | tooling | A | compiler-runtime-v1 | reused | Executed | 4.701 ms | 18.787 ms | 58.498 ms | - | loss |
| `objdump-disassemble` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `parquet-convert` | data | C | allocator-entropy-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `parquet-convert` | data | C | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `parquet-convert` | data | C | native | tool_unavailable | - | - | - | - | - | unavailable |
| `perl-reduce` | tooling | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `perl-reduce` | tooling | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `perl-reduce` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `pil-image-transform` | scientific | C | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `pil-image-transform` | scientific | C | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `pil-image-transform` | scientific | C | native | refused | Executed | - | - | - | - | ineligible |
| `py-compile` | analysis | C | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `py-compile` | analysis | C | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `py-compile` | analysis | C | native | refused | Executed | - | - | - | - | ineligible |
| `py-compileall` | analysis | C | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `py-compileall` | analysis | C | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `py-compileall` | analysis | C | native | refused | Executed | - | - | - | - | ineligible |
| `python-csv-json` | data | C | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `python-csv-json` | data | C | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `python-csv-json` | data | C | native | refused | Executed | - | - | - | - | ineligible |
| `readelf-header` | tooling | A | allocator-entropy-v1 | reused | Executed | 2.536 ms | 16.052 ms | 39.469 ms | - | loss |
| `readelf-header` | tooling | A | compiler-runtime-v1 | reused | Executed | 2.468 ms | 16.945 ms | 36.992 ms | - | loss |
| `readelf-header` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `ruff-check` | analysis | C | allocator-entropy-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `ruff-check` | analysis | C | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `ruff-check` | analysis | C | native | tool_unavailable | - | - | - | - | - | unavailable |
| `sed-substitute-file` | data | A | allocator-entropy-v1 | reused | Executed | 14.360 ms | 79.874 ms | 135.311 ms | - | loss |
| `sed-substitute-file` | data | A | compiler-runtime-v1 | reused | Executed | 13.571 ms | 73.351 ms | 117.568 ms | - | loss |
| `sed-substitute-file` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `shellcheck-script` | analysis | C | allocator-entropy-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `shellcheck-script` | analysis | C | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `shellcheck-script` | analysis | C | native | tool_unavailable | - | - | - | - | - | unavailable |
| `sort-lines` | data | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `sort-lines` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `sort-lines` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `sort-uniq-counts` | data | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `sort-uniq-counts` | data | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `sort-uniq-counts` | data | A | native | refused | Executed | - | - | - | - | ineligible |
| `strip-binary` | tooling | A | allocator-entropy-v1 | reused | Executed | - | - | - | - | ineligible |
| `strip-binary` | tooling | A | compiler-runtime-v1 | reused | Executed | - | - | - | - | ineligible |
| `strip-binary` | tooling | A | native | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `tar-create` | packaging | A | native | refused | Executed | - | - | - | - | ineligible |
| `tar-gzip` | packaging | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `tar-gzip` | packaging | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `tar-gzip` | packaging | A | native | refused | Executed | - | - | - | - | ineligible |
| `unzip-extract` | packaging | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `unzip-extract` | packaging | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `unzip-extract` | packaging | A | native | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `xz-0-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `xz-6-file` | compression | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `xz-6-file` | compression | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `xz-6-file` | compression | A | native | refused | Executed | - | - | - | - | ineligible |
| `zip-create` | packaging | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `zip-create` | packaging | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `zip-create` | packaging | A | native | refused | Executed | - | - | - | - | ineligible |
| `zlib-archive` | real-project | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `zlib-archive` | real-project | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `zlib-archive` | real-project | A | native | refused | Executed | - | - | - | - | ineligible |
| `zlib-compile-adler32` | real-project | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `zlib-compile-adler32` | real-project | A | compiler-runtime-v1 | reused | Executed | 99.790 ms | 78.373 ms | 351.740 ms | 12 | marginal_win |
| `zlib-compile-adler32` | real-project | A | native | refused | Executed | - | - | - | - | ineligible |
| `zlib-compile-deflate` | real-project | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `zlib-compile-deflate` | real-project | A | compiler-runtime-v1 | reused | Executed | 611.465 ms | 83.075 ms | 819.066 ms | 1 | clear_win |
| `zlib-compile-deflate` | real-project | A | native | refused | Executed | - | - | - | - | ineligible |
| `zlib-gzip-tarball` | real-project | A | allocator-entropy-v1 | refused | Executed | - | - | - | - | ineligible |
| `zlib-gzip-tarball` | real-project | A | compiler-runtime-v1 | refused | Executed | - | - | - | - | ineligible |
| `zlib-gzip-tarball` | real-project | A | native | refused | Executed | - | - | - | - | ineligible |
| `zstd-19-file` | compression | A | allocator-entropy-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `zstd-19-file` | compression | A | compiler-runtime-v1 | tool_unavailable | - | - | - | - | - | unavailable |
| `zstd-19-file` | compression | A | native | tool_unavailable | - | - | - | - | - | unavailable |

## Negative results

- `awk-float-reduce` (allocator-entropy-v1): **refused** — process read system clock: realtime; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `awk-float-reduce` (compiler-runtime-v1): **refused** — process read system clock: realtime; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `awk-float-reduce` (native): **refused** — process read randomness via getrandom; process read system clock: realtime
- `awk-reduce` (allocator-entropy-v1): **refused** — process read system clock: realtime; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `awk-reduce` (compiler-runtime-v1): **refused** — process read system clock: realtime; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `awk-reduce` (native): **refused** — process read randomness via getrandom; process read system clock: realtime
- `bzip2-9-file` (native): **refused** — process read randomness via getrandom
- `c-numeric-integration` (native): **refused** — process read randomness via getrandom
- `cppcheck-project` (allocator-entropy-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'cppcheck'}
- `cppcheck-project` (compiler-runtime-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'cppcheck'}
- `cppcheck-project` (native): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'cppcheck'}
- `cut-columns` (native): **refused** — process read randomness via getrandom
- `fs-chmod-output` (allocator-entropy-v1): **refused** — unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `fs-chmod-output` (compiler-runtime-v1): **refused** — unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `fs-chmod-output` (native): **refused** — unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-delete-recreate` (allocator-entropy-v1): **refused** — failed filesystem effect is not guardable: /tmp/tracejit-realworld-v2/qualify/fs-delete-recreate__allocator-entropy-v1/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-delete-recreate` (compiler-runtime-v1): **refused** — failed filesystem effect is not guardable: /tmp/tracejit-realworld-v2/qualify/fs-delete-recreate__compiler-runtime-v1/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-delete-recreate` (native): **refused** — failed filesystem effect is not guardable: /tmp/tracejit-realworld-v2/qualify/fs-delete-recreate__native/traced/out.dat (errno 2); unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-hardlink-alias` (allocator-entropy-v1): **refused** — unmodeled successful syscall 265: hard-link creation is not a pathname-equivalent output effect; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-hardlink-alias` (compiler-runtime-v1): **refused** — unmodeled successful syscall 265: hard-link creation is not a pathname-equivalent output effect; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-hardlink-alias` (native): **refused** — unmodeled successful syscall 265: hard-link creation is not a pathname-equivalent output effect; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]; unmodeled successful syscall 326: unmodeled syscall 326 args [0x3, 0x0, 0x1, 0x0, 0x7fffffffc0000000, 0x0]
- `fs-identical-rewrite` (allocator-entropy-v1): **eligible_but_no_hit** — all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `fs-identical-rewrite` (compiler-runtime-v1): **eligible_but_no_hit** — all observed dependencies are guardable or captured outputs; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `fs-identical-rewrite` (native): **eligible_but_no_hit** — all observed dependencies are guardable or captured outputs
- `fs-symlink-input` (allocator-entropy-v1): **refused** — process read process identity via getpid; process read process identity via getppid; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `fs-symlink-input` (compiler-runtime-v1): **refused** — process read process identity via getpid; process read process identity via getppid; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `fs-symlink-input` (native): **refused** — process read process identity via getpid; process read randomness via getrandom; process read process identity via getppid
- `gcc-cc-heavy-tu` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd0095f4b0, 0x7ffd0095fa48, 0x7ffd0095f600, 0x0, 0x7f54117f0380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-cc-heavy-tu` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd4f9532e0, 0x7ffd4f953878, 0x7ffd4f953430, 0x0, 0x7f56ff773380]
- `gcc-cc-small-tu` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffa64e15d0, 0x7fffa64e1b68, 0x7fffa64e1720, 0x0, 0x7f467f41a380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-cc-small-tu` (compiler-runtime-v1): **refused** — process read randomness via getrandom; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-cc-small-tu` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc7f5992e0, 0x7ffc7f599878, 0x7ffc7f599430, 0x0, 0x7f6044ab8380]
- `gcc-cpp-preprocess` (allocator-entropy-v1): **refused** — process read system information via prlimit64; process read system information via sysinfo; process read system clock: realtime
- `gcc-cpp-preprocess` (native): **refused** — process read randomness via getrandom; process read system information via prlimit64; process read system information via sysinfo
- `gcc-fanalyzer` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff236bd750, 0x7fff236bdce8, 0x7fff236bd8a0, 0x0, 0x7ffbf53a4380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-fanalyzer` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc7b237c40, 0x7ffc7b2381d8, 0x7ffc7b237d90, 0x0, 0x7f5d43faf380]
- `gcc-link-only` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffdbe241b70, 0x7ffdbe242048, 0x7ffdbe241aa0, 0x0, 0x7f5863b2a380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-link-only` (compiler-runtime-v1): **refused** — unmodeled successful syscall 98: getrusage outside the audited compiler profile; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-link-only` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffee324aba0, 0x7ffee324b078, 0x7ffee324aad0, 0x0, 0x7fb32c5b5380]
- `gcc-multi-tu-link` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff2d3bedd0, 0x7fff2d3bf358, 0x7fff2d3bef20, 0x0, 0x7f3e27d16380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffca1fe9ac0, 0x7ffca1fea048, 0x7ffca1fe9c10, 0x0, 0x7fd0bc306380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe9b55f800, 0x7ffe9b55fcd8, 0x7ffe9b55f730, 0x0, 0x7f0d13f38380]
- `gcc-multi-tu-link` (compiler-runtime-v1): **refused** — failed filesystem effect is not guardable: /tmp/cc5McYxn.o (errno 17); unmodeled successful syscall 98: getrusage outside the audited compiler profile; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-multi-tu-link` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe6d03ea30, 0x7ffe6d03efb8, 0x7ffe6d03eb80, 0x0, 0x7f6103c00380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc2a761910, 0x7ffc2a761e98, 0x7ffc2a761a60, 0x0, 0x7f25d2616380]; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffde06a2af0, 0x7ffde06a2fc8, 0x7ffde06a2a20, 0x0, 0x7fd8c4916380]
- `gcc-noopt-compile` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc5d648320, 0x7ffc5d6488b8, 0x7ffc5d648470, 0x0, 0x7ff428564380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-noopt-compile` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffe9ea84c0, 0x7fffe9ea8a58, 0x7fffe9ea8610, 0x0, 0x7f936d2f4380]
- `gcc-static-archive` (allocator-entropy-v1): **refused** — process read system clock: monotonic; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-static-archive` (compiler-runtime-v1): **refused** — process read system clock: monotonic; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gcc-static-archive` (native): **refused** — process read randomness via getrandom; process read system clock: monotonic
- `gcc-syntax-only` (allocator-entropy-v1): **refused** — process read system information via prlimit64; process read system information via sysinfo; process read system clock: realtime
- `gcc-syntax-only` (native): **refused** — process read randomness via getrandom; process read system information via prlimit64; process read system information via sysinfo
- `gzip-9-file` (native): **refused** — process read randomness via getrandom
- `gzip-roundtrip` (allocator-entropy-v1): **refused** — unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gzip-roundtrip` (compiler-runtime-v1): **refused** — unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `gzip-roundtrip` (native): **refused** — unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- `jq-sum` (allocator-entropy-v1): **refused** — process read randomness via getrandom; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `jq-sum` (compiler-runtime-v1): **refused** — process read randomness via getrandom; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `jq-sum` (native): **refused** — process read randomness via getrandom
- `jq-transform-file` (allocator-entropy-v1): **refused** — process read process identity via getpid; process read process identity via getppid; process read randomness via getrandom
- `jq-transform-file` (compiler-runtime-v1): **refused** — process read process identity via getpid; process read process identity via getppid; process read randomness via getrandom
- `jq-transform-file` (native): **refused** — process read process identity via getpid; process read randomness via getrandom; process read process identity via getppid
- `make-build` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-build` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-build` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-clean` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-header-change` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-header-change` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-header-change` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-incremental-noop` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-incremental-noop` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `make-incremental-noop` (native): **refused** — unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- `nm-symbols` (allocator-entropy-v1): **eligible_but_no_hit** — all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `nm-symbols` (compiler-runtime-v1): **eligible_but_no_hit** — all observed dependencies are guardable or captured outputs; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `nm-symbols` (native): **refused** — process read randomness via getrandom
- `node-compute` (allocator-entropy-v1): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7fff02f2bc40, 0x7fff02f2bc10, 0x7fd024ef5b5b, 0x7fd025004b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-compute` (compiler-runtime-v1): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffc087651a0, 0x7ffc08765170, 0x7f216c6f5b5b, 0x7f216c804b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-compute` (native): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffe83d33930, 0x7ffe83d33900, 0x7fc8ebef5b5b, 0x7fc8ec004b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-script-file` (allocator-entropy-v1): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffe3c3b3f50, 0x7ffe3c3b3f20, 0x7f72c98f5b5b, 0x7f72c9a04b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-script-file` (compiler-runtime-v1): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffd11741c20, 0x7ffd11741bf0, 0x7f73f08f5b5b, 0x7f73f0a04b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `node-script-file` (native): **refused** — unmodeled successful syscall 125: unmodeled syscall 125 args [0x7ffe3cbd41f0, 0x7ffe3cbd41c0, 0x7f96b22f5b5b, 0x7f96b2404b20, 0x50, 0x0]; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- `numpy-matmul` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `numpy-matmul` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `numpy-matmul` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `objcopy-strip` (native): **refused** — process read randomness via getrandom
- `objdump-disassemble` (native): **refused** — process read randomness via getrandom
- `parquet-convert` (allocator-entropy-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'pyarrow'}
- `parquet-convert` (compiler-runtime-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'pyarrow'}
- `parquet-convert` (native): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'pyarrow'}
- `perl-reduce` (allocator-entropy-v1): **refused** — process read randomness via /dev/urandom; process read system clock: realtime; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `perl-reduce` (compiler-runtime-v1): **refused** — process read randomness via /dev/urandom; process read system clock: realtime; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `perl-reduce` (native): **refused** — process read randomness via getrandom; process read randomness via /dev/urandom; process read system clock: realtime
- `pil-image-transform` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `pil-image-transform` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `pil-image-transform` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compile` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compile` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compile` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compileall` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compileall` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `py-compileall` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `python-csv-json` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `python-csv-json` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `python-csv-json` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `readelf-header` (native): **refused** — process read randomness via getrandom
- `ruff-check` (allocator-entropy-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'ruff'}
- `ruff-check` (compiler-runtime-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'ruff'}
- `ruff-check` (native): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'ruff'}
- `sed-substitute-file` (native): **refused** — process read randomness via getrandom
- `shellcheck-script` (allocator-entropy-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'shellcheck'}
- `shellcheck-script` (compiler-runtime-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'shellcheck'}
- `shellcheck-script` (native): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'shellcheck'}
- `sort-lines` (allocator-entropy-v1): **refused** — process read system information via sched_getaffinity; process read system information via prlimit64; process read system information via sysinfo
- `sort-lines` (compiler-runtime-v1): **refused** — process read system information via sched_getaffinity; process read system information via prlimit64; process read system information via sysinfo
- `sort-lines` (native): **refused** — process read randomness via getrandom; process read system information via sched_getaffinity; process read system information via prlimit64
- `sort-uniq-counts` (allocator-entropy-v1): **refused** — unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- `sort-uniq-counts` (compiler-runtime-v1): **refused** — unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- `sort-uniq-counts` (native): **refused** — unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling; unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- `strip-binary` (native): **refused** — process read randomness via getrandom
- `tar-create` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `tar-create` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `tar-create` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `tar-gzip` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `tar-gzip` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `tar-gzip` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `unzip-extract` (allocator-entropy-v1): **refused** — all observed dependencies are guardable or captured outputs; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution; non-file output cannot be restored: /tmp/tracejit-realworld-v2/qualify/unzip-extract__allocator-entropy-v1/traced/extracted
- `unzip-extract` (compiler-runtime-v1): **refused** — all observed dependencies are guardable or captured outputs; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution; non-file output cannot be restored: /tmp/tracejit-realworld-v2/qualify/unzip-extract__compiler-runtime-v1/traced/extracted
- `unzip-extract` (native): **refused** — process read randomness via getrandom; non-file output cannot be restored: /tmp/tracejit-realworld-v2/qualify/unzip-extract__native/traced/extracted
- `xz-0-file` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-0-file` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-0-file` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-6-file` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-6-file` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `xz-6-file` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `zip-create` (allocator-entropy-v1): **refused** — process read system clock: monotonic; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `zip-create` (compiler-runtime-v1): **refused** — process read system clock: monotonic; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `zip-create` (native): **refused** — process read randomness via getrandom; process read system clock: monotonic
- `zlib-archive` (allocator-entropy-v1): **refused** — process read system clock: monotonic; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `zlib-archive` (compiler-runtime-v1): **refused** — process read system clock: monotonic; executed under the tracejit.compiler-runtime.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `zlib-archive` (native): **refused** — process read randomness via getrandom; process read system clock: monotonic
- `zlib-compile-adler32` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd5f3203d0, 0x7ffd5f320968, 0x7ffd5f320520, 0x0, 0x7f2cd8628380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `zlib-compile-adler32` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd74f9ae90, 0x7ffd74f9b428, 0x7ffd74f9afe0, 0x0, 0x7fe46265d380]
- `zlib-compile-deflate` (allocator-entropy-v1): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffddc8c34f0, 0x7ffddc8c3a88, 0x7ffddc8c3640, 0x0, 0x7f7f9beb4380]; executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- `zlib-compile-deflate` (native): **refused** — unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe2be63350, 0x7ffe2be638e8, 0x7ffe2be634a0, 0x0, 0x7f7dc48bc380]
- `zlib-gzip-tarball` (allocator-entropy-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `zlib-gzip-tarball` (compiler-runtime-v1): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `zlib-gzip-tarball` (native): **refused** — unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded; unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- `zstd-19-file` (allocator-entropy-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'zstd'}
- `zstd-19-file` (compiler-runtime-v1): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'zstd'}
- `zstd-19-file` (native): **tool_unavailable** — {'note': 'not an eligibility measurement', 'path': None, 'tool': 'zstd'}


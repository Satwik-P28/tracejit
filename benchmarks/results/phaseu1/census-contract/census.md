# TraceJIT real-world compatibility census

Commit: `5e2ca1d7efaf5c8772610be1eaf57e3d194e74c2`
 (working tree dirty: `False`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 32
- Attempted: 30
- Reused with a verified cache hit: 7
- Refused by TraceJIT: 22
- Failed to execute: 0
- Blocked on a missing tool: 2
- Eligibility rate: 0.233

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Unknown | 1285 | 2 | 203.379 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 249 | 2 | 63.522 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 227 | 4 | 39.414 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 57 | 2 | 3.520 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | reuse_was_not_obtained | Guarded | 34 | 1 | 2.465 ms | - | - | - |
| `shell-pipeline` | shell | refused | Unknown | 79 | 1 | 5.500 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 316 | 5 | 73.765 ms | - | - | PASS |
| `python-csv-json` | python | refused | Unknown | 200 | 1 | 32.156 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Unknown | 200 | 1 | 31.955 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 2.212 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 28.517 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 445 | 1 | 80.403 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1196 | 0 | 51.239 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 1.541 ms | 7.264 ms | 0.212x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 19 | 1 | 5.580 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | reused | Guarded | 11 | 0 | 20.397 ms | 10.439 ms | 1.954x | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 55 | 0 | 4.757 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Unknown | 73 | 1 | 4.171 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | reused | Guarded | 61 | 0 | 3.097 ms | 18.257 ms | 0.170x | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 23 | 0 | 1.632 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 23 | 0 | 1.498 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 56 | 0 | 2.329 ms | - | - | PASS |
| `wc-line-count` | text | reused | Guarded | 52 | 0 | 1.320 ms | 16.609 ms | 0.079x | PASS |
| `sha256sum-blob` | digest | reused | Guarded | 55 | 0 | 2.169 ms | 19.208 ms | 0.113x | PASS |
| `openssl-sha256` | digest | reused | Guarded | 16 | 0 | 3.794 ms | 20.131 ms | 0.188x | PASS |
| `od-hex-prefix` | inspect | reused | Guarded | 52 | 0 | 1.402 ms | 14.971 ms | 0.094x | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 52 | 1 | 1.684 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 65 | 0 | 3.280 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 64 | 0 | 3.050 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 63 | 0 | 2.068 ms | - | - | PASS |
| `rustc-hello` | rust | blocked: missing rustc | - | - | - | - | - | - | - |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 22 | 22 |
| clock | 7 | 7 |
| system_information | 2 | 5 |
| randomness | 2 | 2 |
| process_identity | 1 | 2 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 72 | 72: fcntl | 6 |
| 98 | 98: getrusage | 4 |
| 5 | 5: fstat | 3 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-s7klm4xh/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe961ce520, 0x7ffe961ceaa8, 0x7ffe961ce670, 0x0, 0x7f4f9462c380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-s7klm4xh/cc-compile-large/source.c -o /tmp/tracejit-census-s7klm4xh/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd2ccdb2e0, 0x7ffd2ccdb868, 0x7ffd2ccdb430, 0x0, 0x7f2e26475380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-link-binary` (refused)

Command: `cc /tmp/tracejit-census-s7klm4xh/cc-link-binary/link.o -o /tmp/tracejit-census-s7klm4xh/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffde9620c90, 0x7ffde9621160, 0x7ffde9620bc0, 0x0, 0x7fa8675cb380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/tracejit-census-s7klm4xh/ar-static-archive/libmember.a /tmp/tracejit-census-s7klm4xh/ar-static-archive/member.o`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `objcopy-strip-unneeded` (reuse_was_not_obtained)

Command: `objcopy --strip-unneeded /tmp/tracejit-census-s7klm4xh/objcopy-strip-unneeded/obj.o /tmp/tracejit-census-s7klm4xh/objcopy-strip-unneeded/obj.stripped.o`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-s7klm4xh/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-s7klm4xh/shell-pipeline/pipeline.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/tracejit-census-s7klm4xh/multi-file-compile-ar-hash/source.c -o /tmp/tracejit-census-s7klm4xh/multi-file-compile-ar-hash/a.o && ar rcs /tmp/tracejit-census-s7klm4xh/multi-file-compile-ar-hash/liba.a /tmp/tracejit-census-s7klm4xh/multi-file-compile-ar-hash/a.o && sha256sum /tmp/tracejit-census-s7klm4xh/multi-file-compile-ar-hash/liba.a > /tmp/tracejit-census-s7klm4xh/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe3fc58c90, 0x7ffe3fc59218, 0x7ffe3fc58de0, 0x0, 0x7f4f4f07c380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-s7klm4xh/python-csv-json/sales.csv /tmp/tracejit-census-s7klm4xh/python-csv-json/customers.csv /tmp/tracejit-census-s7klm4xh/python-csv-json/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-s7klm4xh/python-csv-json-seeded/sales.csv /tmp/tracejit-census-s7klm4xh/python-csv-json-seeded/customers.csv /tmp/tracejit-census-s7klm4xh/python-csv-json-seeded/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-s7klm4xh/awk-codegen/schema.tsv > /tmp/tracejit-census-s7klm4xh/awk-codegen/generated.h`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-s7klm4xh/groff-manpage-html/census.1 > /tmp/tracejit-census-s7klm4xh/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-s7klm4xh/pil-image-transform/source.png /tmp/tracejit-census-s7klm4xh/pil-image-transform/transformed.png`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/tracejit-census-s7klm4xh/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/tracejit-census-s7klm4xh/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/tracejit-census-s7klm4xh/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 3 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 4 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/tracejit-census-s7klm4xh/tar-create-archive/bundle.tar -C /tmp/tracejit-census-s7klm4xh/tar-create-archive lines.txt blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/tracejit-census-s7klm4xh/awk-sum-stdout/lines.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/tracejit-census-s7klm4xh/awk-scientific-iter/numbers.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sort-numbers` (refused)

Command: `sort /tmp/tracejit-census-s7klm4xh/sort-numbers/numbers.txt`

- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `dd-copy-file` (refused)

Command: `dd if=/tmp/tracejit-census-s7klm4xh/dd-copy-file/blob.bin of=/tmp/tracejit-census-s7klm4xh/dd-copy-file/copy.bin bs=4096 status=none`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/tracejit-census-s7klm4xh/jq-sum-values/rows.json`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/tracejit-census-s7klm4xh/perl-sum-values/lines.txt`

- process read randomness via /dev/urandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `make-awk-target` (refused)

Command: `make -C /tmp/tracejit-census-s7klm4xh/make-awk-target all`

- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

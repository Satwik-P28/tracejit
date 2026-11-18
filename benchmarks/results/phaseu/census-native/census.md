# TraceJIT real-world compatibility census

Commit: `b9752324b125b8fd1659d820433d889973ced88d`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 32
- Attempted: 31
- Reused with a verified cache hit: 1
- Refused by TraceJIT: 30
- Failed to execute: 0
- Blocked on a missing tool: 1
- Eligibility rate: 0.032

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Unknown | 1287 | 2 | 278.950 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 251 | 2 | 63.715 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 233 | 4 | 37.490 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 57 | 2 | 3.738 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | refused | Nondeterministic | 33 | 1 | 2.599 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 81 | 1 | 5.549 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 320 | 5 | 81.067 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 199 | 1 | 34.299 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 199 | 1 | 27.319 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 2.767 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 21.565 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Nondeterministic | 444 | 1 | 73.838 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1196 | 0 | 40.595 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 1.635 ms | 16.527 ms | 0.099x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 19 | 1 | 3.865 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | refused | Nondeterministic | 10 | 0 | 12.588 ms | - | - | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 54 | 0 | 3.071 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Nondeterministic | 72 | 1 | 4.833 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | refused | Nondeterministic | 60 | 0 | 2.585 ms | - | - | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 22 | 0 | 1.805 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 22 | 0 | 2.679 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 55 | 0 | 2.727 ms | - | - | PASS |
| `wc-line-count` | text | refused | Nondeterministic | 51 | 0 | 1.536 ms | - | - | PASS |
| `sha256sum-blob` | digest | refused | Nondeterministic | 54 | 0 | 2.483 ms | - | - | PASS |
| `openssl-sha256` | digest | refused | Nondeterministic | 15 | 0 | 8.661 ms | - | - | PASS |
| `od-hex-prefix` | inspect | refused | Nondeterministic | 51 | 0 | 2.581 ms | - | - | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 51 | 1 | 1.919 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 64 | 0 | 4.826 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 63 | 0 | 6.504 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 62 | 0 | 5.089 ms | - | - | FAIL |
| `rustc-hello` | rust | refused | Unknown | 539 | 13 | 145.370 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| randomness | 20 | 21 |
| clock | 11 | 14 |
| process_identity | 4 | 5 |
| system_information | 2 | 5 |
| other:clone file-descriptor and cwd sharing semantics are not elig | 1 | 24 |
| procfs_process_relative | 1 | 7 |
| other:file-backed MAP_SHARED mapping is writable; stores through i | 1 | 2 |
| network | 1 | 1 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 1: more than one process wrote to it, so byte order dep | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 4 |
| 98 | 98: getrusage | 4 |
| 72 | 72: fcntl | 3 |
| 157 | 157: prctl | 1 |
| 16 | 16: ioctl | 1 |
| 233 | 233: epoll_ctl | 1 |
| 290 | 290: eventfd2 | 1 |
| 332 | 332: statx | 1 |
| 7 | 7: poll | 1 |
| 73 | 73: flock | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/final2/native-scratch/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcb986a4a0, 0x7ffcb986aa28, 0x7ffcb986a5f0, 0x0, 0x7f15ae08c380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/final2/native-scratch/cc-compile-large/source.c -o /tmp/final2/native-scratch/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff6d7a6660, 0x7fff6d7a6be8, 0x7fff6d7a67b0, 0x0, 0x7fcee77f3380]

### `cc-link-binary` (refused)

Command: `cc /tmp/final2/native-scratch/cc-link-binary/link.o -o /tmp/final2/native-scratch/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc7264ace0, 0x7ffc7264b1b0, 0x7ffc7264ac10, 0x0, 0x7f6ddd45f380]

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/final2/native-scratch/ar-static-archive/libmember.a /tmp/final2/native-scratch/ar-static-archive/member.o`

- process read randomness via getrandom
- process read system clock: monotonic

### `objcopy-strip-unneeded` (refused)

Command: `objcopy --strip-unneeded /tmp/final2/native-scratch/objcopy-strip-unneeded/obj.o /tmp/final2/native-scratch/objcopy-strip-unneeded/obj.stripped.o`

- process read randomness via getrandom

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/final2/native-scratch/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/final2/native-scratch/shell-pipeline/pipeline.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/final2/native-scratch/multi-file-compile-ar-hash/source.c -o /tmp/final2/native-scratch/multi-file-compile-ar-hash/a.o && ar rcs /tmp/final2/native-scratch/multi-file-compile-ar-hash/liba.a /tmp/final2/native-scratch/multi-file-compile-ar-hash/a.o && sha256sum /tmp/final2/native-scratch/multi-file-compile-ar-hash/liba.a > /tmp/final2/native-scratch/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff68566010, 0x7fff68566598, 0x7fff68566160, 0x0, 0x7f84288ba380]

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/final2/native-scratch/python-csv-json/sales.csv /tmp/final2/native-scratch/python-csv-json/customers.csv /tmp/final2/native-scratch/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/final2/native-scratch/python-csv-json-seeded/sales.csv /tmp/final2/native-scratch/python-csv-json-seeded/customers.csv /tmp/final2/native-scratch/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/final2/native-scratch/awk-codegen/schema.tsv > /tmp/final2/native-scratch/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/final2/native-scratch/groff-manpage-html/census.1 > /tmp/final2/native-scratch/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/final2/native-scratch/pil-image-transform/source.png /tmp/final2/native-scratch/pil-image-transform/transformed.png`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/final2/native-scratch/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/final2/native-scratch/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling

### `bzip2-compress-stdout` (refused)

Command: `bzip2 -c /tmp/final2/native-scratch/bzip2-compress-stdout/blob.bin`

- process read randomness via getrandom

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/final2/native-scratch/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: status-flag change on fd 3 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 4 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/final2/native-scratch/tar-create-archive/bundle.tar -C /tmp/final2/native-scratch/tar-create-archive lines.txt blob.bin`

- process read randomness via getrandom
- process read system clock: realtime
- process wrote network: failed socket control (errno 2)

### `sed-rewrite-stdout` (refused)

Command: `sed s/value=/v=/g /tmp/final2/native-scratch/sed-rewrite-stdout/lines.txt`

- process read randomness via getrandom

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/final2/native-scratch/awk-sum-stdout/lines.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/final2/native-scratch/awk-scientific-iter/numbers.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `sort-numbers` (refused)

Command: `sort /tmp/final2/native-scratch/sort-numbers/numbers.txt`

- process read randomness via getrandom
- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo

### `wc-line-count` (refused)

Command: `wc -l /tmp/final2/native-scratch/wc-line-count/lines.txt`

- process read randomness via getrandom

### `sha256sum-blob` (refused)

Command: `sha256sum /tmp/final2/native-scratch/sha256sum-blob/blob.bin`

- process read randomness via getrandom

### `openssl-sha256` (refused)

Command: `openssl dgst -sha256 /tmp/final2/native-scratch/openssl-sha256/blob.bin`

- process read randomness via getrandom

### `od-hex-prefix` (refused)

Command: `od -An -tx1 -N 256 /tmp/final2/native-scratch/od-hex-prefix/blob.bin`

- process read randomness via getrandom

### `dd-copy-file` (refused)

Command: `dd if=/tmp/final2/native-scratch/dd-copy-file/blob.bin of=/tmp/final2/native-scratch/dd-copy-file/copy.bin bs=4096 status=none`

- process read randomness via getrandom
- process read system clock: monotonic

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/final2/native-scratch/jq-sum-values/rows.json`

- process read randomness via getrandom

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/final2/native-scratch/perl-sum-values/lines.txt`

- process read randomness via getrandom
- process read randomness via /dev/urandom
- process read system clock: realtime

### `make-awk-target` (refused)

Command: `make -C /tmp/final2/native-scratch/make-awk-target all`

- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified

### `rustc-hello` (refused)

Command: `rustc -O /tmp/final2/native-scratch/rustc-hello/hello.rs -o /tmp/final2/native-scratch/rustc-hello/hello`

- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffce407e1e0, 0x3, 0x0, 0x0, 0xfefa3203, 0x178bfbff]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 290: unmodeled syscall 290 args [0x0, 0x80800, 0x0, 0x5634311558b0, 0x78, 0x0]
- unmodeled successful syscall 233: unmodeled syscall 233 args [0x3, 0x1, 0x4, 0x7ffce407b238, 0x78, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd6831fec00, 0x7fd6831fec00, 0x72656b726f772d74, 0x7fd683406780, 0x1]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd682ffdc00, 0x7fd682ffdc00, 0x72656b726f772d74, 0x0, 0x7fd682ffe6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd682dfcc00, 0x7fd682dfcc00, 0x72656b726f772d74, 0x0, 0x7fd682dfd6c0]
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd682bfbc00, 0x7fd682bfbc00, 0x72656b726f772d74, 0x0, 0x7fd682bfc6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd6829fac00, 0x7fd6829fac00, 0x72656b726f772d74, 0x0, 0x7fd6829fb6c0]
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd6827f9c00, 0x7fd6827f9c00, 0x72656b726f772d74, 0x0, 0x7fd6827fa6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd6825f8c00, 0x7fd6825f8c00, 0x72656b726f772d74, 0x0, 0x7fd6825f96c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fd6823f7c00, 0x7fd6823f7c00, 0x72656b726f772d74, 0x0, 0x7fd6823f86c0]
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 73: unmodeled syscall 73 args [0x6, 0x1, 0x0, 0x0, 0x0, 0x6c6d6f742e7367]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7fff364dbd30, 0x3, 0x0, 0x0, 0x3, 0x7f1df8b7b380]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/statm
- unmodeled successful syscall 332: statx result is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f1de47faf80, 0x7f1de47faf80, 0x632d6c72, 0x7f1df5abfb80, 0x1]
- unmodeled failed syscall 332 (errno 2): statx AT_SYMLINK_NOFOLLOW result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx AT_SYMLINK_NOFOLLOW result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 72: status-flag change on fd 4 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 4 whose open file description is shared or unclassified
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f1de3ffaf80, 0x7f1de3ffaf80, 0x63747375, 0x7f1df5abfb80, 0x7f1de3fff6c0]
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f1ddb179f80, 0x7f1ddb179f80, 0x726f74616e696472, 0x7f1df5abfb80, 0x7f1ddb17e6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f1dda5faf80, 0x7f1dda5faf80, 0x302e756763207470, 0x7f1df5abfb80, 0x7f1dda5ff6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f1dda5faf80, 0x7f1dda5faf80, 0x302e756763206f74, 0x7f1df5abfb80, 0x7f1dda5ff6c0]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 16: status-flag change on fd 5 whose open file description is shared or unclassified
- unmodeled successful syscall 16: status-flag change on fd 7 whose open file description is shared or unclassified
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffde01e1af0, 0x3, 0x0, 0xa, 0x3, 0x7f62098f2380]
- process-relative procfs dependency: /proc/self/maps
- unmodeled successful syscall 5: fstat on pipe descriptor 2 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7f1de3f71954, 0x2, 0xffffffff, 0x0, 0x0, 0x0]
- unmodeled successful syscall 16: status-flag change on fd 7 whose open file description is shared or unclassified
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- pipe 1: more than one process wrote to it, so byte order depends on scheduling


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

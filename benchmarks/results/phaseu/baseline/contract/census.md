# TraceJIT real-world compatibility census

Commit: `b9752324b125b8fd1659d820433d889973ced88d`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 32
- Attempted: 31
- Reused with a verified cache hit: 7
- Refused by TraceJIT: 24
- Failed to execute: 0
- Blocked on a missing tool: 1
- Eligibility rate: 0.226

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Unknown | 1288 | 2 | 224.592 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 252 | 2 | 47.209 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 234 | 4 | 28.726 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 58 | 2 | 3.691 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | refused | Nondeterministic | 34 | 1 | 2.800 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 82 | 1 | 4.138 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 321 | 5 | 61.840 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 200 | 1 | 34.412 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 200 | 1 | 27.902 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 33 | 1 | 3.226 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 117 | 1 | 27.598 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 445 | 1 | 72.148 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1197 | 0 | 42.328 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 2.148 ms | 14.153 ms | 0.152x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 20 | 1 | 4.538 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | reused | Guarded | 11 | 0 | 12.945 ms | 21.173 ms | 0.611x | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 55 | 0 | 3.314 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Nondeterministic | 73 | 1 | 2.996 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | reused | Guarded | 61 | 0 | 2.370 ms | 28.827 ms | 0.082x | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 23 | 0 | 1.751 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 23 | 0 | 1.882 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 56 | 0 | 2.914 ms | - | - | PASS |
| `wc-line-count` | text | reused | Guarded | 52 | 0 | 1.641 ms | 25.298 ms | 0.065x | PASS |
| `sha256sum-blob` | digest | reused | Guarded | 55 | 0 | 3.141 ms | 25.223 ms | 0.125x | PASS |
| `openssl-sha256` | digest | reused | Guarded | 16 | 0 | 4.854 ms | 25.402 ms | 0.191x | PASS |
| `od-hex-prefix` | inspect | reused | Guarded | 52 | 0 | 1.656 ms | 18.559 ms | 0.089x | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 52 | 1 | 1.629 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 65 | 0 | 4.532 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Unknown | 64 | 0 | 4.064 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 63 | 0 | 5.071 ms | - | - | FAIL |
| `rustc-hello` | rust | refused | Unknown | 540 | 13 | 128.030 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 24 | 24 |
| clock | 9 | 11 |
| system_information | 4 | 7 |
| process_identity | 3 | 4 |
| failed_descriptor_operation | 2 | 2 |
| randomness | 2 | 2 |
| other:clone file-descriptor and cwd sharing semantics are not elig | 1 | 24 |
| procfs_process_relative | 1 | 7 |
| other:file-backed MAP_SHARED mapping is writable; stores through i | 1 | 2 |
| network | 1 | 1 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 1: more than one process wrote to it, so byte order dep | 1 | 1 |
| unhashable_open | 1 | 1 |
| unrestorable_output | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 5 |
| 16 | 16: ioctl | 4 |
| 98 | 98: getrusage | 4 |
| 72 | 72: fcntl | 3 |
| 291 | 291: epoll_create1 | 2 |
| 157 | 157: prctl | 1 |
| 233 | 233: epoll_ctl | 1 |
| 290 | 290: eventfd2 | 1 |
| 332 | 332: statx | 1 |
| 7 | 7: poll | 1 |
| 73 | 73: flock | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/base2/contract-scratch/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd2ad23790, 0x7ffd2ad23d18, 0x7ffd2ad238e0, 0x0, 0x7f03dd4e3380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/base2/contract-scratch/cc-compile-large/source.c -o /tmp/base2/contract-scratch/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe9138de70, 0x7ffe9138e3f8, 0x7ffe9138dfc0, 0x0, 0x7fa7fa962380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-link-binary` (refused)

Command: `cc /tmp/base2/contract-scratch/cc-link-binary/link.o -o /tmp/base2/contract-scratch/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc58adfc00, 0x7ffc58ae00d0, 0x7ffc58adfb30, 0x0, 0x7f5a66259380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/base2/contract-scratch/ar-static-archive/libmember.a /tmp/base2/contract-scratch/ar-static-archive/member.o`

- process read system information via prlimit64
- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `objcopy-strip-unneeded` (refused)

Command: `objcopy --strip-unneeded /tmp/base2/contract-scratch/objcopy-strip-unneeded/obj.o /tmp/base2/contract-scratch/objcopy-strip-unneeded/obj.stripped.o`

- process read system information via prlimit64
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/base2/contract-scratch/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/base2/contract-scratch/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/base2/contract-scratch/multi-file-compile-ar-hash/source.c -o /tmp/base2/contract-scratch/multi-file-compile-ar-hash/a.o && ar rcs /tmp/base2/contract-scratch/multi-file-compile-ar-hash/liba.a /tmp/base2/contract-scratch/multi-file-compile-ar-hash/a.o && sha256sum /tmp/base2/contract-scratch/multi-file-compile-ar-hash/liba.a > /tmp/base2/contract-scratch/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd8e2d31f0, 0x7ffd8e2d3778, 0x7ffd8e2d3340, 0x0, 0x7f78509fe380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/base2/contract-scratch/python-csv-json/sales.csv /tmp/base2/contract-scratch/python-csv-json/customers.csv /tmp/base2/contract-scratch/python-csv-json/report.json`

- process read system clock: monotonic
- process read randomness via getrandom
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/base2/contract-scratch/python-csv-json-seeded/sales.csv /tmp/base2/contract-scratch/python-csv-json-seeded/customers.csv /tmp/base2/contract-scratch/python-csv-json-seeded/report.json`

- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/base2/contract-scratch/awk-codegen/schema.tsv > /tmp/base2/contract-scratch/awk-codegen/generated.h`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/base2/contract-scratch/groff-manpage-html/census.1 > /tmp/base2/contract-scratch/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/base2/contract-scratch/pil-image-transform/source.png /tmp/base2/contract-scratch/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f308e0172a8, 0x0, 0x0]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution
- non-file output cannot be restored: /dev/null

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/base2/contract-scratch/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/base2/contract-scratch/gzip-roundtrip-file/gunzip.bin`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/base2/contract-scratch/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/base2/contract-scratch/tar-create-archive/bundle.tar -C /tmp/base2/contract-scratch/tar-create-archive lines.txt blob.bin`

- process read system clock: realtime
- process wrote network: failed socket control (errno 2)
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/base2/contract-scratch/awk-sum-stdout/lines.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/base2/contract-scratch/awk-scientific-iter/numbers.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sort-numbers` (refused)

Command: `sort /tmp/base2/contract-scratch/sort-numbers/numbers.txt`

- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `dd-copy-file` (refused)

Command: `dd if=/tmp/base2/contract-scratch/dd-copy-file/blob.bin of=/tmp/base2/contract-scratch/dd-copy-file/copy.bin bs=4096 status=none`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/base2/contract-scratch/jq-sum-values/rows.json`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/base2/contract-scratch/perl-sum-values/lines.txt`

- opened dependency cannot be guarded: /dev/null
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 3
- unmodeled successful syscall 5: fstat on unclassified fd 3
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `make-awk-target` (refused)

Command: `make -C /tmp/base2/contract-scratch/make-awk-target all`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `rustc-hello` (refused)

Command: `rustc -O /tmp/base2/contract-scratch/rustc-hello/hello.rs -o /tmp/base2/contract-scratch/rustc-hello/hello`

- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffda9b34320, 0x3, 0x0, 0x0, 0xfefa3203, 0x178bfbff]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x7ffda9b31870, 0x0, 0x5614586878b0, 0x78, 0x0]
- unmodeled successful syscall 290: unmodeled syscall 290 args [0x0, 0x80800, 0x0, 0x5614586878b0, 0x78, 0x0]
- unmodeled successful syscall 233: unmodeled syscall 233 args [0x3, 0x1, 0x4, 0x7ffda9b31338, 0x78, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb66ffec00, 0x7fbb66ffec00, 0x72656b726f772d74, 0x7fbb67206780, 0x1]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb66dfdc00, 0x7fbb66dfdc00, 0x72656b726f772d74, 0x0, 0x7fbb66dfe6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb66bfcc00, 0x7fbb66bfcc00, 0x72656b726f772d74, 0x0, 0x7fbb66bfd6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb669fbc00, 0x7fbb669fbc00, 0x72656b726f772d74, 0x0, 0x7fbb669fc6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb667fac00, 0x7fbb667fac00, 0x72656b726f772d74, 0x0, 0x7fbb667fb6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb665f9c00, 0x7fbb665f9c00, 0x72656b726f772d74, 0x0, 0x7fbb665fa6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb663f8c00, 0x7fbb663f8c00, 0x72656b726f772d74, 0x0, 0x7fbb663f96c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fbb661f7c00, 0x7fbb661f7c00, 0x72656b726f772d74, 0x0, 0x7fbb661f86c0]
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
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffdf85f3fd0, 0x3, 0x0, 0x0, 0x3, 0x7f6acbd88380]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/statm
- unmodeled successful syscall 332: statx result is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f6ab79faf80, 0x7f6ab79faf80, 0x632d6c72, 0x7f6ac8cbfb80, 0x1]
- unmodeled failed syscall 332 (errno 2): statx AT_SYMLINK_NOFOLLOW result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx AT_SYMLINK_NOFOLLOW result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f6ab71faf80, 0x7f6ab71faf80, 0x63747375, 0x7f6ac8cbfb80, 0x7f6ab71ff6c0]
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
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f6aae379f80, 0x7f6aae379f80, 0x726f74616e696472, 0x7f6ac8cbfb80, 0x7f6aae37e6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f6aad7faf80, 0x7f6aad7faf80, 0x302e756763207470, 0x7f6ac8cbfb80, 0x7f6aad7ff6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f6aad7faf80, 0x7f6aad7faf80, 0x302e756763206f74, 0x7f6ac8cbfb80, 0x7f6aad7ff6c0]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x5, 0x5421, 0x7f6ab7171954, 0x0, 0x7f6ab7f5a200, 0x0]
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x7, 0x5421, 0x7f6ab7171954, 0x0, 0x7f6ab7f5a200, 0x0]
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 2
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 2
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffdde8d7900, 0x3, 0x0, 0xa, 0x3, 0x7fb77bdb3380]
- process-relative procfs dependency: /proc/self/maps
- unmodeled successful syscall 5: fstat on pipe descriptor 2 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 2
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7f6ab7171954, 0x2, 0xffffffff, 0x0, 0x0, 0x0]
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x7, 0x5421, 0x7f6ab7171964, 0x0, 0x0, 0x0]
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- pipe 1: more than one process wrote to it, so byte order depends on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

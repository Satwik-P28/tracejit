# TraceJIT real-world compatibility census

Commit: `b9752324b125b8fd1659d820433d889973ced88d`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 32
- Attempted: 31
- Reused with a verified cache hit: 7
- Refused by TraceJIT: 23
- Failed to execute: 0
- Blocked on a missing tool: 1
- Eligibility rate: 0.226

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Unknown | 1288 | 2 | 196.142 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 252 | 2 | 47.121 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 234 | 4 | 21.725 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 58 | 2 | 3.422 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | reuse_was_not_obtained | Guarded | 34 | 1 | 2.462 ms | - | - | - |
| `shell-pipeline` | shell | refused | Unknown | 82 | 1 | 3.716 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 321 | 5 | 65.279 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 200 | 1 | 40.777 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 200 | 1 | 40.061 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 33 | 1 | 2.716 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 117 | 1 | 16.906 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Nondeterministic | 445 | 1 | 79.513 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1197 | 0 | 43.200 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 2.869 ms | 18.647 ms | 0.154x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 20 | 1 | 4.309 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | reused | Guarded | 11 | 0 | 13.778 ms | 16.102 ms | 0.856x | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 55 | 0 | 2.706 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Nondeterministic | 73 | 1 | 2.458 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | reused | Guarded | 61 | 0 | 2.087 ms | 23.053 ms | 0.091x | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 23 | 0 | 1.857 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 23 | 0 | 1.601 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 56 | 0 | 2.685 ms | - | - | PASS |
| `wc-line-count` | text | reused | Guarded | 52 | 0 | 1.615 ms | 27.247 ms | 0.059x | PASS |
| `sha256sum-blob` | digest | reused | Guarded | 55 | 0 | 2.570 ms | 27.573 ms | 0.093x | PASS |
| `openssl-sha256` | digest | reused | Guarded | 16 | 0 | 4.598 ms | 27.422 ms | 0.168x | PASS |
| `od-hex-prefix` | inspect | reused | Guarded | 52 | 0 | 1.842 ms | 23.236 ms | 0.079x | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 52 | 1 | 1.690 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 65 | 0 | 3.718 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 64 | 0 | 3.807 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 63 | 0 | 4.815 ms | - | - | FAIL |
| `rustc-hello` | rust | refused | Unknown | 540 | 13 | 131.288 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 23 | 23 |
| clock | 11 | 14 |
| process_identity | 4 | 5 |
| randomness | 4 | 4 |
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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/final2/contract-scratch/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe997b7f50, 0x7ffe997b84d8, 0x7ffe997b80a0, 0x0, 0x7f79bf185380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/final2/contract-scratch/cc-compile-large/source.c -o /tmp/final2/contract-scratch/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffee32699e0, 0x7ffee3269f68, 0x7ffee3269b30, 0x0, 0x7fcbd88e6380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-link-binary` (refused)

Command: `cc /tmp/final2/contract-scratch/cc-link-binary/link.o -o /tmp/final2/contract-scratch/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff6fa7d440, 0x7fff6fa7d910, 0x7fff6fa7d370, 0x0, 0x7fc509fe9380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/final2/contract-scratch/ar-static-archive/libmember.a /tmp/final2/contract-scratch/ar-static-archive/member.o`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `objcopy-strip-unneeded` (reuse_was_not_obtained)

Command: `objcopy --strip-unneeded /tmp/final2/contract-scratch/objcopy-strip-unneeded/obj.o /tmp/final2/contract-scratch/objcopy-strip-unneeded/obj.stripped.o`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/final2/contract-scratch/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/final2/contract-scratch/shell-pipeline/pipeline.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/final2/contract-scratch/multi-file-compile-ar-hash/source.c -o /tmp/final2/contract-scratch/multi-file-compile-ar-hash/a.o && ar rcs /tmp/final2/contract-scratch/multi-file-compile-ar-hash/liba.a /tmp/final2/contract-scratch/multi-file-compile-ar-hash/a.o && sha256sum /tmp/final2/contract-scratch/multi-file-compile-ar-hash/liba.a > /tmp/final2/contract-scratch/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc50555270, 0x7ffc505557f8, 0x7ffc505553c0, 0x0, 0x7ff344c35380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/final2/contract-scratch/python-csv-json/sales.csv /tmp/final2/contract-scratch/python-csv-json/customers.csv /tmp/final2/contract-scratch/python-csv-json/report.json`

- process read system clock: monotonic
- process read randomness via getrandom
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/final2/contract-scratch/python-csv-json-seeded/sales.csv /tmp/final2/contract-scratch/python-csv-json-seeded/customers.csv /tmp/final2/contract-scratch/python-csv-json-seeded/report.json`

- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/final2/contract-scratch/awk-codegen/schema.tsv > /tmp/final2/contract-scratch/awk-codegen/generated.h`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/final2/contract-scratch/groff-manpage-html/census.1 > /tmp/final2/contract-scratch/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/final2/contract-scratch/pil-image-transform/source.png /tmp/final2/contract-scratch/pil-image-transform/transformed.png`

- process read system clock: monotonic
- process read randomness via getrandom
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/final2/contract-scratch/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/final2/contract-scratch/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/final2/contract-scratch/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: status-flag change on fd 3 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 4 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/final2/contract-scratch/tar-create-archive/bundle.tar -C /tmp/final2/contract-scratch/tar-create-archive lines.txt blob.bin`

- process read system clock: realtime
- process wrote network: failed socket control (errno 2)
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/final2/contract-scratch/awk-sum-stdout/lines.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/final2/contract-scratch/awk-scientific-iter/numbers.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sort-numbers` (refused)

Command: `sort /tmp/final2/contract-scratch/sort-numbers/numbers.txt`

- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `dd-copy-file` (refused)

Command: `dd if=/tmp/final2/contract-scratch/dd-copy-file/blob.bin of=/tmp/final2/contract-scratch/dd-copy-file/copy.bin bs=4096 status=none`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/final2/contract-scratch/jq-sum-values/rows.json`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/final2/contract-scratch/perl-sum-values/lines.txt`

- process read randomness via /dev/urandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `make-awk-target` (refused)

Command: `make -C /tmp/final2/contract-scratch/make-awk-target all`

- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `rustc-hello` (refused)

Command: `rustc -O /tmp/final2/contract-scratch/rustc-hello/hello.rs -o /tmp/final2/contract-scratch/rustc-hello/hello`

- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7fff60eb5680, 0x3, 0x0, 0x0, 0xfefa3203, 0x178bfbff]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 290: unmodeled syscall 290 args [0x0, 0x80800, 0x0, 0x55d2d6ccb8b0, 0x78, 0x0]
- unmodeled successful syscall 233: unmodeled syscall 233 args [0x3, 0x1, 0x4, 0x7fff60eb26b8, 0x78, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523c3fec00, 0x7f523c3fec00, 0x72656b726f772d74, 0x7f523c606780, 0x1]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523c1fdc00, 0x7f523c1fdc00, 0x72656b726f772d74, 0x0, 0x7f523c1fe6c0]
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523bffcc00, 0x7f523bffcc00, 0x72656b726f772d74, 0x0, 0x7f523bffd6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523bdfbc00, 0x7f523bdfbc00, 0x72656b726f772d74, 0x0, 0x7f523bdfc6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523bbfac00, 0x7f523bbfac00, 0x72656b726f772d74, 0x0, 0x7f523bbfb6c0]
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523b9f9c00, 0x7f523b9f9c00, 0x72656b726f772d74, 0x0, 0x7f523b9fa6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523b7f8c00, 0x7f523b7f8c00, 0x72656b726f772d74, 0x0, 0x7f523b7f96c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7f523b5f7c00, 0x7f523b5f7c00, 0x72656b726f772d74, 0x0, 0x7f523b5f86c0]
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
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffdfbed3820, 0x3, 0x0, 0x0, 0x3, 0x7fe573e70380]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/statm
- unmodeled successful syscall 332: statx result is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe55fbfaf80, 0x7fe55fbfaf80, 0x632d6c72, 0x7fe570ebfb80, 0x1]
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
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe55f3faf80, 0x7fe55f3faf80, 0x63747375, 0x7fe570ebfb80, 0x7fe55f3ff6c0]
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
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe556579f80, 0x7fe556579f80, 0x726f74616e696472, 0x7fe570ebfb80, 0x7fe55657e6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe5559faf80, 0x7fe5559faf80, 0x302e756763207470, 0x7fe570ebfb80, 0x7fe5559ff6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe5559faf80, 0x7fe5559faf80, 0x302e756763206f74, 0x7fe570ebfb80, 0x7fe5559ff6c0]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 16: status-flag change on fd 5 whose open file description is shared or unclassified
- unmodeled successful syscall 16: status-flag change on fd 7 whose open file description is shared or unclassified
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffd2801cbc0, 0x3, 0x0, 0xa, 0x3, 0x7f3f100d7380]
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
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7fe55f371954, 0x2, 0xffffffff, 0x0, 0x0, 0x0]
- unmodeled successful syscall 16: status-flag change on fd 7 whose open file description is shared or unclassified
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- pipe 1: more than one process wrote to it, so byte order depends on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

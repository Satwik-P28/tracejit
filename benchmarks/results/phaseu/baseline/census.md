# TraceJIT real-world compatibility census

Commit: `e107bb83fb5b14443e134a8b037a7c8608ab7d43`
 (working tree dirty: `False`)

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
| `cc-compile-fixture` | compiler | refused | Unknown | 1259 | 2 | 208.657 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 251 | 2 | 57.738 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 233 | 4 | 42.657 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 57 | 2 | 6.490 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | refused | Nondeterministic | 33 | 1 | 5.848 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 81 | 1 | 8.037 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 320 | 5 | 68.874 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 199 | 1 | 62.459 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 199 | 1 | 30.556 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 4.933 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 30.700 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 444 | 1 | 76.199 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1168 | 0 | 51.087 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 2.120 ms | 14.550 ms | 0.146x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 19 | 1 | 3.760 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | refused | Nondeterministic | 10 | 0 | 20.002 ms | - | - | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 54 | 0 | 5.683 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Nondeterministic | 72 | 1 | 5.012 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | refused | Nondeterministic | 60 | 0 | 2.963 ms | - | - | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 22 | 0 | 1.444 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 22 | 0 | 2.384 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 55 | 0 | 2.468 ms | - | - | PASS |
| `wc-line-count` | text | refused | Nondeterministic | 51 | 0 | 2.825 ms | - | - | PASS |
| `sha256sum-blob` | digest | refused | Nondeterministic | 54 | 0 | 3.089 ms | - | - | PASS |
| `openssl-sha256` | digest | refused | Nondeterministic | 15 | 0 | 7.348 ms | - | - | PASS |
| `od-hex-prefix` | inspect | refused | Nondeterministic | 51 | 0 | 2.586 ms | - | - | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 51 | 1 | 2.713 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 64 | 0 | 7.280 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Unknown | 63 | 0 | 12.026 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 62 | 0 | 5.826 ms | - | - | FAIL |
| `rustc-hello` | rust | refused | Unknown | 539 | 13 | 119.537 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| randomness | 18 | 18 |
| clock | 9 | 11 |
| system_information | 4 | 7 |
| process_identity | 3 | 4 |
| failed_descriptor_operation | 2 | 2 |
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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/census-base/scratch/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe9788fbd0, 0x7ffe97890158, 0x7ffe9788fd20, 0x0, 0x7fe071780380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/census-base/scratch/cc-compile-large/source.c -o /tmp/census-base/scratch/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffddfdb1ab0, 0x7ffddfdb2038, 0x7ffddfdb1c00, 0x0, 0x7fdbe826c380]

### `cc-link-binary` (refused)

Command: `cc /tmp/census-base/scratch/cc-link-binary/link.o -o /tmp/census-base/scratch/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffda89f19b0, 0x7ffda89f1e80, 0x7ffda89f18e0, 0x0, 0x7f50ee020380]

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/census-base/scratch/ar-static-archive/libmember.a /tmp/census-base/scratch/ar-static-archive/member.o`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system clock: monotonic

### `objcopy-strip-unneeded` (refused)

Command: `objcopy --strip-unneeded /tmp/census-base/scratch/objcopy-strip-unneeded/obj.o /tmp/census-base/scratch/objcopy-strip-unneeded/obj.stripped.o`

- process read randomness via getrandom
- process read system information via prlimit64

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/census-base/scratch/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/census-base/scratch/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/census-base/scratch/multi-file-compile-ar-hash/source.c -o /tmp/census-base/scratch/multi-file-compile-ar-hash/a.o && ar rcs /tmp/census-base/scratch/multi-file-compile-ar-hash/liba.a /tmp/census-base/scratch/multi-file-compile-ar-hash/a.o && sha256sum /tmp/census-base/scratch/multi-file-compile-ar-hash/liba.a > /tmp/census-base/scratch/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff910a4690, 0x7fff910a4c18, 0x7fff910a47e0, 0x0, 0x7f39d2fb9380]

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/census-base/scratch/python-csv-json/sales.csv /tmp/census-base/scratch/python-csv-json/customers.csv /tmp/census-base/scratch/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/census-base/scratch/python-csv-json-seeded/sales.csv /tmp/census-base/scratch/python-csv-json-seeded/customers.csv /tmp/census-base/scratch/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/census-base/scratch/awk-codegen/schema.tsv > /tmp/census-base/scratch/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/census-base/scratch/groff-manpage-html/census.1 > /tmp/census-base/scratch/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/census-base/scratch/pil-image-transform/source.png /tmp/census-base/scratch/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f4f164172a8, 0x0, 0x0]

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- non-file output cannot be restored: /dev/null

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/census-base/scratch/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/census-base/scratch/gzip-roundtrip-file/gunzip.bin`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling

### `bzip2-compress-stdout` (refused)

Command: `bzip2 -c /tmp/census-base/scratch/bzip2-compress-stdout/blob.bin`

- process read randomness via getrandom

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/census-base/scratch/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/census-base/scratch/tar-create-archive/bundle.tar -C /tmp/census-base/scratch/tar-create-archive lines.txt blob.bin`

- process read randomness via getrandom
- process read system clock: realtime
- process wrote network: failed socket control (errno 2)

### `sed-rewrite-stdout` (refused)

Command: `sed s/value=/v=/g /tmp/census-base/scratch/sed-rewrite-stdout/lines.txt`

- process read randomness via getrandom

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/census-base/scratch/awk-sum-stdout/lines.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/census-base/scratch/awk-scientific-iter/numbers.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `sort-numbers` (refused)

Command: `sort /tmp/census-base/scratch/sort-numbers/numbers.txt`

- process read randomness via getrandom
- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo

### `wc-line-count` (refused)

Command: `wc -l /tmp/census-base/scratch/wc-line-count/lines.txt`

- process read randomness via getrandom

### `sha256sum-blob` (refused)

Command: `sha256sum /tmp/census-base/scratch/sha256sum-blob/blob.bin`

- process read randomness via getrandom

### `openssl-sha256` (refused)

Command: `openssl dgst -sha256 /tmp/census-base/scratch/openssl-sha256/blob.bin`

- process read randomness via getrandom

### `od-hex-prefix` (refused)

Command: `od -An -tx1 -N 256 /tmp/census-base/scratch/od-hex-prefix/blob.bin`

- process read randomness via getrandom

### `dd-copy-file` (refused)

Command: `dd if=/tmp/census-base/scratch/dd-copy-file/blob.bin of=/tmp/census-base/scratch/dd-copy-file/copy.bin bs=4096 status=none`

- process read randomness via getrandom
- process read system clock: monotonic

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/census-base/scratch/jq-sum-values/rows.json`

- process read randomness via getrandom

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/census-base/scratch/perl-sum-values/lines.txt`

- opened dependency cannot be guarded: /dev/null
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 3
- unmodeled successful syscall 5: fstat on unclassified fd 3

### `make-awk-target` (refused)

Command: `make -C /tmp/census-base/scratch/make-awk-target all`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled

### `rustc-hello` (refused)

Command: `rustc -O /tmp/census-base/scratch/rustc-hello/hello.rs -o /tmp/census-base/scratch/rustc-hello/hello`

- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffe6681f630, 0x3, 0x0, 0x0, 0xfefa3203, 0x178bfbff]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 13): statx result is not modeled
- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x7ffe6681cb70, 0x0, 0x558d9ae208b0, 0x78, 0x0]
- unmodeled successful syscall 290: unmodeled syscall 290 args [0x0, 0x80800, 0x0, 0x558d9ae208b0, 0x78, 0x0]
- unmodeled successful syscall 233: unmodeled syscall 233 args [0x3, 0x1, 0x4, 0x7ffe6681c638, 0x78, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52dffec00, 0x7fc52dffec00, 0x72656b726f772d74, 0x7fc52e206780, 0x1]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52ddfdc00, 0x7fc52ddfdc00, 0x72656b726f772d74, 0x0, 0x7fc52ddfe6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52dbfcc00, 0x7fc52dbfcc00, 0x72656b726f772d74, 0x0, 0x7fc52dbfd6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52d9fbc00, 0x7fc52d9fbc00, 0x72656b726f772d74, 0x0, 0x7fc52d9fc6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52d7fac00, 0x7fc52d7fac00, 0x72656b726f772d74, 0x0, 0x7fc52d7fb6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52d5f9c00, 0x7fc52d5f9c00, 0x72656b726f772d74, 0x0, 0x7fc52d5fa6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52d3f8c00, 0x7fc52d3f8c00, 0x72656b726f772d74, 0x0, 0x7fc52d3f96c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fc52d1f7c00, 0x7fc52d1f7c00, 0x72656b726f772d74, 0x0, 0x7fc52d1f86c0]
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
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7fffe4efad80, 0x3, 0x0, 0x0, 0x3, 0x7fb36c936380]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/statm
- unmodeled successful syscall 332: statx result is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fb3585faf80, 0x7fb3585faf80, 0x632d6c72, 0x7fb3698bfb80, 0x1]
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
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fb357dfaf80, 0x7fb357dfaf80, 0x63747375, 0x7fb3698bfb80, 0x7fb357dff6c0]
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
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fb34ef79f80, 0x7fb34ef79f80, 0x726f74616e696472, 0x7fb3698bfb80, 0x7fb34ef7e6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fb34e3faf80, 0x7fb34e3faf80, 0x302e756763207470, 0x7fb3698bfb80, 0x7fb34e3ff6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fb34e3faf80, 0x7fb34e3faf80, 0x302e756763206f74, 0x7fb3698bfb80, 0x7fb34e3ff6c0]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x5, 0x5421, 0x7fb357d71954, 0x0, 0x7fb358b5a200, 0x0]
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x7, 0x5421, 0x7fb357d71954, 0x0, 0x7fb358b5a200, 0x0]
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 2
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 2
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffcde5a3300, 0x3, 0x0, 0xa, 0x3, 0x7f7ac3abb380]
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
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7fb357d71954, 0x2, 0xffffffff, 0x0, 0x0, 0x0]
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x7, 0x5421, 0x7fb357d71964, 0x0, 0x0, 0x0]
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- pipe 1: more than one process wrote to it, so byte order depends on scheduling


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

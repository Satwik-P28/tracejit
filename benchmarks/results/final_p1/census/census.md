# TraceJIT real-world compatibility census

Commit: `026e660f6722ee7dddbf8ec00caaf52a817c36cf`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 32
- Attempted: 32
- Reused with a verified cache hit: 1
- Refused by TraceJIT: 30
- Failed to execute: 1
- Blocked on a missing tool: 0
- Eligibility rate: 0.031

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Nondeterministic | 656 | 2 | 83.625 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Nondeterministic | 223 | 2 | 43.333 ms | - | - | PASS |
| `clang-compile-large` | compiler | refused | Nondeterministic | 221 | 2 | 41.554 ms | - | - | PASS |
| `cc-link-binary` | linker | refused | Unknown | 281 | 1 | 19.494 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 92 | 2 | 8.908 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | refused | Nondeterministic | 23 | 1 | 1.327 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 42 | 1 | 1.651 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Nondeterministic | 291 | 5 | 55.443 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 188 | 1 | 19.857 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 188 | 1 | 19.726 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 23 | 1 | 1.459 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 110 | 1 | 10.171 ms | - | - | PASS |
| `pil-image-transform` | image | workload_failed | - | - | - | - | - | - | - |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 648 | 0 | 32.412 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 0.968 ms | 3.131 ms | 0.309x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 20 | 1 | 1.850 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | refused | Nondeterministic | 10 | 0 | 8.565 ms | - | - | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 26 | 0 | 1.359 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Nondeterministic | 56 | 1 | 1.043 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | refused | Nondeterministic | 20 | 0 | 0.954 ms | - | - | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 12 | 0 | 0.864 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 12 | 0 | 0.741 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 13 | 0 | 1.131 ms | - | - | PASS |
| `wc-line-count` | text | refused | Nondeterministic | 9 | 0 | 0.649 ms | - | - | PASS |
| `sha256sum-blob` | digest | refused | Nondeterministic | 12 | 0 | 1.053 ms | - | - | PASS |
| `openssl-sha256` | digest | refused | Nondeterministic | 15 | 0 | 2.221 ms | - | - | PASS |
| `od-hex-prefix` | inspect | refused | Nondeterministic | 9 | 0 | 0.725 ms | - | - | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 23 | 1 | 0.827 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 21 | 0 | 1.927 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Unknown | 21 | 0 | 1.646 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 34 | 0 | 0.845 ms | - | - | PASS |
| `rustc-hello` | rust | refused | Unknown | 472 | 7 | 100.317 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| randomness | 22 | 22 |
| clock | 9 | 11 |
| process_identity | 4 | 6 |
| system_information | 4 | 6 |
| failed_descriptor_operation | 2 | 2 |
| other:clone file-descriptor and cwd sharing semantics are not elig | 1 | 11 |
| procfs_process_relative | 1 | 5 |
| network | 1 | 1 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 2: more than one process wrote to it, so byte order dep | 1 | 1 |
| other:pipe 3: a read returned less than it requested and more data | 1 | 1 |
| unhashable_open | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 5 |
| 16 | 16: ioctl | 4 |
| 72 | 72: fcntl | 3 |
| 98 | 98: getrusage | 2 |
| 157 | 157: prctl | 1 |
| 233 | 233: epoll_ctl | 1 |
| 290 | 290: eventfd2 | 1 |
| 291 | 291: epoll_create1 | 1 |
| 332 | 332: statx | 1 |
| 7 | 7: poll | 1 |
| 73 | 73: flock | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /agent/repos/tracejit-final-adv/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-8ugkhpd9/cc-compile-fixture/fixture.o`

- process read randomness via getrandom

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-8ugkhpd9/cc-compile-large/source.c -o /tmp/tracejit-census-8ugkhpd9/cc-compile-large/source.o`

- process read randomness via getrandom

### `clang-compile-large` (refused)

Command: `clang -O2 -Wall -Wextra -c /tmp/tracejit-census-8ugkhpd9/clang-compile-large/source.c -o /tmp/tracejit-census-8ugkhpd9/clang-compile-large/clang.o`

- process read randomness via getrandom

### `cc-link-binary` (refused)

Command: `cc /tmp/tracejit-census-8ugkhpd9/cc-link-binary/link.o -o /tmp/tracejit-census-8ugkhpd9/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe4ed90a90, 0x7ffe4ed90ef0, 0x7ffe4ed909c0, 0x0, 0x7f5536eb1380]

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/tracejit-census-8ugkhpd9/ar-static-archive/libmember.a /tmp/tracejit-census-8ugkhpd9/ar-static-archive/member.o`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system clock: monotonic

### `objcopy-strip-unneeded` (refused)

Command: `objcopy --strip-unneeded /tmp/tracejit-census-8ugkhpd9/objcopy-strip-unneeded/obj.o /tmp/tracejit-census-8ugkhpd9/objcopy-strip-unneeded/obj.stripped.o`

- process read randomness via getrandom
- process read system information via prlimit64

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-8ugkhpd9/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-8ugkhpd9/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 3: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/tracejit-census-8ugkhpd9/multi-file-compile-ar-hash/source.c -o /tmp/tracejit-census-8ugkhpd9/multi-file-compile-ar-hash/a.o && ar rcs /tmp/tracejit-census-8ugkhpd9/multi-file-compile-ar-hash/liba.a /tmp/tracejit-census-8ugkhpd9/multi-file-compile-ar-hash/a.o && sha256sum /tmp/tracejit-census-8ugkhpd9/multi-file-compile-ar-hash/liba.a > /tmp/tracejit-census-8ugkhpd9/multi-file-compile-ar-hash/liba.sha256`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system information via prlimit64
- process read system clock: monotonic

### `python-csv-json` (refused)

Command: `/usr/bin/python3 /agent/repos/tracejit-final-adv/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-8ugkhpd9/python-csv-json/sales.csv /tmp/tracejit-census-8ugkhpd9/python-csv-json/customers.csv /tmp/tracejit-census-8ugkhpd9/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/usr/bin/python3 /agent/repos/tracejit-final-adv/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-8ugkhpd9/python-csv-json-seeded/sales.csv /tmp/tracejit-census-8ugkhpd9/python-csv-json-seeded/customers.csv /tmp/tracejit-census-8ugkhpd9/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /agent/repos/tracejit-final-adv/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-8ugkhpd9/awk-codegen/schema.tsv > /tmp/tracejit-census-8ugkhpd9/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-8ugkhpd9/groff-manpage-html/census.1 > /tmp/tracejit-census-8ugkhpd9/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (workload_failed)

Command: `/usr/bin/python3 /agent/repos/tracejit-final-adv/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-8ugkhpd9/pil-image-transform/source.png /tmp/tracejit-census-8ugkhpd9/pil-image-transform/transformed.png`

- Traceback (most recent call last):
  File "/agent/repos/tracejit-final-adv/benchmarks/realworld/workloads/image_transform.py", line 37, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "/agent/repos/tracejit-final-adv/benchmarks/realworld/workloads/image_transform.py", line 24, in main
    from PIL import Image
ModuleNotFoundError: No module named 'PIL'


### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /agent/repos/tracejit-final-adv/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/tracejit-census-8ugkhpd9/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/tracejit-census-8ugkhpd9/gzip-roundtrip-file/gunzip.bin`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling

### `bzip2-compress-stdout` (refused)

Command: `bzip2 -c /tmp/tracejit-census-8ugkhpd9/bzip2-compress-stdout/blob.bin`

- process read randomness via getrandom

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/tracejit-census-8ugkhpd9/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/tracejit-census-8ugkhpd9/tar-create-archive/bundle.tar -C /tmp/tracejit-census-8ugkhpd9/tar-create-archive lines.txt blob.bin`

- process read randomness via getrandom
- process read system clock: realtime
- process wrote network: failed socket control (errno 2)

### `sed-rewrite-stdout` (refused)

Command: `sed s/value=/v=/g /tmp/tracejit-census-8ugkhpd9/sed-rewrite-stdout/lines.txt`

- process read randomness via getrandom

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/tracejit-census-8ugkhpd9/awk-sum-stdout/lines.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/tracejit-census-8ugkhpd9/awk-scientific-iter/numbers.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `sort-numbers` (refused)

Command: `sort /tmp/tracejit-census-8ugkhpd9/sort-numbers/numbers.txt`

- process read randomness via getrandom
- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo

### `wc-line-count` (refused)

Command: `wc -l /tmp/tracejit-census-8ugkhpd9/wc-line-count/lines.txt`

- process read randomness via getrandom

### `sha256sum-blob` (refused)

Command: `sha256sum /tmp/tracejit-census-8ugkhpd9/sha256sum-blob/blob.bin`

- process read randomness via getrandom

### `openssl-sha256` (refused)

Command: `openssl dgst -sha256 /tmp/tracejit-census-8ugkhpd9/openssl-sha256/blob.bin`

- process read randomness via getrandom

### `od-hex-prefix` (refused)

Command: `od -An -tx1 -N 256 /tmp/tracejit-census-8ugkhpd9/od-hex-prefix/blob.bin`

- process read randomness via getrandom

### `dd-copy-file` (refused)

Command: `dd if=/tmp/tracejit-census-8ugkhpd9/dd-copy-file/blob.bin of=/tmp/tracejit-census-8ugkhpd9/dd-copy-file/copy.bin bs=4096 status=none`

- process read randomness via getrandom
- process read system clock: monotonic

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/tracejit-census-8ugkhpd9/jq-sum-values/rows.json`

- process read randomness via getrandom

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/tracejit-census-8ugkhpd9/perl-sum-values/lines.txt`

- opened dependency cannot be guarded: /dev/null
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 3
- unmodeled successful syscall 5: fstat on unclassified fd 3

### `make-awk-target` (refused)

Command: `make -C /tmp/tracejit-census-8ugkhpd9/make-awk-target all`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled

### `rustc-hello` (refused)

Command: `rustc -O /tmp/tracejit-census-8ugkhpd9/rustc-hello/hello.rs -o /tmp/tracejit-census-8ugkhpd9/rustc-hello/hello`

- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffdd3a3fb00, 0x3, 0x0, 0x1, 0xfffa3227, 0x5fabfbff]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x7ffdd3a3d070, 0x0, 0x55612520d8b0, 0x78, 0x0]
- unmodeled successful syscall 290: unmodeled syscall 290 args [0x0, 0x80800, 0x0, 0x55612520d8b0, 0x78, 0x0]
- unmodeled successful syscall 233: unmodeled syscall 233 args [0x3, 0x1, 0x4, 0x7ffdd3a3cb38, 0x78, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe14cbfec00, 0xf, 0x72656b726f772d74, 0x7fe14ce06780, 0x1]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe14c7fcc00, 0xf, 0x72656b726f772d74, 0x0, 0x7fe14c7fd6c0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe14c9fdc00, 0xf, 0x72656b726f772d74, 0x0, 0x7fe14c9fe6c0]
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7fe14c5fbc00, 0xf, 0x72656b726f772d74, 0x0, 0x7fe14c5fc6c0]
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 73: unmodeled syscall 73 args [0x6, 0x1, 0x0, 0x0, 0x0, 0x6c6d6f742e7367]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- process-relative procfs dependency: /proc/self/cgroup
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffd730f6030, 0x3, 0x0, 0x0, 0x3, 0x7ff455f63380]
- process-relative procfs dependency: /proc/self/maps
- process-relative procfs dependency: /proc/self/statm
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled failed syscall 332 (errno 2): statx AT_SYMLINK_NOFOLLOW result is not modeled
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7ff4463fe000, 0x2, 0x6c727463, 0xffffffff, 0x0]
- unmodeled failed syscall 332 (errno 14): statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7ff445bfd080, 0x1, 0x74737572, 0xffffffff, 0x0]
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
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7ff43e9fcce0, 0xb, 0x726f74616e696472, 0xffffffff, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7ff43d7fdeb0, 0xf, 0x6578776661733172, 0xffffffff, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7ff43cffdeb0, 0x9, 0x302e756763207470, 0xffffffff, 0x0]
- clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse
- unmodeled successful syscall 157: unmodeled syscall 157 args [0xf, 0x7ff43d7fdeb0, 0x9, 0x302e756763206f74, 0xffffffff, 0x0]
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled successful syscall 332: statx result is not modeled
- unmodeled failed syscall 332 (errno 2): statx result is not modeled
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x7, 0x5421, 0x7ff445be3b9c, 0x0, 0x7ff446973d10, 0x0]
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x9, 0x5421, 0x7ff445be3b9c, 0x0, 0x7ff446973d10, 0x0]
- unmodeled successful syscall 5: fstat on pipe descriptor 2 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 2 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcc311da30, 0x7ffcc311df90, 0x7ffcc311d960, 0x0, 0x7f513705e380]
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ff445be3b9c, 0x2, 0xffffffff, 0x0, 0x0, 0x0]
- unmodeled successful syscall 16: unmodeled syscall 16 args [0x9, 0x5421, 0x7ff445be3bac, 0x0, 0x0, 0x0]
- unmodeled successful syscall 332: statx AT_SYMLINK_NOFOLLOW result is not modeled
- pipe 2: more than one process wrote to it, so byte order depends on scheduling


## Environment

```text
Linux cursor 6.12.113+ #1 SMP PREEMPT_DYNAMIC Fri Nov 13 20:22:28 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

# TraceJIT real-world compatibility census

Commit: `7f013a5490b5566d6b18fbd5d2a29463a4842ba5`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 32
- Attempted: 30
- Reused with a verified cache hit: 1
- Refused by TraceJIT: 29
- Failed to execute: 0
- Blocked on a missing tool: 2
- Eligibility rate: 0.033

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Unknown | 1283 | 2 | 228.433 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 247 | 2 | 48.693 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 225 | 4 | 22.706 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 56 | 2 | 3.437 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | refused | Nondeterministic | 32 | 1 | 2.531 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 78 | 1 | 4.733 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 314 | 5 | 51.142 ms | - | - | PASS |
| `python-csv-json` | python | refused | Unknown | 199 | 1 | 28.898 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Unknown | 199 | 1 | 29.652 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 31 | 1 | 2.267 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 115 | 1 | 14.652 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 444 | 1 | 67.332 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1195 | 0 | 41.545 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 1.821 ms | 6.766 ms | 0.269x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 18 | 1 | 2.456 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | refused | Nondeterministic | 10 | 0 | 9.905 ms | - | - | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 54 | 0 | 2.603 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Unknown | 72 | 1 | 2.523 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | refused | Nondeterministic | 60 | 0 | 1.927 ms | - | - | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 22 | 0 | 1.413 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 22 | 0 | 1.246 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 55 | 0 | 1.899 ms | - | - | PASS |
| `wc-line-count` | text | refused | Nondeterministic | 51 | 0 | 1.432 ms | - | - | PASS |
| `sha256sum-blob` | digest | refused | Nondeterministic | 54 | 0 | 2.369 ms | - | - | PASS |
| `openssl-sha256` | digest | refused | Nondeterministic | 15 | 0 | 5.430 ms | - | - | PASS |
| `od-hex-prefix` | inspect | refused | Nondeterministic | 51 | 0 | 1.894 ms | - | - | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 51 | 1 | 2.079 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 64 | 0 | 4.778 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 63 | 0 | 5.529 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 62 | 0 | 4.091 ms | - | - | FAIL |
| `rustc-hello` | rust | blocked: missing rustc | - | - | - | - | - | - | - |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| randomness | 16 | 17 |
| clock | 7 | 7 |
| system_information | 2 | 5 |
| process_identity | 1 | 2 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 3: a read returned less than it requested and more data | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 72 | 72: fcntl | 6 |
| 98 | 98: getrusage | 4 |
| 5 | 5: fstat | 3 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-0upffb_8/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe5bdc64c0, 0x7ffe5bdc6a48, 0x7ffe5bdc6610, 0x0, 0x7fc335df2380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-0upffb_8/cc-compile-large/source.c -o /tmp/tracejit-census-0upffb_8/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff2827b1a0, 0x7fff2827b728, 0x7fff2827b2f0, 0x0, 0x7f497cdb5380]

### `cc-link-binary` (refused)

Command: `cc /tmp/tracejit-census-0upffb_8/cc-link-binary/link.o -o /tmp/tracejit-census-0upffb_8/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd40b27030, 0x7ffd40b27500, 0x7ffd40b26f60, 0x0, 0x7fd7b685c380]

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/tracejit-census-0upffb_8/ar-static-archive/libmember.a /tmp/tracejit-census-0upffb_8/ar-static-archive/member.o`

- process read randomness via getrandom
- process read system clock: monotonic

### `objcopy-strip-unneeded` (refused)

Command: `objcopy --strip-unneeded /tmp/tracejit-census-0upffb_8/objcopy-strip-unneeded/obj.o /tmp/tracejit-census-0upffb_8/objcopy-strip-unneeded/obj.stripped.o`

- process read randomness via getrandom

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-0upffb_8/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-0upffb_8/shell-pipeline/pipeline.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 3: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/tracejit-census-0upffb_8/multi-file-compile-ar-hash/source.c -o /tmp/tracejit-census-0upffb_8/multi-file-compile-ar-hash/a.o && ar rcs /tmp/tracejit-census-0upffb_8/multi-file-compile-ar-hash/liba.a /tmp/tracejit-census-0upffb_8/multi-file-compile-ar-hash/a.o && sha256sum /tmp/tracejit-census-0upffb_8/multi-file-compile-ar-hash/liba.a > /tmp/tracejit-census-0upffb_8/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff1e2989e0, 0x7fff1e298f68, 0x7fff1e298b30, 0x0, 0x7f09218b6380]

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-0upffb_8/python-csv-json/sales.csv /tmp/tracejit-census-0upffb_8/python-csv-json/customers.csv /tmp/tracejit-census-0upffb_8/python-csv-json/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-0upffb_8/python-csv-json-seeded/sales.csv /tmp/tracejit-census-0upffb_8/python-csv-json-seeded/customers.csv /tmp/tracejit-census-0upffb_8/python-csv-json-seeded/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-0upffb_8/awk-codegen/schema.tsv > /tmp/tracejit-census-0upffb_8/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-0upffb_8/groff-manpage-html/census.1 > /tmp/tracejit-census-0upffb_8/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-0upffb_8/pil-image-transform/source.png /tmp/tracejit-census-0upffb_8/pil-image-transform/transformed.png`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/tracejit-census-0upffb_8/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/tracejit-census-0upffb_8/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling

### `bzip2-compress-stdout` (refused)

Command: `bzip2 -c /tmp/tracejit-census-0upffb_8/bzip2-compress-stdout/blob.bin`

- process read randomness via getrandom

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/tracejit-census-0upffb_8/xz-compress-stdout/blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 3 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 4 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified

### `tar-create-archive` (refused)

Command: `tar -cf /tmp/tracejit-census-0upffb_8/tar-create-archive/bundle.tar -C /tmp/tracejit-census-0upffb_8/tar-create-archive lines.txt blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded

### `sed-rewrite-stdout` (refused)

Command: `sed s/value=/v=/g /tmp/tracejit-census-0upffb_8/sed-rewrite-stdout/lines.txt`

- process read randomness via getrandom

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/tracejit-census-0upffb_8/awk-sum-stdout/lines.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/tracejit-census-0upffb_8/awk-scientific-iter/numbers.txt`

- process read randomness via getrandom
- process read system clock: realtime

### `sort-numbers` (refused)

Command: `sort /tmp/tracejit-census-0upffb_8/sort-numbers/numbers.txt`

- process read randomness via getrandom
- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo

### `wc-line-count` (refused)

Command: `wc -l /tmp/tracejit-census-0upffb_8/wc-line-count/lines.txt`

- process read randomness via getrandom

### `sha256sum-blob` (refused)

Command: `sha256sum /tmp/tracejit-census-0upffb_8/sha256sum-blob/blob.bin`

- process read randomness via getrandom

### `openssl-sha256` (refused)

Command: `openssl dgst -sha256 /tmp/tracejit-census-0upffb_8/openssl-sha256/blob.bin`

- process read randomness via getrandom

### `od-hex-prefix` (refused)

Command: `od -An -tx1 -N 256 /tmp/tracejit-census-0upffb_8/od-hex-prefix/blob.bin`

- process read randomness via getrandom

### `dd-copy-file` (refused)

Command: `dd if=/tmp/tracejit-census-0upffb_8/dd-copy-file/blob.bin of=/tmp/tracejit-census-0upffb_8/dd-copy-file/copy.bin bs=4096 status=none`

- process read randomness via getrandom
- process read system clock: monotonic

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/tracejit-census-0upffb_8/jq-sum-values/rows.json`

- process read randomness via getrandom

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/tracejit-census-0upffb_8/perl-sum-values/lines.txt`

- process read randomness via getrandom
- process read randomness via /dev/urandom
- process read system clock: realtime

### `make-awk-target` (refused)

Command: `make -C /tmp/tracejit-census-0upffb_8/make-awk-target all`

- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

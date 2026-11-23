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
| `cc-compile-fixture` | compiler | refused | Unknown | 1283 | 2 | 242.984 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 247 | 2 | 47.703 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 225 | 4 | 17.829 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 56 | 2 | 2.761 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | refused | Nondeterministic | 32 | 1 | 2.052 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 78 | 1 | 4.822 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 314 | 5 | 68.119 ms | - | - | PASS |
| `python-csv-json` | python | refused | Unknown | 199 | 1 | 29.563 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Unknown | 199 | 1 | 28.497 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 31 | 1 | 2.224 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 115 | 1 | 13.815 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 444 | 1 | 73.318 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1195 | 0 | 51.122 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 1.786 ms | 7.155 ms | 0.250x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 18 | 1 | 2.848 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | refused | Nondeterministic | 10 | 0 | 9.800 ms | - | - | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 54 | 0 | 2.568 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Unknown | 72 | 1 | 3.199 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | refused | Nondeterministic | 60 | 0 | 2.017 ms | - | - | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 22 | 0 | 1.311 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 22 | 0 | 1.209 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 55 | 0 | 2.025 ms | - | - | PASS |
| `wc-line-count` | text | refused | Nondeterministic | 51 | 0 | 1.627 ms | - | - | PASS |
| `sha256sum-blob` | digest | refused | Nondeterministic | 54 | 0 | 2.083 ms | - | - | PASS |
| `openssl-sha256` | digest | refused | Nondeterministic | 15 | 0 | 5.775 ms | - | - | PASS |
| `od-hex-prefix` | inspect | refused | Nondeterministic | 51 | 0 | 1.769 ms | - | - | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 51 | 1 | 1.818 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 64 | 0 | 3.447 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 63 | 0 | 3.758 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 62 | 0 | 4.952 ms | - | - | FAIL |
| `rustc-hello` | rust | blocked: missing rustc | - | - | - | - | - | - | - |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 29 | 29 |
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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-6xxg7131/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcc12f4c30, 0x7ffcc12f51b8, 0x7ffcc12f4d80, 0x0, 0x7fd3d7cf6380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-6xxg7131/cc-compile-large/source.c -o /tmp/tracejit-census-6xxg7131/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffe66c1c60, 0x7fffe66c21e8, 0x7fffe66c1db0, 0x0, 0x7f695fd94380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-link-binary` (refused)

Command: `cc /tmp/tracejit-census-6xxg7131/cc-link-binary/link.o -o /tmp/tracejit-census-6xxg7131/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffee41f4370, 0x7ffee41f4840, 0x7ffee41f42a0, 0x0, 0x7f89b4469380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/tracejit-census-6xxg7131/ar-static-archive/libmember.a /tmp/tracejit-census-6xxg7131/ar-static-archive/member.o`

- process read randomness via getrandom
- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `objcopy-strip-unneeded` (refused)

Command: `objcopy --strip-unneeded /tmp/tracejit-census-6xxg7131/objcopy-strip-unneeded/obj.o /tmp/tracejit-census-6xxg7131/objcopy-strip-unneeded/obj.stripped.o`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-6xxg7131/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-6xxg7131/shell-pipeline/pipeline.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 3: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/tracejit-census-6xxg7131/multi-file-compile-ar-hash/source.c -o /tmp/tracejit-census-6xxg7131/multi-file-compile-ar-hash/a.o && ar rcs /tmp/tracejit-census-6xxg7131/multi-file-compile-ar-hash/liba.a /tmp/tracejit-census-6xxg7131/multi-file-compile-ar-hash/a.o && sha256sum /tmp/tracejit-census-6xxg7131/multi-file-compile-ar-hash/liba.a > /tmp/tracejit-census-6xxg7131/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffa9c36470, 0x7fffa9c369f8, 0x7fffa9c365c0, 0x0, 0x7f969a303380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-6xxg7131/python-csv-json/sales.csv /tmp/tracejit-census-6xxg7131/python-csv-json/customers.csv /tmp/tracejit-census-6xxg7131/python-csv-json/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-6xxg7131/python-csv-json-seeded/sales.csv /tmp/tracejit-census-6xxg7131/python-csv-json-seeded/customers.csv /tmp/tracejit-census-6xxg7131/python-csv-json-seeded/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-6xxg7131/awk-codegen/schema.tsv > /tmp/tracejit-census-6xxg7131/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-6xxg7131/groff-manpage-html/census.1 > /tmp/tracejit-census-6xxg7131/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-6xxg7131/pil-image-transform/source.png /tmp/tracejit-census-6xxg7131/pil-image-transform/transformed.png`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `gzip-roundtrip-file` (refused)

Command: `sh -c gzip -c -n /tmp/tracejit-census-6xxg7131/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/tracejit-census-6xxg7131/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `bzip2-compress-stdout` (refused)

Command: `bzip2 -c /tmp/tracejit-census-6xxg7131/bzip2-compress-stdout/blob.bin`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/tracejit-census-6xxg7131/xz-compress-stdout/blob.bin`

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

Command: `tar -cf /tmp/tracejit-census-6xxg7131/tar-create-archive/bundle.tar -C /tmp/tracejit-census-6xxg7131/tar-create-archive lines.txt blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sed-rewrite-stdout` (refused)

Command: `sed s/value=/v=/g /tmp/tracejit-census-6xxg7131/sed-rewrite-stdout/lines.txt`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/tracejit-census-6xxg7131/awk-sum-stdout/lines.txt`

- process read randomness via getrandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/tracejit-census-6xxg7131/awk-scientific-iter/numbers.txt`

- process read randomness via getrandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sort-numbers` (refused)

Command: `sort /tmp/tracejit-census-6xxg7131/sort-numbers/numbers.txt`

- process read randomness via getrandom
- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `wc-line-count` (refused)

Command: `wc -l /tmp/tracejit-census-6xxg7131/wc-line-count/lines.txt`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sha256sum-blob` (refused)

Command: `sha256sum /tmp/tracejit-census-6xxg7131/sha256sum-blob/blob.bin`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `openssl-sha256` (refused)

Command: `openssl dgst -sha256 /tmp/tracejit-census-6xxg7131/openssl-sha256/blob.bin`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `od-hex-prefix` (refused)

Command: `od -An -tx1 -N 256 /tmp/tracejit-census-6xxg7131/od-hex-prefix/blob.bin`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `dd-copy-file` (refused)

Command: `dd if=/tmp/tracejit-census-6xxg7131/dd-copy-file/blob.bin of=/tmp/tracejit-census-6xxg7131/dd-copy-file/copy.bin bs=4096 status=none`

- process read randomness via getrandom
- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/tracejit-census-6xxg7131/jq-sum-values/rows.json`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/tracejit-census-6xxg7131/perl-sum-values/lines.txt`

- process read randomness via getrandom
- process read randomness via /dev/urandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `make-awk-target` (refused)

Command: `make -C /tmp/tracejit-census-6xxg7131/make-awk-target all`

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

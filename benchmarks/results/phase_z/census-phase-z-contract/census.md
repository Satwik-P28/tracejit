# TraceJIT real-world compatibility census

Commit: `7f013a5490b5566d6b18fbd5d2a29463a4842ba5`
 (working tree dirty: `True`)

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
| `cc-compile-fixture` | compiler | refused | Unknown | 1284 | 2 | 223.469 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 248 | 2 | 45.791 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 226 | 4 | 23.135 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 57 | 2 | 3.134 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | reuse_was_not_obtained | Guarded | 33 | 1 | 2.702 ms | - | - | - |
| `shell-pipeline` | shell | refused | Unknown | 79 | 1 | 4.316 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 315 | 5 | 50.630 ms | - | - | PASS |
| `python-csv-json` | python | refused | Unknown | 200 | 1 | 27.274 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Unknown | 200 | 1 | 27.630 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 2.273 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 13.042 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 445 | 1 | 69.523 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1196 | 0 | 43.123 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 2.372 ms | 19.260 ms | 0.123x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 19 | 1 | 2.731 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | reused | Guarded | 11 | 0 | 9.880 ms | 9.043 ms | 1.093x | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 55 | 0 | 2.531 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Unknown | 73 | 1 | 2.659 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | reused | Guarded | 61 | 0 | 1.841 ms | 12.960 ms | 0.142x | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 23 | 0 | 1.373 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 23 | 0 | 1.153 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 56 | 0 | 1.993 ms | - | - | PASS |
| `wc-line-count` | text | reused | Guarded | 52 | 0 | 1.416 ms | 11.404 ms | 0.124x | PASS |
| `sha256sum-blob` | digest | reused | Guarded | 55 | 0 | 1.841 ms | 13.878 ms | 0.133x | PASS |
| `openssl-sha256` | digest | reused | Guarded | 16 | 0 | 3.895 ms | 11.976 ms | 0.325x | PASS |
| `od-hex-prefix` | inspect | reused | Guarded | 52 | 0 | 1.229 ms | 11.656 ms | 0.105x | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 52 | 1 | 1.467 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 65 | 0 | 3.258 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 64 | 0 | 3.568 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 63 | 0 | 3.744 ms | - | - | FAIL |
| `rustc-hello` | rust | blocked: missing rustc | - | - | - | - | - | - | - |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 22 | 22 |
| clock | 7 | 7 |
| system_information | 2 | 5 |
| other:pipe 1: a read returned less than it requested and more data | 2 | 2 |
| randomness | 2 | 2 |
| process_identity | 1 | 2 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 72 | 72: fcntl | 6 |
| 98 | 98: getrusage | 4 |
| 5 | 5: fstat | 3 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-sk1zpg9z/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffddfdb1690, 0x7ffddfdb1c18, 0x7ffddfdb17e0, 0x0, 0x7f27a91ed380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-sk1zpg9z/cc-compile-large/source.c -o /tmp/tracejit-census-sk1zpg9z/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe9db9f4f0, 0x7ffe9db9fa78, 0x7ffe9db9f640, 0x0, 0x7f04d4900380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-link-binary` (refused)

Command: `cc /tmp/tracejit-census-sk1zpg9z/cc-link-binary/link.o -o /tmp/tracejit-census-sk1zpg9z/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff9ad97a50, 0x7fff9ad97f20, 0x7fff9ad97980, 0x0, 0x7f9f7e62c380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/tracejit-census-sk1zpg9z/ar-static-archive/libmember.a /tmp/tracejit-census-sk1zpg9z/ar-static-archive/member.o`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `objcopy-strip-unneeded` (reuse_was_not_obtained)

Command: `objcopy --strip-unneeded /tmp/tracejit-census-sk1zpg9z/objcopy-strip-unneeded/obj.o /tmp/tracejit-census-sk1zpg9z/objcopy-strip-unneeded/obj.stripped.o`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-sk1zpg9z/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-sk1zpg9z/shell-pipeline/pipeline.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `multi-file-compile-ar-hash` (refused)

Command: `sh -c cc -O2 -c /tmp/tracejit-census-sk1zpg9z/multi-file-compile-ar-hash/source.c -o /tmp/tracejit-census-sk1zpg9z/multi-file-compile-ar-hash/a.o && ar rcs /tmp/tracejit-census-sk1zpg9z/multi-file-compile-ar-hash/liba.a /tmp/tracejit-census-sk1zpg9z/multi-file-compile-ar-hash/a.o && sha256sum /tmp/tracejit-census-sk1zpg9z/multi-file-compile-ar-hash/liba.a > /tmp/tracejit-census-sk1zpg9z/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc2deb4ef0, 0x7ffc2deb5478, 0x7ffc2deb5040, 0x0, 0x7f518b052380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-sk1zpg9z/python-csv-json/sales.csv /tmp/tracejit-census-sk1zpg9z/python-csv-json/customers.csv /tmp/tracejit-census-sk1zpg9z/python-csv-json/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-sk1zpg9z/python-csv-json-seeded/sales.csv /tmp/tracejit-census-sk1zpg9z/python-csv-json-seeded/customers.csv /tmp/tracejit-census-sk1zpg9z/python-csv-json-seeded/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-sk1zpg9z/awk-codegen/schema.tsv > /tmp/tracejit-census-sk1zpg9z/awk-codegen/generated.h`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-sk1zpg9z/groff-manpage-html/census.1 > /tmp/tracejit-census-sk1zpg9z/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-sk1zpg9z/pil-image-transform/source.png /tmp/tracejit-census-sk1zpg9z/pil-image-transform/transformed.png`

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

Command: `sh -c gzip -c -n /tmp/tracejit-census-sk1zpg9z/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/tracejit-census-sk1zpg9z/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/tracejit-census-sk1zpg9z/xz-compress-stdout/blob.bin`

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

Command: `tar -cf /tmp/tracejit-census-sk1zpg9z/tar-create-archive/bundle.tar -C /tmp/tracejit-census-sk1zpg9z/tar-create-archive lines.txt blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/tracejit-census-sk1zpg9z/awk-sum-stdout/lines.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/tracejit-census-sk1zpg9z/awk-scientific-iter/numbers.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sort-numbers` (refused)

Command: `sort /tmp/tracejit-census-sk1zpg9z/sort-numbers/numbers.txt`

- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `dd-copy-file` (refused)

Command: `dd if=/tmp/tracejit-census-sk1zpg9z/dd-copy-file/blob.bin of=/tmp/tracejit-census-sk1zpg9z/dd-copy-file/copy.bin bs=4096 status=none`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/tracejit-census-sk1zpg9z/jq-sum-values/rows.json`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/tracejit-census-sk1zpg9z/perl-sum-values/lines.txt`

- process read randomness via /dev/urandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `make-awk-target` (refused)

Command: `make -C /tmp/tracejit-census-sk1zpg9z/make-awk-target all`

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

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
| `cc-compile-fixture` | compiler | refused | Unknown | 1284 | 2 | 234.233 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 248 | 2 | 55.207 ms | - | - | PASS |
| `clang-compile-large` | compiler | blocked: missing clang | - | - | - | - | - | - | - |
| `cc-link-binary` | linker | refused | Unknown | 226 | 4 | 23.333 ms | - | - | PASS |
| `ar-static-archive` | archiver | refused | Nondeterministic | 57 | 2 | 3.640 ms | - | - | PASS |
| `objcopy-strip-unneeded` | toolchain | reuse_was_not_obtained | Guarded | 33 | 1 | 3.358 ms | - | - | - |
| `shell-pipeline` | shell | refused | Unknown | 79 | 1 | 6.045 ms | - | - | PASS |
| `multi-file-compile-ar-hash` | multi_file | refused | Unknown | 315 | 5 | 62.435 ms | - | - | PASS |
| `python-csv-json` | python | refused | Unknown | 200 | 1 | 32.341 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Unknown | 200 | 1 | 27.560 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 2.398 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 13.234 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 445 | 1 | 72.369 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Nondeterministic | 1196 | 0 | 49.879 ms | - | - | PASS |
| `gzip-compress-stdout` | compress | reused | Guarded | 9 | 0 | 1.765 ms | 7.229 ms | 0.244x | PASS |
| `gzip-roundtrip-file` | compress | refused | Unknown | 19 | 1 | 2.490 ms | - | - | PASS |
| `bzip2-compress-stdout` | compress | reused | Guarded | 11 | 0 | 11.193 ms | 9.235 ms | 1.212x | PASS |
| `xz-compress-stdout` | compress | refused | Unknown | 55 | 0 | 2.490 ms | - | - | PASS |
| `tar-create-archive` | archiver | refused | Unknown | 73 | 1 | 2.493 ms | - | - | PASS |
| `sed-rewrite-stdout` | text | reused | Guarded | 61 | 0 | 2.074 ms | 15.476 ms | 0.134x | PASS |
| `awk-sum-stdout` | text | refused | Nondeterministic | 23 | 0 | 1.570 ms | - | - | PASS |
| `awk-scientific-iter` | scientific | refused | Nondeterministic | 23 | 0 | 1.215 ms | - | - | PASS |
| `sort-numbers` | text | refused | Nondeterministic | 56 | 0 | 2.046 ms | - | - | PASS |
| `wc-line-count` | text | reused | Guarded | 52 | 0 | 1.239 ms | 14.657 ms | 0.085x | PASS |
| `sha256sum-blob` | digest | reused | Guarded | 55 | 0 | 1.828 ms | 13.453 ms | 0.136x | PASS |
| `openssl-sha256` | digest | reused | Guarded | 16 | 0 | 4.804 ms | 14.439 ms | 0.333x | PASS |
| `od-hex-prefix` | inspect | reused | Guarded | 52 | 0 | 1.472 ms | 10.755 ms | 0.137x | PASS |
| `dd-copy-file` | io | refused | Nondeterministic | 52 | 1 | 2.433 ms | - | - | PASS |
| `jq-sum-values` | data | refused | Nondeterministic | 65 | 0 | 6.107 ms | - | - | PASS |
| `perl-sum-values` | script | refused | Nondeterministic | 64 | 0 | 12.812 ms | - | - | PASS |
| `make-awk-target` | build | refused | Unknown | 63 | 0 | 3.969 ms | - | - | FAIL |
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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/24375cea864939ae012511ac/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-xryz3_h9/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff944c2c20, 0x7fff944c31a8, 0x7fff944c2d70, 0x0, 0x7f6c22cb5380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-xryz3_h9/cc-compile-large/source.c -o /tmp/tracejit-census-xryz3_h9/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd0494e770, 0x7ffd0494ecf8, 0x7ffd0494e8c0, 0x0, 0x7f4130255380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `cc-link-binary` (refused)

Command: `cc /tmp/tracejit-census-xryz3_h9/cc-link-binary/link.o -o /tmp/tracejit-census-xryz3_h9/cc-link-binary/linked`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd027865f0, 0x7ffd02786ac0, 0x7ffd02786520, 0x0, 0x7fb189aac380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `ar-static-archive` (refused)

Command: `ar rcs /tmp/tracejit-census-xryz3_h9/ar-static-archive/libmember.a /tmp/tracejit-census-xryz3_h9/ar-static-archive/member.o`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `objcopy-strip-unneeded` (reuse_was_not_obtained)

Command: `objcopy --strip-unneeded /tmp/tracejit-census-xryz3_h9/objcopy-strip-unneeded/obj.o /tmp/tracejit-census-xryz3_h9/objcopy-strip-unneeded/obj.stripped.o`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-xryz3_h9/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-xryz3_h9/shell-pipeline/pipeline.out`

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

Command: `sh -c cc -O2 -c /tmp/tracejit-census-xryz3_h9/multi-file-compile-ar-hash/source.c -o /tmp/tracejit-census-xryz3_h9/multi-file-compile-ar-hash/a.o && ar rcs /tmp/tracejit-census-xryz3_h9/multi-file-compile-ar-hash/liba.a /tmp/tracejit-census-xryz3_h9/multi-file-compile-ar-hash/a.o && sha256sum /tmp/tracejit-census-xryz3_h9/multi-file-compile-ar-hash/liba.a > /tmp/tracejit-census-xryz3_h9/multi-file-compile-ar-hash/liba.sha256`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcb6c7d6c0, 0x7ffcb6c7dc48, 0x7ffcb6c7d810, 0x0, 0x7f5e6b850380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-xryz3_h9/python-csv-json/sales.csv /tmp/tracejit-census-xryz3_h9/python-csv-json/customers.csv /tmp/tracejit-census-xryz3_h9/python-csv-json/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-xryz3_h9/python-csv-json-seeded/sales.csv /tmp/tracejit-census-xryz3_h9/python-csv-json-seeded/customers.csv /tmp/tracejit-census-xryz3_h9/python-csv-json-seeded/report.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-xryz3_h9/awk-codegen/schema.tsv > /tmp/tracejit-census-xryz3_h9/awk-codegen/generated.h`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-xryz3_h9/groff-manpage-html/census.1 > /tmp/tracejit-census-xryz3_h9/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/24375cea864939ae012511ac/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-xryz3_h9/pil-image-transform/source.png /tmp/tracejit-census-xryz3_h9/pil-image-transform/transformed.png`

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

Command: `sh -c gzip -c -n /tmp/tracejit-census-xryz3_h9/gzip-roundtrip-file/blob.bin | gzip -dc > /tmp/tracejit-census-xryz3_h9/gzip-roundtrip-file/gunzip.bin`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `xz-compress-stdout` (refused)

Command: `xz -c -0 /tmp/tracejit-census-xryz3_h9/xz-compress-stdout/blob.bin`

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

Command: `tar -cf /tmp/tracejit-census-xryz3_h9/tar-create-archive/bundle.tar -C /tmp/tracejit-census-xryz3_h9/tar-create-archive lines.txt blob.bin`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-sum-stdout` (refused)

Command: `awk { s += $2 } END { printf "%d\n", s } /tmp/tracejit-census-xryz3_h9/awk-sum-stdout/lines.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `awk-scientific-iter` (refused)

Command: `awk BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf "%.10f\n", x } /tmp/tracejit-census-xryz3_h9/awk-scientific-iter/numbers.txt`

- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `sort-numbers` (refused)

Command: `sort /tmp/tracejit-census-xryz3_h9/sort-numbers/numbers.txt`

- process read system information via sched_getaffinity
- process read system information via prlimit64
- process read system information via sysinfo
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `dd-copy-file` (refused)

Command: `dd if=/tmp/tracejit-census-xryz3_h9/dd-copy-file/blob.bin of=/tmp/tracejit-census-xryz3_h9/dd-copy-file/copy.bin bs=4096 status=none`

- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `jq-sum-values` (refused)

Command: `jq [.[].value] | add /tmp/tracejit-census-xryz3_h9/jq-sum-values/rows.json`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `perl-sum-values` (refused)

Command: `perl -lne $s += $1 if /value=(\d+)/; END { print $s+0 } /tmp/tracejit-census-xryz3_h9/perl-sum-values/lines.txt`

- process read randomness via /dev/urandom
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `make-awk-target` (refused)

Command: `make -C /tmp/tracejit-census-xryz3_h9/make-awk-target all`

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

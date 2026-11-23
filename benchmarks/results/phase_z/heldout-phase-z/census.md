# TraceJIT real-world compatibility census

Commit: `7f013a5490b5566d6b18fbd5d2a29463a4842ba5`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 20
- Attempted: 20
- Reused with a verified cache hit: 7
- Refused by TraceJIT: 10
- Failed to execute: 0
- Blocked on a missing tool: 0
- Eligibility rate: 0.350

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 274 | 1 | 14.310 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 471 | 7 | 63.525 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 68 | 0 | 72.663 ms | - | - | FAIL |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 72 | 3 | 5.566 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | reuse_was_not_obtained | Guarded | 33 | 1 | 2.083 ms | - | - | - |
| `heldout-objdump-disassemble` | toolchain | reused | Guarded | 35 | 0 | 6.723 ms | 16.232 ms | 0.414x | PASS |
| `heldout-readelf-header` | toolchain | reused | Guarded | 31 | 0 | 2.431 ms | 12.272 ms | 0.198x | PASS |
| `heldout-nm-symbols` | toolchain | reuse_was_not_obtained | Guarded | 57 | 0 | 2.458 ms | - | - | - |
| `heldout-tar-gzip` | archive | refused | Unknown | 90 | 1 | 4.871 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | reuse_was_not_obtained | Guarded | 27 | 2 | 2.076 ms | - | - | - |
| `heldout-iconv-transcode` | text | reused | Guarded | 55 | 0 | 1.470 ms | 16.074 ms | 0.091x | PASS |
| `heldout-base64-encode` | text | reused | Guarded | 53 | 0 | 1.347 ms | 12.934 ms | 0.104x | PASS |
| `heldout-md5sum` | digest | reused | Guarded | 55 | 0 | 2.455 ms | 15.764 ms | 0.156x | PASS |
| `heldout-cut-columns` | data | reused | Guarded | 53 | 0 | 1.404 ms | 16.213 ms | 0.087x | PASS |
| `heldout-grep-count` | text | refused | Unknown | 55 | 0 | 2.565 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 72 | 1 | 3.822 ms | - | - | PASS |
| `heldout-comm-sorted` | text | reused | Guarded | 55 | 0 | 1.506 ms | 12.442 ms | 0.121x | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 101 | 0 | 7.050 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Unknown | 162 | 1 | 24.462 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 65 | 0 | 7.395 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 10 | 10 |
| procfs_process_relative | 3 | 6 |
| other:pipe 1: a read returned less than it requested and more data | 3 | 3 |
| clock | 2 | 2 |
| other:pipe 2: a read returned less than it requested and more data | 2 | 2 |
| process_identity | 1 | 2 |
| system_information | 1 | 2 |
| other:pipe 4: a read returned less than it requested and more data | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 4 |
| 72 | 72: fcntl | 4 |
| 7 | 7: poll | 1 |
| 98 | 98: getrusage | 1 |

## Refusal detail

### `heldout-gcc-preprocess` (refused)

Command: `gcc -E -I /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-preprocess/project /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-preprocess/project/main.c -o /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-preprocess/main.i`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-compile-link/project /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-compile-link/project/main.c /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-compile-link/project/util.c -o /tmp/tracejit-heldout-kd45yhrq/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe6fabcb90, 0x7ffe6fabd128, 0x7ffe6fabcce0, 0x0, 0x7fb7b44f8380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd440de640, 0x7ffd440debd8, 0x7ffd440de790, 0x0, 0x7f565f376380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe9a0e4850, 0x7ffe9a0e4d28, 0x7ffe9a0e4780, 0x0, 0x7fb78bad7380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-make-build` (refused)

Command: `make -C /tmp/tracejit-heldout-kd45yhrq/heldout-make-build/project all`

- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/tracejit-heldout-kd45yhrq/heldout-ar-ranlib/libheldout.a /tmp/tracejit-heldout-kd45yhrq/heldout-ar-ranlib/util.o && ranlib /tmp/tracejit-heldout-kd45yhrq/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-strip-binary` (reuse_was_not_obtained)

Command: `strip --strip-unneeded -o /tmp/tracejit-heldout-kd45yhrq/heldout-strip-binary/app-stripped /tmp/tracejit-heldout-kd45yhrq/heldout-strip-binary/app-full`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-nm-symbols` (reuse_was_not_obtained)

Command: `nm --defined-only /tmp/tracejit-heldout-kd45yhrq/heldout-nm-symbols/app-full`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/tracejit-heldout-kd45yhrq/heldout-tar-gzip/bundle.tar.gz -C /tmp/tracejit-heldout-kd45yhrq/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-unzip-extract` (reuse_was_not_obtained)

Command: `unzip -q -o /tmp/tracejit-heldout-kd45yhrq/heldout-unzip-extract/extracted.zip -d /tmp/tracejit-heldout-kd45yhrq/heldout-unzip-extract/unzipped`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/tracejit-heldout-kd45yhrq/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/tracejit-heldout-kd45yhrq/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/tracejit-heldout-kd45yhrq/heldout-sort-unique-pipeline/frequencies.txt`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/tracejit-heldout-kd45yhrq/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffc821d1550, 0x4, 0x0, 0x7fbe325b2fc0, 0x55d1b647d010, 0x0]
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-python-json` (refused)

Command: `/opt/freestyle/python/bin/python3 -c import json,sys
rows = json.load(open(sys.argv[1]))
out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]
open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))
 /tmp/tracejit-heldout-kd45yhrq/heldout-python-json/rows.json /tmp/tracejit-heldout-kd45yhrq/heldout-python-json/filtered.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-shell-script` (refused)

Command: `sh /tmp/tracejit-heldout-kd45yhrq/heldout-shell-script/script.sh /tmp/tracejit-heldout-kd45yhrq/heldout-shell-script/words.txt`

- process-relative procfs dependency: /proc/self/maps
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- process-relative procfs dependency: /proc/self/maps
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- process-relative procfs dependency: /proc/self/maps
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- process-relative procfs dependency: /proc/self/maps
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 4: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

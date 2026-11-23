# TraceJIT real-world compatibility census

Commit: `7f013a5490b5566d6b18fbd5d2a29463a4842ba5`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 20
- Attempted: 20
- Reused with a verified cache hit: 0
- Refused by TraceJIT: 20
- Failed to execute: 0
- Blocked on a missing tool: 0
- Eligibility rate: 0.000

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 273 | 1 | 11.170 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 470 | 7 | 58.791 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 67 | 0 | 67.411 ms | - | - | FAIL |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 71 | 3 | 5.654 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | refused | Nondeterministic | 32 | 1 | 3.687 ms | - | - | PASS |
| `heldout-objdump-disassemble` | toolchain | refused | Nondeterministic | 34 | 0 | 5.984 ms | - | - | PASS |
| `heldout-readelf-header` | toolchain | refused | Nondeterministic | 30 | 0 | 2.910 ms | - | - | PASS |
| `heldout-nm-symbols` | toolchain | refused | Nondeterministic | 56 | 0 | 2.303 ms | - | - | PASS |
| `heldout-tar-gzip` | archive | refused | Unknown | 89 | 1 | 5.369 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | refused | Nondeterministic | 26 | 2 | 2.829 ms | - | - | PASS |
| `heldout-iconv-transcode` | text | refused | Nondeterministic | 54 | 0 | 3.875 ms | - | - | PASS |
| `heldout-base64-encode` | text | refused | Nondeterministic | 52 | 0 | 1.992 ms | - | - | PASS |
| `heldout-md5sum` | digest | refused | Nondeterministic | 54 | 0 | 3.698 ms | - | - | PASS |
| `heldout-cut-columns` | data | refused | Nondeterministic | 52 | 0 | 1.660 ms | - | - | PASS |
| `heldout-grep-count` | text | refused | Unknown | 54 | 0 | 1.937 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 71 | 1 | 5.562 ms | - | - | PASS |
| `heldout-comm-sorted` | text | refused | Nondeterministic | 54 | 0 | 1.885 ms | - | - | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 100 | 0 | 5.821 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Unknown | 161 | 1 | 25.554 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 64 | 0 | 8.290 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 20 | 20 |
| randomness | 12 | 12 |
| procfs_process_relative | 3 | 6 |
| clock | 2 | 2 |
| process_identity | 1 | 2 |
| system_information | 1 | 2 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |
| other:pipe 3: a read returned less than it requested and more data | 1 | 1 |
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

Command: `gcc -E -I /tmp/tracejit-heldout-odkn9gws/heldout-gcc-preprocess/project /tmp/tracejit-heldout-odkn9gws/heldout-gcc-preprocess/project/main.c -o /tmp/tracejit-heldout-odkn9gws/heldout-gcc-preprocess/main.i`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/tracejit-heldout-odkn9gws/heldout-gcc-compile-link/project /tmp/tracejit-heldout-odkn9gws/heldout-gcc-compile-link/project/main.c /tmp/tracejit-heldout-odkn9gws/heldout-gcc-compile-link/project/util.c -o /tmp/tracejit-heldout-odkn9gws/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe2a186630, 0x7ffe2a186bc8, 0x7ffe2a186780, 0x0, 0x7f18a3bb2380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc4b009ea0, 0x7ffc4b00a438, 0x7ffc4b009ff0, 0x0, 0x7f0db8e41380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff5cde6b20, 0x7fff5cde6ff8, 0x7fff5cde6a50, 0x0, 0x7f8de03b2380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-make-build` (refused)

Command: `make -C /tmp/tracejit-heldout-odkn9gws/heldout-make-build/project all`

- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/tracejit-heldout-odkn9gws/heldout-ar-ranlib/libheldout.a /tmp/tracejit-heldout-odkn9gws/heldout-ar-ranlib/util.o && ranlib /tmp/tracejit-heldout-odkn9gws/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-strip-binary` (refused)

Command: `strip --strip-unneeded -o /tmp/tracejit-heldout-odkn9gws/heldout-strip-binary/app-stripped /tmp/tracejit-heldout-odkn9gws/heldout-strip-binary/app-full`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-objdump-disassemble` (refused)

Command: `objdump -d --no-show-raw-insn /tmp/tracejit-heldout-odkn9gws/heldout-objdump-disassemble/app-full`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-readelf-header` (refused)

Command: `readelf -h /tmp/tracejit-heldout-odkn9gws/heldout-readelf-header/app-full`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-nm-symbols` (refused)

Command: `nm --defined-only /tmp/tracejit-heldout-odkn9gws/heldout-nm-symbols/app-full`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/tracejit-heldout-odkn9gws/heldout-tar-gzip/bundle.tar.gz -C /tmp/tracejit-heldout-odkn9gws/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-unzip-extract` (refused)

Command: `unzip -q -o /tmp/tracejit-heldout-odkn9gws/heldout-unzip-extract/extracted.zip -d /tmp/tracejit-heldout-odkn9gws/heldout-unzip-extract/unzipped`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-iconv-transcode` (refused)

Command: `iconv -f UTF-8 -t ISO-8859-1 /tmp/tracejit-heldout-odkn9gws/heldout-iconv-transcode/words.txt`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-base64-encode` (refused)

Command: `base64 -w 76 /tmp/tracejit-heldout-odkn9gws/heldout-base64-encode/words.txt`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-md5sum` (refused)

Command: `md5sum /tmp/tracejit-heldout-odkn9gws/heldout-md5sum/words.txt`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-cut-columns` (refused)

Command: `cut -d , -f 1,3 /tmp/tracejit-heldout-odkn9gws/heldout-cut-columns/sales.csv`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/tracejit-heldout-odkn9gws/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/tracejit-heldout-odkn9gws/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/tracejit-heldout-odkn9gws/heldout-sort-unique-pipeline/frequencies.txt`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-comm-sorted` (refused)

Command: `comm -12 /tmp/tracejit-heldout-odkn9gws/heldout-comm-sorted/a.txt /tmp/tracejit-heldout-odkn9gws/heldout-comm-sorted/b.txt`

- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/tracejit-heldout-odkn9gws/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffe688e9e60, 0x4, 0x0, 0x7f7f34db2fc0, 0x55ce8d968010, 0x0]
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-python-json` (refused)

Command: `/opt/freestyle/python/bin/python3 -c import json,sys
rows = json.load(open(sys.argv[1]))
out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]
open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))
 /tmp/tracejit-heldout-odkn9gws/heldout-python-json/rows.json /tmp/tracejit-heldout-odkn9gws/heldout-python-json/filtered.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-shell-script` (refused)

Command: `sh /tmp/tracejit-heldout-odkn9gws/heldout-shell-script/script.sh /tmp/tracejit-heldout-odkn9gws/heldout-shell-script/words.txt`

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
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 3: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 4: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

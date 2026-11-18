# TraceJIT real-world compatibility census

Commit: `b9752324b125b8fd1659d820433d889973ced88d`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 20
- Attempted: 20
- Reused with a verified cache hit: 6
- Refused by TraceJIT: 13
- Failed to execute: 0
- Blocked on a missing tool: 0
- Eligibility rate: 0.300

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 276 | 1 | 14.426 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 480 | 7 | 59.118 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 68 | 0 | 91.279 ms | - | - | FAIL |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 73 | 3 | 6.555 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | refused | Nondeterministic | 34 | 1 | 3.081 ms | - | - | PASS |
| `heldout-objdump-disassemble` | toolchain | refused | Nondeterministic | 35 | 0 | 2.950 ms | - | - | PASS |
| `heldout-readelf-header` | toolchain | reused | Guarded | 31 | 0 | 2.072 ms | 36.477 ms | 0.057x | PASS |
| `heldout-nm-symbols` | toolchain | refused | Nondeterministic | 58 | 0 | 4.950 ms | - | - | PASS |
| `heldout-tar-gzip` | archive | refused | Unknown | 91 | 1 | 6.349 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | reuse_was_not_obtained | Guarded | 29 | 2 | 2.960 ms | - | - | - |
| `heldout-iconv-transcode` | text | reused | Guarded | 55 | 0 | 2.402 ms | 24.963 ms | 0.096x | PASS |
| `heldout-base64-encode` | text | reused | Guarded | 53 | 0 | 1.824 ms | 30.088 ms | 0.061x | PASS |
| `heldout-md5sum` | digest | reused | Guarded | 55 | 0 | 2.341 ms | 22.146 ms | 0.106x | PASS |
| `heldout-cut-columns` | data | reused | Guarded | 53 | 0 | 2.515 ms | 28.908 ms | 0.087x | PASS |
| `heldout-grep-count` | text | refused | Unknown | 55 | 0 | 3.286 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 74 | 1 | 5.442 ms | - | - | PASS |
| `heldout-comm-sorted` | text | reused | Guarded | 55 | 0 | 2.373 ms | 33.236 ms | 0.071x | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 105 | 0 | 8.402 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Nondeterministic | 162 | 1 | 44.238 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 66 | 0 | 10.209 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 13 | 13 |
| system_information | 5 | 6 |
| procfs_process_relative | 3 | 6 |
| clock | 3 | 4 |
| process_identity | 2 | 3 |
| failed_descriptor_operation | 2 | 2 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |
| unhashable_open | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 4 |
| 16 | 16: ioctl | 1 |
| 7 | 7: poll | 1 |
| 72 | 72: fcntl | 1 |
| 98 | 98: getrusage | 1 |

## Refusal detail

### `heldout-gcc-preprocess` (refused)

Command: `gcc -E -I /tmp/base2/held-contract-scratch/heldout-gcc-preprocess/project /tmp/base2/held-contract-scratch/heldout-gcc-preprocess/project/main.c -o /tmp/base2/held-contract-scratch/heldout-gcc-preprocess/main.i`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/base2/held-contract-scratch/heldout-gcc-compile-link/project /tmp/base2/held-contract-scratch/heldout-gcc-compile-link/project/main.c /tmp/base2/held-contract-scratch/heldout-gcc-compile-link/project/util.c -o /tmp/base2/held-contract-scratch/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe0c6de670, 0x7ffe0c6dec08, 0x7ffe0c6de7c0, 0x0, 0x7f23df841380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcad6872a0, 0x7ffcad687838, 0x7ffcad6873f0, 0x0, 0x7fe671b02380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcaea07570, 0x7ffcaea07a48, 0x7ffcaea074a0, 0x0, 0x7fe451cf8380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-make-build` (refused)

Command: `make -C /tmp/base2/held-contract-scratch/heldout-make-build/project all`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/base2/held-contract-scratch/heldout-ar-ranlib/libheldout.a /tmp/base2/held-contract-scratch/heldout-ar-ranlib/util.o && ranlib /tmp/base2/held-contract-scratch/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read process identity via getppid
- process read system information via prlimit64
- process read system clock: monotonic
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-strip-binary` (refused)

Command: `strip --strip-unneeded -o /tmp/base2/held-contract-scratch/heldout-strip-binary/app-stripped /tmp/base2/held-contract-scratch/heldout-strip-binary/app-full`

- process read system information via prlimit64
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-objdump-disassemble` (refused)

Command: `objdump -d --no-show-raw-insn /tmp/base2/held-contract-scratch/heldout-objdump-disassemble/app-full`

- process read system information via prlimit64
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-nm-symbols` (refused)

Command: `nm --defined-only /tmp/base2/held-contract-scratch/heldout-nm-symbols/app-full`

- process read system information via prlimit64
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/base2/held-contract-scratch/heldout-tar-gzip/bundle.tar.gz -C /tmp/base2/held-contract-scratch/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-unzip-extract` (reuse_was_not_obtained)

Command: `unzip -q -o /tmp/base2/held-contract-scratch/heldout-unzip-extract/extracted.zip -d /tmp/base2/held-contract-scratch/heldout-unzip-extract/unzipped`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/base2/held-contract-scratch/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/base2/held-contract-scratch/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/base2/held-contract-scratch/heldout-sort-unique-pipeline/frequencies.txt`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/base2/held-contract-scratch/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- failed fd operation on -1 is not modeled (errno 9)
- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffe71e0de40, 0x4, 0x0, 0x7f688b9b2fc0, 0x55b0e2206010, 0x0]
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 1
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- opened dependency cannot be guarded: /dev/null
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-python-json` (refused)

Command: `/opt/freestyle/python/bin/python3 -c import json,sys
rows = json.load(open(sys.argv[1]))
out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]
open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))
 /tmp/base2/held-contract-scratch/heldout-python-json/rows.json /tmp/base2/held-contract-scratch/heldout-python-json/filtered.json`

- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-shell-script` (refused)

Command: `sh /tmp/base2/held-contract-scratch/heldout-shell-script/script.sh /tmp/base2/held-contract-scratch/heldout-shell-script/words.txt`

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
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

# TraceJIT real-world compatibility census

Commit: `b9752324b125b8fd1659d820433d889973ced88d`
 (working tree dirty: `True`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 20
- Attempted: 20
- Reused with a verified cache hit: 8
- Refused by TraceJIT: 10
- Failed to execute: 0
- Blocked on a missing tool: 0
- Eligibility rate: 0.400

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 276 | 1 | 14.675 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 474 | 7 | 76.582 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 68 | 0 | 106.064 ms | - | - | FAIL |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 71 | 3 | 11.267 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | reuse_was_not_obtained | Guarded | 34 | 1 | 3.683 ms | - | - | - |
| `heldout-objdump-disassemble` | toolchain | reused | Guarded | 35 | 0 | 5.398 ms | 32.928 ms | 0.164x | PASS |
| `heldout-readelf-header` | toolchain | reused | Guarded | 31 | 0 | 3.057 ms | 20.108 ms | 0.152x | PASS |
| `heldout-nm-symbols` | toolchain | reused | Guarded | 57 | 0 | 4.607 ms | 23.168 ms | 0.199x | PASS |
| `heldout-tar-gzip` | archive | refused | Unknown | 90 | 1 | 7.302 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | reuse_was_not_obtained | Guarded | 29 | 2 | 3.979 ms | - | - | - |
| `heldout-iconv-transcode` | text | reused | Guarded | 55 | 0 | 2.736 ms | 17.329 ms | 0.158x | PASS |
| `heldout-base64-encode` | text | reused | Guarded | 53 | 0 | 2.570 ms | 26.120 ms | 0.098x | PASS |
| `heldout-md5sum` | digest | reused | Guarded | 55 | 0 | 3.480 ms | 32.515 ms | 0.107x | PASS |
| `heldout-cut-columns` | data | reused | Guarded | 53 | 0 | 2.488 ms | 21.038 ms | 0.118x | PASS |
| `heldout-grep-count` | text | refused | Unknown | 55 | 0 | 1.635 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 72 | 1 | 6.300 ms | - | - | PASS |
| `heldout-comm-sorted` | text | reused | Guarded | 55 | 0 | 1.296 ms | 23.681 ms | 0.055x | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 101 | 0 | 4.240 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Nondeterministic | 162 | 1 | 37.054 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 65 | 0 | 9.451 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 10 | 10 |
| procfs_process_relative | 3 | 6 |
| clock | 3 | 4 |
| process_identity | 2 | 3 |
| system_information | 1 | 2 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |
| randomness | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 4 |
| 7 | 7: poll | 1 |
| 72 | 72: fcntl | 1 |
| 98 | 98: getrusage | 1 |

## Refusal detail

### `heldout-gcc-preprocess` (refused)

Command: `gcc -E -I /tmp/final/census_v03.py-contract/scratch/heldout-gcc-preprocess/project /tmp/final/census_v03.py-contract/scratch/heldout-gcc-preprocess/project/main.c -o /tmp/final/census_v03.py-contract/scratch/heldout-gcc-preprocess/main.i`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/final/census_v03.py-contract/scratch/heldout-gcc-compile-link/project /tmp/final/census_v03.py-contract/scratch/heldout-gcc-compile-link/project/main.c /tmp/final/census_v03.py-contract/scratch/heldout-gcc-compile-link/project/util.c -o /tmp/final/census_v03.py-contract/scratch/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe2aad7760, 0x7ffe2aad7cf8, 0x7ffe2aad78b0, 0x0, 0x7fcab9f88380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc2085ef00, 0x7ffc2085f498, 0x7ffc2085f050, 0x0, 0x7f3682ed3380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffdd984140, 0x7fffdd984618, 0x7fffdd984070, 0x0, 0x7f583f80d380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-make-build` (refused)

Command: `make -C /tmp/final/census_v03.py-contract/scratch/heldout-make-build/project all`

- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/final/census_v03.py-contract/scratch/heldout-ar-ranlib/libheldout.a /tmp/final/census_v03.py-contract/scratch/heldout-ar-ranlib/util.o && ranlib /tmp/final/census_v03.py-contract/scratch/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: monotonic
- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-strip-binary` (reuse_was_not_obtained)

Command: `strip --strip-unneeded -o /tmp/final/census_v03.py-contract/scratch/heldout-strip-binary/app-stripped /tmp/final/census_v03.py-contract/scratch/heldout-strip-binary/app-full`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/final/census_v03.py-contract/scratch/heldout-tar-gzip/bundle.tar.gz -C /tmp/final/census_v03.py-contract/scratch/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-unzip-extract` (reuse_was_not_obtained)

Command: `unzip -q -o /tmp/final/census_v03.py-contract/scratch/heldout-unzip-extract/extracted.zip -d /tmp/final/census_v03.py-contract/scratch/heldout-unzip-extract/unzipped`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/final/census_v03.py-contract/scratch/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/final/census_v03.py-contract/scratch/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/final/census_v03.py-contract/scratch/heldout-sort-unique-pipeline/frequencies.txt`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/final/census_v03.py-contract/scratch/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffece3062e0, 0x4, 0x0, 0x7fa9499b2fc0, 0x556fddeb3010, 0x0]
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-python-json` (refused)

Command: `/opt/freestyle/python/bin/python3 -c import json,sys
rows = json.load(open(sys.argv[1]))
out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]
open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))
 /tmp/final/census_v03.py-contract/scratch/heldout-python-json/rows.json /tmp/final/census_v03.py-contract/scratch/heldout-python-json/filtered.json`

- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-shell-script` (refused)

Command: `sh /tmp/final/census_v03.py-contract/scratch/heldout-shell-script/script.sh /tmp/final/census_v03.py-contract/scratch/heldout-shell-script/words.txt`

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

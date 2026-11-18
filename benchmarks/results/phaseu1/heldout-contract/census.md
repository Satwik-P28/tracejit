# TraceJIT real-world compatibility census

Commit: `5e2ca1d7efaf5c8772610be1eaf57e3d194e74c2`
 (working tree dirty: `False`)

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
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 274 | 1 | 12.578 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 472 | 7 | 70.058 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 68 | 0 | 2.219 ms | - | - | PASS |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 71 | 3 | 6.247 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | reuse_was_not_obtained | Guarded | 34 | 1 | 3.040 ms | - | - | - |
| `heldout-objdump-disassemble` | toolchain | reused | Guarded | 35 | 0 | 2.969 ms | 18.585 ms | 0.160x | PASS |
| `heldout-readelf-header` | toolchain | reused | Guarded | 31 | 0 | 1.434 ms | 18.919 ms | 0.076x | PASS |
| `heldout-nm-symbols` | toolchain | reused | Guarded | 57 | 0 | 2.283 ms | 17.589 ms | 0.130x | PASS |
| `heldout-tar-gzip` | archive | refused | Unknown | 90 | 1 | 4.178 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | reuse_was_not_obtained | Guarded | 29 | 2 | 2.501 ms | - | - | - |
| `heldout-iconv-transcode` | text | reused | Guarded | 55 | 0 | 1.622 ms | 17.410 ms | 0.093x | PASS |
| `heldout-base64-encode` | text | reused | Guarded | 53 | 0 | 1.464 ms | 17.938 ms | 0.082x | PASS |
| `heldout-md5sum` | digest | reused | Guarded | 55 | 0 | 1.720 ms | 23.169 ms | 0.074x | PASS |
| `heldout-cut-columns` | data | reused | Guarded | 53 | 0 | 1.248 ms | 13.701 ms | 0.091x | PASS |
| `heldout-grep-count` | text | refused | Unknown | 55 | 0 | 1.728 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 72 | 1 | 3.964 ms | - | - | PASS |
| `heldout-comm-sorted` | text | reused | Guarded | 55 | 0 | 1.637 ms | 16.966 ms | 0.096x | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 101 | 0 | 5.376 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Unknown | 162 | 1 | 26.560 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 65 | 0 | 9.889 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| other:executed under the tracejit.allocator-entropy.v1 contract; r | 10 | 10 |
| procfs_process_relative | 3 | 6 |
| clock | 2 | 2 |
| process_identity | 1 | 2 |
| system_information | 1 | 2 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |
| randomness | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 4 |
| 72 | 72: fcntl | 4 |
| 7 | 7: poll | 1 |
| 98 | 98: getrusage | 1 |

## Refusal detail

### `heldout-gcc-preprocess` (refused)

Command: `gcc -E -I /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-preprocess/project /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-preprocess/project/main.c -o /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-preprocess/main.i`

- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-compile-link/project /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-compile-link/project/main.c /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-compile-link/project/util.c -o /tmp/tracejit-heldout-5bpy8j0p/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcb326d200, 0x7ffcb326d798, 0x7ffcb326d350, 0x0, 0x7f3e1f07f380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcd7726c10, 0x7ffcd77271a8, 0x7ffcd7726d60, 0x0, 0x7f89dbf48380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcd4861ac0, 0x7ffcd4861f98, 0x7ffcd48619f0, 0x0, 0x7f19280a7380]
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-make-build` (refused)

Command: `make -C /tmp/tracejit-heldout-5bpy8j0p/heldout-make-build/project all`

- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/tracejit-heldout-5bpy8j0p/heldout-ar-ranlib/libheldout.a /tmp/tracejit-heldout-5bpy8j0p/heldout-ar-ranlib/util.o && ranlib /tmp/tracejit-heldout-5bpy8j0p/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read process identity via getppid
- process read system clock: monotonic
- process read randomness via getrandom
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-strip-binary` (reuse_was_not_obtained)

Command: `strip --strip-unneeded -o /tmp/tracejit-heldout-5bpy8j0p/heldout-strip-binary/app-stripped /tmp/tracejit-heldout-5bpy8j0p/heldout-strip-binary/app-full`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/tracejit-heldout-5bpy8j0p/heldout-tar-gzip/bundle.tar.gz -C /tmp/tracejit-heldout-5bpy8j0p/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-unzip-extract` (reuse_was_not_obtained)

Command: `unzip -q -o /tmp/tracejit-heldout-5bpy8j0p/heldout-unzip-extract/extracted.zip -d /tmp/tracejit-heldout-5bpy8j0p/heldout-unzip-extract/unzipped`

- all observed dependencies are guardable or captured outputs
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/tracejit-heldout-5bpy8j0p/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/tracejit-heldout-5bpy8j0p/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/tracejit-heldout-5bpy8j0p/heldout-sort-unique-pipeline/frequencies.txt`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/tracejit-heldout-5bpy8j0p/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffdcae70ef0, 0x4, 0x0, 0x7f83b7db2fc0, 0x55e934f27010, 0x0]
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
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
 /tmp/tracejit-heldout-5bpy8j0p/heldout-python-json/rows.json /tmp/tracejit-heldout-5bpy8j0p/heldout-python-json/filtered.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- executed under the tracejit.allocator-entropy.v1 contract; reuse is reproducible within that contract, not equivalent to native execution

### `heldout-shell-script` (refused)

Command: `sh /tmp/tracejit-heldout-5bpy8j0p/heldout-shell-script/script.sh /tmp/tracejit-heldout-5bpy8j0p/heldout-shell-script/words.txt`

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

# TraceJIT real-world compatibility census

Commit: `5e2ca1d7efaf5c8772610be1eaf57e3d194e74c2`
 (working tree dirty: `False`)

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
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 273 | 1 | 12.535 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 471 | 7 | 64.873 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 67 | 0 | 2.029 ms | - | - | PASS |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 70 | 3 | 6.134 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | refused | Nondeterministic | 33 | 1 | 2.050 ms | - | - | PASS |
| `heldout-objdump-disassemble` | toolchain | refused | Nondeterministic | 34 | 0 | 3.520 ms | - | - | PASS |
| `heldout-readelf-header` | toolchain | refused | Nondeterministic | 30 | 0 | 1.420 ms | - | - | PASS |
| `heldout-nm-symbols` | toolchain | refused | Nondeterministic | 56 | 0 | 2.883 ms | - | - | PASS |
| `heldout-tar-gzip` | archive | refused | Unknown | 89 | 1 | 5.107 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | refused | Nondeterministic | 28 | 2 | 2.957 ms | - | - | PASS |
| `heldout-iconv-transcode` | text | refused | Nondeterministic | 54 | 0 | 2.489 ms | - | - | PASS |
| `heldout-base64-encode` | text | refused | Nondeterministic | 52 | 0 | 2.097 ms | - | - | PASS |
| `heldout-md5sum` | digest | refused | Nondeterministic | 54 | 0 | 3.460 ms | - | - | PASS |
| `heldout-cut-columns` | data | refused | Nondeterministic | 52 | 0 | 2.392 ms | - | - | PASS |
| `heldout-grep-count` | text | refused | Unknown | 54 | 0 | 2.475 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 71 | 1 | 4.998 ms | - | - | PASS |
| `heldout-comm-sorted` | text | refused | Nondeterministic | 54 | 0 | 1.272 ms | - | - | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 100 | 0 | 8.331 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Unknown | 161 | 1 | 29.181 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 64 | 0 | 10.597 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| randomness | 12 | 12 |
| procfs_process_relative | 3 | 6 |
| clock | 2 | 2 |
| process_identity | 1 | 2 |
| system_information | 1 | 2 |
| other:pipe 2: a read returned less than it requested and more data | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 4 |
| 72 | 72: fcntl | 4 |
| 7 | 7: poll | 1 |
| 98 | 98: getrusage | 1 |

## Refusal detail

### `heldout-gcc-preprocess` (refused)

Command: `gcc -E -I /tmp/tracejit-heldout-_34sgfar/heldout-gcc-preprocess/project /tmp/tracejit-heldout-_34sgfar/heldout-gcc-preprocess/project/main.c -o /tmp/tracejit-heldout-_34sgfar/heldout-gcc-preprocess/main.i`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/tracejit-heldout-_34sgfar/heldout-gcc-compile-link/project /tmp/tracejit-heldout-_34sgfar/heldout-gcc-compile-link/project/main.c /tmp/tracejit-heldout-_34sgfar/heldout-gcc-compile-link/project/util.c -o /tmp/tracejit-heldout-_34sgfar/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff07490f40, 0x7fff074914d8, 0x7fff07491090, 0x0, 0x7f11b1201380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff6aa64e50, 0x7fff6aa653e8, 0x7fff6aa64fa0, 0x0, 0x7fe4cc24a380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffe36d80c50, 0x7ffe36d81128, 0x7ffe36d80b80, 0x0, 0x7f11b64e0380]

### `heldout-make-build` (refused)

Command: `make -C /tmp/tracejit-heldout-_34sgfar/heldout-make-build/project all`

- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 1 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 3 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 72: status-flag change on fd 2 whose open file description is shared or unclassified
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/tracejit-heldout-_34sgfar/heldout-ar-ranlib/libheldout.a /tmp/tracejit-heldout-_34sgfar/heldout-ar-ranlib/util.o && ranlib /tmp/tracejit-heldout-_34sgfar/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: monotonic

### `heldout-strip-binary` (refused)

Command: `strip --strip-unneeded -o /tmp/tracejit-heldout-_34sgfar/heldout-strip-binary/app-stripped /tmp/tracejit-heldout-_34sgfar/heldout-strip-binary/app-full`

- process read randomness via getrandom

### `heldout-objdump-disassemble` (refused)

Command: `objdump -d --no-show-raw-insn /tmp/tracejit-heldout-_34sgfar/heldout-objdump-disassemble/app-full`

- process read randomness via getrandom

### `heldout-readelf-header` (refused)

Command: `readelf -h /tmp/tracejit-heldout-_34sgfar/heldout-readelf-header/app-full`

- process read randomness via getrandom

### `heldout-nm-symbols` (refused)

Command: `nm --defined-only /tmp/tracejit-heldout-_34sgfar/heldout-nm-symbols/app-full`

- process read randomness via getrandom

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/tracejit-heldout-_34sgfar/heldout-tar-gzip/bundle.tar.gz -C /tmp/tracejit-heldout-_34sgfar/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling

### `heldout-unzip-extract` (refused)

Command: `unzip -q -o /tmp/tracejit-heldout-_34sgfar/heldout-unzip-extract/extracted.zip -d /tmp/tracejit-heldout-_34sgfar/heldout-unzip-extract/unzipped`

- process read randomness via getrandom

### `heldout-iconv-transcode` (refused)

Command: `iconv -f UTF-8 -t ISO-8859-1 /tmp/tracejit-heldout-_34sgfar/heldout-iconv-transcode/words.txt`

- process read randomness via getrandom

### `heldout-base64-encode` (refused)

Command: `base64 -w 76 /tmp/tracejit-heldout-_34sgfar/heldout-base64-encode/words.txt`

- process read randomness via getrandom

### `heldout-md5sum` (refused)

Command: `md5sum /tmp/tracejit-heldout-_34sgfar/heldout-md5sum/words.txt`

- process read randomness via getrandom

### `heldout-cut-columns` (refused)

Command: `cut -d , -f 1,3 /tmp/tracejit-heldout-_34sgfar/heldout-cut-columns/sales.csv`

- process read randomness via getrandom

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/tracejit-heldout-_34sgfar/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/tracejit-heldout-_34sgfar/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/tracejit-heldout-_34sgfar/heldout-sort-unique-pipeline/frequencies.txt`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `heldout-comm-sorted` (refused)

Command: `comm -12 /tmp/tracejit-heldout-_34sgfar/heldout-comm-sorted/a.txt /tmp/tracejit-heldout-_34sgfar/heldout-comm-sorted/b.txt`

- process read randomness via getrandom

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/tracejit-heldout-_34sgfar/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffe8d5551e0, 0x4, 0x0, 0x7fa96ebb2fc0, 0x559d901b9010, 0x0]
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling

### `heldout-python-json` (refused)

Command: `/opt/freestyle/python/bin/python3 -c import json,sys
rows = json.load(open(sys.argv[1]))
out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]
open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))
 /tmp/tracejit-heldout-_34sgfar/heldout-python-json/rows.json /tmp/tracejit-heldout-_34sgfar/heldout-python-json/filtered.json`

- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 0, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 1, whose flags are not guarded
- unmodeled successful syscall 72: fcntl query 1 on inherited or unclassified fd 2, whose flags are not guarded

### `heldout-shell-script` (refused)

Command: `sh /tmp/tracejit-heldout-_34sgfar/heldout-shell-script/script.sh /tmp/tracejit-heldout-_34sgfar/heldout-shell-script/words.txt`

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


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

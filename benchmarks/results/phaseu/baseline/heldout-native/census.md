# TraceJIT real-world compatibility census

Commit: `b9752324b125b8fd1659d820433d889973ced88d`
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
| `heldout-gcc-preprocess` | compiler | refused | Nondeterministic | 275 | 1 | 12.929 ms | - | - | PASS |
| `heldout-gcc-compile-link` | compiler | refused | Unknown | 479 | 7 | 91.600 ms | - | - | PASS |
| `heldout-make-build` | build | refused | Unknown | 67 | 0 | 86.514 ms | - | - | FAIL |
| `heldout-ar-ranlib` | archiver | refused | Nondeterministic | 72 | 3 | 10.969 ms | - | - | PASS |
| `heldout-strip-binary` | toolchain | refused | Nondeterministic | 33 | 1 | 4.467 ms | - | - | PASS |
| `heldout-objdump-disassemble` | toolchain | refused | Nondeterministic | 34 | 0 | 7.318 ms | - | - | PASS |
| `heldout-readelf-header` | toolchain | refused | Nondeterministic | 30 | 0 | 3.777 ms | - | - | PASS |
| `heldout-nm-symbols` | toolchain | refused | Nondeterministic | 57 | 0 | 4.874 ms | - | - | PASS |
| `heldout-tar-gzip` | archive | refused | Unknown | 90 | 1 | 7.194 ms | - | - | PASS |
| `heldout-unzip-extract` | archive | refused | Nondeterministic | 28 | 2 | 4.447 ms | - | - | PASS |
| `heldout-iconv-transcode` | text | refused | Nondeterministic | 54 | 0 | 2.728 ms | - | - | PASS |
| `heldout-base64-encode` | text | refused | Nondeterministic | 52 | 0 | 2.128 ms | - | - | PASS |
| `heldout-md5sum` | digest | refused | Nondeterministic | 54 | 0 | 3.197 ms | - | - | PASS |
| `heldout-cut-columns` | data | refused | Nondeterministic | 52 | 0 | 2.727 ms | - | - | PASS |
| `heldout-grep-count` | text | refused | Unknown | 54 | 0 | 3.142 ms | - | - | PASS |
| `heldout-sort-unique-pipeline` | shell | refused | Unknown | 73 | 1 | 6.589 ms | - | - | PASS |
| `heldout-comm-sorted` | text | refused | Nondeterministic | 54 | 0 | 2.372 ms | - | - | PASS |
| `heldout-find-xargs` | shell | refused | Unknown | 104 | 0 | 7.169 ms | - | - | PASS |
| `heldout-python-json` | python | refused | Nondeterministic | 161 | 1 | 36.825 ms | - | - | PASS |
| `heldout-shell-script` | shell | refused | Unknown | 65 | 0 | 9.243 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| randomness | 13 | 13 |
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

Command: `gcc -E -I /tmp/base2/held-native-scratch/heldout-gcc-preprocess/project /tmp/base2/held-native-scratch/heldout-gcc-preprocess/project/main.c -o /tmp/base2/held-native-scratch/heldout-gcc-preprocess/main.i`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime

### `heldout-gcc-compile-link` (refused)

Command: `gcc -O1 -Wall -I /tmp/base2/held-native-scratch/heldout-gcc-compile-link/project /tmp/base2/held-native-scratch/heldout-gcc-compile-link/project/main.c /tmp/base2/held-native-scratch/heldout-gcc-compile-link/project/util.c -o /tmp/base2/held-native-scratch/heldout-gcc-compile-link/app`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd1b021d30, 0x7ffd1b0222c8, 0x7ffd1b021e80, 0x0, 0x7f0bbcf25380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc395da7c0, 0x7ffc395dad58, 0x7ffc395da910, 0x0, 0x7f744fdc0380]
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd7e4e50f0, 0x7ffd7e4e55c8, 0x7ffd7e4e5020, 0x0, 0x7f4ba9836380]

### `heldout-make-build` (refused)

Command: `make -C /tmp/base2/held-native-scratch/heldout-make-build/project all`

- unmodeled successful syscall 72: fcntl command 4 is not modeled
- unmodeled successful syscall 72: fcntl command 4 is not modeled

### `heldout-ar-ranlib` (refused)

Command: `sh -c ar rcs /tmp/base2/held-native-scratch/heldout-ar-ranlib/libheldout.a /tmp/base2/held-native-scratch/heldout-ar-ranlib/util.o && ranlib /tmp/base2/held-native-scratch/heldout-ar-ranlib/libheldout.a`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system information via prlimit64
- process read system clock: monotonic

### `heldout-strip-binary` (refused)

Command: `strip --strip-unneeded -o /tmp/base2/held-native-scratch/heldout-strip-binary/app-stripped /tmp/base2/held-native-scratch/heldout-strip-binary/app-full`

- process read randomness via getrandom
- process read system information via prlimit64

### `heldout-objdump-disassemble` (refused)

Command: `objdump -d --no-show-raw-insn /tmp/base2/held-native-scratch/heldout-objdump-disassemble/app-full`

- process read randomness via getrandom
- process read system information via prlimit64

### `heldout-readelf-header` (refused)

Command: `readelf -h /tmp/base2/held-native-scratch/heldout-readelf-header/app-full`

- process read randomness via getrandom

### `heldout-nm-symbols` (refused)

Command: `nm --defined-only /tmp/base2/held-native-scratch/heldout-nm-symbols/app-full`

- process read randomness via getrandom
- process read system information via prlimit64

### `heldout-tar-gzip` (refused)

Command: `tar -czf /tmp/base2/held-native-scratch/heldout-tar-gzip/bundle.tar.gz -C /tmp/base2/held-native-scratch/heldout-tar-gzip/project main.c util.c util.h Makefile`

- unmodeled successful syscall 5: fstat on pipe descriptor 4 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling

### `heldout-unzip-extract` (refused)

Command: `unzip -q -o /tmp/base2/held-native-scratch/heldout-unzip-extract/extracted.zip -d /tmp/base2/held-native-scratch/heldout-unzip-extract/unzipped`

- process read randomness via getrandom

### `heldout-iconv-transcode` (refused)

Command: `iconv -f UTF-8 -t ISO-8859-1 /tmp/base2/held-native-scratch/heldout-iconv-transcode/words.txt`

- process read randomness via getrandom

### `heldout-base64-encode` (refused)

Command: `base64 -w 76 /tmp/base2/held-native-scratch/heldout-base64-encode/words.txt`

- process read randomness via getrandom

### `heldout-md5sum` (refused)

Command: `md5sum /tmp/base2/held-native-scratch/heldout-md5sum/words.txt`

- process read randomness via getrandom

### `heldout-cut-columns` (refused)

Command: `cut -d , -f 1,3 /tmp/base2/held-native-scratch/heldout-cut-columns/sales.csv`

- process read randomness via getrandom

### `heldout-grep-count` (refused)

Command: `grep -c ^gamma- /tmp/base2/held-native-scratch/heldout-grep-count/words.txt`

- process-relative procfs dependency: /proc/self/maps

### `heldout-sort-unique-pipeline` (refused)

Command: `sh -c sort /tmp/base2/held-native-scratch/heldout-sort-unique-pipeline/words.txt | uniq -c | sort -k1,1nr -k2,2 > /tmp/base2/held-native-scratch/heldout-sort-unique-pipeline/frequencies.txt`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 2: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `heldout-comm-sorted` (refused)

Command: `comm -12 /tmp/base2/held-native-scratch/heldout-comm-sorted/a.txt /tmp/base2/held-native-scratch/heldout-comm-sorted/b.txt`

- process read randomness via getrandom

### `heldout-find-xargs` (refused)

Command: `sh -c find /tmp/base2/held-native-scratch/heldout-find-xargs/project -name '*.c' -print0 | sort -z | xargs -0 wc -l`

- failed fd operation on -1 is not modeled (errno 9)
- process-relative procfs dependency: /proc/self/fd
- unmodeled successful syscall 7: unmodeled syscall 7 args [0x7ffc459e80c0, 0x4, 0x0, 0x7f37db5b2fc0, 0x55afa228e010, 0x0]
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 1
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- opened dependency cannot be guarded: /dev/null

### `heldout-python-json` (refused)

Command: `/opt/freestyle/python/bin/python3 -c import json,sys
rows = json.load(open(sys.argv[1]))
out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]
open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))
 /tmp/base2/held-native-scratch/heldout-python-json/rows.json /tmp/base2/held-native-scratch/heldout-python-json/filtered.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `heldout-shell-script` (refused)

Command: `sh /tmp/base2/held-native-scratch/heldout-shell-script/script.sh /tmp/base2/held-native-scratch/heldout-shell-script/words.txt`

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

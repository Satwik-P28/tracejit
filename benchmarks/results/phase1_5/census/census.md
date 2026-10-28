# TraceJIT real-world compatibility census

Commit: `9b47a9ae6229b7bcf3bef372ec7d43ea54553239`
 (working tree dirty: `False`)

Every number below came from this host in this run. Refusals are reported, not excluded.

## Eligibility

- Requested workloads: 9
- Attempted: 9
- Reused with a verified cache hit: 0
- Refused by TraceJIT: 9
- Failed to execute: 0
- Blocked on a missing tool: 0
- Eligibility rate: 0.000

attempted = every requested workload whose required tools were present and whose direct execution succeeded. Tool-missing and workload-failed entries are excluded from the rate and listed separately.

## Workloads

| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cc-compile-fixture` | compiler | refused | Unknown | 1228 | 2 | 119.862 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 235 | 2 | 45.415 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 78 | 1 | 4.149 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 175 | 1 | 28.783 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 175 | 1 | 29.184 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 31 | 1 | 1.969 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 114 | 1 | 15.407 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 410 | 1 | 71.256 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1136 | 0 | 38.341 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| access_check_not_guardable | 4 | 28 |
| unclassified_descriptor | 4 | 8 |
| clock | 3 | 5 |
| process_identity | 3 | 4 |
| randomness | 3 | 3 |
| failed_descriptor_operation | 1 | 1 |
| unrestorable_output | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 293 | 293: pipe2 | 5 |
| 439 | 439: faccessat2 | 3 |
| 98 | 98: getrusage | 2 |
| 291 | 291: epoll_create1 | 1 |
| 5 | 5: fstat | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-qlbvdi8d/cc-compile-fixture/fixture.o`

- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /tmp
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffcea317b68, 0x80000, 0x1405e30, 0x7fed25e1bc58, 0x0, 0x0]
- read from unclassified fd 3
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffed4e66340, 0x0, 0x200, 0x35597ff, 0x0]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffcea318868, 0x80000, 0x1401540, 0x1405c88, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc87bbbef0, 0x7ffc87bbc478, 0x7ffc87bbc040, 0x0, 0x7fd337397380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-qlbvdi8d/cc-compile-large/source.c -o /tmp/tracejit-census-qlbvdi8d/cc-compile-large/source.o`

- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /tmp
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff4cfe8538, 0x80000, 0x1963e40, 0x7f6b7661bc58, 0x0, 0x0]
- read from unclassified fd 3
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffdb272c590, 0x0, 0x200, 0x41c07ff, 0x0]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff4cfe9238, 0x80000, 0x195f520, 0x1963c98, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff35339bd0, 0x7fff3533a158, 0x7fff35339d20, 0x0, 0x7f710a71a380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-qlbvdi8d/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-qlbvdi8d/shell-pipeline/pipeline.out`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff755bba90, 0x0, 0x4, 0x1, 0x7f695d004b20, 0x30]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff755bba90, 0x0, 0x5, 0x1, 0x7f695d004b20, 0x30]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff755bba90, 0x0, 0x5, 0x1, 0x7f695d004b20, 0x30]
- failed fd operation on -1 is not modeled (errno 9)

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-qlbvdi8d/python-csv-json/sales.csv /tmp/tracejit-census-qlbvdi8d/python-csv-json/customers.csv /tmp/tracejit-census-qlbvdi8d/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-qlbvdi8d/python-csv-json-seeded/sales.csv /tmp/tracejit-census-qlbvdi8d/python-csv-json-seeded/customers.csv /tmp/tracejit-census-qlbvdi8d/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-qlbvdi8d/awk-codegen/schema.tsv > /tmp/tracejit-census-qlbvdi8d/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-qlbvdi8d/groff-manpage-html/census.1 > /tmp/tracejit-census-qlbvdi8d/groff-manpage-html/census.out`

- successful access check cannot be guarded exactly: /usr/bin/groff
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff50747068, 0x0, 0x1, 0x55d1d50c4840, 0x55d1d50ab010, 0x7f99fba04ac0]
- unmodeled successful syscall 5: fstat on unclassified fd 0
- unmodeled successful syscall 5: fstat on unclassified fd 1
- read from unclassified fd 0
- read from unclassified fd 0
- read from unclassified fd 0

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-qlbvdi8d/pil-image-transform/source.png /tmp/tracejit-census-qlbvdi8d/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f35bb0172a8, 0x0, 0x0]

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c`

- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/lto-wrapper
- successful access check cannot be guarded exactly: /dev/null
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc5f859b18, 0x80000, 0x1766770, 0x7fd09981bc58, 0x0, 0x0]
- read from unclassified fd 3
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffdcf37a540, 0x0, 0x200, 0x3cab7ff, 0x0]
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/collect2
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/liblto_plugin.so
- non-file output cannot be restored: /dev/null


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

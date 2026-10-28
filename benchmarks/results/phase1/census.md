# TraceJIT real-world compatibility census

Commit: `6358522e2eee7b8aa7f59acca88e061f72166d8e`
 (working tree dirty: `True`)

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
| `cc-compile-fixture` | compiler | refused | Unknown | 1230 | 2 | 119.184 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 237 | 2 | 46.000 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 81 | 1 | 3.727 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 175 | 1 | 27.627 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 175 | 1 | 27.482 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 2.001 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 115 | 1 | 15.188 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 410 | 1 | 68.210 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1137 | 0 | 35.418 ms | - | - | PASS |

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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-555g6g9z/cc-compile-fixture/fixture.o`

- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /tmp
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc936beeb8, 0x80000, 0xac2e30, 0x7fa7d3e1bc58, 0x0, 0x0]
- read from unclassified fd 3
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffd1e3efb10, 0x0, 0x200, 0x3cc17ff, 0x0]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc936bfbb8, 0x80000, 0xabe540, 0xac2c88, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffed6c99d00, 0x7ffed6c9a288, 0x7ffed6c99e50, 0x0, 0x7f8228833380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-555g6g9z/cc-compile-large/source.c -o /tmp/tracejit-census-555g6g9z/cc-compile-large/source.o`

- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/bin/cc
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- successful access check cannot be guarded exactly: /tmp
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fffa1e4b1f8, 0x80000, 0x16c6e40, 0x7f0ef4e1bc58, 0x0, 0x0]
- read from unclassified fd 3
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7fffd3c0a7e0, 0x0, 0x200, 0x33ae7ff, 0x0]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fffa1e4bef8, 0x80000, 0x16c2520, 0x16c6c98, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffd63cb2fc0, 0x7ffd63cb3548, 0x7ffd63cb3110, 0x0, 0x7f1017cf0380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-555g6g9z/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-555g6g9z/shell-pipeline/pipeline.out`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffd62d899c0, 0x0, 0x4, 0x1, 0x7fa793004b20, 0x30]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffd62d899c0, 0x0, 0x5, 0x1, 0x7fa793004b20, 0x30]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffd62d899c0, 0x0, 0x5, 0x1, 0x7fa793004b20, 0x30]
- failed fd operation on -1 is not modeled (errno 9)

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-555g6g9z/python-csv-json/sales.csv /tmp/tracejit-census-555g6g9z/python-csv-json/customers.csv /tmp/tracejit-census-555g6g9z/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-555g6g9z/python-csv-json-seeded/sales.csv /tmp/tracejit-census-555g6g9z/python-csv-json-seeded/customers.csv /tmp/tracejit-census-555g6g9z/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-555g6g9z/awk-codegen/schema.tsv > /tmp/tracejit-census-555g6g9z/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-555g6g9z/groff-manpage-html/census.1 > /tmp/tracejit-census-555g6g9z/groff-manpage-html/census.out`

- successful access check cannot be guarded exactly: /usr/bin/groff
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc45887a28, 0x0, 0x1, 0x5614d3ceda30, 0x5614d3cd4010, 0x7efd1fe04ac0]
- unmodeled successful syscall 5: fstat on unclassified fd 0
- unmodeled successful syscall 5: fstat on unclassified fd 1
- read from unclassified fd 0
- read from unclassified fd 0
- read from unclassified fd 0

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-555g6g9z/pil-image-transform/source.png /tmp/tracejit-census-555g6g9z/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f1e4e2172a8, 0x0, 0x0]

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
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffdbfdcd348, 0x80000, 0x2188770, 0x7f72bce1bc58, 0x0, 0x0]
- read from unclassified fd 3
- successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13
- unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffda325d4f0, 0x0, 0x200, 0x29b77ff, 0x0]
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/collect2
- successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/liblto_plugin.so
- non-file output cannot be restored: /dev/null


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

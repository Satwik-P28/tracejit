# TraceJIT real-world compatibility census

Commit: `2edbf0d8aed82f00a7605205d1d8cc79d139cd4d`
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
| `cc-compile-fixture` | compiler | refused | Unknown | 1235 | 2 | 132.663 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 242 | 2 | 49.537 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 81 | 1 | 3.633 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 175 | 1 | 28.791 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 175 | 1 | 29.524 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 1.937 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 15.988 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 410 | 1 | 69.826 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1145 | 0 | 39.505 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| unclassified_descriptor | 4 | 11 |
| clock | 3 | 5 |
| process_identity | 3 | 4 |
| randomness | 3 | 3 |
| failed_descriptor_operation | 1 | 1 |
| unrestorable_output | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 293 | 293: pipe2 | 5 |
| 98 | 98: getrusage | 2 |
| 291 | 291: epoll_create1 | 1 |
| 5 | 5: fstat | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-0mdhrg8e/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffe406e4258, 0x80000, 0x1363e30, 0x7efccb61bc58, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffe406e4f58, 0x80000, 0x135f540, 0x1363c88, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff26e4b090, 0x7fff26e4b618, 0x7fff26e4b1e0, 0x0, 0x7f3fc30bf380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-0mdhrg8e/cc-compile-large/source.c -o /tmp/tracejit-census-0mdhrg8e/cc-compile-large/source.o`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc9e0a7bd8, 0x80000, 0x1248e40, 0x7f6844a1bc58, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc9e0a88d8, 0x80000, 0x1244520, 0x1248c98, 0x0, 0x0]
- read from unclassified fd 3
- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffe52c50e0, 0x7fffe52c5668, 0x7fffe52c5230, 0x0, 0x7f0d9b8f5380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-0mdhrg8e/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-0mdhrg8e/shell-pipeline/pipeline.out`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff7e8fed30, 0x0, 0x4, 0x1, 0x7f8c74604b20, 0x30]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff7e8fed30, 0x0, 0x5, 0x1, 0x7f8c74604b20, 0x30]
- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fff7e8fed30, 0x0, 0x5, 0x1, 0x7f8c74604b20, 0x30]
- failed fd operation on -1 is not modeled (errno 9)

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-0mdhrg8e/python-csv-json/sales.csv /tmp/tracejit-census-0mdhrg8e/python-csv-json/customers.csv /tmp/tracejit-census-0mdhrg8e/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-0mdhrg8e/python-csv-json-seeded/sales.csv /tmp/tracejit-census-0mdhrg8e/python-csv-json-seeded/customers.csv /tmp/tracejit-census-0mdhrg8e/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-0mdhrg8e/awk-codegen/schema.tsv > /tmp/tracejit-census-0mdhrg8e/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-0mdhrg8e/groff-manpage-html/census.1 > /tmp/tracejit-census-0mdhrg8e/groff-manpage-html/census.out`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc79edf6e8, 0x0, 0x1, 0x5642ea7dfa30, 0x5642ea7c6010, 0x7f036de04ac0]
- unmodeled successful syscall 5: fstat on unclassified fd 0
- unmodeled successful syscall 5: fstat on unclassified fd 1
- read from unclassified fd 0
- read from unclassified fd 0
- read from unclassified fd 0
- read from unclassified fd 0
- read from unclassified fd 0
- read from unclassified fd 0

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-0mdhrg8e/pil-image-transform/source.png /tmp/tracejit-census-0mdhrg8e/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f40cbe172a8, 0x0, 0x0]

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c`

- unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffda41d5f38, 0x80000, 0x14c1770, 0x7fea2a21bc58, 0x0, 0x0]
- read from unclassified fd 3
- non-file output cannot be restored: /dev/null


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

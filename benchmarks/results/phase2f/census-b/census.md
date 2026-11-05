# TraceJIT real-world compatibility census

Commit: `be94f388a947f314fa5077d3bfeded33fe12ee1a`
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
| `cc-compile-fixture` | compiler | refused | Unknown | 1237 | 2 | 136.388 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 244 | 2 | 50.268 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 81 | 1 | 3.805 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 190 | 1 | 30.711 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 190 | 1 | 27.835 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 1.975 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 13.976 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 430 | 1 | 67.822 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1147 | 0 | 35.691 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| clock | 4 | 6 |
| randomness | 4 | 4 |
| process_identity | 3 | 4 |
| other:pipe 1: a read returned less than it requested and more data | 2 | 2 |
| system_information | 1 | 2 |
| failed_descriptor_operation | 1 | 1 |
| unrestorable_output | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 5 | 5: fstat | 2 |
| 98 | 98: getrusage | 2 |
| 16 | 16: ioctl | 1 |
| 291 | 291: epoll_create1 | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/3ead97f7907244943d2638d7/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-mspxtqxn/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc765a4ef0, 0x7ffc765a5478, 0x7ffc765a5040, 0x0, 0x7f6c33895380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-mspxtqxn/cc-compile-large/source.c -o /tmp/tracejit-census-mspxtqxn/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcc1975620, 0x7ffcc1975ba8, 0x7ffcc1975770, 0x0, 0x7f1194d09380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-mspxtqxn/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-mspxtqxn/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-mspxtqxn/python-csv-json/sales.csv /tmp/tracejit-census-mspxtqxn/python-csv-json/customers.csv /tmp/tracejit-census-mspxtqxn/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-mspxtqxn/python-csv-json-seeded/sales.csv /tmp/tracejit-census-mspxtqxn/python-csv-json-seeded/customers.csv /tmp/tracejit-census-mspxtqxn/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-mspxtqxn/awk-codegen/schema.tsv > /tmp/tracejit-census-mspxtqxn/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-mspxtqxn/groff-manpage-html/census.1 > /tmp/tracejit-census-mspxtqxn/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-mspxtqxn/pil-image-transform/source.png /tmp/tracejit-census-mspxtqxn/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f17486172a8, 0x0, 0x0]

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/3ead97f7907244943d2638d7/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- non-file output cannot be restored: /dev/null


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

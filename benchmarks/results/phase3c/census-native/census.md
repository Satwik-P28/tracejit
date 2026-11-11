# TraceJIT real-world compatibility census

Commit: `df6cc86243972f7200be9dfb2cc4a3c52db9cf2b`
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
| `cc-compile-fixture` | compiler | refused | Unknown | 1241 | 2 | 165.776 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 248 | 2 | 53.081 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 78 | 1 | 4.010 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 190 | 1 | 40.350 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 190 | 1 | 45.548 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 31 | 1 | 2.791 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 115 | 1 | 20.219 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 430 | 1 | 91.902 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1152 | 0 | 43.311 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| clock | 4 | 6 |
| randomness | 4 | 4 |
| process_identity | 3 | 4 |
| system_information | 1 | 2 |
| failed_descriptor_operation | 1 | 1 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/3ead97f7907244943d2638d7/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-uzn0lf_6/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff2e9d6e30, 0x7fff2e9d73b8, 0x7fff2e9d6f80, 0x0, 0x7fea0b7a5380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-uzn0lf_6/cc-compile-large/source.c -o /tmp/tracejit-census-uzn0lf_6/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffcfd8bac0, 0x7fffcfd8c048, 0x7fffcfd8bc10, 0x0, 0x7f2d6286d380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-uzn0lf_6/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-uzn0lf_6/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-uzn0lf_6/python-csv-json/sales.csv /tmp/tracejit-census-uzn0lf_6/python-csv-json/customers.csv /tmp/tracejit-census-uzn0lf_6/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-uzn0lf_6/python-csv-json-seeded/sales.csv /tmp/tracejit-census-uzn0lf_6/python-csv-json-seeded/customers.csv /tmp/tracejit-census-uzn0lf_6/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-uzn0lf_6/awk-codegen/schema.tsv > /tmp/tracejit-census-uzn0lf_6/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-uzn0lf_6/groff-manpage-html/census.1 > /tmp/tracejit-census-uzn0lf_6/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-uzn0lf_6/pil-image-transform/source.png /tmp/tracejit-census-uzn0lf_6/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f92148172a8, 0x0, 0x0]

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/3ead97f7907244943d2638d7/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- non-file output cannot be restored: /dev/null


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Sun Nov  8 09:00:04 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

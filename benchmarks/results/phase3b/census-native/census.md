# TraceJIT real-world compatibility census

Commit: `58c39a7927e6d25b9f9cdde711f29d7f3b9fbf5d`
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
| `cc-compile-fixture` | compiler | refused | Unknown | 1243 | 2 | 149.236 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 250 | 2 | 47.475 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 81 | 1 | 4.966 ms | - | - | PASS |
| `python-csv-json` | python | refused | Unknown | 190 | 1 | 32.562 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Unknown | 190 | 1 | 28.658 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 32 | 1 | 2.385 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 116 | 1 | 20.128 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 430 | 1 | 77.559 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1153 | 0 | 50.908 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| clock | 2 | 2 |
| randomness | 2 | 2 |
| process_identity | 1 | 2 |
| system_information | 1 | 2 |
| failed_descriptor_operation | 1 | 1 |
| other:pipe 1: a read returned less than it requested and more data | 1 | 1 |
| unrestorable_output | 1 | 1 |

### Unmodeled syscalls

| Syscall | Name | Workloads blocked |
| ---: | --- | ---: |
| 8 | 8: lseek | 3 |
| 5 | 5: fstat | 2 |
| 98 | 98: getrusage | 2 |
| 16 | 16: ioctl | 1 |
| 291 | 291: epoll_create1 | 1 |

## Refusal detail

### `cc-compile-fixture` (refused)

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/3ead97f7907244943d2638d7/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-jq9kzwye/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff8b7ce250, 0x7fff8b7ce7d8, 0x7fff8b7ce3a0, 0x0, 0x7fd769988380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-jq9kzwye/cc-compile-large/source.c -o /tmp/tracejit-census-jq9kzwye/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffcd15fbfa0, 0x7ffcd15fc528, 0x7ffcd15fc0f0, 0x0, 0x7f39558a6380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-jq9kzwye/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-jq9kzwye/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-jq9kzwye/python-csv-json/sales.csv /tmp/tracejit-census-jq9kzwye/python-csv-json/customers.csv /tmp/tracejit-census-jq9kzwye/python-csv-json/report.json`

- unmodeled successful syscall 8: lseek on inherited descriptor 0 whose open file description (/dev/null) is not modelled

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-jq9kzwye/python-csv-json-seeded/sales.csv /tmp/tracejit-census-jq9kzwye/python-csv-json-seeded/customers.csv /tmp/tracejit-census-jq9kzwye/python-csv-json-seeded/report.json`

- unmodeled successful syscall 8: lseek on inherited descriptor 0 whose open file description (/dev/null) is not modelled

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-jq9kzwye/awk-codegen/schema.tsv > /tmp/tracejit-census-jq9kzwye/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-jq9kzwye/groff-manpage-html/census.1 > /tmp/tracejit-census-jq9kzwye/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/3ead97f7907244943d2638d7/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-jq9kzwye/pil-image-transform/source.png /tmp/tracejit-census-jq9kzwye/pil-image-transform/transformed.png`

- unmodeled successful syscall 8: lseek on inherited descriptor 0 whose open file description (/dev/null) is not modelled
- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f499ea172a8, 0x0, 0x0]

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

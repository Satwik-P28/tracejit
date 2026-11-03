# TraceJIT real-world compatibility census

Commit: `0ccf181184050fb265212ca9315f0b39933d5871`
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
| `cc-compile-fixture` | compiler | refused | Unknown | 1240 | 2 | 140.854 ms | - | - | PASS |
| `cc-compile-large` | compiler | refused | Unknown | 247 | 2 | 50.688 ms | - | - | PASS |
| `shell-pipeline` | shell | refused | Unknown | 77 | 1 | 4.308 ms | - | - | PASS |
| `python-csv-json` | python | refused | Nondeterministic | 179 | 1 | 30.297 ms | - | - | PASS |
| `python-csv-json-seeded` | python | refused | Nondeterministic | 179 | 1 | 29.307 ms | - | - | PASS |
| `awk-codegen` | codegen | refused | Nondeterministic | 31 | 1 | 1.991 ms | - | - | PASS |
| `groff-manpage-html` | documentation | refused | Unknown | 115 | 1 | 15.173 ms | - | - | PASS |
| `pil-image-transform` | image | refused | Unknown | 414 | 1 | 70.445 ms | - | - | PASS |
| `cc-syntax-only-lint` | lint | refused | Unknown | 1151 | 0 | 37.555 ms | - | - | PASS |

## Blocker ranking

| Blocker | Workloads blocked | Total occurrences |
| --- | ---: | ---: |
| clock | 4 | 6 |
| randomness | 4 | 4 |
| process_identity | 3 | 4 |
| other:pipe 1: a read returned less than it requested and more data | 2 | 2 |
| system_information | 1 | 2 |
| failed_descriptor_operation | 1 | 1 |
| other:pipe 3: a read returned less than it requested and more data | 1 | 1 |
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

Command: `cc -O2 -Wall -Wextra -c /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c -o /tmp/tracejit-census-pftpbt6z/cc-compile-fixture/fixture.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffda9931820, 0x7ffda9931da8, 0x7ffda9931970, 0x0, 0x7ff69f1af380]

### `cc-compile-large` (refused)

Command: `cc -O2 -Wall -Wextra -c /tmp/tracejit-census-pftpbt6z/cc-compile-large/source.c -o /tmp/tracejit-census-pftpbt6z/cc-compile-large/source.o`

- unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffc2fe12620, 0x7ffc2fe12ba8, 0x7ffc2fe12770, 0x0, 0x7f16e18a4380]

### `shell-pipeline` (refused)

Command: `sh -c awk '{ digest = (digest * 1315423911 + $1) % 4294967296 } END { printf "%08x\n", digest }' /tmp/tracejit-census-pftpbt6z/shell-pipeline/numbers.txt | sort | uniq -c | awk '{ print $2 }' > /tmp/tracejit-census-pftpbt6z/shell-pipeline/pipeline.out`

- failed fd operation on -1 is not modeled (errno 9)
- unmodeled failed syscall 16 (errno 25): TCGETS on unclassified fd 0
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling
- pipe 3: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `python-csv-json` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-pftpbt6z/python-csv-json/sales.csv /tmp/tracejit-census-pftpbt6z/python-csv-json/customers.csv /tmp/tracejit-census-pftpbt6z/python-csv-json/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `python-csv-json-seeded` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/etl.py /tmp/tracejit-census-pftpbt6z/python-csv-json-seeded/sales.csv /tmp/tracejit-census-pftpbt6z/python-csv-json-seeded/customers.csv /tmp/tracejit-census-pftpbt6z/python-csv-json-seeded/report.json`

- process read randomness via getrandom
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

### `awk-codegen` (refused)

Command: `sh -c awk -f /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/codegen.awk /tmp/tracejit-census-pftpbt6z/awk-codegen/schema.tsv > /tmp/tracejit-census-pftpbt6z/awk-codegen/generated.h`

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: realtime

### `groff-manpage-html` (refused)

Command: `sh -c groff -Tutf8 -man /tmp/tracejit-census-pftpbt6z/groff-manpage-html/census.1 > /tmp/tracejit-census-pftpbt6z/groff-manpage-html/census.out`

- unmodeled successful syscall 5: fstat on pipe descriptor 0 reports buffered byte counts, which depend on scheduling
- unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte counts, which depend on scheduling
- pipe 1: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling

### `pil-image-transform` (refused)

Command: `/opt/freestyle/python/bin/python3 /workspace/chats/c4bae51ae7d50b70f5bd4fc1/benchmarks/realworld/workloads/image_transform.py /tmp/tracejit-census-pftpbt6z/pil-image-transform/source.png /tmp/tracejit-census-pftpbt6z/pil-image-transform/transformed.png`

- unmodeled successful syscall 291: unmodeled syscall 291 args [0x80000, 0x0, 0x0, 0x7f9534c172a8, 0x0, 0x0]

### `cc-syntax-only-lint` (refused)

Command: `cc -fsyntax-only -Wall -Wextra -Werror /workspace/chats/c4bae51ae7d50b70f5bd4fc1/tests/fixtures/fixture_driver.c`

- process read randomness via getrandom
- process read system information via prlimit64
- process read system information via sysinfo
- process read system clock: realtime
- non-file output cannot be restored: /dev/null


## Environment

```text
Linux freestyle-vm 6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
```

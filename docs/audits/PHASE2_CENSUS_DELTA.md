# Phase 2B — Compatibility census delta

Measured at commit `2edbf0d` on Ubuntu 24.04.5, kernel 6.1.102, x86_64, 2 vCPU.
Raw artifact: `benchmarks/results/phase2/census-2edbf0d/census.json` and `census.md`.
Configuration: `--runs 3 --warmups 1`, the same fixed nine-workload suite and the same denominator
as the Phase 1 census, so the comparison is longitudinal and nothing was added or removed to
improve the rate.

## Headline

| Metric | Phase 1 (`6358522` + fixes) | Phase 2B (`2edbf0d`) |
| --- | --- | --- |
| Attempted | 9 | 9 |
| Blocked by missing tool | 0 | 0 |
| Execution failures | 0 | 0 |
| Output equivalence | 9 / 9 PASS | **9 / 9 PASS** |
| Reusable (eligible) | 0 | **0** |
| Cache hit obtained | 0 | **0** |
| Top blocker | `access` checks (4 workloads, 28 occurrences) | `unclassified_descriptor` (4 workloads, 11 occurrences) |

**Eligibility rate: 0.000 over the full denominator of 9.** The Phase 2B acceptance target — three
genuinely reusable workload categories — is **NOT MET**. [VERIFIED]

## Per workload

| Workload | Classification | Eligible | Dependencies | Equivalence | Blocker now |
| --- | --- | --- | --- | --- | --- |
| `cc-compile-fixture` | `UNKNOWN` | no | 1235 | PASS | `unclassified_descriptor`, `pipe2`, `getrusage` |
| `cc-compile-large` | `UNKNOWN` | no | 242 | PASS | `unclassified_descriptor`, `pipe2`, `getrusage` |
| `cc-syntax-only-lint` | `UNKNOWN` | no | 1145 | PASS | `unclassified_descriptor`, `pipe2` |
| `groff-manpage-html` | `UNKNOWN` | no | 116 | PASS | `unclassified_descriptor`, `pipe2`, `fstat` |
| `shell-pipeline` | `UNKNOWN` | no | 81 | PASS | `pipe2`, failed descriptor operation |
| `pil-image-transform` | `UNKNOWN` | no | 410 | PASS | `epoll_create1`, `unclassified_descriptor` |
| `awk-codegen` | `NONDETERMINISTIC` | no | 32 | PASS | clock, process identity, randomness |
| `python-csv-json` | `NONDETERMINISTIC` | no | 175 | PASS | clock, process identity, randomness |
| `python-csv-json-seeded` | `NONDETERMINISTIC` | no | 175 | PASS | clock, process identity, randomness |

Every refusal is a refusal TraceJIT chose; none is a crash, a wrong answer, or a missing tool.

## Blocker ranking at `2edbf0d`

Occurrences are counted per workload, not per repeated syscall, so 40 `access` calls in one
workload rank as one affected workload.

| Blocker | Workloads | Occurrences | Fixable? |
| --- | ---: | ---: | --- |
| `unclassified_descriptor` | 4 | 11 | Yes — needs descriptor identity for fds that are neither files nor sockets |
| `pipe2` (293) | 5 | — | Partly — internal pipes are modelling work, not a semantic impossibility |
| `clock` | 3 | 5 | No, not safely: interpreter and `awk` startup read clocks |
| `process_identity` | 3 | 4 | No, not safely |
| `randomness` | 3 | 3 | No, not safely |
| `getrusage` (98) | 2 | 2 | Yes — resource-usage read, guardable in principle |
| `epoll_create1` (291) | 1 | 1 | Yes — internal event interface |
| `fstat` (5) on an unclassified fd | 1 | 1 | Yes — same fix as `unclassified_descriptor` |
| `access` checks | **0** | **0** | **Done in this phase** |

The three `NONDETERMINISTIC` workloads are refused for reasons that are not implementation gaps:
`awk` and CPython startup read the clock, their process identity and randomness. Making them
reusable requires an explicit determinism model for the interpreter (a pinned hash seed, a clock
source, a process-identity contract), not a classifier exception. Setting `PYTHONHASHSEED` alone
did not change the classification — `python-csv-json-seeded` is still refused — which is the
expected and honest result.

## Interpretation

The change did what it was designed to do: it removed the single most frequent refusal cause (28
occurrences across 4 workloads) and every workload still produces byte-identical results to a
direct run. It did not move the eligibility rate, because the remaining blockers sit on the same
workloads. That is recorded as a failure of the phase target, not reframed as progress.

The next change with the highest expected eligibility return is the descriptor-identity gap
(`unclassified_descriptor` + `fstat` + `epoll_create1`), because it is a single mechanism covering
6 of the 11 remaining blocker occurrences and it is a correctness problem in its own right rather
than a benchmark convenience.

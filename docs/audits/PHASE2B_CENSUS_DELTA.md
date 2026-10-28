# Real-world compatibility census — Phase 2B delta

Two runs of the same nine fixed workloads, same host, same denominator. Nothing was added, removed
or redefined.

| | Phase 2 (`2edbf0d`) | Phase 2B (`b57bc7f`) |
| --- | --- | --- |
| Requested | 9 | 9 |
| Attempted (tools present, direct run succeeded) | 9 | 9 |
| Missing tool / execution failure | 0 / 0 | 0 / 0 |
| Output equivalence | 9/9 PASS | **9/9 PASS** |
| Reused with a verified hit | 0 | **0** |
| **Eligibility rate** | **0.000** | **0.000** |
| Top blocker | `access` checks (4 workloads, 28 occurrences) | `clock` (4 workloads, 6 occurrences) |

Raw data: `benchmarks/results/phase2/census-2edbf0d/` and
`benchmarks/results/phase2b/census-b57bc7f/`.

## Verdict against the phase target

The target was three reusable real-world workload categories. **The result is zero, and it is not
close enough to claim partial success.** Two mechanisms landed and each removed a real blocker, but
every workload still has at least one unmodeled or genuinely nondeterministic observation left.

This is the third consecutive phase reporting 0/9. The value of the result is that the obstruction
is now specific rather than generic: each workload fails for a stated reason, and three of the nine
fail because of a property that whole-command reuse cannot establish in principle (see below).

## Per-workload blockers now

| Workload | Classification | Remaining blockers |
| --- | --- | --- |
| `cc-compile-fixture` | Unknown | `getrusage` (98) |
| `cc-compile-large` | Unknown | `getrusage` (98) |
| `cc-syntax-only-lint` | Unknown | `getrandom`, `prlimit64`, `sysinfo`, realtime clock, `/dev/null` as output |
| `shell-pipeline` | Unknown | pipe short-read-then-more ×2, `fstat` on pipes ×6, `TCGETS` on fd 0, `close(-1)` |
| `groff-manpage-html` | Unknown | `fstat` on pipes ×2, pipe short-read-then-more |
| `pil-image-transform` | Unknown | `epoll_create1` (291) |
| `python-csv-json` | Nondeterministic | `getrandom`, `gettid`, monotonic + realtime clock |
| `python-csv-json-seeded` | Nondeterministic | same (setting `PYTHONHASHSEED` does not remove interpreter startup randomness) |
| `awk-codegen` | Nondeterministic | `getpid`, `getppid`, `getrandom`, realtime clock |

## Ranked blockers and what each would actually take

| Rank | Blocker | Workloads | Is it physics or missing work? |
| --- | --- | --- | --- |
| 1 | `getrusage` | 2 (both compiler workloads) | Missing model, **but** the value is CPU time and peak RSS, which are nondeterministic. Guardable only by declaring the observation irrelevant to output, which needs evidence, not a table entry |
| 2 | pipe short-read-then-more | 3 | **Cannot be certified** by whole-command reuse. Requires per-process reuse or an explicit, documented assumption |
| 3 | `fstat` on a pipe | 1 (`shell-pipeline`), 1 (`groff`) | Refused deliberately: `st_size` is buffered-byte count. Modeling would require proving the program ignores it |
| 4 | interpreter startup `getrandom`/`gettid`/clock | 3 | Physics of the runtime. Needs a documented determinism model for the interpreter, not a classifier exemption |
| 5 | `epoll_create1` + wait semantics | 1 (`PIL`) | Missing work: model the epoll fd and treat wakeups on internal fds as pipe-like; wakeup order is scheduling dependent |
| 6 | `/dev/null` as an output sink | 1 | Missing work: a write to `/dev/null` needs no restoration, so it can be treated as a modelled sink rather than an unrestorable output |
| 7 | `close(-1)` failure, `TCGETS` on inherited fd 0 | 1 | Small model gaps; `close(-1)` is `EBADF` and carries no state |

Items 6 and 7 are the cheapest and would not move eligibility on their own, because the same
workloads are also blocked by pipe semantics and interpreter randomness. That ordering is the
practical argument against fixing them next: they are individually sound but would not change a
single command from refused to reusable.

## The conclusion the measurements support

The nine workloads split into three groups:

1. **Refused for missing models** (2 compiler workloads, `PIL`, two small gaps). Reachable, but each
   remaining model has a soundness question attached, and the cheapest ones do not unlock anything.
2. **Refused because the observation is genuinely nondeterministic** (3 interpreter workloads).
   Reuse would require controlling or excluding runtime startup randomness, which is a compatibility
   model, not a syscall table.
3. **Refused because whole-command reuse cannot certify the property** (the pipelines). Fixing these
   requires changing how results are reused, not what is recorded.

Group 3 is the most consequential finding of this phase and the reason the phase target was not met:
the architecture's unit of reuse is the whole command, and a streaming pipeline's intermediate
boundaries are not observable in a way that bounds them.

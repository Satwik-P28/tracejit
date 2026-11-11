# Phase 3E: Epoll Lifecycle and the Controlled-Execution Frontier

Base: `62425a9` (Phase 3C on `main`), with Phase 3D at `a86b8e2` on PR #6.
Phase 3E branch: `phase3e/epoll-and-effect-frontier`.

**Outcome: the epoll blocker is removed, but no census workload becomes reusable.** The census
remains 9 attempted, 0 reused, 9 refused. Pillow now reaches a precise nondeterminism refusal
instead of an unmodeled epoll refusal. The controlled-Python track produced an inventory and a
negative design finding, not an enabled contract.

## 1. Phase 3D review closure

PR #6 is still a **draft**, based on `phase3d/compatibility-retrieval`, with two commits:

- `1cc5912` — Phase 3D retrieval prototype and census evidence.
- `a86b8e2` — review fix: propagate candidate lookup errors during admission.

GitHub CI run `43094044134` (push, job `130778199626`) and run `43094052744` (pull request, job
`130778215433`) both completed **successfully** for `a86b8e2`. Local gates after the review fix also
pass. The PR remains draft and unmerged because the retrieval change has no established performance
benefit and the broader review is not complete.

### Correctness findings

| Question | Finding | Action |
| --- | --- | --- |
| SQLite error during admission | `.ok()` silently converted a database failure into an empty candidate set. | Replaced with `?`; errors now fail the command. |
| Candidate deleted between ID query and fetch | `None` is a legitimate concurrent-prune miss. | Skip that ID; never reuse it. |
| Candidate replaced between ID query and fetch | The replacement may be newer or unrelated, but it is decoded and every guard is re-run. | Safe fail-closed; no blind reuse. |
| Malformed candidate payload | Decode returns `None`. | Skip it; remaining candidates still validate. |
| Newly inserted candidate after the ID query | It is not in the original ID list. | Possible stale miss, never a false hit. |
| Query consistency | ID selection and record fetches are separate SQLite statements. | Sufficient for safety because guards are the authoritative check; a transaction would only change freshness. |
| Performance | Oldest-target medians were worse at four of seven bounds; 64 candidates 80.4 ms versus 82.2 ms. | Keep the feature experimental; default bound remains 8. |

The review fix and cache regression are on PR #6’s branch. The Phase 3D audit now points to PR #6
instead of describing the work as merely a local branch. This Phase 3E branch does not include the
Phase 3D retrieval code beyond that fix.

## 2. Track A: epoll compatibility

### Observed behavior

`strace -f` on the exact Pillow workload, filtered to descriptor and epoll calls, showed:

```text
epoll_create1(EPOLL_CLOEXEC) = 3
close(3)                    = 0
```

There was no `epoll_ctl`, `epoll_wait`, `epoll_pwait`, `dup`, or fork inheritance associated with
that instance. The instance was created and destroyed without being registered or observed.
`epoll(7)` defines the instance as an in-kernel interest list plus ready list; without registration
or waiting, no readiness information can reach the program.

### Candidate models

1. **Strict create/use/close lifecycle.** Track the instance, every `epoll_ctl` registration, every
   wait, wakeup order, and descriptor duplication. This is the only model that could admit real
   event loops, but it requires deterministic readiness ordering. **Not implemented.**
2. **Restricted internal-descriptor contract.** Admit creation and close only when the instance is
   never registered, waited on, or exposed. Duplication and `CLOEXEC` tracking are safe because they
   do not observe readiness. Any `epoll_ctl`, `epoll_wait`, or read from the instance remains
   unclassified. **Implemented.**
3. **Conservative refusal with a different strategy.** Refuse all epoll and require the program to
   avoid event loops, or run under a deterministic execution system. **Retained** for used epoll
   instances and any readiness-dependent operation.

The implementation adds `FdState::Epoll`. `epoll_create1` records the returned descriptor and
`EPOLL_CLOEXEC`; `dup`/`dup2`/`dup3` preserve the state through the existing descriptor table;
`close` removes it; a failed `epoll_create1` is an unknown effect. `epoll_ctl` and `epoll_wait` are
still unmodeled and therefore refuse. The state is per traced process and is closed on `exec` when
`CLOEXEC` is set.

### Adversarial coverage

| Case | Result |
| --- | --- |
| `epoll_create_only` | First execution `Guarded`; second `Reused`; output correct. |
| `epoll_dup_close` | Creation, duplication, and both closes reuse safely. |
| `epoll_ctl_use` | Successful registration of a pipe read end is unmodeled and refuses. |
| failed creation | Recorded as unknown; no descriptor state is invented. |
| leaked descriptor | Not yet rejected; the descriptor is closed by process exit and no readiness is observed. This is a coverage gap, not a claim of general leak support. |
| fork/exec inheritance | `CLOEXEC` is tracked and existing process-state cloning preserves the descriptor state; a dedicated fork test remains open. |
| resource exhaustion | A failed creation is refused, but an explicit `RLIMIT_NOFILE` exhaustion test was not added. |
| scheduling/readiness | Never admitted: `epoll_ctl`/`epoll_wait` refuse. |

The tests are `epoll_create_and_close_is_reusable`, `epoll_duplicate_and_close_is_reusable`, and
`epoll_control_use_is_refused`.

### Census effect

`benchmarks/results/phase3e/census-native/`:

- **9 attempted, 0 reused, 9 refused, 0 execution failures.**
- `epoll_create1` has disappeared from the unmodeled-syscall ranking.
- `pil-image-transform` is now `Nondeterministic`, blocked by `getrandom`, monotonic/realtime
  clocks, and `gettid` — the same Python-runtime wall as the CSV workload.
- Direct Pillow median: 93.81 ms. Traced cold median: 356.63 ms. No hit exists, so no speedup is
  claimed.

## 3. Track B: controlled Python inventory

The two Python workloads use the same command shape and standard-library ETL script. The observed
inventory, with `PYTHONHASHSEED` unset or `0` and `PYTHONDONTWRITEBYTECODE=1`, was:

| Category | Observation |
| --- | --- |
| Entropy | 3 `getrandom` calls unseeded; 2 seeded. Some are runtime initialization even with hash seeding. |
| Realtime clock | `clock_gettime(CLOCK_REALTIME)` / `gettimeofday` path. |
| Monotonic clock | `clock_gettime(CLOCK_MONOTONIC)` during startup/runtime. |
| Process identity | `getpid`, `getppid`, `gettid`. |
| vDSO | TraceJIT disarms vDSO time entry points, so these become real syscalls; a controlled contract must cover that path. |
| Files/environment | 189–190 dependencies; CSV inputs, Python modules, environment and executable identity. |
| Descriptors | No subprocess tree and one process; no observed application thread creation. |
| Unmodeled syscalls | None after epoll; the remaining refusal is classified nondeterminism. |
| Output equivalence | Both seeded and unseeded runs produced identical `report.json` bytes on this host, but identical output is not proof of deterministic inputs. |

The reasons from TraceJIT are exactly:

```text
process read randomness via getrandom
process read system clock: monotonic
process read system clock: realtime
process read process identity via getpid
process read process identity via getppid
process read process identity via gettid
```

### Why no contract was enabled

The existing controlled contracts are deliberately audited to exact binaries, build IDs, call
sites, and byte signatures. A Python contract cannot safely reuse those profiles:

- CPython is a dynamically loaded interpreter; the executable is not the only module making the
  observations.
- `getrandom` is used for runtime state (including hash/allocator initialization), so a fixed value
  changes application-visible behavior, not just incidental accounting.
- A virtual clock/PID contract would change semantics for any application code that reads them.
  That is acceptable only as an explicit contract, with native and controlled records separated.
- Threading, subprocesses, descriptor inheritance, and signal timing expand the contract beyond the
  single-process ETL workload.
- A faithful implementation needs CPython build/call-site profiles or a broader syscall
  virtualization layer. Guessing an audited profile would violate the project’s fail-closed rule.

No controlled record, no mixed contract, and no Python reuse was produced. The negative result is
that **epoll was not the compatibility wall**; the wall is the absence of a defensible controlled
runtime for Python.

### Literature and competing approaches

- Hermit controls scheduling, clocks, random bytes, process IDs, file metadata, and CPU features;
  it is the closest whole-system alternative for these observations
  (<https://rrnewton.github.io/hermit/>, <https://github.com/facebookexperimental/hermit>).
- rr records nondeterministic inputs and replays them with instruction-level control
  (<https://rr-project.org/>; CACM, “Deterministic Record-and-Replay”, 2025).
- Firebuild derives cacheability from observed command and child behavior
  (<https://github.com/firebuild/firebuild>).
- Salsa uses revisioned queries and the red-green algorithm
  (<https://salsa-rs.github.io/salsa/overview.html>); Adapton uses demand-driven computation graphs
  (<https://plt.cs.northwestern.edu/pkg-build/doc/adapton%40Adapton/index.html>).
- CEGAR refines an abstraction from counterexamples; it can add narrow object-kind predicates, but
  cannot turn an unstable observation into a stable guard (Clarke et al., CAV 2000,
  <https://link.springer.com/content/pdf/10.1007/10722167_15.pdf>).
- Linux epoll semantics: <https://man7.org/linux/man-pages/man7/epoll.7.html>.
- ccache/sccache manifest indexing remains the closest model for compact candidate headers; a
  manifest is a hint, not a guard.

## 4. Combined graph

The same causal distinction explains all three phases:

```text
object identity (fd/inode/device, not name)
        |
        v
operation semantics (create, register, wait, read, close)
        |
        v
observation source: external input | execution-produced state | schedule
        |
        +--> external and stable  -> guardable -> native cache
        +--> externally virtualizable -> controlled contract -> separate cache
        +--> execution-produced or schedule -> refuse or deterministic execution
```

- `/dev/null` is stable object identity plus a constant operation: guardable.
- A create/close-only epoll instance has no observable readiness: process-internal.
- `epoll_ctl`/`epoll_wait` expose readiness and scheduling: controlled execution or refusal.
- Python clocks/entropy/PIDs are execution-produced or environment-dependent observations: a
  guard cannot pin them; a contract must define them.
- Candidate metadata is a retrieval hint; full guards remain the validity proof.

A common typed effect model should therefore carry `(object_kind, operation, information_source,
stability, contract)` rather than only a syscall name. That is a design direction, not an
implemented type system.

## 5. Verification and limits

- `cargo fmt --all -- --check`: pass.
- Clippy `--workspace --all-targets --all-features -- -D warnings`: pass.
- Workspace tests: **136 passed**.
- Linux integration: **48 passed**, 0 failed; local `PROVEN` remains skipped without Landlock.
- Release build: pass. Release binary SHA-256:
  `8b333af78f74dea09cda7a5cbb95e027c47f65f6beefb4a7c99fabbbf4bddeee`.
- Phase 3E census: 9 attempted, 0 reused, 9 refused, 0 failures.

Limitations:

- PR #6 hosted checks are confirmed for `a86b8e2`; Phase 3E’s branch is separate and its hosted
  checks were not available when this audit was written.
- No controlled Python contract was implemented, so the controlled track is an inventory and a
  falsification, not a compatibility result.
- Leaked epoll descriptors, explicit `RLIMIT_NOFILE` exhaustion, and fork/exec inheritance lack
  dedicated tests.
- The census is a local host measurement, not a production workload study.
- The epoll model is intentionally narrow; it does not support event loops.

## 6. Next experiments

1. Add an audited CPython contract for one exact interpreter build, beginning with fixed clocks and
   entropy while leaving PIDs native; reject any application buffer outside the audited call sites.
2. Add a fork/exec epoll fixture and an explicit fd-exhaustion fixture; require refusal or a proven
   safe lifecycle before admitting leaks.
3. Run two independent controlled cold executions and require identical outputs plus identical
   controlled effect sets before any controlled reuse.
4. Keep candidate retrieval experimental until a compact header index demonstrates a reproducible
   win with full-guard fallback.

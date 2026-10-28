# Phase 1 → Phase 2 handoff

Recommendations are derived from measurements in this Phase 1, not from
intuition. Each entry states the evidence, the expected benefit **as a
hypothesis**, the correctness argument that would have to hold, the risk of
weakening fail-closed behavior, and the effort. Nothing here is a measured
result, and no recommendation authorizes a whitelist of a non-deterministic
observable.

Evidence base:

- `docs/audits/PHASE1_COMPATIBILITY_REPORT.md` — 0 of 9 real workloads reusable,
  with ranked blockers.
- `docs/audits/PHASE1_RELIABILITY_AUDIT.md` — five reliability defects plus one
  execution-equivalence defect (D6), all fixed.
- `docs/audits/PHASE1_BENCHMARK_REPORT.md` — current-commit timings and the
  historical values they are compared against.

## R1 — Exact guarding for successful `access()` checks

**Evidence.** 28 of the 41 recorded refusal occurrences, across all four compiler
workloads (`cc-compile-fixture`, `cc-compile-large`, `cc-syntax-only-lint`,
`groff-manpage-html`). `faccessat2` (439) is unmodeled and appears in three of
them.

**Why it is first.** It is the single largest measured blocker on the workload
class most likely to be a real TraceJIT user (C/`cc` compilation), and the
existing guard machinery already covers the underlying observable: the tracer
records metadata and absence dependencies elsewhere.

**Correctness argument required.** A successful access check is a dependency on
"this path resolves and is readable/searchable/writable by this identity". The
guard must re-evaluate exactly that predicate (existence, mode bits, ownership,
search permission on every ancestor) and deoptimize when it changes. If any part
cannot be re-evaluated exactly, the workload must stay refused — a partial
approximation of permissions would silently weaken the guard.

**Benefit hypothesis.** Compilers move from `UNKNOWN` to *classifiable*. This
does not by itself produce a hit: `pipe2`, unclassified descriptors and
`getrusage` also appear. Expect a prerequisite, not an immediate win.

**Risk.** Medium. Permission semantics (ACLs, mount options, `noexec`, user
namespaces) are easy to model incompletely; the failure mode is a false hit.
Mitigation: exhaustive fixture coverage of permission changes before any
workload may become eligible.

**Effort.** Medium.

## R2 — Pipe and IPC modeling for self-contained process trees

**Evidence.** `pipe2` (293) blocks 5 of 9 workloads; `read from unclassified fd`
blocks 4; the shell pipeline is blocked by pipes alone plus one failed `close`.

**Why it is second.** It is the most *frequent* blocker and it gates the entire
shell-pipeline class, plus compiler drivers that talk to `cc1` over pipes.

**Correctness argument required.** The only sound form is: every endpoint of the
pipe is part of the traced tree, the data entering the tree through the pipe is
provably derived from hashed inputs, and no other process can write to it. That
yields "the pipeline's output is a function of the traced processes' hashed
inputs" — which is exactly what whole-command reuse needs. Interleaving and
buffering must not be observable in the result.

**Benefit hypothesis.** Unlocks the shell/workflow class (`awk | sort | uniq`,
and build steps that pipe). Potentially the largest *practical* unlock after R1.

**Risk.** Medium-high. Pipe payloads are unhashed bytes crossing a process
boundary; treating them as internal without proving the endpoints invites a
false hit when a peer writes from outside the tree (e.g. a wrapper that reads
the user's stdin into the pipe).

**Effort.** Medium-high, mostly in tracer fd provenance (`FdState` for pipe
ends, write-side tracking, and cross-process dependency edges).

## R3 — Harmless unmodeled syscalls: failed descriptor operations and legacy `fstat`

**Evidence.** `failed fd operation on -1 is not modeled (errno 9)` blocks the
shell pipeline; unmodeled `fstat` (5) appears twice in the `groff` workload.

**Why it is cheap.** A failing `close(-1)` observes nothing and mutates nothing;
a `fstat` on a descriptor the tracer has already classified is a metadata read
that maps onto the existing file-metadata dependency.

**Correctness argument required.** Both must be *modeled*, not tolerated: the
failing operation must be recorded as "an operation that failed with errno 9 and
therefore had no effect", and the `fstat` must attach the same metadata
dependency as `newfstatat`. If a variant cannot be classified, it stays
unmodeled.

**Benefit hypothesis.** Small and immediate; removes a second independent reason
from the shell workload and makes `groff` a single-syscall refusal. No
eligibility by itself.

**Risk.** Low, provided the errno is recorded as part of the observable.

**Effort.** Low.

## R4 — `/dev/null` and other always-empty special files as discardable outputs

**Evidence.** `non-file output cannot be restored: /dev/null` blocks
`cc-syntax-only-lint`; many compiler and lint invocations write to `/dev/null`.

**Correctness argument required.** `/dev/null` is defined to discard writes and
read as empty, so its content is a constant function of the input; recording it
as an output is unnecessary. The refusal should become "discarded, not
restorable" rather than `UNKNOWN`. This must not extend to `/dev/zero`,
character devices with state, or FIFOs.

**Benefit hypothesis.** Small, but it is the only blocker of its kind and it
costs nothing in safety. Expect a handful of extra classifiable compiler runs.

**Risk.** Low (a fixed device with defined semantics).

**Effort.** Low.

## R5 — Interpreter/runtime startup determinism (research, not a table entry)

**Evidence.** All three interpreted workloads are refused by reads made before
the workload's own code runs: `getrandom` (3 workloads), `clock_gettime`
monotonic and realtime (3), `getpid`/`getppid`/`gettid` (3). Setting
`PYTHONHASHSEED=0` changed nothing.

**Why it is the largest class.** Every test runner, linter, code generator, and
build script is behind it. The measured cold-tracing overhead (see the benchmark
report) is also dominated by interpreter startup work.

**What must not be done.** Do not whitelist `getrandom`, clocks, or process
identity. They are genuinely non-deterministic; reuse based on an assumption
that their values do not reach the output is exactly the kind of unproven
assumption V1 forbids.

**What a sound Phase 2 looks like.** Two research directions, in order of
credibility:

1. **Prove non-escape.** For a specific runtime, show by construction that a
   given entropy read is confined to a runtime-internal seed that cannot reach
   any observed output, and enforce it with a fixture that fails if it does.
2. **Explicit determinism profile.** Pin the runtime's entropy and identity
   sources through documented environment controls that the *guest* accepts as
   part of its own contract (as `PYTHONHASHSEED` already is for hashing), verify
   with adversarial fixtures, and record the profile in the execution identity.

**Benefit hypothesis.** The largest potential unlock in the whole list, and
unproven. Treat any estimate as a hypothesis: nothing in Phase 1 measures the
reuse rate that would follow.

**Risk.** High. This is where a false hit is most likely to be introduced,
because the temptation is to declare "these reads don't matter" without evidence.

**Effort.** High (research-grade).

## R6 — Descriptor-lifecycle syscalls for self-contained trees: `epoll_create1`, `eventfd`, `timerfd`

**Evidence.** `epoll_create1` (291) is the **only** blocker for
`pil-image-transform`, because CPython imports `selectors` at startup.

**Correctness argument required.** Creating an epoll fd is not by itself
observable, but the readiness notifications it produces are scheduling-dependent.
A sound treatment must show that readiness ordering never reaches the output, or
refuse whenever a wait returns. This is the same argument family as R5, applied
to scheduling rather than entropy.

**Benefit hypothesis.** Converts "one syscall away" Python workloads into
classifiable ones — but they will still be refused by R5's reads, so this is not
independently sufficient.

**Risk.** Medium-high.

**Effort.** Medium.

## R7 — `getrusage`: classify accurately, do not unlock

**Evidence.** Unmodeled `getrusage` (98) in both `cc -c` workloads.

**Recommendation.** Record it as `NONDETERMINISTIC` system information instead of
"unmodeled syscall", so the refusal reason is accurate and the audit trail says
why. Do **not** treat it as safe: resource usage depends on scheduling and the
machine.

**Benefit.** Documentation and reason quality only.

**Risk.** Low if it changes only the reason, not eligibility. Any attempt to make
it reusable is a correctness error.

**Effort.** Low.

## R8 — Exercise `PROVEN` on a Landlock-capable host

**Evidence.** The audit host's kernel returns `ENOSYS` for
`landlock_create_ruleset`, so no sandbox assertion in Phase 1 could run and
`PROVEN` was never produced.

**Recommendation.** Run the existing sandbox tests, `scripts/demo.sh` and the
benchmark suite on a kernel with Landlock ABI 3+ (Ubuntu 24.04 with the default
enablement, or a GitHub-hosted runner as `benchmarks/*.yml` already do). Phase 1
makes no `PROVEN` claim precisely because this could not be checked here.

**Benefit.** Closes the largest untested area of the safety story.

**Risk.** None to correctness; it may reveal sandbox defects.

**Effort.** Low (re-run existing CI on a capable runner).

## R9 — Benchmark and census methodology hardening

**Evidence.** This Phase 1 had to repair the harnesses before it could trust
them (audit D5) and to add per-sample noise reporting, commit stamping, and a
repository-mutation check. The sweep on this host ran on a 2 vCPU VM whose
timings are noticeably noisier than the historical GitHub-runner numbers.

**Recommendation.** (a) Keep the census in CI (`phase1.yml` already does) and
publish its `census.json` per commit; (b) record CPU governor/turbo state and
virtualization in the environment block; (c) run the native benchmark in at least
two independent sessions and report both, since single-session medians on this
host moved by a few percent between runs.

**Benefit.** Makes future claims independently checkable.

**Risk.** None.

**Effort.** Low.

## Explicitly not recommended for Phase 2

- Whitelisting `getrandom`, clock reads, process identity, or `getrusage` to make
  benchmarks look better. That is the one change that would destroy the
  project's premise.
- Partial-graph or sub-command caching before whole-command dependency
  completeness is demonstrated. The census shows the dependency model is still
  incomplete (unclassified descriptors, unproven pipes).
- eBPF or kernel-side tracing to widen coverage, and a persistent daemon: the
  hit-path profile in `benchmarks/results/break-even.md` shows the fixed cost is
  guard validation plus process startup, which a daemon does not remove.
- Treating a sequence of `rename(2)` calls as an atomic multi-file restoration.
  Reliability audit D1 documents why it is not, and the residual crash-consistency
  limitation remains open.

## What Phase 1 leaves unfinished

1. No real-world workload is reusable; only the synthetic C workloads are.
2. Crash-atomic multi-output restoration is still not achieved (D1 residual).
3. `PROVEN` is still unexercised on the audit host.
4. Ownership changes and shared-library swaps were not tested as input
   mutations (documented gaps in the correctness matrix).

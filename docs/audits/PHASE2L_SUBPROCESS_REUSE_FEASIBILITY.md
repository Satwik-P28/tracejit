# Phase 2L — feasibility of transparent subprocess-level reuse

Question: can TraceJIT reuse an eligible child command inside a workflow whose top-level command is
ineligible (for example `make`), and would that be a larger opportunity than whole-command caching?

## Options compared

| Approach | Correctness contract | Status here |
| --- | --- | --- |
| Whole-command caching (current) | One identity, one process tree, one trace; every observed effect guarded before output is exposed | Implemented; `make`/`cc` are `Unknown` because the tree reads clocks and entropy and uses pipes |
| Explicitly wrapped child (`tracejit run -- cc ...`) | Same contract applied to the child; parent sees only its stdout/stderr/exit/files | Safe today, but the wrapper must be inserted by the user or build system, and the child must itself be eligible |
| Transparent interception of every `execve` inside the tree | Requires per-child identity, scoped dependency recording, and a decision about parent-child communication before the parent can observe the child | Not implemented; high hazard |

## Hazards a transparent design must solve

1. **Identity and scope.** A child's output is consumed by its parent, not by the caller. Reuse must
   reproduce the child's stdout/stderr/exit *as the parent observes them* (pipes, partial reads,
   `SIGPIPE`, ordering) — the whole-command model currently refuses multi-writer or short-read pipe
   patterns.
2. **Inherited descriptors.** The parent may hold or share descriptors with the child; the Phase 2L
   descriptor contract covers only stdin of the whole command and refuses everything else.
3. **Environment and cwd.** `make` varies both per recipe; an identity must bind them exactly.
4. **Signals and process identity.** `SIGCHLD`, wait statuses, `getpid`/`gettid` in the child, and
   jobserver tokens are observable.
5. **Filesystem ordering.** Two children may write the same path; replaying one changes what the
   other observes.
6. **Concurrency.** Parallel `make -j` children race, so a hit must be validated against the state
   the parent actually presents at exec time, not at the start of the build.

## Prior art

Firebuild, Riker and Incr all target process-level caching in build systems. Their existence shows
the direction is real, but their assumptions differ from V1's threat model: build-tool caching
generally accepts a build-system-provided dependency model, while TraceJIT's premise is to infer and
guard dependencies for an unmodified command. This document does not claim details of their
internals beyond that shared shape.

## Evidence from this tree

- `make -j4`, `cc -c`, `sh` and pipelines are `Unknown`/`Nondeterministic` at whole-command level
  (clocks, allocator entropy, pipes). Wrapping a single compiler invocation would inherit the same
  refusals, so it would not produce a hit today.
- Eligible tools (`minigzip`, `bzip2`) already reuse as whole commands; their hit cost is ~14-30 ms
  against 200-400 ms of work, and sessions are dominated by builds, not by those tools.
- The measured session result confirms the limit: bzip2 reuses both directions yet nets 0.98-1.04x
  because the build dominates.
- A transparent design cannot reuse a child unless the child's own trace is eligible. The current
  classifier refuses essentially every `cc`/`make` child for the same reasons the parent is refused.

## Decision

**Do not build transparent subprocess interception now.** The evidence does not establish a
measurable advantage, and the correctness surface (pipes, shared descriptors, signals, parallel
ordering) is much larger than the whole-command contract. The next useful experiment is a bounded
one: measure explicit wrapping of an eligible tool inside `make` (for example a `GZIP`-style
variable) on a build that repeatedly invokes that tool, with the existing whole-command engine. If
that shows a material saving, revisit interception with per-child identity and pipe-scoped output as
a separate contract.

Whole-command caching remains the only implemented reuse unit; no new subsystem was added.

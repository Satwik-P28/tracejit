# Phase 3D: Compatibility Frontier and Incremental Retrieval

Base for Phase 3D: `62425a9` (Phase 3C plus the descriptor-identity correction on `main`).
Review branch: `phase3d/compatibility-retrieval`.

This audit separates three questions that were previously conflated: whether Phase 3C can be
merged, whether a descriptor name identifies the object the kernel acts on, and whether more native
workloads can reuse. The third answer is still no: the census is **9 attempted, 0 reused, 9 refused,
0 execution failures**. The value of this phase is a smaller set of well-identified blockers, not a
compatibility claim.

## 1. PR #5 verification and merge status

PR #5 (`phase3c/latency-candidates-lseek`) was checked before any merge:

- Hosted `validate` check `130748778127` in run `43085530864`: **success**.
- An earlier `validate` check `130746053030`: **success**.
- No human reviews. CodeRabbit reported **skipped: draft pull request**.
- The PR remained a draft; the workspace has no authenticated GitHub CLI/API session, so it cannot
  be marked ready, approved, or merged through the API.

The Phase 3C content was therefore integrated by fast-forward to `62425a9` under the same
repository policy used for Phase 3B: `main` is unprotected and its only ruleset is disabled, so no
approving review is required. The review branch and `main` both point at `62425a9`. PR #5 remains an
open draft record because the API operation is unavailable; this is a reporting limitation, not an
unresolved code defect.

Local review found and fixed one blocking defect before integration: the `/dev/null` admission was
path-based. It is now descriptor-based. Full gates after that fix: fmt, Clippy with `-D warnings`,
**132 workspace tests**, **45 Linux integration tests**, and release build all pass. `PROVEN` is a
local SKIP because Landlock is unavailable; hosted CI is the enforcement evidence for that path.

**Follow-up (Phase 3E).** PR #6 tracks this branch. Its head is `a86b8e2`, which adds the
review fix for `.ok()` error suppression and a cache regression for pruning/malformed records.
PR #6 remains a draft. Its hosted CI runs exist, but their conclusions were not readable without
authentication in this workspace, so no hosted-success claim is made. The retrieval prototype stays
experimental because it has no established performance benefit.

## 2. `/dev/null` descriptor identity

### Why the pathname was insufficient

`FdState::InheritedFile(path)` comes from `readlink(/proc/<pid>/fd/<fd>)`. That is a name, not an
identity. A bind mount, a different mount namespace, or a replaced node can make a path recorded as
`/dev/null` refer to a regular file or another device. Linux's `null_lseek` returns zero for every
whence on the null device, but that fact does not transfer to a different object that happened to
have the same name when it was recorded.

### The guard

`is_null_device_fd(pid, fd)` stats `/proc/<pid>/fd/<fd>` and requires both:

1. a character device, and
2. `st_rdev == makedev(1, 3)` (the Linux null device).

Any metadata failure, a regular file, a different device, or a closed/replaced descriptor returns
false. The `lseek` branch then falls through to the ordinary inherited-descriptor refusal. No
global seek exemption was added.

The `/proc/<pid>/fd` lookup follows the magic link to the open file description's object, so the
check is on the object the kernel would seek, not on the textual target. A device node with the same
major/minor is the null driver regardless of which path or bind mount supplied it. A mount namespace
that hides `/dev/null` does not change the answer; failure to inspect is a refusal.

### Tests and limits

- `linux::phase3d_tests::null_device_identity_is_not_path_only`: a real `/dev/null` descriptor is
  accepted; a regular file descriptor is rejected.
- `dev_null_seek_is_reusable`: the valid `lseek(0, ...)` fixture still reuses.
- `regular_file_stdin_seek_is_reused_as_an_offset_stream`: regular-file stdin is not treated as
  null; it uses the existing inherited-stream model, which tracks offsets and is safe to reuse.
- Existing inherited-stream guard tests still reject a changed stdin identity.

A true end-to-end bind-mount substitution of `/dev/null` was not run because this workspace cannot
create a mount namespace without privileges. That limitation is explicit; the direct descriptor test
covers the identity predicate, while the end-to-end path keeps the conservative refusal fallback.
A descriptor replaced concurrently after the check is outside the stopped-syscall window this guard
observes; multi-threaded `dup2` races remain an area for a future ptrace-level test.

## 3. Candidate retrieval: the improvement was lazy decoding, then lazy fetching

Phase 3C's `Cache::find_candidates` executed one SQLite query and collected every encoded
`record_json` blob, then core decoded one at a time. That is **lazy deserialization**, not
incremental database retrieval. The old query still read all payloads before validating the first
candidate.

Phase 3D adds two stages:

1. `find_candidate_ids` selects only ordered `execution_id` values.
2. `find_candidate_by_id` fetches one `record_json` only when validation reaches that candidate.

The loop still decodes one record and runs that candidate's complete guards before requesting the
next. The `always` admission path is incremental; other admission modes still decode the full set
because eligibility needs all candidates. No metadata predicate, fingerprint, or index is allowed
to replace a guard. A malformed record remains a skip, not a hit.

### Repeated comparison

Three fresh-cache sessions per bound, same harness and fixture as Phase 3C. Values are medians in
milliseconds; Phase 3C values are the earlier three-session run.

| Bound | Newest 3C | Newest 3D | Oldest 3C | Oldest 3D | Miss 3D |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 11.489 | 9.328 | 6.304 | 5.552 | 14.099 |
| 2 | 12.558 | 9.204 | 12.181 | 14.195 | 16.352 |
| 4 | 11.327 | 10.205 | 14.605 | 15.407 | 19.809 |
| 8 | 12.195 | 11.755 | 20.979 | 20.566 | 24.216 |
| 16 | 12.289 | 10.656 | 25.057 | 28.476 | 28.960 |
| 32 | 13.465 | 12.447 | 42.281 | 47.989 | 45.006 |
| 64 | 14.520 | 13.753 | 82.210 | 80.397 | 83.829 |

**Finding: no general speedup.** Newest-first hits improve modestly (0.6-3.4 ms, and 0.8 ms at 64).
Oldest-target hits get worse at four of seven bounds, consistent with one SQLite round trip per
candidate. At 64 candidates the oldest target is 80.4 ms versus 82.2 ms before, which is not a
material win. The prototype proves the retrieval shape and preserves correctness, but it is not
justified as a performance improvement and should not displace the default bound of 8.

The next retrieval experiment should test a compact metadata table (identity, generation, and a
non-authoritative preferred-candidate hint) with a fallback that validates every candidate. That
can reduce I/O without turning metadata into a guard substitute.

## 4. Native compatibility graph

The census was rerun with the release binary (`sha256
f4e8305ae8131dea381999e69707da08945913ba16c878b1ff514d33a5dded75`) and `--admission always`.
Raw data: `benchmarks/results/phase3d/census-native/`.

| Workload | Exact dependency | Can a sound guard represent it? | Required direction |
| --- | --- | --- | --- |
| `cc-compile-fixture` | `getrusage(98)` | No: resource use is produced by the execution being predicted. | Controlled execution or a model that proves the value cannot affect output. |
| `cc-compile-large` | `getrusage(98)` | Same causal dependency. | Same. |
| `shell-pipeline` | `fstat` on a pipe reports buffered bytes; `ioctl(TCGETS)`; failed fd operation | No: the count depends on scheduling and pipe state, not an external input snapshot. | Deterministic scheduler/controlled execution, or refusal. |
| `python-csv-json` | clock, randomness, `gettid` | A guard can only pin a value that is already stable; time/entropy/PID are not. | Explicit controlled-execution contract. |
| `python-csv-json-seeded` | clock, randomness, `gettid` (seeding does not remove them) | Same. | Same. |
| `awk-codegen` | `getpid`, `getppid`, randomness, clock | Process identity is execution-specific; a guard on the recorded PID always invalidates. | Virtualized identity and entropy under a contract. |
| `groff-manpage-html` | pipe `fstat`, short reads followed by more data | No: the observation is a scheduling artifact. | Deterministic pipe replay/controlled execution. |
| `pil-image-transform` | `epoll_create1(291)` | Possibly: creation alone may be effect-free if later waits are modeled. Not established. | Test a narrow model; do not assume it is harmless. |
| `cc-syntax-only-lint` | randomness, `sysinfo`/`prlimit64`, clock, unrestorable output | Mixed: system information and entropy need control; output restoration needs a contract. | Controlled execution plus output-contract work. |

The `lseek` blocker disappeared from the unmodeled ranking, but no workload crossed the reuse
threshold. Blocker reduction without reuse is not compatibility progress.

## 5. Complete-session benchmark

`benchmarks/results/phase3d/complete-session.json` records three fresh-cache sessions. Each session
primes a guarded copy, hits it, changes the input, then runs a nondeterministic workload.

| Step | Decision (3/3) | Classification | Median wall |
| --- | --- | --- | ---: |
| Prime | Executed | Guarded | 19.04 ms |
| Unchanged rerun | Reused | Guarded | 8.57 ms |
| Content invalidation | Executed | Guarded | 16.69 ms |
| Randomness workload | Executed, not eligible | Nondeterministic | 11.05 ms |

The hit is 2.2x faster end-to-end than the first execution in this tiny fixture; that is a session
observation, not a general speedup. The invalidation correctly retraces. The refused workload still
executes natively but must never reuse, which is the intended fail-closed behavior. No refusal was
silently converted into a cache hit.

## 6. Research directions and competing solutions

The persistent graph is in `docs/research/RESEARCH_GRAPH.md`; experiments are in
`docs/research/EXPERIMENT_REGISTER.md`.

- **Syscall semantics and effect typing.** The census shows that a syscall name is not an effect
  class. `fstat` on a regular file is stable; `fstat` on a pipe exposes scheduling. The effect type
  must include the object kind and the observation's information source. This is the same lesson as
  `/dev/null`: identity and context decide whether an operation is replayable.
- **CEGAR.** Counterexample-guided refinement is appropriate for choosing a *smaller sound model*
  from observed failures: start with a coarse refusal, use a counterexample to add a precise
  predicate or object-kind discriminator, and revalidate. It does not permit deleting a failing
  guard to obtain a hit. The descriptor fix is a hand-worked refinement step.
- **Hermit-style controlled execution.** Hermit's record/replay approach makes clocks, randomness,
  process identity, and scheduling reproducible. That is the right competitor for the four
  nondeterministic census workloads, but it changes execution semantics and must be a separate
  contract from native reuse.
- **Firebuild's observed-dependency model.** Firebuild intercepts process behavior and records
  dependencies for later reuse. TraceJIT is more conservative and guard-oriented. Firebuild is a
  useful source for dependency completeness and process-tree coverage, not evidence that a missing
  guard is safe.
- **Salsa and Adapton.** Both separate an input revision from a derived computation and invalidate
  queries when inputs change. They suggest compact metadata and generation-aware candidate lists.
  They do not provide OS-level proof that a file's content or a pipe's state is unchanged; the
  existing guards remain necessary.
- **ccache/sccache manifest indexing.** Manifest/direct modes index compiler inputs and outputs.
  This is the closest practical model for candidate headers and preferred-candidate hints, with a
  conservative fallback when the manifest is stale. It does not justify a metadata-only hit.
- **Filesystem integrity and descriptor semantics.** `statx`, `fs-verity`, `fanotify`, and
  `openat2`/`RESOLVE_*` offer stronger identity and change detection than pathnames. They can
  strengthen guards or reduce hashing, but none can make a pipe schedule deterministic or a clock
  stable.

## 7. Hypotheses tested

| Hypothesis | Result |
| --- | --- |
| H-3D-01: actual descriptor identity can admit null seeks while rejecting a pathname lookalike | **Supported** for the identity predicate; real null accepted, regular descriptor rejected. Bind-mount end-to-end remains untested due privileges. |
| H-3D-02: fetching one record per candidate reduces oldest-target cost | **Rejected** as a performance claim; mixed and mostly worse results. Retrieval is genuinely incremental, but SQLite round trips dominate. |
| H-3D-03: removing the `lseek` blocker produces a reusable census workload | **Rejected**: still 0/9 reused. |
| H-3D-04: the four nondeterministic workloads need controlled execution rather than a stable guard | **Supported by causal inspection**, not yet by an implemented controlled runtime. |

## 8. Limits and next experiments

- Do not merge this Phase 3D branch automatically. It changes retrieval behavior and needs review;
  the performance result is negative.
- Run the descriptor substitution test inside a user/mount namespace on a host that permits it,
  and add a concurrent `dup2` test.
- Prototype a compact candidate-header table with full guard fallback, then rerun this exact
  three-session harness.
- For one workload each, implement a controlled clock/entropy/PID contract and a deterministic pipe
  schedule in isolation. Require output equivalence and explicit native/controlled separation
  before claiming reuse.
- Test whether `epoll_create1` can be modeled narrowly without treating later readiness as stable.
- Keep the census denominator fixed. A refused workload is a negative result, not a workload to tune
  until it passes.

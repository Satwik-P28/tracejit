# Phase X1: single-pass validation audit

Phase X removed one of the two guard passes a cache hit used to run. This audit asks a narrower
question than the Phase X report did: **can the removed pass have prevented an incorrect HIT, or
contributed anything other than earlier rejection?** The answer, argued below, is no — with one
newly accepted execution class, stated explicitly, and with two defects found elsewhere on the
same path and fixed.

Starting point: `e8abc16` on `research/phase-x`, PR #41, base `main` = `c720112`. The production
change under audit is `8d9a45d`; the evidence commits are `fac3f0d`, `c378b68`, `e8abc16`, and
this audit's own commits.

Verdict: **promotable**. No newly introduced incorrect HIT was found. Two defects on the hit path
were found and fixed (a missing CAS object aborted the command; the profiler did not reset its
counters), three permanent regressions were added, and the CI instability was traced to an
unsound test assumption rather than a product defect.

## 1. The cache-hit sequence

`tracejit_core::run` once the identity is prepared. Everything above the `VALIDATE` line is
invisible outside the process and its own cache directory.

```text
PreparedExecution::new      read /proc/self/exe, argv, env, cwd -> identity;  no workspace write
Cache::open                 SQLite open/schema; cache dir only;  may create cache files
lookup_key                  hash of the identity
descriptor preflight        /proc/self/fd scan; refuses fds > 2 that the child would inherit
interrupted-restore check   dead restore-intent marker -> refuse HIT, retrace
find_candidates             SELECT record_json newest-first;  read-only
admission policy            optional cost row SELECT
  ┌─ per candidate ────────────────────────────────────────────────────────────────┐
  │ decode                  serde_json of the record;  malformed -> skip candidate   │
  │ contract + class gate   Guarded/PROVEN only; enforce mode requires PROVEN       │
  │ get_bytes(stdout)       read CAS object, BLAKE3 verify;  cache dir only         │
  │ get_bytes(stderr)       same                                              (*)   │
  │ verify_inherited_offsets lseek(0,..) probe, restored to start_offset      (*)   │
  │ VALIDATE --------------- single validate_all pass ----------------------(**)   │
  │ GuardsPassed::admit     typestate gate: no failure -> token, else deopt         │
  │ restore_outputs         preconditions -> stage -> verify -> backup -> rename    │
  │ apply_inherited_offsets lseek(0) to the recorded end offset                     │
  │ ExposableHit            stdout/stderr/exit become observable here               │
  └────────────────────────────────────────────────────────────────────────────────┘
(*)  touches a descriptor the caller shared, and is restored / verified before validation
(**) the only pass; a failure deoptimizes without mutating the workspace
```

State transitions the typestate makes unrepresentable: `Candidate → ExposableHit` without
`GuardsPassed`; `GuardsPassed → ExposableHit` without `ArtifactsVerified`; and
`ArtifactsVerified → ExposableHit` without restore + inherited-offset application. The token that
carries the bytes is the only way to reach `report_from_record(RunKind::Reused, ..)`.

## 2. What happens before the surviving pass

The question the audit has to answer is whether dropping the earlier pass removed an *ordering*
guarantee: something that must happen only after validation now happens before it.

| Operation before `VALIDATE` | Touches the workspace? | Can change a dependency? | Notes |
| --- | --- | --- | --- |
| `PreparedExecution::new` | no | no | reads `/proc/self/exe`, argv, env, cwd |
| `Cache::open` | no | no | creates/opens SQLite under the cache root |
| `find_candidates` | no | no | read-only SELECT, newest first |
| `CandidateBytes::decode` | no | no | pure parse; malformed records are skipped |
| admission cost lookup | no | no | read-only, `Admission::Always` skips it |
| `get_bytes` (stdout, stderr) | no | no | reads + BLAKE3-verifies cache objects |
| `verify_inherited_stream_offsets` | no file write | no | `lseek(0)` probe, restored to the recorded start offset |
| interrupted-restore consume | cache dir | no | deletes its own dead intent files |

Two operations deserve their own paragraph.

**Loading the cached streams cannot invalidate a dependency.** `get_bytes` opens only
`<cache>/objects/<hash>`, rehashes the bytes and compares. The cache root is never inside an
observed dependency set for the workloads under test, and even if it were, a guard naming a cache
object would be validated *after* the load, so it would observe the current object.

**The inherited-offset probe is a mutation, but not of a dependency.** `verify_inherited_stream_offsets`
checks the caller's stdin offset, seeks to the recorded end offset to prove the seek is
reproducible, then seeks back to the recorded start offset. It runs before validation both before
and after Phase X, so it is not a regression. It does mean the *caller's* open file description is
touched on a path that may deoptimize; if the restore-to-start seek fails, the function returns an
error and the caller retraces with the offset wherever the failed seek left it. That is unchanged
by this phase, and is recorded as an existing limitation rather than a new one (see §5).

## 3. Equivalence argument

Notation: `V(t)` is "the guard list validates against the live state at time `t`"; `R` is the
restore operation; `O(t)` is the externally observable result of restoring at `t`.

* **Before Phase X** a HIT required `V(t₁) ∧ V(t₂) ∧ R` with `t₁ < t₂`, where `t₁` was the first
  pass and `t₂` the pre-restore pass.
* **After Phase X** a HIT requires `V(t₂) ∧ R`.

**Theorem.** If the guard list is a sound abstraction of the command's observable dependency set
(assumption A1), and every guard is evaluated against live state at the moment it runs (A2), then
any execution accepted after the change is observationally equivalent to a native execution.

**Proof.** After the change a HIT implies `V(t₂)`. `V(t₂)` means every recorded dependency matched
the live filesystem at `t₂`. The restore begins immediately after `t₂` and restores exactly the
recorded outputs (A3: the CAS objects verified byte-for-byte against their names before any
destination is mutated). Therefore the observable result at `t₂` equals the recorded result, which
equalled the native result when the record was created (A4). `V(t₁)` is not used.

**What the removed pass could have added.** Only rejection of executions where the state matched at
`t₂` but not at some earlier `t₁`. That class is non-empty and newly accepted: an input that is
mutated and then restored to the recorded content before the surviving pass. It is safe precisely
because the hit decision is a function of state at `t₂`, and the restore is a function of the
recorded outputs, not of the history that produced the state at `t₂`. Nothing in the record is
history-dependent: every guard is a predicate over current metadata, current content, current
environment, or the current open descriptions — none is a counter, a log, or a monotonic sequence.
That property is what makes the change sound; it is assumption **A5** and it is the one to re-check
whenever a new guard kind is added. A guard that asserted "this file was never modified since the
trace" would break the argument, and would also break the documented re-validation contract.

**Assumptions, stated so they can be attacked**

* **A1** The guard list over-approximates the command's observable dependencies: for every input
  the command read, a guard exists whose predicate fails when that input's relevant bytes or
  metadata change (modulo the documented metadata granularity limits).
* **A2** Guards read live state, not a snapshot: `validate_all` performs `stat`/`read`/`readlink`
  on the path at validation time, and hashes bytes it reads then.
* **A3** `restore_outputs` verifies every CAS object before mutating any destination, and rolls back
  on a mid-apply failure; a hard kill leaves a durable intent that refuses the next HIT.
* **A4** Record creation executed the same identity and stored its outputs faithfully; this is the
  base contract the whole cache already relied on.
* **A5** No guard predicate depends on execution history between `t₁` and `t₂` (all are
  state predicates).
* **A6** `t₂` precedes every externally visible restore, and the typestate makes the token
  unreachable without `V(t₂)`.
* **A7** The residual window between `t₂` and the completion of the restore is the pre-existing,
  documented V1 TOCTOU limitation, unchanged by this phase (the pre-restore pass was already the
  last check before the restore).

**A5 is where an unsound version of this optimisation would fail.** The rejected Phase X experiment
(one content digest shared per path within a pass) violated the equivalent of A2 for *later* guards
in the same pass: a digest computed at `t_a` was used to answer a guard at `t_b > t_a`. Its
same-timestamp counterexample is a permanent regression in
`crates/tracejit-guards/src/phase_x_tests.rs`. Phase X1 adds the complementary regression for the
class this change *does* accept: a mutation injected before the stream load and reverted before the
surviving pass must produce a HIT whose bytes equal native execution
(`a_mutation_before_candidate_loading_that_is_restored_is_a_sound_hit`). The pre-load injection
point is `TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH` (+ `_RESTORE_HEX`); the existing pre-validation hook
is unchanged.

## 4. Existing limitation versus new regression

| Property | Before Phase X | After Phase X | Classification |
| --- | --- | --- | --- |
| Input changes before the surviving pass | rejected, possibly by pass 1 | rejected by the surviving pass | unchanged |
| Input changes and is reverted before the surviving pass | rejected by pass 1 | accepted | **newly accepted, proved safe under A5** |
| Input changes during the restore | not detected | not detected | pre-existing limitation (documented) |
| Corrupt CAS object | deopt before restore | deopt before restore | unchanged |
| Missing CAS object | fatal command error | deopt, retrace | **defect fixed here** |
| Inherited stdin offset probe | mutates then restores fd 0 | same | pre-existing |
| Partial restore with hard kill | intent marker refuses next HIT | same | unchanged |

## 5. Adversarial matrix

Each row names the mechanism and the test that pins it. New tests are marked **X1**.

| # | Scenario | Mechanism | Test |
| --- | --- | --- | --- |
| 1 | Input changed during candidate loading | pre-load injection hook, not reverted | `toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit` (same guard outcome), **X1** restored variant below |
| 2 | Input changed immediately before the surviving pass | pre-validation hook | `toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit` |
| 3 | Input changed immediately after the pass (during restore) | `TRACEJIT_TEST_RESTORE_PAUSE_PATH` + SIGKILL harness | `scripts/phase_k4_restore_fault.sh`, `interrupted_restore_intent_refuses_hit` |
| 4 | Corrupted cached stdout | corrupt CAS object | `corrupt_stream_is_rejected_before_output_restoration` (case `output_presence_stdout`) |
| 5 | Corrupted cached stderr | corrupt CAS object | same test, case `output_presence_stderr` |
| 6 | Corrupted cached output artifact | corrupt CAS object | `a_corrupted_cached_output_fails_closed` |
| 7 | Missing CAS object | delete the object file | **X1** `a_missing_cached_object_retraces_instead_of_aborting` |
| 8 | Multiple candidates, mixed validity | two recordings, third input | **X1** `retained_candidates_with_an_unrecorded_input_never_hit`, `alternating_inputs_reuse_a_retained_candidate` |
| 9 | Inherited regular-file offsets | offset-stream model | `regular_file_stdin_seek_is_reused_as_an_offset_stream`, `inherited_stdin_seek_model_reproduces_offsets_and_refuses_unsound_cases` |
| 10 | Inherited descriptor replacement | concurrent replacement, enumerator failure | `concurrent_inherited_descriptor_replacements_are_refused`, `descriptor_enumeration_failure_is_fail_closed` |
| 11 | Cache corruption then retracing | repair path | `corrupted_objects_are_repaired_and_reuse_resumes` |
| 12 | Hard kill during restoration | pause hook + SIGKILL | `phase_k4_hard_kill_recovery` (`scripts/phase_k4_restore_fault.sh`) |
| 13 | Multi-output partial restoration | injected restore failure, rollback | `phase_k4_soft_fail_retrace`, `phase_d_restore_under_contention_does_not_serve_corrupt_bytes` |
| 14 | Dependency mutation during failed candidate evaluation | guard failure then retrace | row 8 plus `metadata_symlink_and_environment_changes_miss` |
| 15 | Phase W1 rename-source counterexample | source re-created after rename | `rename_source_bytes_are_an_input_even_when_the_source_is_recreated` |
| 16 | Mutation reverted before the surviving pass (the newly accepted class) | pre-load hook + restore bytes | **X1** `a_mutation_before_candidate_loading_that_is_restored_is_a_sound_hit` |

Independent oracle: every row compares replayed bytes, exit status and filesystem effects against a
native execution of the same command line, and the differential fuzzer
(`benchmarks/differential/fuzz.py --seed 29`) compares 120 generated cases against native output
with `incorrect_hits = 0`.

## 6. Defects found and fixed

**D1 (correctness/robustness, hit path). A missing CAS object aborted the command.**
`Cache::get_bytes` mapped `ENOENT` to `CacheError::Io`, and the hit loop treats any non-corruption
error as fatal. A pruned, partially copied or interrupted-eviction cache therefore failed `run`
instead of retracing a command that succeeds when simply executed again. Fixed by reporting a
missing object as `CorruptObject` (the record is unservable, exactly like a corrupt one), which the
hit loop already handles by deoptimizing and retracing; the retrace re-stores the object. Regression:
`a_missing_cached_object_retraces_instead_of_aborting`.

**D2 (instrumentation). `take_guard_profile` did not reset its counters.**
The doc comment promised "resetting the collectors", but only the pass list and the observed-path
set were drained; the per-kind and per-operation atomics accumulated across calls, and a second
`take()` in one process would repeat the first measurement. It also subtracted `u64` deltas without
a guard, so a reset during an in-flight pass would underflow (panic in debug). Fixed by resetting
scalars with `swap(0)`, clearing the path sets, and using saturating deltas. No production caller
calls `take()` twice, so no shipped number was affected.

## 7. Instrumentation audit

| Check | Verdict |
| --- | --- |
| Inactive by default | `TRACEJIT_GUARD_PROFILE` unset ⇒ `enabled()` false; `take()` returns `None` |
| No allocation when off | every counter is a predictable branch on a `OnceLock<bool>`; `Scoped::start` and `PassScope::start` return `None` without allocating |
| Environment parsed once | `std::sync::OnceLock` caches the variable for the process |
| Does not mutate dependency state | counters, a `Mutex<Vec<PassStats>>` and a path set; no filesystem writes |
| Does not change guard order | `count_kind`/`observe_path` are called beside the existing match arms; `validate_all` wraps `validate_all_inner` and returns its result unchanged |
| Overflow | `other_ns` saturates; pass deltas now saturate (§6 D2); durations use `try_from(..).unwrap_or(u64::MAX)` |
| JSON compatibility | `PhaseTimings.guard_recheck_ns` has `#[serde(default)]`; `guard_profile` is optional and skipped when absent; unknown fields are ignored by older readers |
| Overhead reported | measured +3.7 % when enabled, unmeasurable when disabled (Phase X report §8.3); every number in §9 below states whether the profiler was on |

No debugging code was left in the production crates. The two test hooks
(`TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH`, `TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH` and their
`_RESTORE_HEX` companions) are absolute-path-only, inert unless set, and documented as test-only.

## 8. CI instability: `allocator_entropy_contract_reuses_a_glibc_tool` and `inherited_stdin_reuse_is_stable_across_fresh_sessions`

**Observation.** CI run #253 passed on `fac3f0d`; #254 failed 4 minutes later on the
documentation-only `c378b68`; #255 passed on `e8abc16`. The failing step was `Tests`
(`cargo test --workspace`), and the failure text was identical for both tests:

```text
left:  "Nondeterministic"
right: "Guarded"
reasons: ["process read randomness via getrandom",
          "executed under the tracejit.allocator-entropy.v1 contract; ..."]
```

**What the contract requires.** `allocator-entropy-v1` absorbs exactly one thing: glibc's allocator
`getrandom(8, GRND_NONBLOCK)` probe. Admission is a profile match, not a pattern match — the trace
side (`crates/tracejit-trace/src/linux.rs`) refuses unless the issuing library's GNU build ID is in
`ALLOCATOR_ENTROPY_PROFILES`, the reported stop offset and destination offset equal the audited
ones, and the instruction bytes around the `syscall` equal the recorded signature. There is exactly
one audited profile: glibc `2.39-0ubuntu8.9`, build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65`.
A refused probe stays an ordinary `getrandom` read, which is classified `Nondeterministic` with
reason `process read randomness via getrandom` — precisely the observed failure.

**Evidence.** This workspace's host is that exact build (`ldd --version` = 2.39-0ubuntu8.9, build ID
`a4a7…ea65`), which is why both tests pass here in 10/10 consecutive runs and at 1, 2, 4 and 8 test
threads. The failure is therefore not about concurrency, descriptor inheritance, cache directories
or scheduling pressure: it is the *runtime identity* of the runner image.

**Classification.** **B + C, triggered by D.** The product did the right thing (B: a legitimate
contract refusal — an unaudited runtime must never be absorbed). The test made an unsound assumption
(C: "the runner's glibc is the audited build"). The trigger is image drift (D): GitHub's
`ubuntu-24.04` image is periodically rebuilt with glibc patch updates, each of which changes the
build ID, and different VMs in the pool can be on either side of a rollout — which is exactly how
two identical-code runs minutes apart can disagree.

**Fix (without weakening fail-closed logic).** `ci.yml` now publishes the runner's runtime identity
as a notice annotation (`Runner glibc: <version> build_id=<id>`), because step logs are not public
but annotations are. The two tests read this host's libc build ID and, when it is not the audited
one, assert the *refusal* — classification `Nondeterministic`, no reuse, identical bytes — and print
`RESULT controlled-sed SKIP unaudited runtime <id>` instead of asserting a HIT the contract correctly
forbids. On an audited runner the full reuse path still runs. Nothing about the product's admission
logic changed; the only production-side effect is the missing-CAS fix from §6.

**Honest limitation.** The role of the build ID is established by code reading and by this host
matching the audited profile exactly, not by capturing the failing runner's `readelf` output, which
is not retrievable after the fact. The next CI run on an unaudited image will now state its build ID
in a public annotation, which settles the question with no further ambiguity. Until such a run has
been observed, this is a strongly supported hypothesis rather than a closed loop, and it is
recorded here as such. If a future failing run reports the audited build ID, the cause is elsewhere
and this section is wrong.

## 9. Verification run on this host

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace --no-fail-fast` | 241 tests, 0 failed (integration target 75) |
| Linux integration, `--test-threads=1` | 75/75 |
| Linux integration, `--test-threads=2 / 4 / 8` | 75/75 each |
| Linux integration, default parallelism ×10 consecutive | 10/10 runs, 75/75 each |
| `cargo build --workspace --release` | pass |
| `cargo audit` | clean (110 dependencies, 1533 advisories) |
| State-machine model check | PASS (`restore_intent` 5 states, 0 violations) |
| Restore fault injection | soft-fail retrace PASS, hard-kill recovery PASS |
| Differential fuzz, seed 29 | 120/120 ok, **0 incorrect hits** |
| Descriptor inheritance | `inherited_descriptor_beyond_stdin_is_never_reused`, `concurrent_inherited_descriptor_replacements_are_refused` |
| Phase W1 rename-source | `rename_source_bytes_are_an_input_even_when_the_source_is_recreated` |
| Malformed record / corrupt CAS | `corrupt_stream_is_rejected_before_output_restoration`, `a_corrupted_cached_output_fails_closed`, `corrupted_objects_are_repaired_and_reuse_resumes`, X1 missing-object test |

Not run here: the real-world compatibility census (unchanged code path, Phase X ran it against the
same tree) — declared, not claimed as passing.

## 10. Performance re-verification (this host, one machine)

Pristine `c720112` release binary (`/tmp/tj-baseline`, built from a clean worktree) versus the
candidate (`/tmp/tj-candidate`). Paired, interleaved, 3 units × 10 rounds = 30 samples per arm,
`benchmarks/phase_x/ab.py`:

| Arm | median | p95 | n |
| --- | --- | --- | --- |
| baseline (two passes) | 126.507 ms | 145.541 ms | 30 |
| candidate (one pass) | 79.246 ms | 91.226 ms | 30 |
| speedup | **1.596×** | 1.596× | |

Sessions (`benchmarks/phase_w/session.py`, 3 units, edits at rounds 7 and 12, 48 invocations):
12.442 s → 10.595 s (1.174×), 12.936 s → 10.683 s (1.211×), and 8.398 s → 6.660 s over 27
invocations (1.261×); all arms `objects_match_native = true`, hit/deopt/miss counts equal between
arms except for one run-to-run deopt that moved between arms.
Non-compiler (`benchmarks/phase_x/workloads.py`): ETL 13.575 → 11.733 ms (1.157×), `true` 15.065 →
11.123 ms (1.354×), `sort-small` (never reuses) 40.008 → 37.345 ms over 20 rounds (1.071×, i.e. the
miss path is unchanged and the spread is noise).

**Cross-machine caveat.** Phase X measured 116.677 → 67.274 ms (1.734×) on its host. This host is
slower in absolute terms for both arms, and the *ratio* reproduced at 1.60× rather than 1.73×. The
two absolute pairs must not be mixed; the reproducible claim is the ratio and the invariant
(syscalls, bytes hashed, decisions), not the microseconds.

Guard cost with the profiler on (one warm `cc` unit, this host): 386 guards, one pass, 52.674 ms of
validation of which **48.343 ms is content hashing (91.8 %)**, 0.599 ms `stat`, 0.374 ms `open`,
0.115 ms `readlink`, 0.099 ms access, 3.1 ms other; 107,160,458 bytes hashed over 57 content
guards, 1737 `read`, 249 `stat`, 57 `open`, 60 `readlink`, 18 directory probes, 11 environment
reads; peak RSS 10.7 MB. That is the budget Phase Y has to attack.

## 11. PR and merge status

PR #41 (`Phase X: eliminate duplicate warm-hit validation pass`) is open, **draft**, base `main`
at `c720112`, head `e8abc16`, `mergeable_state: clean`, 4 commits. This workspace has no GitHub
write credentials (`cloud_git` performs fetch/pull/push only; `gh` is unauthenticated; no token is
present in the environment), so **marking the PR ready, editing its description, and pressing
merge are blocked here**. The branch is pushed; merging a fast-forward into `main` is technically
possible through the push credential, but it is a published-state change that the mission reserves
for the PR flow, so it is reported as blocked rather than performed. Nothing was tagged and v0.3
was not published.

## 12. Remaining limitations

1. **Restore-window TOCTOU**: a dependency mutated after the surviving pass and before the restore
   completes is still not detected. This is the documented V1 limitation, unchanged by Phase X, and
   the removed pass did not reduce it (it was not the last check before the restore).
2. **Metadata granularity**: a same-size rewrite inside one filesystem timestamp tick that also
   preserves `ctime` is invisible to `FileMetadata`; content guards catch it, but a dependency
   recorded only as metadata would not. The Phase X counterexample regression pins this.
3. **Inherited stdin offset on a failed hit**: the probe mutates the caller's open file description
   and restores it; a failure during restoration leaves the offset wherever the last successful seek
   put it. Fail-closed for reuse, not transactional for the caller's descriptor.
4. **Contract admission is per build**: the `allocator-entropy-v1` path is exercised only on an
   audited glibc build, so CI coverage of that specific contract depends on the runner image.
5. **Missing record-level validation for arbitrarily damaged SQLite rows** is unchanged: a record
   that fails to decode is skipped, but a database that cannot be read remains an error rather than
   a retrace.

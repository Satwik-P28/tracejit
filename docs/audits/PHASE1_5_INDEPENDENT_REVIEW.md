# Phase 1.5 independent review

Scope: the ten commits between `f90b4db` (pre-Phase-1) and `ccde07a` (Phase 1 tip), their five
audit documents, and the behaviour they claim. Everything below was re-derived from the current
tree and from execution on this host, not from the Phase 1 reports.

Branch: `verify/phase1-5`, created from `ccde07a`.

## 1. What Phase 1 actually changed

28 files, +8465/-88. Code changes are confined to four files:

| File | Delta | Purpose |
| --- | --- | --- |
| `crates/tracejit-cache/src/lib.rs` | +550 | transactional restoration, CAS repair, deletion precondition, marker adoption |
| `crates/tracejit-core/src/lib.rs` | +109 | recover from cache-integrity failures instead of aborting |
| `crates/tracejit-trace/src/linux.rs` | +8 | preserve the caller's `argv[0]` |
| `crates/tracejit-cli/tests/linux_integration.rs` | +392 | end-to-end invalidation, concurrency, corruption, `argv[0]` |

Everything else is documentation, the real-world census, benchmark artifacts and workflows. No
guard, classifier, dependency-collection or sandbox logic was touched, so Phase 1 could not have
widened reuse eligibility, and it did not.

## 2. Claim-by-claim verification

| ID | Phase 1 claim | Status | Evidence from this review |
| --- | --- | --- | --- |
| D1 | Restoration no longer leaves a half-restored workspace | **PASS** | Staging, hard-link backups and reverse rollback are in `restore_outputs`; six cache unit tests cover replacement, later-stage failure, mixed file+deletion, corrupt object, symlink substitution, second attempt. Re-ran: all pass. Guarantees are in-process only (see §5). |
| D2 | A corrupt CAS object is repaired instead of wedging the command forever | **PASS** | Corrupted every object of a primed cache: run exits `0`, stdout is correct, the record is rewritten, and reuse resumes. Regression test `corrupted_objects_are_repaired_and_reuse_resumes`. |
| D3 | A malformed record deoptimizes instead of failing the command | **PASS** | Poisoned `record_json` with `{"id":`: run exits `0`, output correct. Test `a_malformed_record_fails_closed_instead_of_reusing` plus the end-to-end path. |
| D4 | A deletion precondition cannot act on a path that changed shape | **PASS** | Recorded deletion replaced by a symlink: exits `1` with `the path to delete is no longer the regular file the traced run removed`, and the substituted target is left untouched. Still fatal after my D8 fix, deliberately. |
| D5 | Benchmarks are commit-stamped, immutable and isolated | **PASS with one defect (D10)** | Commit stamp, per-sample JSON and scratch directories are real. The `working_tree_dirty` field was sampled *after* the workload wrote its output, so it always read `true` — see D10. |
| D6 | Preserving `argv[0]` restores interpreter selection | **PASS** | `./link` → `argv0=./link` (direct and traced), symlink chain `./link2` → `./link2`, PATH name `link` → `link`. The pre-fix failure was reproducible as a missing Python module and zero output files. |
| D7 | A peer's marker is not foreign content | **PASS** | 160 concurrent cold starts (16 processes × 10 rounds) against one fresh root: 0 `unsafe cache root` refusals, 83 hits, 77 misses, no failed starts. |

Two of the Phase 1 claims were **narrower than stated**, which is why they needed testing:

- D6 fixed `argv[0]` but not the *script path*: `$0` still diverged for scripts (D9).
- D2/D3 fixed two of the three ways an entry can become unusable; the third, a refused
  replacement, still aborted a command that succeeds when re-run (D8).

## 3. New defects found in Phase 1.5

### D8 — a refused cached replacement aborted a command that otherwise succeeds (fixed)

Severity: **medium**. Introduced by D1's stricter precondition, not present before Phase 1.

A hard link to an output is neither a recorded dependency nor an input mutation, so no guard
observes it; `nlink != 1` is only seen by `validate_output_precondition`. Phase 1 returned that
refusal as an error, so `tracejit run` exited `1`:

```
$ tracejit run -- ./w -- ... ; ln second.txt second.link ; tracejit run -- ./w
tracejit: cached output precondition failed at …/second.txt: the current output has multiple hard links
exit=1
$ ./w          # the same command, executed directly
exit=0
```

A cache is supposed to refuse to serve stale bytes; it is not supposed to make a working command
fail. Fix: `tracejit-core::run` treats a refused *replacement* as a deoptimization and retraces,
which rewrites the output exactly as the cache would have restored it. A refused *deletion* stays
fatal, because re-running such a command would act on the substituted path rather than restore a
recorded absence — D4's protection is preserved. Verified: `exit=0`, `cache MISS`, outputs
correct; the deletion case still exits `1` with the substituted target intact.

### D9 — a traced script did not see the script path the caller used (fixed)

Severity: **low** (fidelity, not cache safety). With `argv[0]` preserved:

| Invocation | Direct `$0` | Traced `$0` before fix |
| --- | --- | --- |
| `./s.sh` | `./s.sh` | `/tmp/h3/s.sh` |

The kernel passes the `execve` path to the interpreter, so exec'ing the canonical target hands the
script an absolute path. A script that derives a path from `$0` observes the difference. This is
not a false-hit path — the invoked argv is part of the identity, so cached and replayed output stay
consistent with each other — but it is a direct-versus-traced divergence. Fix: exec the path the
caller named when it still canonicalizes to the recorded executable, and keep the resolved path for
PATH-name invocations that cannot be execed as a path. Verified by
`a_traced_script_sees_the_callers_script_path`.

### D10 — benchmark provenance recorded every run as dirty (fixed)

Severity: **low** (metadata, no effect on timings). `benchmark.py` and `break_even.py` sampled
`git status --porcelain` *after* measurement, by which point the workload had written
`benchmarks/workloads/c-etl/output/` inside the repository. Every artifact said
`working_tree_dirty: true` while the tree was clean at launch, so the field could not distinguish a
clean checkout from a modified one. Fix: sample once at start-up. Both harnesses still write only
their `--output-dir`, and the Phase 1 workflow's "repository was not mutated" check still holds.

### D11 — the seccomp capability probe reported the wrong thing (fixed)

Severity: **low** (fail-closed, but the telemetry lied). `capabilities()` tested
`prctl(PR_GET_NO_NEW_PRIVS) >= 0`, which succeeds on any kernel with `prctl` and says nothing about
whether a seccomp *filter* can be installed. `doctor` could therefore print `seccomp yes` on a
kernel where `apply_seccomp` fails, and `PROVEN` would be claimed from a capability that was never
established. The install itself fails closed, so no unsafe reuse followed. Fix:
`SECCOMP_GET_ACTION_AVAIL`, the documented probe for the filter interface, plus a test that
installs the filter directly (see the security report).

## 4. What the existing tests do not establish

- Concurrency tests use one process for `Cache::open` races; SQLite does not invoke the busy
  handler for a same-process lock conflict, so `database is locked` is possible there. That is not
  the CLI's model (one connection per process) and is documented as unsupported rather than fixed.
- A guard→restore window still exists between validation and `rename(2)`. Substitution inside it
  replaces the directory entry rather than redirecting the write (verified), but a mutation to a
  *dependency* inside that window is not detectable.
- Nothing in Phase 1 or this review exercises Landlock. Every enforcement claim is therefore
  conditional; see the security report.

## 5. Crash consistency, stated precisely

`restore_outputs` guarantees: no destination is touched until every precondition, every CAS object
and every backup exists. A failure while applying rolls the applied subset back in reverse order.
It does **not** guarantee atomicity across a hard kill: a `SIGKILL` between two renames leaves a
mixed workspace plus stray staging and backup files, there is no journal, and the destination
directory is not `fsync`ed after renames, so a machine failure can lose an otherwise completed
restoration. A repeat invocation recovers, because a re-execution rewrites the outputs — verified
by `a_second_attempt_after_a_failed_restoration_recovers`.

## 6. Verdict on the Phase 1 fixes

Each of the seven Phase 1 defects is genuinely resolved for the case it described, and the fixes
introduce no new reuse eligibility. Two of them were incomplete at their edges (D8, D9), and one
benchmark field was unreliable (D10); all three are fixed here with regression tests. The most
important limitation of Phase 1 is not a defect in the code but a gap in the evidence: the sandbox
was never exercised on a Landlock-capable kernel.

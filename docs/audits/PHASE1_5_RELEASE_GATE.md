# Phase 1.5 release gate

Verdict: **CONDITIONAL PASS.**

The Phase 1 fixes are correct for the cases they describe, the defects this review found are fixed
with regression tests, and the tree builds and tests clean. The condition is enforcement: `PROVEN`
has still never been exercised, because no Landlock-capable kernel was available. That is an
evidence gap, not a known defect, and it is the one item that must close before Phase 2 builds
anything on enforcement claims.

Criteria used: (1) every Phase 1 defect independently reproduced or falsified; (2) every defect found
in this review fixed with a test that fails before the fix; (3) no new reuse eligibility and no
weakened safety check; (4) the full validation gate green on the final tree; (5) all unverified
properties stated explicitly; (6) no claim resting on a skipped test or a borrowed measurement.

## 1. Verified correctness properties

| Property | Status | Evidence |
| --- | --- | --- |
| Only `PROVEN`/`GUARDED` are reusable; `UNKNOWN` never is | **PASS** | 48/48 classification fixtures |
| A dependency change deoptimizes | **PASS** | `RESULT mutation DEOPT`, integration suite |
| A malformed record never serves cached bytes | **PASS** | poisoned JSON → retrace, correct output |
| A corrupt CAS object never serves tampered bytes | **PASS** | every object corrupted → retrace, correct stdout, reuse resumes |
| Restoration mutates nothing before all checks pass | **PASS** | corrupt-object and precondition tests assert untouched destinations |
| A failed restoration rolls back in-process | **PASS** | later-stage failure, mixed file+deletion, second attempt |
| A refused replacement does not fail the command | **PASS** | D8 fix, new test, exit 0 where the pre-fix tree exited 1 |
| A refused deletion stays fatal | **PASS** | D4 preserved, substituted target untouched |
| `argv[0]` matches direct execution | **PASS** | symlink, symlink chain, PATH name |
| Script `$0` matches direct execution | **PASS** | D9 fix, new test |
| Concurrent cold starts never refuse their own root | **PASS** | 160 starts, 0 refusals |
| Seccomp filter denies its forbidden surface | **PASS** | filter installed directly, socket/ptrace → `EPERM` |
| Enforcement never installs a partial policy | **PASS** | `apply` errors without Landlock |

## 2. Unverified correctness properties

| Property | Status | Consequence |
| --- | --- | --- |
| Crash atomicity of multi-file restoration | **UNVERIFIED** | a `SIGKILL` between renames can leave a mixed workspace; recovery by re-execution works |
| Durability of a completed restoration | **UNVERIFIED** | parent directory is not `fsync`ed |
| Concurrent restore plus dependency mutation | **UNVERIFIED** | outside the supported single-writer model |
| Executable swapped between hashing and `exec` | **UNVERIFIED** | profile could describe a different binary than the one that ran |
| Ownership/group mutation on a dependency | **UNVERIFIED** | fingerprint carries uid/gid; no fixture mutates it |
| Shared library replaced after validation | **UNVERIFIED** | same class as the executable swap |
| `$0` for a PATH-named script | **UNVERIFIED** | cannot be preserved |
| Landlock filesystem confinement | **BLOCKED** | needs a Landlock-capable kernel |
| `PROVEN` classification under enforcement | **BLOCKED** | same |

## 3. Remaining security risks

Ranked in `PHASE1_5_SECURITY_REPORT.md` §5. The two that matter for Phase 2: unverified Landlock
enforcement, and the guard→restore window in which a dependency can change without being rechecked.

## 4. Failing, skipped and blocked tests

| Item | Status | Reason |
| --- | --- | --- |
| `supported_sandbox_enforces_declared_surface` | **SKIP** | no Landlock on this kernel; prints the reason and returns |
| `enforcement_refuses_when_landlock_is_absent` | **PASS** (this host) | asserts the fail-closed path; self-skips on a Landlock host |
| Break-even sweep at this commit | **BLOCKED** | did not finish in the verification window; no numbers reported |
| Everything else in `cargo test --workspace` | **PASS** | exit 0 |

No test was weakened, skipped, or marked ignored to make the gate pass. The two Landlock probes skip
by design and are reported as SKIP everywhere they appear.

## 5. Benchmark reproducibility

Two independent native sessions on this host agree to within 0.4% on speedup (2.1003x vs 2.0923x) and
0.5% on hit latency. Both recorded PASS for output equivalence, mutation/deopt and hit assertion. The
`working_tree_dirty` label is truthful in both: the tree carried the two harness files being fixed
for D10 at launch, which is exactly what the field should report. The break-even band for this commit
is **not established**; see `PHASE1_5_FINAL_BENCHMARKS.md` §5.

## 6. Was `PROVEN` exercised?

**No.** Not here, and not in Phase 1. `landlock_create_ruleset` returns `ENOSYS` on this kernel and
Landlock is absent from the active LSM list, so `can_prove()` is false, `apply` refuses to install
anything, and the sandbox test documents the skip. The seccomp half is now verified independently,
which is strictly more coverage than Phase 1 had, but it is not a `PROVEN` run and is not reported as
one.

## 7. Are the Phase 1 fixes safe to merge?

**Yes, conditionally.** They are directionally conservative: no reuse eligibility was widened, no
classifier or guard logic changed, every refusal still refuses, and all four defects found here are
fixed with tests that fail beforehand. Merging does not depend on Landlock, because without it the
`PROVEN` path simply cannot be entered.

## 8. Must resolve before Phase 2

1. **Run the enforcement gate on a Landlock-capable runner.** `.github/workflows/ci.yml` already sets
   `TRACEJIT_REQUIRE_PROVEN=1`, asserts `proven yes`, and fails on `RESULT sandbox SKIP`. Executing it
   needs a push, which is not authorised here.
2. **Decide the crash-consistency contract.** If Phase 2 relies on restoration surviving a kill,
   the staged-rename scheme needs a journal and a directory `fsync`; otherwise say plainly that it
   does not survive, as this document does.
3. **Close or accept the executable-swap TOCTOU** (`hash → exec`), which is the only unverified
   item that could produce a *false* profile rather than an unavailable one.
4. **Freeze the reuse cost budget.** A hit costs 47.6% of this workload's direct
   run; any Phase 2 widening of eligibility must not add guard cost without re-measuring.
5. Nothing in this phase authorises a push, merge, release, or a change to `main`.

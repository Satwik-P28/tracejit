# Phase 1.5 correctness results

Every status below is from a run on this host (Ubuntu 24.04.5, kernel 6.1.102, x86_64, 2 vCPU),
not from the Phase 1 reports.

Statuses: **PASS** executed and passed, **FAIL** executed and failed, **SKIP** deliberately not
exercised for a documented environmental reason, **BLOCKED** cannot be executed here.

## 1. Suites

| Suite | Result | Notes |
| --- | --- | --- |
| `cargo fmt --all -- --check` | **PASS** | |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** | |
| `cargo test --workspace` | **PASS** | all suites green, exit 0 |
| `cargo test -p tracejit-cli --test linux_integration -- --test-threads=1` | **PASS** | 23 tests (was 20) |
| Adversarial classification table | **PASS** | 48/48 fixtures match expected class *and* eligibility |
| Guarded hit / deopt / replay | **PASS** | `RESULT guarded_hit PASS` |
| Mutation deoptimization | **PASS** | `RESULT mutation DEOPT` |
| Sandbox enforcement (seccomp half) | **PASS** | new; see §3 |
| Sandbox enforcement (Landlock half) | **SKIP** | `ENOSYS` on this kernel |
| `PROVEN` classification under enforcement | **BLOCKED** | requires Landlock |

## 2. Phase 1 defect verification, reproduced from the CLI

| Case | Expectation | Result |
| --- | --- | --- |
| D1 later-stage restoration failure | workspace unchanged after rollback | **PASS** (`failure_during_a_later_replacement_rolls_the_first_one_back`) |
| D1 corrupt object | no destination touched | **PASS** (`a_corrupt_object_fails_before_any_destination_is_touched`) |
| D1 interrupted restoration, then retry | retry succeeds, no stray temp files | **PASS** |
| D2 every CAS object corrupted | exit 0, correct stdout, reuse resumes | **PASS** (new end-to-end test) |
| D3 record JSON poisoned | exit 0, correct output | **PASS** |
| D4 deletion replaced by a symlink | refuse, target untouched | **PASS** (exit 1, target intact) |
| D6 symlink, symlink chain, PATH | `argv[0]` identical to direct | **PASS** (`./link`, `./link2`, `link`) |
| D7 160 concurrent cold starts | no false `unsafe cache root` | **PASS** (0 refusals, 0 failed starts) |

## 3. Tests added in Phase 1.5

| Test | Crate | Guards against |
| --- | --- | --- |
| `a_hard_linked_output_retraces_instead_of_aborting` | `tracejit-cli` | D8: a refused replacement failing a command that succeeds when re-run |
| `a_traced_script_sees_the_callers_script_path` | `tracejit-cli` | D9: `$0` divergence for scripts |
| `corrupted_objects_are_repaired_and_reuse_resumes` | `tracejit-cli` | D2 regression: repair must restore reuse, not just avoid a crash |
| `seccomp_filter_alone_denies_its_forbidden_surface` | `tracejit-sandbox` | D11: the filter was never installed by any test without Landlock |
| `enforcement_refuses_when_landlock_is_absent` | `tracejit-sandbox` | a partial policy must never be installed |

The D8 test fails against the pre-fix tree (`exit=1` with the precondition message) and passes after
the fix, so it is a genuine regression test rather than a description of current behaviour.

## 4. Differential checks performed

Direct versus traced, comparing exit status, stdout, stderr and output files:

| Property | Result |
| --- | --- |
| `argv[0]` for `./prog`, `./link`, `./link2`, PATH name | **PASS** identical |
| `$0` for `./script.sh` | **PASS** identical after the D9 fix |
| stdout of the C ETL workload | **PASS** (`output_equivalence: true`, harness) |
| output file bytes after a hit | **PASS** (harness compares SHA-256 across baseline, traced, cached) |
| exit status propagation, including nonzero | **PASS** (`nonzero_exit` fixture, integration suite) |
| mutation of a dependency between runs | **PASS** deoptimizes and reports the changed path |

## 5. Deliberate non-adoption: property-based testing

No property-based framework was added. The invariants worth fuzzing here are filesystem-state
properties over a *sequence of syscall outcomes* (partial `rename`, `ENOSPC`, `EACCES`, `EEXIST`),
and the crate already has deterministic fault injection for exactly that
(`tracejit_cache::fault`, test-only `should_fail`), which makes each scenario reproducible by path
rather than by a shrinking search. Adding `proptest` would introduce a new dev-dependency and
randomised timing in a suite that runs ptrace under a wall-clock budget, for coverage that
deterministic scenarios already give. This is a judgement call, recorded as such: **no property was
established by sampling.**

## 6. Remaining correctness gaps (all reproducible, none silently ignored)

| Gap | Status | Note |
| --- | --- | --- |
| `SIGKILL` between two renames during restoration | **UNVERIFIED** | Documented limitation; no journal, so a mixed workspace is possible. Recovery by re-execution works |
| Machine failure after renames (no directory `fsync`) | **UNVERIFIED** | durability of a completed restoration is not guaranteed |
| Concurrent restore and concurrent dependency mutation | **UNVERIFIED** | no test; both are outside the supported single-writer model |
| Executable replaced between hashing and `exec` | **UNVERIFIED** | could record a profile under one binary and run another |
| Ownership/group changes on a dependency | **UNVERIFIED** | fingerprint carries uid/gid, but no fixture mutates them |
| Shared library swap after validation | **UNVERIFIED** | library bytes are hashed as a dependency, but the swap window is untested |
| Deleted output replaced by a hard-linked file (nlink 1 vs 2) | **PASS** | refusal is fatal, which is intended |
| Same-process, multi-connection cache | **FAIL by design** | `database is locked`; unsupported configuration |
| `$0` for a PATH-named script (`PATH=… script.sh`) | **UNVERIFIED** | cannot be preserved: a name without a separator cannot be execed as a path |

Behaviour that Phase 1 claimed atomically is **not** atomic, and this document does not claim it:
restoration is staged-and-rolled-back, not a multi-file transaction.

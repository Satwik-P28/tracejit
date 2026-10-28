# Phase 1 correctness matrix

Every row below is an executed test or an explicitly recorded gap. Nothing is
marked passing because it was inspected; a pass means the named test ran and
asserted the stated behavior in this repository's workspace on Linux x86_64.

Host: Ubuntu 24.04.5, kernel 6.1.102, x86_64, 2 vCPU, Landlock **unavailable**
(`ENOSYS`). Because of the last item, `PROVEN` could not be produced on this host
and the sandbox assertions reported their documented skip; those rows say so
rather than claiming a pass.

Reproduce:

```bash
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture --test-threads=1
sh benchmarks/realworld/repro/partial_restore.sh ./target/release/tracejit
```

## 1. Classification matrix (48 fixtures)

`crates/tracejit-cli/tests/linux_integration.rs::adversarial_classification_table`
runs every entry of `tests/fixtures/cases.json` through `tracejit analyze --json`
and requires the classification *and* the reuse-eligibility flag to match.
Result: **48 passed, 0 failed** (`RESULT classification PASS`).

| Class | Cases | Expected | Result |
| --- | ---: | --- | --- |
| `GUARDED`, eligible | 30 | recorded and revalidatable | PASS |
| `NONDETERMINISTIC`, ineligible | 13 | clocks, randomness, process identity, system information, network, signals, tempfile | PASS |
| `UNKNOWN`, ineligible | 5 | `/proc/self`, `clone`, shared writable `mmap`, unmodeled `ioctl` | PASS |

Ineligible cases include `vdso_clock`, `clock_realtime`, `clock_monotonic`,
`getrandom`, `urandom`, `process_identity`, `system_info`, `tempfile_creation`,
`network_connect`, `network_send`, `dns_lookup`, `unix_socket`,
`proc_self`, `clone_thread`, `mmap_shared_write`, `mmap_shared_mprotect`, and
`unknown_ioctl`.

## 2. Guard, deopt, and reuse behavior

| # | Case | Test | Expected | Result |
| --- | --- | --- | --- | --- |
| 1 | Cold run, guarded hit, output restore, replay | `guarded_hit_deopt_restore_and_replay` | `MISS`, then `HIT`, deleted output restored, stdout/stderr/exit replayed | PASS |
| 2 | Input content change | same test | `DEOPT` and `explain` names the changed dependency | PASS |
| 3 | Environment change | same test | no `HIT` | PASS |
| 4 | Same-size content change with `mtime` restored via `touch -r` | `same_size_content_change_with_original_mtime_deoptimizes` | `DEOPT` | PASS |
| 5 | Same change under `--guard-mode fast` | `fast_guard_mode_still_deoptimizes_on_a_content_change` | `DEOPT` | PASS |
| 6 | Permission change on an input | `permission_change_deoptimizes` | `DEOPT` | PASS |
| 7 | Symlink retarget | `metadata_symlink_and_environment_changes_miss` | `DEOPT` | PASS |
| 8 | Metadata-only change (same bytes, new `mtime`) | same test | `DEOPT` | PASS |
| 9 | Dependency removed | `removing_a_dependency_deoptimizes` | `DEOPT` | PASS |
| 10 | Dependency that appeared where absence was guarded | `an_absence_guard_reports_a_file_that_appeared` | `HIT` while absent, `DEOPT` after creation | PASS |
| 11 | A child process's file dependency changes | `child_process_dependency_change_deoptimizes` | `DEOPT` | PASS |
| 12 | Executed interpreter changes | `executed_interpreter_change_deoptimizes` | `DEOPT` | PASS |
| 13 | Working directory changes | `working_directory_change_is_a_miss` | `MISS` (new identity), never `HIT` | PASS |
| 14 | Nondeterministic or unknown workload run twice | `nondeterministic_and_unknown_cases_never_reuse` | never `HIT` for `getrandom`, `unknown_ioctl`, `network_send`, `vdso_clock` | PASS |
| 15 | Non-zero exit status | `guarded_hit_deopt_restore_and_replay` | `7` reproduced on reuse | PASS |
| 16 | Caller-supplied `argv[0]` reaches the traced process unchanged | `traced_execution_preserves_the_caller_supplied_argv0` | direct and traced `$0` identical; **failed pre-fix (defect D6)** | PASS |
| 17 | A real Python workload that writes a file under tracing | `benchmarks/realworld/census.py` (`pil-image-transform`) | exit status, stdout and output hash identical to direct execution; **pre-fix it exited 1 with zero writes (defect D6)** | PASS |

## 3. Multi-output restoration (Phase 1 step 3A)

Unit tests in `crates/tracejit-cache`, plus the end-to-end reproduction script.

| # | Scenario required by the brief | Coverage | Before the fix | After the fix |
| --- | --- | --- | --- | --- |
| 1 | Two or more cached output files | `restores_multiple_outputs_over_existing_content` | PASS | PASS |
| 2 | Failure during the second or later replacement | `failure_during_a_later_replacement_rolls_the_first_one_back` | would leave output 1 replaced (**defect D1**) | PASS — rolled back |
| 3 | Permission change after precondition validation | `benchmarks/realworld/repro/partial_restore.sh` (read-only parent directory) | partial restoration observed | PASS — workspace untouched |
| 4 | Symlink substitution between validation and write | `a_symlink_substituted_before_the_swap_cannot_redirect_the_write` | PASS (`rename` replaces the link) | PASS |
| 5 | Corrupted content-addressed object | `a_corrupt_object_fails_before_any_destination_is_touched` | object rejected, but unrecoverable (**D2**) | PASS — rejected, then repaired on retrace |
| 6 | Process termination during restoration | not deterministically testable in-process | unknown | **UNSUPPORTED** — no recovery journal; documented limitation |
| 7 | Output files that already exist | `restores_multiple_outputs_over_existing_content` | PASS | PASS |
| 8 | Output files that have been deleted | `restoration_respects_create_precondition` | PASS | PASS |
| 9 | Mixed file restoration and deletion | `mixed_file_and_deletion_restoration_rolls_both_back` | would leave a mixed workspace | PASS — both undone |
| 10 | Repeated invocation after an interrupted restoration | `a_second_attempt_after_a_failed_restoration_recovers` | n/a | PASS — no staging or backup files left behind |
| 11 | Delete target replaced by a directory | `deleting_a_path_replaced_by_a_directory_fails_closed` | attempted `remove_file` (**D4**) | PASS — refused, directory intact |

## 4. Concurrency, corruption, and security

| # | Case | Coverage | Result |
| --- | --- | --- | --- |
| 1 | Concurrent cache reads for one key | `concurrent_cache_reads_all_reuse_the_same_result` (8 parallel processes) | PASS — all `HIT`, identical stdout |
| 2 | Concurrent cold runs for an identical key | `concurrent_identical_runs_neither_fail_nor_reuse_unsafely` (8 parallel processes) | PASS |
| 2b | Same, at 32 parallel processes, pre-fix and post-fix binary | shell probe | PASS — 0 non-zero exits, 0 errors; cross-process SQLite contention **not reproduced** (see S1) |
| 2c | First-time initialization of one fresh cache root by concurrent starts | `a_marker_written_by_a_peer_is_not_unrelated_content`, `concurrent_first_initialization_never_refuses_its_own_marker` | PASS — the false `unsafe cache root` abort (**defect D7**) is fixed; `database is locked` from eight connections *in one process* is tolerated as documented, expected SQLite behaviour (S1) |
| 2d | Several connections in one process | `concurrent_first_initialization_never_refuses_its_own_marker` (control) | **UNSUPPORTED** — not serialized; the supported model is one cache connection per process, which is what the CLI does (S1) |
| 3 | Corrupted cached output object | `a_corrupted_cached_output_fails_closed` | PASS — no cached byte served, run retraces, object repaired, next run reuses |
| 4 | Truncated or invalid SQLite record | `a_malformed_record_fails_closed_instead_of_reusing` | PASS at the cache layer (`CacheError::Serialization`, fail closed). The end-to-end retrace path is covered by the same code branch as case 3 but is not asserted end to end: **UNSUPPORTED end-to-end** |
| 5 | Cache root replaced by a symlink | `a_symlinked_cache_root_is_refused` | PASS — refused with `unsafe cache root` |
| 6 | Cache root containing unrelated user content | `cache_root_refuses_existing_unrelated_content` | PASS — refused, user data untouched |
| 7 | `cache clear` on a directory with unrelated files | `clear_removes_only_owned_cache_entries` | PASS |
| 8 | Tracer survives a tracee killed by SIGKILL | `a_self_killed_child_is_reported_and_never_reused` | PASS — exit status 137 reported, no hang, never reused |
| 9 | Unsupported syscall behavior | `unknown_ioctl` in the classification matrix | PASS — `UNKNOWN`, ineligible |
| 10 | Dependency mutated concurrently during the run | — | **DOCUMENTED LIMITATION** (`SAFETY.md` TOCTOU section). Not detected; not tested |
| 11 | Cache subdirectory replaced by a symlink | — | **UNSUPPORTED** — recorded as hardening candidate S3 in the reliability audit |

## 5. Sandbox and enforcement

| # | Case | Result |
| --- | --- | --- |
| 1 | Partial sandbox cannot produce `PROVEN` | `unsupported_or_partial_sandbox_cannot_prove` — PASS |
| 2 | Declared path allowed, undeclared path/network/forbidden syscall denied | `supported_sandbox_enforces_declared_surface` — **SKIPPED** (`seccomp or Landlock ABI 3+ is unavailable` on this audit host) |
| 3 | End-to-end `--enforce` run | **SKIPPED** — same reason, `RESULT sandbox SKIP` printed by `sandbox_declared_path_succeeds_and_other_effects_are_denied` |
| 4 | `doctor` reports the capability gap instead of pretending | PASS — `proven no` plus an explicit problem line |

No `PROVEN` claim is made anywhere in this Phase 1 report.

## 6. Workspace test counts (this run)

| Suite | Tests | Result |
| --- | ---: | --- |
| `tracejit-cache` unit | 16 | PASS |
| `tracejit-cli` unit (`src/main.rs`) | 5 | PASS |
| `tracejit-cli` `linux_integration` | 20 | PASS |
| `tracejit-core` unit | 7 | PASS |
| `tracejit-effects` unit | 5 | PASS |
| `tracejit-guards` unit | 8 | PASS |
| `tracejit-sandbox` unit | 2 | PASS |
| `tracejit-trace` unit | 5 | PASS |
| **Total** | **68** | **PASS** |
| `cargo fmt --all -- --check` | — | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | — | PASS |

## 7. Gaps that Phase 1 did not close

1. **Crash atomicity.** Restoration is recoverable within a process, not across a
   hard kill (reliability audit D1, residual limitation 1).
2. **Ownership change as an input mutation.** Not tested: changing a file's owner
   requires privileges this audit host does not have for arbitrary files.
3. **Direct shared-library mutation.** `executed_interpreter_change_deoptimizes`
   covers an executed interpreter; swapping a `libc.so` on the host was not
   attempted because it is not a safe operation on a shared machine.
4. **Malformed record through the CLI.** Covered at the cache layer only.
5. **`PROVEN`.** No Landlock on the audit host.
6. **Concurrent dependency mutation.** Deliberately documented, not asserted.

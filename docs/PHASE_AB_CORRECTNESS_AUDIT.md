# Phase AB correctness audit

Scope: the single production change of Phase AB (`Cache::restore_outputs`
returns early when a record has no workspace outputs) plus the new adversarial
tests and the benchmark harnesses that make claims about correctness. Everything
below was run on this host at the Phase AB head; nothing is inferred.

Evidence: this document, `benchmarks/results/phaseab/` (`smoke/`, `build_integrity.json`,
`ab_hits.json`, `entropy_study_1000.json`, `entropy_predict.json`).

## 1. What the change can affect, and what it cannot

`restore_outputs` is the only code that mutates the workspace on a hit. The
skipped block is:

1. `validate_output_precondition` for each output — nothing to validate when the
   list is empty;
2. `stage_output` per output — nothing to stage;
3. `sync_staged_parents` — empty input;
4. `backup_destination` per existing output — none;
5. `write_restore_intent` — records the destinations that are about to be
   renamed, so that a hard kill between renames forces the next run to refuse
   HIT;
6. `apply_output` per output — none;
7. `clear_restore_intent`.

With an empty list, steps 5–7 are the *only* work performed, and they protect
renames that cannot happen. The safety property they implement is unchanged:
there is no multi-file apply to be interrupted, so there is no mixed workspace to
detect.

Not affected: guard validation, CAS object verification, decision persistence,
stream replay, admission, classification, or the identity. A record with outputs
still writes and clears the intent exactly as before.

## 2. Tests

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace --no-fail-fast` | pass, 0 failed |
| `cargo test -p tracejit-cli --test linux_integration -- --test-threads=4` | **85/85** (84 before; +1 new) |
| New cache regression `restoring_no_outputs_writes_no_restore_intent` | pass — no intent file, no interrupted-restore flag on reopen, no temp files |
| New integration `application_stack_entropy_is_never_admitted_by_a_contract` | pass — a stack-buffer `getrandom(8, GRND_NONBLOCK)` is `Nondeterministic` under both contracts and never reused |
| New fixture case `getrandom_nonblock_stack` in `cases.json` | pass in `adversarial_classification_table` |
| `python3 scripts/modelcheck/check_state_machines.py` | PASS, 0 violations, `restore_crash` 2 mixed-kill states recorded as a limitation |
| Differential fuzz, seed 29 | PASS, 0 incorrect hits |
| Restore fault injection (`scripts/phase_k4_restore_fault.sh`) | PASS: soft-fail retrace and hard-kill recovery |
| W1 adversarial oracle (`benchmarks/phase_w1/audit.py`) | 13/13 pass |
| `cargo audit` | pass, 110 crates, no advisory |
| Frozen corpus smoke (`AA_MODE=smoke`) | 42 declared cells, 40 attempted, 10 reused, 8 timed rows, schema + accounting valid, **0 incorrect hits**, 13/13 preserved counterexamples, 0 stale race observations |
| Whole-build experiment (32 TUs × 12 schedules × 4 arms) | every `.o` compared to a clean reference; no incorrect artifact in any arm that ran the compiler; the corruption schedules are analysed in `OUTPUT_INTEGRITY_ECONOMICS.md` |

The new integration test is the guard rail for the entropy work: the admitted
request shape issued from *application* code must stay ineligible even under the
contracts, so the intermittent gcc refusal cannot be "fixed" by widening
admission.

## 3. New behaviour found, not introduced

The whole-build experiment exposed a property of timestamp-preserving restore
that no unit test covered: after TraceJIT restored a correct object, the object's
replayed mtime was older than the archive built from the corrupted bytes, so
`make`/`ar u` considered the archive current and left the corrupted member in
place. `ccache` writes the restored object fresh, so its archive was updated.
The object bytes were right in both cases.

This is recorded as a limitation, not fixed here. Fixing it means changing what
reuse preserves about output metadata, which is an Obs-contract question
(`SAFETY.md` excludes timestamps from the preservation claim) and needs its own
adversarial review. `OUTPUT_INTEGRITY_ECONOMICS.md` §3 states it plainly.

## 4. Not covered

* A prune racing a restore remains untested (Phase AA1's open item) — unchanged
  by this phase.
* The validate→restore TOCTOU window is unchanged and still documented.
* Landlock/`PROVEN` paths SKIP on this host; the sandbox tests are unchanged.
* The new test asserts the classification boundary, not a statistical rate; the
  rate is measured separately at 1,000 trials.

**Table: Candidates accepted into the product and candidates rejected with the measurement that rejected them.**

| Candidate | Status | Evidence |
| --- | --- | --- |
| Drop the redundant first guard pass before loading cached streams | accepted | docs/PHASE_X_REPORT.md; one pass remains, immediately before restore; guard-pass regression suite in tracejit-core |
| Skip the durable restore intent for records with no workspace outputs | accepted | docs/PHASE_AB_REPORT.md; paired A/B on cut, gzip -6, sed with CIs excluding zero |
| Drop the pre-delete/pre-rename input snapshot when the same execution recreates the path | accepted | docs/PHASE_W_REPORT.md; regression superseded_delete_does_not_pin_the_next_run_to_the_old_bytes |
| Report the record's determinism class on the reuse path | accepted | docs/PHASE_AF_REPORT.md; linux_integration::enforced_execution_is_proven_reused_and_invalidated |
| Promote F_GETFD on inherited descriptors to a modelled no-op | rejected | docs/PHASE_AD_REPORT.md §14: sound but inert, 0 of 48 census cells changed; unit test pins the refusal |
| Model F_GETFL/F_SETFL on inherited or internal pipes | rejected | docs/PHASE_AD_REPORT.md §14: shared, externally mutable status flags |
| Model tar's realtime clock read | rejected | docs/PHASE_AD_REPORT.md §14: no clock contract exists; --mtime does not remove the read |
| Relax metadata guards with a metadata-preserving clone | rejected | docs/PHASE_AC_REPORT.md: unjustifiable field precision, reproduced divergence |
| Snapshot inputs to close the validation-to-restore race | rejected | docs/TOCTOU_CORRECTNESS_BOUNDARY.md: redefines observable state and doubles hit cost |
| Cooperative flock mode for reuse | rejected | docs/TOCTOU_CORRECTNESS_BOUNDARY.md: not a guarantee against an uncooperative writer |
| Change default admission from auto to always | rejected | docs/PHASE_AD_REPORT.md §7: 3.4-4.2% on one session, unproven, costs one-shot tracing |
| Fused hash-and-write, streaming cached bytes, mmap replay | rejected | docs/PHASE_AE_REPORT.md §13: each exposes unverified bytes or adds a failure mode |
| Cache guard results between runs (metadata-only revalidation) | rejected | docs/PHASE_AE_REPORT.md §13: reintroduces the same-timestamp defect |
| Parallel guard validation across 8 threads | rejected | docs/PHASE_W_REPORT.md: sequential guard walk dominates; 111.7 to 110.6 ms median, reverted |
| Grant the parent directory of a declared output REMOVE_FILE/MAKE_REG so gzip can be enforced | rejected | docs/PHASE_AF_REPORT.md §5: does not help (the refusal is an unmodelled EEXIST write) and widens the policy |
| Grant parent-directory replacement rights to make producers enforceable | rejected | docs/PHASE_AF_REPORT.md §5: the blocking effect is the command's own failed O_EXCL, not the directory grant |

*Source: benchmarks/phase_af/optimisations.json, curated from the phase reports named in each row*

# Validation-to-restore TOCTOU (Phase AD)

The remaining documented race: an input can change after the last guard validation and before
the cached outputs become visible. This study states precisely what the implementation does
today, what each candidate mitigation would buy, and why none of them is implemented in this
phase.

## 1. The window

A HIT does, in order: look up the record, run every guard, restore outputs, expose streams.
Between the last guard and the last restored byte, an external writer can replace or modify an
input. The cached bytes then describe a world that no longer exists.

TraceJIT already re-validates inputs in a second pass immediately before restoration
(`maybe_test_mutate_before_validation` models an attacker inside that window), and the
integration test `toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit` injects a
mutation exactly there with `TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH` and requires a deopt and a
re-execution rather than a HIT. That test is part of the gates. What it proves is that the
second pass exists and fails closed; it does **not** prove the window is closed, because a
mutation after that pass is still unobserved.

## 2. Measured cost of the passes

The validation pass is content hashing, so its cost is proportional to the recorded inputs, not
to the number of guards. From `docs/ARTIFACT_BENCHMARKS.md`: a 1 MiB gzip HIT costs 6.0 ms end
to end, of which roughly 0.3 ms is BLAKE3 over the 1 MiB input at ~3 GB/s; a 100 MiB HIT costs
85 ms, of which ~20 ms is hashing 100 MiB of input. A third or fourth pass would add that same
small amount per pass. Cost is therefore not the reason the race remains open; atomicity is.

## 3. Candidate mitigations

| approach | what it actually guarantees | cost | verdict |
| --- | --- | --- | --- |
| second validation pass (implemented) | a mutation *before the pass* is caught | ~0.3 ms/MiB | keep; already there |
| N validation passes | narrows, never closes the window | n × hash | pointless without a freeze |
| cooperative workspace lock | writers that use the same lock cannot interleave | one `flock` per run | partial only: uncooperative writers ignore it; cannot be advertised as a guarantee |
| input snapshotting (copy inputs to a private directory, validate the copies) | the *snapshot* is stable; cached bytes are consistent with the snapshot, not with the live workspace | copy of every input per HIT (O(bytes), plus inode/mtime drift) | changes the meaning of the result; would double the hit cost of a 100 MiB input for no user-visible benefit unless the user asked for snapshot semantics |
| fd pinning (`open` inputs once before validation and read from the fds) | closes the path→inode race for files the tracer opens itself | one fd per input; does not stop in-place writes to the same inode after the last `read` | partial: catches rename/replace, not truncate-and-rewrite |
| filesystem isolation (mount namespace + read-only bind mount of inputs, writable overlay for outputs) | writers outside the namespace cannot change the input view *during* the run | needs privileges or a Landlock-capable kernel; overlay copy-up cost on output writes | real freeze for cooperating infrastructure; unavailable unprivileged on this host and not implemented |
| versioned execution environments (rename workspace generations) | each HIT names an immutable generation | renames + storage per generation | complete only if every writer participates; otherwise same as a lock |
| explicit mutation-free window (user declares "no writer during this command") | a contract, not an enforcement | zero | honest but shifts the burden; can be offered as documentation, not as a safety claim |

Two conclusions follow from the table. First, **no userspace-only mechanism closes the race
against an uncooperative writer**; every complete option requires either a privileged
filesystem namespace or a convention that the writers also obey. Second, **snapshotting is not
a mitigation of this race** — it redefines the observable state that the cached bytes describe,
which is a product decision, not a bug fix.

## 4. What was done in this phase

Nothing in the product. The deterministic injection test and the second pass remain the
mitigation; the limitation stays documented in `LIMITATIONS.md` and the release checklist
records it as an open correctness item. A cooperative-lock mode was considered and rejected:
it adds a new failure mode (a command that itself opens the workspace with `flock` would block
or fail differently under TraceJIT) and cannot be claimed as a guarantee, so it fails both the
cost/benefit test and the project's rule against unproven claims.

## 5. What would change the answer

A Landlock- or namespace-capable execution environment where inputs are bound read-only for the
duration of a HIT, verified on a host that can actually enforce it. That is the same
prerequisite as the `PROVEN` label in `SAFETY.md`; until such a host is in the test matrix, the
honest statement is "validated, then restored, with a second validation pass and a documented
window", not "atomic".

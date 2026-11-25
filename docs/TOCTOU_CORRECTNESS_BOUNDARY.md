# Validation-to-restore TOCTOU: the actual boundary (Phase AE)

This document replaces the TOCTOU section of `docs/PHASE_AD_REPORT.md` and corrects
`docs/TOCTOU_MITIGATION_STUDY.md` where it describes the implementation. The correction is
narrow and important: **warm reuse performs one surviving guard-validation pass, not two**,
and the measured consequence is that a mutation after that pass produces stale output.

## 1. What the code does

A warm HIT, in order: look up the candidate record; validate every guard once
(`validate_all` in `crates/tracejit-core/src/lib.rs`); restore output files through the CAS;
expose cached stdout/stderr through the typestate gate; persist the decision. The earlier
"first pass" was removed in Phase X; the integration test
`toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit` exercises the *surviving* pass, so
Phase AD's "second validation pass" description of the product was wrong even though the test
name (kept for continuity) still says `recheck`.

The window that remains: from the end of guard validation to the moment the cached bytes become
visible (stdout write, restored file rename, metadata application).

## 2. The deterministic and probabilistic experiments

Harness: `benchmarks/phase_ae/toctou_race.py`; raw output
`benchmarks/results/phaseae/toctou_race.json`, regenerated in this phase against the current
`main`-based binary (`tracejit` sha256 `b6c3bab9…`). The input changes are injected at five
points using the product's own test-only hooks.

| interleaving | mechanism | measured decision | output | correct? |
| --- | --- | --- | --- | --- |
| mutation **before** validation | `TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH` | `Deoptimized` → `Executed` | new-input output | yes, detected |
| mutation before the cached streams are loaded | `TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH` | `Deoptimized` → `Executed` | new-input output | yes, detected |
| mutation then immediate revert in the same hook | `PRE_LOAD_MUTATE_PATH` + `PRE_LOAD_RESTORE_HEX` | `Deoptimized` → `Executed` | old-input output | yes — the rewrite changed mtime, so the metadata guard fired; a transient rewrite is *detected*, not invisible |
| mutation **after** validation, before the staged output is applied | `TRACEJIT_TEST_RESTORE_PAUSE_PATH` (30 s pause), external writer after 1 s | **`Reused`** | **old-input output** | **no — this is the residual race** |
| concurrent writer during hashing of a 64 MiB input (8 trials) | no hook, 2 ms writes | 8/8 `Deoptimized` | new-input output | yes, detected |

The fourth row is the documented guarantee's edge, measured rather than assumed:
`undetected_stale_bytes: true`. The cached bytes describe a workspace state that no longer
exists, and the command reports success.

Two claims that must **not** be made:

* "the second pass catches a mutation after validation" — there is no second pass;
* "the window is closed" — it is not, and the experiment above shows the exact failure.

## 3. Why descriptors, bind mounts and Landlock do not close it

* **An open file descriptor does not freeze content.** `read()` through a pinned fd after an
  external `pwrite()`/`truncate()` returns the new bytes. Only `O_PATH` + re-hash would notice,
  and that is another validation pass, not a freeze.
* **A read-only bind mount does not make the backing inode immutable.** It removes `MAY_WRITE`
  for that mount's path resolution; a writer holding any other mount of the same superblock, or
  `CAP_DAC_OVERRIDE`, still writes the inode.
* **Landlock restricts the processes it is applied to.** It confines the traced command's tree;
  it does not stop an unrelated process from writing the workspace during the HIT. It narrows
  the *effect* surface of the replayed command, not the input's mutability.
* **`PROVEN` is not a proof of equivalence.** It asserts that seccomp-BPF and Landlock ABI ≥ 3
  were installed for that execution after the effects were already `GUARDED`
  (`SAFETY.md`). It says nothing about external writers, and it does not make the observable
  result formally equal to a native run. The word invites that misreading; a future release
  should rename the label (for example `ENFORCED`) with an explicit migration, which this phase
  does not do because it would break the documented `PROVEN`/`GUARDED` contract and every
  consumer of it.

## 4. Mitigations considered, and why none is adopted

| approach | what it would actually guarantee | cost | decision |
| --- | --- | --- | --- |
| additional validation passes | narrows the window; never closes it | n × input hashing (measured: 39.4 ms for 100 MiB) | rejected — no guarantee for real cost |
| snapshot inputs per HIT | the cached bytes describe the snapshot, not the live workspace | copy of every input per HIT; changes the observable semantics | rejected — a product decision, not a race fix |
| immutable content-addressed inputs | safe **if** the workflow writes inputs through the store and never mutates them in place | workflow change; not compatible with arbitrary live workspaces | rejected for general use; documented as an operating mode for pipelines that already do this |
| kernel-verified immutable files (fs-verity) | detects modification of the verified file after enablement | requires a filesystem and kernel that support enabling verity, and a conversion step | not attempted: no kernel here can exercise the successful admission path, and Phase AD's promotion attempt already failed for this reason |
| cooperative `flock` protocol | writers that take the same lock cannot interleave | one lock per run; new failure mode for commands that lock the workspace themselves | rejected — cannot be advertised as a guarantee |
| isolated workspace generations (rename-based) | each HIT names an immutable generation | storage per generation; every writer must participate | rejected for the same reason as the lock |
| namespace freeze (mount namespace + read-only bind of inputs) | writers outside the namespace cannot change the input view during the run | privileges or a Landlock-capable kernel; not available unprivileged here and not implemented | the only complete userspace option; blocked by capability |

No generally sound **and** economical mitigation exists for arbitrary live workspaces in this
environment. That is a negative result, and it is preserved as one.

## 5. Operating assumptions for the research prerelease

TraceJIT may be described as *guarded reuse* under these explicit assumptions:

1. **Stable inputs during reuse.** No process outside TraceJIT writes the recorded inputs
   between the start of guard validation and the exposure of cached output. Reuse is safe for
   pipelines that produce an input and then consume it without concurrent mutation.
2. **No hostile local writer.** A local attacker who can write the workspace can win the
   residual race; TraceJIT does not defend against that adversary, and does not claim to.
3. **Single writer per output path.** Restoration is transactional per output, but two
   concurrent TraceJIT processes writing the same output are outside the contract.
4. **Refusal is the default under uncertainty.** `UNKNOWN`, `NONDETERMINISTIC` and failed
   enforcement never reuse; deoptimisation re-executes and the result is the native one.

What is claimed: every guard recorded from the traced execution passed at the moment it was
checked, and no cached byte reached the caller before that check. What is not claimed: that no
input changed after the check. The gap is bounded by the measured window above and must appear
in the release notes and the paper's limitations section.

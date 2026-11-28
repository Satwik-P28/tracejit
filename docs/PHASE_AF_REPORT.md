# Phase AF report — final research artifact and v0.3.0-alpha.1 qualification

Phase AF adds no reuse mechanism, no new effect class, and no new execution contract. It closes
the research programme: it qualifies what already exists, corrects claims that the evidence did
not support, and freezes the release, the paper and the reproduction package.

Base: `68ba406` (main). Work branch: `research/phase-af` from `b81242d`.

## 1. What the phase changed

| area | change |
| --- | --- |
| enforcement evidence | `benchmarks/phase_af/enforcement_lifecycle.py` drives the full lifecycle **on a capable host** (Landlock ABI 8 here), two arms, 11 assertions |
| enforcement tests | four new `tracejit-sandbox` tests: read/write separation, unexpected neighbour file, installation failure, capability mismatch |
| enforcement regressions | `linux_integration::a_producer_that_replaces_an_existing_output_is_not_promoted`; `enforced_execution_is_proven_reused_and_invalidated` now also asserts the plain-mode `classified PROVEN` line |
| reporting | the plain-mode reuse report prints `classified <class>`, which was previously shown only after a miss |
| tables | `benchmarks/phase_af/build_tables.py` emits eight publication tables from raw evidence; `test_tables.py` checks them |
| artifact scale | `benchmarks/results/phaseaf/artifact_scale.json` measured on a pinned 1 MiB / 10 MiB archive, not transcribed from prose |
| optimisations | `benchmarks/phase_af/optimisations.json` — accepted items cite the regression that protects them; rejected items cite why |
| documents | `docs/FINAL_CORRECTNESS_CONTRACT.md`, this report, the release qualification, the paper audit, the reproduction package |
| public docs | `README.md` rewritten; `SAFETY.md`, `SECURITY.md`, `docs/LIMITATIONS.md` reconciled with the contract |
| release | version `0.3.0-alpha.1`, packaged and installed from the archive |

## 2. Enforcement: what was proved, and where

The previous phase concluded that no Landlock-capable environment was reachable. That conclusion
was **wrong for this host**: a direct syscall probe returns ABI 8, so the lifecycle was qualified
locally instead of only in CI. Both are now recorded, and they are different kinds of evidence:

* **CI-hosted** (GitHub runner, kernel 7.0.0-1017-azure, glibc 2.39-0ubuntu8.12, Landlock ABI 8,
  seccomp and ptrace present): guarded reuse succeeded and a second enforced execution was
  classified `PROVEN`, in run `45573903708`. That probe stopped after two invocations, so CI did
  **not** demonstrate enforced reuse.
* **Local** (`enforcement_lifecycle.py`): read-only arm — GUARDED → `PROVEN` → **Reused `PROVEN`**
  → input mutation → deopt → `PROVEN` again. Producer arm — guarded reuse works, but `--enforce`
  stays `UNKNOWN`, because the command recreates its output under `O_EXCL`, which the policy does
  not model.

Neither is independent external reproduction. No third party has run this.

**`PROVEN` means the required policy was installed and the execution observed under it.** It is
not a proof of observational equivalence, and the paper and the contract both say so in those
words. The machine-readable label is unchanged for compatibility.

The producer case is the honest negative result: a gzip-style producer cannot reach `PROVEN`. A
parent-directory `REMOVE_FILE|MAKE_REG` grant was tried and reverted — it did not change the
outcome and widened the policy, so it was not worth keeping.

## 3. Claims corrected

| claim | correction |
| --- | --- |
| "95 ms is a lower bound on verified replay" | it is a serial sum of measured component costs (read, hash, copy, write), not a bound; the components can overlap and the input and compressed sizes differ |
| "10–15% advantage over Firebuild" | not supported by any interval this project computed; removed |
| Firebuild as a replay-engine baseline | Firebuild does not reuse this workload at all. The bzip2 comparison is an *applicability* comparison: TraceJIT 545.3 ms, native 2846.7 ms, Firebuild 0.8.6.2 3119.4 ms — 5.22× and 80.84% less cumulative execution time |
| break-even | four definitions now stated separately: first invocation count with equal cost, first with strictly positive saving, measured at sampled session lengths, and model-estimated |
| "no Landlock-capable environment existed" | false; see §2 |

## 4. Gates actually run

See `docs/RELEASE_QUALIFICATION_V03.md` for commands, commits and outputs. Summary: formatting,
clippy, workspace tests, Linux integration, sandbox policy tests, enforcement lifecycle, table
generation and its tests, version consistency, packaging, clean install, installer failure paths,
model state-machine check, and the soft-fail restore scenario all pass. Two items are explicitly
not claimed: differential fuzzing was not run here, and the hard-kill restore scenario skipped in
this configuration (its `RESULT` line says `SKIP`, and the property it targets is covered by
`interrupted_restore_intent_refuses_hit`).

The restore-fault harness was repaired during this phase. It previously scoped its fault hook to a
single invocation, but the inherited environment is part of the cache key, so the hooked run could
never hit and both scenarios passed without touching the restore path. It also kept its cache
inside the directory under test, so cache writes perturbed the observed listing. Both are fixed,
and the soft-fail scenario now proves it reached the restore path (it asserts the injected-failure
reason, which only exists inside `restore_outputs`).

## 5. What remains unresolved, by design

* The validation-to-restore race (`docs/TOCTOU_CORRECTNESS_BOUNDARY.md`) is real, reproducible, and
  not fixed. TraceJIT is not race-free.
* Producer-style commands cannot be enforced.
* Native compatibility is narrow: 28 of 162 attempted census commands reused, 0 incorrect.
* One performance host plus one CI host; no independent external reproduction.
* The packaged artifact was built from a dirty tree; a published artifact must be rebuilt from a
  clean, tagged tree.

## 6. Phase status

This is the final planned phase. There is no Phase AG, and none is proposed here: the remaining
items are limitations to disclose, not work to schedule.

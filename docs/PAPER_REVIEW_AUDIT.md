# Skeptical reviewer audit of the manuscript

Role: a reviewer for a systems venue, reading `paper/main.tex` as submitted. This file records
what such a reviewer would object to, which objections were fixed from existing evidence, and
which cannot be fixed without new experiments. It is deliberately harsher than the paper.

Title under review: **The Cost of Conservative Reuse: Correctness and Performance Trade-offs in
Automatic Command Caching**.

## 1. Summary judgement

The paper's contribution is a *measurement and boundary* paper: an automatic command cache that
refuses far more than it accepts, with an explicit correctness contract, a reproduced residual
race, and a competitive evaluation that includes its own losses. That is a legitimate contribution
and the negative results are the strongest part. The weak parts are external validity (one
performance host), the absence of independent reproduction, and the fact that the headline speedup
comes from a single workload family.

## 2. Objections found, and their disposition

| # | Reviewer objection | Disposition |
| --- | --- | --- |
| 1 | **Novelty is overstated.** "Automatic caching of arbitrary commands" is not new (Rattle, Firebuild, ccache, process memoization). | Fixed. The introduction and related work now state the delta as *conservative admission + an explicit contract + a measured boundary*, not as a new mechanism. |
| 2 | **The headline 5.22× is one workload.** | Disclosed. Reported as an applicability result for bzip2 -9 on a 25-invocation session, with Firebuild's non-reuse stated explicitly, and paired with the workloads where TraceJIT loses (hash-only, compiler). |
| 3 | **Firebuild comparison may be invalid.** Different engine semantics. | Fixed. The paper no longer calls it a replay-engine speed comparison. It reports three roles separately: Firebuild as an applicability baseline, ccache as a same-class baseline for compilers, and native as the reference. |
| 4 | **"Lower bound" on replay cost is unjustified.** | Fixed. The 95 ms figure is described as a serial sum of measured component costs, with the note that components can overlap and input/compressed sizes differ. |
| 5 | **`PROVEN` reads like a correctness proof.** | Fixed. Defined in the abstract, §4 and the contract as "the required policy was installed and the execution observed under it". The limitation is restated in the conclusion. |
| 6 | **The residual race is buried.** | Fixed. It is in the correctness section as a worked counterexample with the reproduction command, in the abstract, in the README safety block, and in SAFETY.md. |
| 7 | **Sample sizes and variance.** Paired runs, but how many, and what intervals? | Partly fixed. Per-invocation accounting and paired design are described with the number of invocations per cell, and the intervals recorded in `benchmarks/results/`. What is missing: a power analysis, and any cross-host variance estimate. Not fixable without a second host. |
| 8 | **Controlled vs native execution conflated.** | Fixed. §4 separates native and controlled execution, and RESULTS reports both the native-eligible count and the controlled-contract count, which is where the paper's honest small number lives. |
| 9 | **Only 28 of 162 commands reused — is the system useful?** | Kept as a finding, not excused. The paper reports 177 declared, 162 attempted, 28 reused, 0 incorrect, and explains the two dominant causes (allocator entropy, unmodelled descriptors). |
| 10 | **Break-even arithmetic.** | Fixed. Four definitions are stated and the tables label which one each row uses. |
| 11 | **Instrumentation inflates the measured interval.** | Disclosed. The Firebuild harness reads reuse decisions via `-s`, and that parsing is inside the timed interval; TraceJIT's decision reporting is likewise inside it. The paper says so instead of claiming a narrow percentage win. |
| 12 | **No independent reproduction.** | Cannot be fixed from inside the project. Stated in Limitations and in the artifact-availability section. |
| 13 | **Threats to validity from a single host.** | Disclosed. One 4-vCPU performance host plus one CI runner with a different kernel; no second performance platform. |
| 14 | **Corrupt-object and crash-recovery claims need fault-injection detail.** | Partly fixed. The paper cites the soft-fail and crash-recovery harnesses and says the hard-kill scenario was skipped in the final qualification run. |
| 15 | **Bibliography must be primary sources.** | Fixed. The draft entries that could not be verified were removed; every remaining entry is a primary paper, repository or specification that was checked. |
| 16 | **Reproducibility claim without a clean artifact.** | Fixed. The paper cites the packaged artifact and states that it was built from a dirty tree, so binaries are not claimed reproducible. |
| 17 | **Why is there no comparison at equal hit ratio?** | Acknowledged as a real gap. No experiment in this project equalizes hit ratio across engines, so the paper does not claim an efficiency advantage per hit. |
| 18 | **Statistical interpretation.** | Fixed where it mattered: no "significant" claims without an interval, and the 10–15% Firebuild margin was deleted because no interval supported it. |

## 3. Claims removed from the draft

* "TraceJIT eliminates redundant compilation work" — false for the compiler workloads, where
  ccache dominates.
* "Near-universal compatibility" — 28/162.
* "Race-free" / "atomic restore" — contradicted by the Phase AE counterexample and by the
  multi-output restore limitation.
* "10–15% faster than Firebuild" — no interval supported it.
* "95 ms is a lower bound" — replaced by a cost model statement.

## 4. Venue readiness

| venue class | verdict |
| --- | --- |
| student research symposium / undergraduate thesis | **ready.** Complete contract, reproducible artifacts, honest negative results. |
| workshop (e.g. a systems or reproducibility workshop) | **plausible.** The boundary/negative-results framing fits a workshop's appetite for "what did not work", provided the paper leads with the contract and the measured refusals rather than the 5.22×. |
| full systems conference | **not ready.** Blockers: a single performance host; no independent reproduction; the competitive matrix mixes engine classes without an equal-hit-ratio control; the reuse rate is low enough that the practical claim is narrow; and the enforcement qualification, while real, is not externally replicated. |

The honest fix for the conference case is a second performance platform, an equal-hit-ratio
experiment, and a third-party reproduction — none of which this phase can supply, and none of
which should be faked.

## 5. What a reviewer should be told to check first

1. `docs/FINAL_CORRECTNESS_CONTRACT.md` — every invariant's stated assumption.
2. `benchmarks/results/phaseae/toctou_race.json` — the counterexample, reproducible with
   `python3 benchmarks/phase_ae/toctou_race.py`.
3. `paper/tables/*.tex` against `benchmarks/results/` — the tables are generated, so any
   transcription error would be a generator bug, and `build_tables.py --check` fails on
   inconsistency.
4. `benchmarks/phase_af/enforcement_lifecycle.py` — the two arms, including the producer arm that
   never reaches `PROVEN`.

# Phase Q — quantum-inspired dependency optimisation: measured results and decision

**Decision: reject.** No quantum-inspired or metaheuristic method is eligible for
production. Guard ordering is a sort (`O(n log n)`, provably optimal for independent
guards), candidate ordering at the V1 cap is exact enumeration of 40 320 orders, and
every evaluated metaheuristic returns the same plan at 300–11 000× the decision cost of
the greedy rule. The largest real opportunity found is not an optimisation algorithm at
all: it is the candidate scan at high retention, where a learned ordering already exists
and needs no solver.

All numbers below are produced by `tjq_experiments.py` and stored in
`results/measurements.json`; the full run takes ≈56 s. Objective values are deterministic
for the fixed seed; decision-time figures vary by a few percent between runs. Product
crates are untouched.

---

## 1. Problem size: is annealing even justified?

Measured from committed Phase 3C artifacts (`benchmarks/results/phase3c/`):

| Quantity | Value | Source |
| --- | --- | --- |
| Guards per measured guarded command | **33** | `latency.json`, stable rows |
| Adjacency blocks (metadata+hash pairs) | **28** | `compile_guards` inventory |
| Correlated groups needing enumeration | **5** | guard inventory |
| Retained candidates per identity (V1 cap) | **8** | Phase 3A |
| Guard validation, measured median | **5.945 ms** | `latency.json` |
| Warm-HIT wall, measured median | **31.57 ms** | `latency.json` |
| Deoptimised (guard-failure) wall, measured median | **245.70 ms** | `latency.json` |
| Cold trace wall, measured median | **266.31 ms** | `latency.json` |
| Candidate validation cost, fitted | **1.133 ms/candidate**, R² = 0.991 | `candidate-scaling.json` |

Ordering search spaces: `28! ≈ 3.05e29` for guard blocks, `8! = 40 320` for candidates
at the cap, and `2^28 = 268 435 456` DP states (`28·2^28 = 7.52e9` transitions) if one
tried exact dynamic programming. The measured objective is a 33-item sorting problem
with five latent binary factors — **not** a large combinatorial instance. That alone is
grounds to expect annealing to lose, and the experiments confirm it.

## 2. What the objective actually rewards

`E[cost(π)] = Σ_k c_{π_k} · P(all earlier guards pass)`.

A **passing** run validates every guard, so every permutation costs the same. Ordering
can only reduce work on runs that **fail**. The measured deopt row records
`checked: 30, passed: 29`: production paid 29 of 30 guard validations before detecting
the change, i.e. **96.7 %** of the guard budget. With the ratio rule the failing
metadata guard is validated first, so the same rejection costs ~0.03 ms. The measured
upper bound is:

```
5.945 ms × 29/30 = 5.747 ms  →  5.720 ms saved per failed candidate
          = 2.33 % of the 245.70 ms deopt wall
          = 0.00 % of a successful hit
```

That is the entire prize. Everything below is judged against it.

## 3. E1 — greedy is exact for independent guards

870 random instances, n = 4…16, 0 suboptimal plans within a 1e-12 relative tolerance;
25 n = 6 instances cross-checked against brute-force enumeration of all 720 orders with
0 disagreements between the exact DP and the brute force. This reproduces
Boothroyd/Mitten (see `RELATED_WORK.md`); it is confirmation, not a new result.

Building this test found two real modelling bugs that now have regression tests: the
survival product must exclude the failing guard itself, and an adjacency block's cost
must be its *expected* internal cost, not the sum of its guards (a metadata failure
means the content hash is never paid).

## 4. E2 — the measured 33-guard workload

| Plan | Asset changed (ms) | Stable (ms) | Decision cost (ms) |
| --- | ---: | ---: | ---: |
| Current production order | 3.248 | 5.800 | 0 |
| **Ratio-greedy (sort)** | **0.027** | **5.606** | **0.078** |
| Local search | 0.027 | 5.606 | 8.29 |
| Simulated annealing | 0.027 | — | 736.5 |
| Tabu search | 0.027 | — | 5 510.4 |
| Parallel tempering | 0.027 | — | 12 984.3 |

- Greedy saves **3.220 ms** on the modelled change scenario and **5.720 ms** on the
  measured shape (2.33 % of the deopt wall).
- SA, tabu and PT add **0.000 ms** over the sort and cost 0.74–13.0 s to decide.
- In the stable instance greedy is 0.194 ms lower, but that difference comes entirely
  from the modelled 1e-4 per-guard spurious failure rate. On a true all-pass hit the
  cost is identical for every order: **ordering cannot help a successful warm hit**.
- Our reconstruction places the failing asset at guard 15/33; the recorded order placed
  it at 30/30. The measured-shape number above is the empirical anchor; the model is the
  conservative one.

## 5. E3 — correlated invalidation and shared dependencies

12 instances, 16 blocks, 8 groups, exact expectation over `2^8` latent states.

| Solver | Mean gap vs best found | Max gap | Extra cost vs greedy (ms) | Runtime (ms) | Speedup needed to break even |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current production order | 31.87 % | 67.93 % | +0.487 | 0 | — |
| **Ratio-greedy** | **2.34 %** | 7.27 % | 0 | 0.096 | — |
| Local search | 0.0016 % | 0.019 % | −0.0362 | 11.3 | **313×** |
| Simulated annealing | 0.0054 % | 0.010 % | −0.0362 | 235.9 | 6 524× |
| Tabu search | 0.0000 % | 0.000 % | −0.0363 | 202.9 | 5 595× |
| Parallel tempering | 0.0086 % | 0.019 % | −0.0361 | 402.8 | 11 163× |
| Branch and bound (20k node cap) | 1.30 % | 3.76 % | −0.0166 | 819.4 | 49 337× |

Correlation is the only regime where the greedy rule leaves anything on the table, and
what it leaves is **0.036 ms per plan**. Local search recovers it; SA and PT recover the
same amount and consume 20–36× more time. To be net-positive, an implementation would
have to be ~313× faster than this Python local search — a Rust port is plausibly in that
range only if it also gave up the exact objective evaluation, and the gain is still
0.036 ms against a 5.9 ms guard budget. Branch and bound was **not exact** on any
instance at the node cap; it is reported only as a baseline and is worse than local
search.

## 6. E4 — candidate ordering: the real opportunity, still not annealing

Measured candidate behaviour (`candidate-scaling.json`): newest candidate is validated
first at ~12–14 ms wall; the oldest/“target” candidate sits at depth `m` and costs
`8.52 + 1.133·m` ms (R² = 0.991).

| Retention | Newest-first model (ms) | Optimal-order model (ms) | Probability-weighted saving (ms) | Measured gap: deepest − newest (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.133 | 1.133 | 0.000 | −5.185 (noise) |
| 2 | 1.649 | 1.649 | 0.000 | −0.377 (noise) |
| 4 | 2.749 | 2.322 | 0.427 | 3.278 |
| **8 (V1 cap)** | 4.368 | 3.945 | **0.423** | **8.784** |
| 16 | 8.325 | 7.929 | 0.396 | 12.768 |
| 32 | 17.730 | 17.398 | 0.332 | 28.816 |
| 64 | 38.767 | 38.526 | 0.241 | 67.690 |

- The `measured_gap` column is the maximum possible prize if the matching candidate were
  always first: **8.78 ms at the V1 cap**, 67.69 ms at 64 retained candidates.
- Exact enumeration of all 40 320 orders at the cap takes 81 ms once and returns
  **exactly the greedy order's cost** (3.9446 ms), confirming the sort is optimal at
  `m = 8`.
- A count-based learner on 2 000 training invocations reduces held-out validations from
  **2.843 to 2.142** and captures **0.795 ms** of the measured gap (0.423 ms in expected
  cost), with a **0.0027 ms** decision cost. It equals the exact optimum on the held-out
  stream.

So the candidate scan is worth optimising, but the correct mechanism is a deterministic
learned order (or an index), not a solver. SA/PT were not run on candidate ordering
because the plan space is `8!` and enumerable; any annealer would be strictly dominated
by the 0.003 ms sort that is already exact.

## 7. E5 — QUBO knapsack (offline admission planning)

12 identities, budget 1 015 ms of cold-trace work, 19 QUBO variables, penalty scaled to
a 65-unit max coefficient. Greedy benefit/cost ratio equals the exact DP optimum on this
instance (4 102.08), so the instance is easy; the point is the solver behaviour.

| Solver | Value | Feasible | Runtime |
| --- | ---: | :---: | ---: |
| Exact DP | 4 102.08 | yes | <0.01 ms |
| Greedy ratio | 4 102.08 | yes | <0.01 ms |
| QUBO SA | 4 102.08 | yes | 71.8 ms |
| QUBO tabu | 4 102.08 | yes | 4 200.6 ms |
| QUBO SQA (path integral) | 4 102.08 | yes | 1 687.1 ms |

Penalty-conditioning sweep — a hard budget enforced by a soft penalty is not hard:

| Penalty × | Max coefficient | SA feasible | SA value | SQA feasible | SQA value |
| ---: | ---: | :---: | ---: | :---: | ---: |
| 1 | 65 | yes | 4 102.08 | yes | 4 102.08 |
| 10 | 650 | **no** | 3 894.43 | **no** | 3 894.43 |
| 100 | 6 496 | yes | 4 102.08 | yes | **3 669.15** |

No single coefficient setting gave both samplers a feasible *and* optimal answer. The
feasibility of a hard constraint was decided by penalty scaling and sampler temperature,
not by the model. That is disqualifying for a plan whose feasibility is a correctness
obligation.

## 8. E6 — parallel guard batching as a QUBO partition

28 blocks over 4 workers, serial guard work 5.945 ms.

| Solver | Makespan (ms) | Gap vs lower bound | Runtime (ms) |
| --- | ---: | ---: | ---: |
| LPT | **2.041** | **0.00 %** | <0.01 |
| QUBO tabu | 2.041 | 0.00 % | 843.4 |
| QUBO SA | 2.092 | 2.51 % | 34.6 |
| QUBO SQA | 2.113 | 3.54 % | 2 929.1 |

The lower bound is `max(largest block, serial/4) = max(2.041, 1.486) = 2.041 ms`, and
LPT attains it exactly, so **LPT is optimal on this instance**. The maximum possible
parallel saving is 4.46 ms (5.945 → 2.041), while the cheapest QUBO arm costs 34 ms to
decide — a 7.7× net loss before any safety analysis. Note also that 32/33 guards are
“parallelisable” only in the model; the metadata/content pairs share a descriptor and
the inherited-stream guard mutates shared offset state, so this is an upper bound on a
plan that has not been shown safe.

## 9. E7 — counterexample-guided refinement with held-out splits

6 epochs of nonstationary drift, 12 training and 12 held-out identities; only the
training split updates estimates.

| Arm | Mean held-out cost (ms) |
| --- | ---: |
| Static prior (0.05 everywhere) | **0.9105** |
| Online cumulative Beta counts | 0.9233 (+1.4 %) |
| Online EWMA counts (decay 0.85) | 0.9414 (+3.4 %) |
| Oracle true probabilities | 0.8331 (−8.5 %) |

Counterexample-guided refinement **did not improve** future plans in this setup: both
estimators were worse than a flat prior. With drift, cumulative counts are stale, and
EWMA is noisy at 6 observations per epoch per guard. The oracle gap (8.5 %) shows the
plans are not already perfect, so this is a genuine negative result about the estimator,
not a ceiling. Any future attempt needs per-identity sufficient statistics and a
change-point model, not a global failure counter.

## 10. E8 — admission planning on the recorded Phase K9 matrix

Recorded by the product harness (`phase_k9/admission-eval.json`), not re-run here:
oracle 575.0 ms; production `CurrentAuto` 624.0 ms, regret **49.0 ms** over 34 steps.
An online planner cannot beat a clairvoyant oracle, so its total possible improvement is
bounded by **1.441 ms/step**. The recorded comparison already shows that EWMA,
threshold, confidence-bound and always/never policies are worse than `CurrentAuto`, and
that the confidence bound only ties. Phase Q adds no reason to revisit that decision.

## 11. E9 — session accounting including decision cost

1000 invocations, measured hit wall 31.57 ms, deopt wall 245.70 ms, 5.720 ms saved per
detected failure.

| Deopt rate | Session wall (ms) | Gross saving (ms) | % of wall | Net after per-run sort (ms) | Net after per-run local search (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 % | 31 574.5 | 0.0 | 0.000 | −77.9 | −11 105.8 |
| 1 % | 33 715.7 | 57.2 | 0.170 | −20.7 | −11 048.6 |
| 5 % | 42 280.6 | 286.0 | 0.676 | +208.1 | −10 819.8 |
| 20 % | 74 399.1 | 1 144.0 | 1.538 | +1 066.1 | −9 961.9 |

Re-sorting on every run needs a **1.35 %** deopt rate just to break even; local search
never breaks even at any rate. In production a plan can be compiled once and stored with
the trace, which makes decision cost negligible — but that also removes the need for any
solver at all, since the plan is a sort computed once.

## 12. Correctness and verification

- 93 guard-order plans and 14 candidate-order plans passed the independent structural
  verifier; **0 violations**. The verifier rejects non-permutations, split
  metadata/content pairs, reordered order-dependent guards, and any claimed cost that
  does not recompute.
- 19 self-tests pass, including brute-force agreement for the independent objective, DP
  vs brute force, QUBO energy vs direct evaluation, and verifier rejection cases.
- No plan can skip a guard: `validate_all` still runs over the full guard list before
  any cached byte is exposed, and the ratio rule is only a permutation of that list.

## 13. Accepted and rejected hypotheses

| Hypothesis | Outcome | Evidence |
| --- | --- | --- |
| The ordering problem is large enough to justify annealing | **Rejected** | 28 blocks, 5 correlated groups, `O(n log n)` exact for independent guards (E1) |
| Greedy cost/failure ordering is optimal for independent guards | **Confirmed** (classical, reproduced) | 870 instances, 0 suboptimal (E1) |
| Correlation makes greedy materially suboptimal | **Confirmed but small** | 2.34 % mean gap, 0.036 ms/plan (E3) |
| Local search beats greedy on correlated instances | **Confirmed** | recovers 0.036 ms at 11 ms decision cost (E3) |
| SA / tabu / PT beat local search | **Rejected** | same optimum, 20–36× slower (E3) |
| SQA (path integral) provides an advantage | **Rejected** | equal or worse objective, 1 678–2 943 ms per plan (E5, E6) |
| QUBO can express the ordering objective compactly | **Rejected** | degree-`n` product; no compact QUBO (FORMULATION §5) |
| Penalty QUBO reliably enforces the hard budget | **Rejected** | feasibility flips with penalty scale and sampler (E5) |
| Parallel batching is worth solving | **Rejected for V1** | LPT is optimal at the lower bound; QUBO decision cost is 7.7× the max saving; safety unproven (E6) |
| Counterexample-guided refinement improves plans | **Rejected** | both online arms worse than a static prior on held-out identities (E7) |
| Re-planning every run is cheap | **Rejected** | needs 1.35 % deopt rate to break even (E9) |
| Candidate ordering has a real, measurable prize | **Confirmed** | 8.78 ms at the cap (measured), 67.69 ms at 64 (E4) |
| The prize needs a solver | **Rejected** | `8!` enumeration is exact in 80 ms once; a 0.003 ms sort is exact; a count learner captures it (E4) |
| Admission policy should change | **Rejected** | recorded `CurrentAuto` remains best; oracle gap 1.44 ms/step (E8) |

## 14. Threats to validity

1. **The 33-guard instance is reconstructed** from measured totals and the
   `compile_guards` inventory; per-guard costs are allocated by kind and scaled so the
   total equals the measured `guard_validation_ns`. The failing-guard position differs
   (15/33 modelled vs 30/30 measured); both are reported and the measured anchor is used
   for the headline saving.
2. **Python solver timings** are not production timings. The break-even speedup column
   is the honest way to read them: it says how much faster an implementation would have
   to be before its decision cost paid for itself. It does not assume a language.
3. **Failure probabilities are modelled**, not measured, because the repository records
   guard *counts* and rejection positions, not per-guard failure rates. The E7 negative
   result is specifically about estimating those rates.
4. **No QPU.** Hardware queueing/embedding costs are not measured; they are argued to be
   larger than the 4.46 ms maximum prize, which is a bound, not a measurement.
5. **E5's knapsack instance is easy** (greedy = exact). The conclusion is about solver
   reliability and overhead, not about knapsack hardness.

## 15. Production decision

- Keep the existing guard order. Optionally adopt the ratio order as a **stored plan**
  computed once at trace time (`O(n log n)`, 0.08 ms), gated behind the verifier and a
  new test that the plan is a permutation preserving pair adjacency and stream order.
  Expected benefit: 2.33 % of deopt wall, 0 % of hits. This is a small, honest win that
  does not need Phase Q's machinery — but it is **not merged here**, because the
  measured-shape reconstruction is modelled and a production change should be gated on a
  native benchmark of the real workload.
- Do **not** add annealing, tabu, tempering, SQA, QUBO selection, or parallel guard
  batching. Each either loses on decision cost, violates hard feasibility, or has
  unproven safety for shared-descriptor guards.
- The candidate-scan opportunity is worth a separate, non-quantum phase: measure the
  depth distribution of the matching candidate on real sessions, then either store the
  match index or learn a per-identity order. This is where the milliseconds are.

## 16. Reproduction

```bash
cd research/phase_q
python3 -m venv --system-site-packages .venv
.venv/bin/pip install dwave-samplers dimod   # Apache-2.0, isolated from the crates
.venv/bin/python tjq_selftest.py             # 19 tests, must pass
.venv/bin/python tjq_experiments.py          # ~56 s; writes results/
```

Files: `tjq_anchors.py` (reads committed measurements), `tjq_model.py` (objective and
instance families), `tjq_solvers.py` (greedy, exact DP, SA, tabu, PT, QUBO, LPT),
`tjq_verify.py` (independent verifier), `tjq_experiments.py` (E1–E9),
`tjq_selftest.py`, `FORMULATION.md`, `RELATED_WORK.md`, `PAPER_DRAFT.md`.

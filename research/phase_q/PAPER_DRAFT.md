# Ordering is not the hard part: measured negative results for quantum-inspired dependency-validation scheduling

*Draft — internal. Numbers are from `results/measurements.json` at the commit that
contains this file.*

## Abstract

Build caches that infer an unmodified process's dependencies must validate a guard set
before exposing any cached byte. It is tempting to treat the order of that validation,
or the choice of retained candidate to validate first, as a combinatorial optimisation
problem and to apply annealing, QUBO solvers, or quantum-inspired heuristics. We
measure the real instance in one such system (TraceJIT) and test that temptation
directly. The guard-ordering objective is the classical least-cost fault-detection
problem: with independent guards, sorting by `cost / failure-probability` is optimal,
and we confirm it on 870 random instances with zero suboptimal plans. At the system's
measured size (33 guards, 28 adjacency blocks, 5 correlated groups) the only
correlation-aware gain left on the table is 2.3 % of the guard budget, or 0.036 ms per
plan. Simulated annealing, tabu search, parallel tempering, branch and bound, and
path-integral simulated quantum annealing all return the same or worse plans at
300–11 000× the decision cost of the greedy rule. Two genuinely quadratic sub-problems
(budgeted candidate selection, guard batching) are small enough for exact or LPT
solutions; the QUBO arms either lose on runtime or return budget-infeasible samples,
with feasibility decided by penalty scale rather than by the model. The largest real
opportunity is the candidate scan at high retention (8.8 ms at the V1 cap, 67.7 ms at
64 candidates), and it is captured by a 0.003 ms learned sort, not by a solver. We
report the negative result and the measurement protocol so that similar systems can
avoid paying solver costs for a sorting problem.

## 1. Prior art (not claimed as new)

- The `c_i / p_i` ordering rule and its interchange proof: Johnson (1956),
  Boothroyd (1960), Mitten (1960), Kadane (1969).
- NP-hardness with arbitrary precedence, and exact branch-and-bound for the constrained
  case: Creemers, De Moor & Leus, *EJOR* 2019.
- The same ratio rule rediscovered for filter ordering in ranking/fraud pipelines
  (arXiv 2606.07589, 2026).
- Simulated annealing (Kirkpatrick et al. 1983), parallel tempering
  (Swendsen–Wang 1986; Hukushima–Nemoto 1996), path-integral SQA
  (Kadowaki–Nishimori 1998), QUBO/Ising formulations (D-Wave documentation).

Nothing in Sections 3–5 is a new algorithm. The contribution is the measured instance,
the decision-cost accounting, and the falsification record.

## 2. This work's contributions

1. **A measured instance, not a synthetic one.** Guard counts, guard-validation time,
   candidate-validation cost per retained record (linear fit, R² = 0.991), hit/deopt
   walls, and the observed rejection position (29 of 30 guards paid before a failure)
   are extracted from committed benchmark artifacts of a real system.
2. **An objective that models adjacency blocks correctly.** `validate_all` shares a
   descriptor across a metadata/content pair, so a block's cost is its *expected*
   internal cost, not the sum of its guards. Using the sum produces a provably wrong
   optimum; we show the difference and pin it with a regression test.
3. **Decision-cost accounting that survives implementation language.** For each
   metaheuristic we report `runtime / realised saving` as the speedup it would need to
   break even. SA needs 6 430×, PT 11 023×, local search 307×.
4. **A hard-constraint feasibility result for penalty QUBOs.** On a 19-variable
   budgeted-selection QUBO, no single penalty scale made both SA and SQA return a
   feasible *and* optimal sample; at ×10 both violated the budget, at ×100 SQA was
   feasible but 10.6 % suboptimal. A correctness obligation cannot be delegated to a
   penalty coefficient.
5. **A negative result for counterexample-guided refinement.** With train/test identity
   splits and nonstationary drift, cumulative and EWMA failure-rate estimators were
   worse than a flat prior on held-out identities (+1.4 % and +3.4 %), while an oracle
   with true rates was 8.5 % better. The estimator, not the plan space, is the
   bottleneck.

## 3. Setup

Guards `g_i` with cost `c_i` and failure probability `p_i`, validation stopping at the
first failure:

```
E[cost(π)] = Σ_k c_{π_k} Π_{j<k} (1 − p_{π_j})
```

Correlated invalidation is a latent group state `Z ∈ {0,1}^G`; the expectation is exact
by enumerating `Z` (32 states for the measured set). Hard constraints: block adjacency,
order-dependent stream guards, permutation validity, cost recomputation by an
independent verifier.

Instances: 33-guard measured reconstruction; 870 random independent instances;
12 correlated 16-block/8-group instances; 7 candidate-retention bounds from 1 to 64;
a 12-identity knapsack; a 28-block/4-worker partition; 24 identities × 6 drift epochs.

## 4. Results

| Experiment | Result |
| --- | --- |
| Greedy vs exact DP, independent | 870/870 optimal (≤1e-12); 25/25 brute-force cross-checks agree |
| Measured guard set, change scenario | 3.248 → 0.027 ms modelled; 5.747 → 0.027 ms on the measured 29/30 shape (2.33 % of deopt wall) |
| Correlated guards | greedy 2.34 % above best; local search 0.0016 % at 11 ms; SA 0.005 % at 232 ms; no method beats local search |
| Candidate ordering at cap | 40 320 orders enumerated: exact == greedy; learned order 2.843 → 2.142 validations, 0.795 ms |
| Knapsack QUBO | DP = greedy = 4 102.08; SA 72 ms, SQA 1 678 ms, tabu 4 201 ms; infeasible samples under two penalty scales |
| Partition QUBO | LPT attains the lower bound 2.041 ms; SA +2.5 %, SQA +3.5 %, tabu ties at 844 ms |
| CEGAR | static prior 0.9105 ms, cumulative 0.9233, EWMA 0.9414, oracle 0.8331 |
| Session accounting | per-run sort breaks even at 1.36 % deopt rate; savings ≤1.54 % of session wall |

## 5. Limitations

- Per-guard costs and failure probabilities are reconstructed/ modelled from aggregate
  measurements; the measured rejection position is used as the empirical anchor.
- Solver timings are Python; the break-even multiplier is the language-independent
  statement.
- No QPU was available. Hardware queueing and embedding are argued to exceed the 4.46 ms
  maximum prize, but that is a bound, not a measurement.
- The knapsack instance is easy (greedy = exact); the QUBO conclusion is about
  reliability and overhead, not knapsack hardness.

## 6. Conclusion

For dependency-validation scheduling at this scale, the correct engineering answer is a
sort plus a small exact enumeration, not an annealer. We recommend that systems in this
family measure their own guard and candidate distributions before adopting
quantum-inspired optimisation, and that they report decision cost alongside any solution
quality claim.

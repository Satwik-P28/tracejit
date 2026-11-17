# Related work, prior art, licensing

## The ordering problem is classical, and solved

Ordering independent tests to minimise expected cost is the **least-cost fault-detection
problem** (LCFDP) / sequential testing problem, introduced by Johnson (1956) in an Air
Force reliability context. The ascending `cost / failure-probability` rule and its
interchange proof appear independently in:

- **Boothroyd (1960)** — series systems; the `c_i / p_i` order.
- **Mitten (1960)** — same rule, with the proof by adjacent interchange.
- **Kadane (1969)** — quiz-show / sequential selection variant.
- **Derman, Lieberman & Ross** — sequential stochastic assignment; same interchange
  structure.

Modern treatments that state the result and its limits:

- S. Creemers, B. De Moor, R. Leus, "Sequential testing of n-out-of-n systems:
  precedence theorems and exact methods", *EJOR* 274(3), 2019.
  https://doi.org/10.1016/j.ejor.2018.10.036 — polynomial without precedence, NP-hard
  with arbitrary precedence; exact branch-and-bound for the constrained case.
- "Time-critical testing and search problems", *EJOR* 2022.
  https://www.sciencedirect.com/science/article/abs/pii/S0377221721002642
- Sequential testing of complex systems: a review (2004).
  http://www.cs.umd.edu/projects/reucaar/surveyeval.pdf
- "Optimality of Sequential Filtering Under Independent Cost and Selectivity Models"
  (2026). https://arxiv.org/html/2606.07589v1 — the same ratio rule rediscovered for
  filter ordering in ranking and fraud pipelines, with Monte Carlo evidence that the
  optimal order dominates heuristics.

**Consequence for Phase Q:** for independent guards the optimum is a sort. Adding
annealing, tabu search, or a QUBO cannot improve on it; it can only add decision cost.
Our E1 result reproduces the theorem numerically (870 random instances, 0 suboptimal
plans) rather than claiming it as new.

## Correlation and precedence

When shared dependencies introduce precedence or correlated failures, LCFDP becomes a
scheduling problem with precedence constraints, which is NP-hard. The exact methods in
Creemers et al. are branch-and-bound with dominance rules, not annealing. Our E3
instance has 16 blocks and 8 correlated groups, and a best-improvement local search from
the ratio order reaches the best value found by any method; SA/tabu/PT match it at
20–40× the runtime.

## Annealing, tempering, and QUBO tooling

- Kirkpatrick, Gelatt & Vecchi (1983), "Optimization by Simulated Annealing", *Science*.
- Černý (1985) — SA for the travelling salesman.
- Swendsen & Wang (1986) — replica Monte Carlo; Hukushima & Nemoto (1996) — exchange
  Monte Carlo / parallel tempering.
- Glover (1989) — tabu search.
- Kadowaki & Nishimori (1998) — simulated quantum annealing via path-integral Monte
  Carlo; the `PathIntegralAnnealingSampler` in `dwave-samplers` implements this.
- D-Wave binary quadratic model documentation (QUBO/Ising definitions, penalty
  formulation, minor embedding):
  https://docs.dwavequantum.com/en/latest/concepts/models.html

## Libraries and licensing (all permissive)

| Library | Version installed | License | Used for |
| --- | --- | --- | --- |
| `dimod` | 0.12.23 | Apache-2.0 | BQM construction/decoding |
| `dwave-samplers` | 1.8.0 | Apache-2.0 | SA, tabu, path-integral (SQA) |
| `dwave-ocean-sdk` | not installed | Apache-2.0 | would wrap the samplers + Leap client |
| `numpy` | 2.5.2 | BSD-3-Clause | model evaluation |
| `networkx` | 3.7 (transitive) | BSD-3-Clause | dependency of `dwave-samplers` |

License confirmation: https://docs.dwavequantum.com/en/latest/licenses.html and
https://github.com/dwavesystems/dwave-ocean-sdk (Apache-2.0).

No GPL/AGPL dependency is introduced. Nothing here is added to `Cargo.toml`; the
production crates are untouched. D-Wave Ocean is installed only in
`research/phase_q/.venv`, which is git-ignored.

## Quantum hardware

No QPU was available in this environment, and no numbers from hardware are claimed.
For completeness, a hardware benchmark would have to add, per plan: QUBO construction,
minor embedding (graph-dependent, can fail for dense instances), Leap queue time
(typically far larger than the millisecond-scale problem), readout and post-processing,
and verification of the returned sample against the hard constraints. The candidate
problems here are 19 and 112 variables; the measured value of the best exact/classical
solution is at most 4.46 ms of guard work (E6), which is smaller than the queueing and
embedding overhead alone. We therefore did not attempt hardware access, and report this
as a limitation rather than a result.

## Methods considered and why they do not fit

| Method | Fit to TraceJIT | Reason |
| --- | --- | --- |
| QUBO / Ising | only for selection/partition sub-problems | ordering objective has degree `n` in position indicators |
| Quantum annealing | no | no compact QUBO; hardware overhead ≫ 4.46 ms of possible gain |
| Simulated quantum annealing | evaluated (E5, E6) | no gain over SA/tabu; penalty feasibility failures |
| Simulated annealing | evaluated (E2, E3, E5, E6) | matches local search at 20–40× runtime; never beats greedy |
| Parallel tempering | evaluated (E2, E3) | same optimum as SA, highest runtime |
| Tabu search | evaluated | reaches the same optima; 20× local search runtime |
| Branch and bound | evaluated (E3) | exact only with dominance rules; truncated at 20k nodes it is worse than local search |
| Dynamic programming | exact reference (E1) | `O(n·2^n)`; 7.5e9 transitions at 28 blocks, unusable; the sort is already exact |
| Mixed-integer programming | not implemented | the independent case is a sort; the constrained case has no solver dependency justified at this size |
| Constraint programming | not implemented | constraints are two adjacency/order rules, checked directly |
| Bayesian optimisation | not implemented | no continuous/small-budget parameter to tune; plans are discrete and exact |
| Contextual bandits | not implemented | Phase K9 already rejected bandit admission; candidate ordering has an exact/learned deterministic solution (E4) |
| Submodular optimisation | not applicable | stopping-at-first-failure objective is not submodular in the chosen set |
| Graph partitioning | evaluated as batching surrogate (E6) | LPT hits the lower bound; surrogate adds no value |
| Spectral / flow methods | not applicable | no cut objective in the problem |

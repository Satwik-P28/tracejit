# Phase Q — mathematical formulation

Everything here describes the *order* in which the same guards are validated, or the
*order* in which retained candidates are tried. No formulation permits skipping a
guard, dropping a guard, merging two guards, or reusing a record whose guard set did
not fully pass. Correctness is a constraint on the plan space, not a term in the
objective.

## 1. Guard ordering with independent failures

A traced execution stores guards `g_1 … g_n` with validation costs `c_i > 0` and
failure probabilities `p_i ∈ (0,1)`. Validation stops at the first failure; every guard
must pass before any cached byte is exposed. For a permutation `π`:

```
E[cost(π)] = Σ_{k=1..n}  c_{π_k} · Π_{j<k} (1 − p_{π_j})
```

with `q_i = 1 − p_i`. This is the least-cost fault-detection problem (LCFDP).

**Interchange.** Compare adjacent `i, j`; the common prefix and the common suffix
survival factor cancel, so

```
i before j  ⇔  c_i + q_i c_j ≤ c_j + q_j c_i  ⇔  c_i / p_i ≤ c_j / p_j
```

The relation is a total preorder, so sorting by ascending `c_i / p_i` is optimal for
independent guards — Boothroyd (1960), Mitten (1960), Kadane (1969). The optimum is
computed in `O(n log n)`; no search is required.

**Cost per item is the expected internal cost, not the sum.** TraceJIT validates a
`FileMetadata` guard immediately followed by its `FileHash` guard from one shared file
descriptor. The pair is atomic (`validate_all` relies on the adjacency), but if the
metadata guard fails the content hash is never paid. The correct item cost is therefore

```
c_block = Σ_{i in block} c_i · Π_{j<i, j in block} q_j
```

not `Σ c_i`. Treating the block as its raw sum overestimates the cost of cheap,
failure-prone guards and produces a provably wrong optimum. The harness models both
and the tests pin the difference (`test_measured_instance_shape`,
`test_greedy_matches_exact_dp_on_random_independent_sets`).

## 2. Correlated invalidation and shared dependencies

Guards of the same file are not independent: a changed file invalidates its metadata
guard *and* its content guard, and usually several derived guards. Model latent group
state `Z_g ∈ {0,1}` with `P(Z_g = 1) = ρ_g`, independent across groups. Guard `i`
belongs to group `γ(i)`:

```
P(guard i passes | Z) = 0                 if Z_{γ(i)} = 1
                      = 1 − β_i           otherwise (spurious failure)
```

The exact expectation is a sum over latent states:

```
E[cost(π)] = Σ_{Z ∈ {0,1}^G} P(Z) · Σ_k c_{π_k} · Π_{j<k} P(pass_{π_j} | Z)
```

Only groups with more than one guard need enumeration; a singleton group touches one
guard and enters through its marginal. Let `S = 2^{|G_multi|}`. Then evaluation is
`O(S·n)` and for the measured 33-guard set `|G_multi| = 5`, so `S = 32`. This is exact,
not a sample average.

The greedy rule is no longer optimal once `Z` couples guards, because the marginal
`p_i = 1 − (1−ρ_{γ(i)})(1−β_i)` discards the fact that one failure event removes several
guards at once. With precedence constraints the problem is NP-hard in general
(Creemers et al., EJOR 2019); without precedence it stays polynomial. TraceJIT's
correlation structure is a small number of file-shaped groups, not an arbitrary
precedence DAG, so the practical instance stays small (`|G_multi| ≤ 5`).

## 3. Candidate ordering

`find_candidates` returns at most eight records per identity, newest first, because the
lookup key deliberately excludes file contents. Candidate `k` has validation cost
`v_k` and match probability `a_k` (probability that its guards accept the current
input state). Exactly one candidate can match in the common case.

```
E[cost(π)] = Σ_k v_k · Π_{j<k} (1 − a_j)
```

All candidates of one identity have the same guard structure and therefore the same
`v_k`. The optimal order is descending `a_k`; production's newest-first order is optimal
only when recency equals match probability. At the V1 cap `m = 8`, all `8! = 40 320`
orders can be enumerated exactly in microseconds, so no heuristic is needed even in the
correlated case.

## 4. Hard constraints (checked by the independent verifier)

1. `π` is a permutation of the guard indices: nothing added, dropped, or duplicated.
2. A `FileMetadata`/`FileHash` pair with the same path stays adjacent and in recorded
   order; `validate_all` shares one descriptor across it and the Strict-mode fallback
   depends on the pairing.
3. Order-dependent guards (`InheritedStream`) keep their recorded relative order:
   `apply_inherited_stream_offsets` applies `lseek` calls in plan order, so the last
   one wins on the shared descriptor.
4. The objective is recomputed from the guard list by the verifier; a claimed cost that
   disagrees is a violation.
5. Candidate and assignment plans are checked for permutation/one-hot validity and
   budget feasibility.

`tjq_verify.py` shares no cost arithmetic with the solvers; it recomputes the
expectation by direct enumeration.

## 5. QUBO formulations used (and their limits)

The ordering objective is **not** a compact QUBO. Written over position indicators
`x_{i,k}`, the term `Π_{j<k} q_j` becomes a product of up to `n−1` binary variables, so
an exact QUBO needs exponentially many auxiliary variables. Any compact QUBO for
ordering is therefore a surrogate, and a surrogate optimum is not a plan optimum.

Two genuinely quadratic sub-problems were formulated:

**Budgeted candidate selection (knapsack).** Choose identities to warm under a
validation budget `B`:

```
max Σ b_i x_i   s.t.  Σ c_i x_i ≤ B,  x ∈ {0,1}^m
```

with slack `Σ c_i x_i + Σ 2^j s_j = B` and penalty `λ(· − B)²`, `λ` chosen so a one-unit
overrun costs more than any single benefit. Costs are rescaled to integer units first;
the reported coefficient magnitudes are from that scaled model.

**Guard batching (partition).** Balance `n` atomic blocks over `B` workers by
minimising `Σ_b L_b²`, where `L_b` is the load of worker `b`. Makespan is a max and is
not quadratic; sum-of-squares is the standard quadratic surrogate.

Both are small (19 and 112 variables). Neither is on a production path.

## 6. What is optimised, and what is not

- Optimised: expected guard work before a failure is detected; expected candidate
  validations before the matching candidate.
- Not optimised, not relaxed: which guards exist, whether they pass, classification,
  reuse eligibility, restore ordering, or the decision to expose cached bytes.

A plan produced here is admissible only after the verifier passes and after the same
`validate_all` call runs at execution time. Ordering can make a failing plan cheaper to
reject; it can never make a passing plan skip work, because a passing plan validates
every guard by definition.

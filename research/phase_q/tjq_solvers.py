"""Baselines and solvers for Phase Q.

Every solver returns a plan; every plan is checked by `tjq_verify` before its cost is
used. Solvers never drop, merge, or skip guards.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from tjq_model import CandidateModel, GuardInstance


# ---------------------------------------------------------------------------
# Ordering over adjacency blocks
# ---------------------------------------------------------------------------

def expand(blocks: list[list[int]], block_order: list[int]) -> list[int]:
    order: list[int] = []
    for b in block_order:
        order.extend(blocks[b])
    return order


def current_order(inst: GuardInstance) -> list[int]:
    return list(range(inst.n))


def ratio_order(inst: GuardInstance) -> list[int]:
    """Boothroyd/Mitten (1960): ascending cost / failure-probability per block.

    Optimal for independent blocks (pairwise interchange argument). Blocks are the
    unit here because validate_all shares one fd across a metadata+content pair.
    """
    costs = inst.block_expected_costs
    fails = np.maximum(inst.block_fail_prob, 1e-12)
    ratio = costs / fails
    order = np.argsort(ratio, kind="stable")
    return expand(inst.blocks, [int(b) for b in order])


def exact_dp_independent(inst: GuardInstance) -> tuple[list[int], float, bool]:
    """Exact optimum over block orders when block failures are independent.

    f(mask) = min_j c_j + q_j f(mask | j). Only used for instances where the
    independence assumption holds; returns (order, cost, exact).
    """
    blocks = inst.blocks
    n = len(blocks)
    if n > 18:
        return ratio_order(inst), inst.expected_cost(ratio_order(inst)), False
    costs = inst.block_expected_costs
    q = 1.0 - inst.block_fail_prob
    size = 1 << n
    best = np.full(size, np.inf)
    choice = np.full(size, -1, dtype=np.int16)
    best[size - 1] = 0.0
    all_masks = np.arange(size)
    popcount = np.bitwise_count(all_masks)
    bit_of = (1 << np.arange(n)).astype(np.int64)
    for layer in range(n - 1, -1, -1):
        masks = all_masks[popcount == layer]
        if masks.size == 0:
            continue
        present = (masks[:, None] >> np.arange(n)[None, :]) & 1
        future = masks[:, None] | bit_of[None, :]
        candidate = costs[None, :] + q[None, :] * best[future]
        candidate = np.where(present == 1, np.inf, candidate)
        picks = candidate.argmin(axis=1)
        best[masks] = candidate[np.arange(masks.size), picks]
        choice[masks] = picks
    order_blocks = []
    mask = 0
    while mask != size - 1:
        j = int(choice[mask])
        order_blocks.append(j)
        mask |= 1 << j
    order = expand(blocks, order_blocks)
    return order, float(best[0]), True


def exact_search_correlated(
    inst: GuardInstance, node_limit: int = 400_000
) -> tuple[list[int], float, bool]:
    """Depth-first branch and bound over block orders.

    Lower bound for a prefix is the cost already paid, which any completion must
    include. Initial upper bound is the ratio rule. Returns exact=False if the node
    budget is exhausted, and the best plan found either way.
    """
    blocks = inst.blocks
    n = len(blocks)
    costs = inst.block_costs
    best_order = ratio_order(inst)
    best_cost = inst.expected_cost(best_order)
    nodes = 0
    complete = True

    def dfs(prefix: list[int]) -> None:
        nonlocal best_cost, best_order, nodes, complete
        if not complete:
            return
        # Expected cost already committed by this prefix is a valid lower bound: any
        # completion only adds non-negative expected cost and cannot change survival.
        if prefix:
            committed = inst.expected_cost(expand(blocks, prefix))
            if committed >= best_cost:
                return
        if len(prefix) == n:
            order = expand(blocks, prefix)
            value = inst.expected_cost(order)
            if value < best_cost:
                best_cost, best_order = value, order
            return
        candidates = sorted(
            (j for j in range(n) if j not in prefix),
            key=lambda j: costs[j] / max(inst.block_fail_prob[j], 1e-12),
        )
        for j in candidates:
            nodes += 1
            if nodes > node_limit:
                complete = False
                return
            dfs(prefix + [j])
            if not complete:
                return

    dfs([])
    return best_order, best_cost, complete


# ---------------------------------------------------------------------------
# Metaheuristics over block permutations
# ---------------------------------------------------------------------------

def _objective(inst: GuardInstance, blocks, order_blocks) -> float:
    return inst.expected_cost(expand(blocks, order_blocks))


def _neighbor(order: list[int], rng: np.random.Generator) -> list[int]:
    out = order.copy()
    n = len(out)
    i, j = rng.integers(0, n, size=2)
    if i == j:
        j = (j + 1) % n
    if rng.random() < 0.5:
        out[i], out[j] = out[j], out[i]
    else:
        item = out.pop(int(i))
        out.insert(int(j), item)
    return out


@dataclass
class SolverResult:
    name: str
    order: list[int]
    cost_ns: float
    runtime_ms: float
    evaluations: int


def simulated_annealing(
    inst: GuardInstance,
    rng: np.random.Generator,
    *,
    evaluations: int = 20_000,
    t0: float | None = None,
    t1: float | None = None,
    name: str = "sa",
) -> SolverResult:
    blocks = inst.blocks
    start = [
        int(b)
        for b in np.argsort(
            inst.block_expected_costs / np.maximum(inst.block_fail_prob, 1e-12)
        )
    ]
    current = start.copy()
    current_cost = _objective(inst, blocks, current)
    best, best_cost = current.copy(), current_cost
    mean_cost = float(np.mean(inst.block_costs)) + 1.0
    heat0 = t0 if t0 is not None else 0.05 * mean_cost * inst.n
    heat1 = t1 if t1 is not None else 1e-3 * mean_cost
    began = time.perf_counter()
    for k in range(evaluations):
        temp = heat0 * (heat1 / heat0) ** (k / max(1, evaluations - 1))  # geometric
        candidate = _neighbor(current, rng)
        value = _objective(inst, blocks, candidate)
        delta = value - current_cost
        if delta <= 0 or rng.random() < math.exp(-delta / max(temp, 1e-12)):
            current, current_cost = candidate, value
            if value < best_cost:
                best, best_cost = candidate.copy(), value
    elapsed = (time.perf_counter() - began) * 1e3
    return SolverResult(name, expand(blocks, best), best_cost, elapsed, evaluations)


def tabu_search(
    inst: GuardInstance,
    rng: np.random.Generator,
    *,
    iterations: int = 3_000,
    tenure: int = 7,
    name: str = "tabu",
) -> SolverResult:
    blocks = inst.blocks
    n = len(blocks)
    current = [
        int(b)
        for b in np.argsort(
            inst.block_expected_costs / np.maximum(inst.block_fail_prob, 1e-12)
        )
    ]
    current_cost = _objective(inst, blocks, current)
    best, best_cost = current.copy(), current_cost
    tabu: dict[tuple[int, int], int] = {}
    began = time.perf_counter()
    evaluations = 0
    # n is ~31 blocks: the full n^2 neighbourhood is ~1.4M expected-cost evaluations,
    # which is more than the entire decision budget. Sample a fixed number of moves.
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    per_step = 80 if len(pairs) > 80 else len(pairs)
    for step in range(iterations):
        best_move = None
        best_move_cost = math.inf
        best_pair = None
        picked = rng.choice(len(pairs), size=per_step, replace=False)
        for k in picked:
            i, j = pairs[int(k)]
            candidate = current.copy()
            candidate[i], candidate[j] = candidate[j], candidate[i]
            value = _objective(inst, blocks, candidate)
            evaluations += 1
            is_tabu = tabu.get((i, j), -1) > step
            if is_tabu and value >= best_cost:
                continue
            if value < best_move_cost:
                best_move_cost, best_move, best_pair = value, candidate, (i, j)
        if best_move is None:
            break
        current, current_cost = best_move, best_move_cost
        tabu[best_pair] = step + tenure
        if current_cost < best_cost:
            best, best_cost = current.copy(), current_cost
    elapsed = (time.perf_counter() - began) * 1e3
    return SolverResult(name, expand(blocks, best), best_cost, elapsed, evaluations)


def parallel_tempering(
    inst: GuardInstance,
    rng: np.random.Generator,
    *,
    replicas: int = 8,
    sweeps: int = 1_500,
    name: str = "pt",
) -> SolverResult:
    blocks = inst.blocks
    n = len(blocks)
    mean_cost = float(np.mean(inst.block_costs)) + 1.0
    betas = np.geomspace(1.0 / (0.06 * mean_cost * n), 1.0 / (2e-3 * mean_cost), replicas)
    start = [
        int(b)
        for b in np.argsort(
            inst.block_expected_costs / np.maximum(inst.block_fail_prob, 1e-12)
        )
    ]
    states = [start.copy() for _ in range(replicas)]
    energies = [_objective(inst, blocks, s) for s in states]
    best, best_cost = states[-1].copy(), energies[-1]
    for i, e in enumerate(energies):
        if e < best_cost:
            best, best_cost = states[i].copy(), e
    began = time.perf_counter()
    evaluations = 0
    for sweep in range(sweeps):
        for r in range(replicas):
            for _ in range(max(2, n)):
                candidate = _neighbor(states[r], rng)
                value = _objective(inst, blocks, candidate)
                evaluations += 1
                delta = value - energies[r]
                if delta <= 0 or rng.random() < math.exp(-betas[r] * delta):
                    states[r], energies[r] = candidate, value
                    if value < best_cost:
                        best, best_cost = candidate.copy(), value
        if sweep % 5 == 0:
            for r in range(replicas - 1):
                delta = (betas[r] - betas[r + 1]) * (energies[r] - energies[r + 1])
                if delta >= 0 or rng.random() < math.exp(delta):
                    states[r], states[r + 1] = states[r + 1], states[r]
                    energies[r], energies[r + 1] = energies[r + 1], energies[r]
    elapsed = (time.perf_counter() - began) * 1e3
    return SolverResult(name, expand(blocks, best), best_cost, elapsed, evaluations)


def local_search(
    inst: GuardInstance, *, name: str = "local-search"
) -> SolverResult:
    """Best-improvement swap descent from the ratio order. No temperature."""
    blocks = inst.blocks
    n = len(blocks)
    current = [
        int(b)
        for b in np.argsort(
            inst.block_expected_costs / np.maximum(inst.block_fail_prob, 1e-12)
        )
    ]
    current_cost = _objective(inst, blocks, current)
    began = time.perf_counter()
    evaluations = 0
    improved = True
    while improved:
        improved = False
        for i in range(n):
            for j in range(i + 1, n):
                candidate = current.copy()
                candidate[i], candidate[j] = candidate[j], candidate[i]
                value = _objective(inst, blocks, candidate)
                evaluations += 1
                if value < current_cost - 1e-9:
                    current, current_cost = candidate, value
                    improved = True
    elapsed = (time.perf_counter() - began) * 1e3
    return SolverResult(name, expand(blocks, current), current_cost, elapsed, evaluations)


# ---------------------------------------------------------------------------
# QUBO models (only for genuinely binary problems)
# ---------------------------------------------------------------------------

@dataclass
class QuboProblem:
    name: str
    linear: list[float]
    quadratic: dict[tuple[int, int], float]
    offset: float = 0.0
    n_vars: int = 0

    def energy(self, bits: list[int] | np.ndarray) -> float:
        total = self.offset
        for i, b in enumerate(bits):
            if b:
                total += self.linear[i]
        for (i, j), w in self.quadratic.items():
            if bits[i] and bits[j]:
                total += w
        return float(total)

    def max_abs_coefficient(self) -> float:
        values = [abs(v) for v in self.linear] + [abs(v) for v in self.quadratic.values()]
        return max(values) if values else 0.0

    def to_bqm(self):
        import dimod

        return dimod.BinaryQuadraticModel(
            {i: self.linear[i] for i in range(self.n_vars)},
            {k: v for k, v in self.quadratic.items()},
            self.offset,
            dimod.BINARY,
        )


def knapsack_qubo(
    costs_ms: list[float],
    benefits: list[float],
    budget_ms: float,
    penalty_multiplier: float = 1.0,
) -> tuple[QuboProblem, dict]:
    """Select candidates to pre-validate under a budget: binary knapsack as QUBO.

    Costs are rescaled to small integer units first so the penalty term stays
    conditioned; the scaling factor is reported.
    """
    m = len(costs_ms)
    unit = max(budget_ms, 1e-9) / 100.0
    c = [max(1, int(round(v / unit))) for v in costs_ms]
    budget = int(round(budget_ms / unit))
    # slack in binary expansion so equality is representable
    slack_bits = [1 << k for k in range(int(math.floor(math.log2(max(budget, 1)))) + 1)]
    scale = max(benefits) if benefits else 1.0
    b = [v / scale for v in benefits]
    # A one-unit budget overrun raises the squared penalty by (2U+1); lambda is the
    # smallest value that makes that overrun cost more than any single benefit.
    lam = penalty_multiplier * (max(b) + 0.5) / max(1.0, 2.0 * budget + 1.0)
    n = m + len(slack_bits)
    linear = [0.0] * n
    quad: dict[tuple[int, int], float] = {}
    # diagonal from (sum a_p y_p - U)^2 expanded: a_p^2 - 2 U a_p
    a = c + slack_bits
    for p in range(n):
        linear[p] += lam * (a[p] ** 2 - 2 * budget * a[p])
    for p in range(n):
        for q in range(p + 1, n):
            quad[(p, q)] = lam * 2.0 * a[p] * a[q]
    for i in range(m):
        linear[i] -= b[i]
    offset = lam * budget**2
    problem = QuboProblem("knapsack", linear, quad, offset, n)
    meta = {
        "unit_ms": unit,
        "budget_units": budget,
        "penalty": lam,
        "slack_bits": len(slack_bits),
        "cost_units": c,
        "scale_benefit": scale,
    }
    return problem, meta


def decode_knapsack(bits, m: int) -> list[int]:
    return [i for i in range(m) if bits[i]]


def partition_qubo(costs_ms: list[float], bins: int) -> QuboProblem:
    """Balance guard blocks over workers: minimise sum of squared bin loads.

    Sum-of-squares is a quadratic surrogate for makespan that a QUBO can express
    compactly; makespan itself is a max and is not quadratic.
    """
    n_items = len(costs_ms)
    n = n_items * bins
    linear = [0.0] * n
    quad: dict[tuple[int, int], float] = {}
    for b in range(bins):
        for i in range(n_items):
            p = b * n_items + i
            linear[p] += costs_ms[i] ** 2
            for j in range(i + 1, n_items):
                q = b * n_items + j
                quad[(p, q)] = quad.get((p, q), 0.0) + 2.0 * costs_ms[i] * costs_ms[j]
    total = sum(costs_ms)
    penalty = 2.0 * (total**2) + 1.0
    for i in range(n_items):
        for b in range(bins):
            p = b * n_items + i
            linear[p] += penalty * (1 - 2)
        for b in range(bins):
            for c in range(b + 1, bins):
                quad[(b * n_items + i, c * n_items + i)] = (
                    quad.get((b * n_items + i, c * n_items + i), 0.0) + 2.0 * penalty
                )
    return QuboProblem("partition", linear, quad, penalty * n_items, n)


def decode_partition(bits, n_items: int, bins: int) -> tuple[list[int], bool]:
    assign = []
    feasible = True
    for i in range(n_items):
        chosen = [b for b in range(bins) if bits[b * n_items + i]]
        if len(chosen) != 1:
            feasible = False
            assign.append(chosen[0] if chosen else 0)
        else:
            assign.append(chosen[0])
    return assign, feasible


# ---------------------------------------------------------------------------
# Ocean samplers
# ---------------------------------------------------------------------------

def ocean_sample(problem: QuboProblem, sampler: str, *, reads: int = 200, seed: int = 7):
    """Run a D-Wave Ocean sampler and return (best_bits, energy, runtime_ms, feasible)."""
    from dwave.samplers import (
        PathIntegralAnnealingSampler,
        SimulatedAnnealingSampler,
        TabuSampler,
    )

    begun = time.perf_counter()
    bqm = problem.to_bqm()
    if sampler == "sa":
        result = SimulatedAnnealingSampler().sample(bqm, num_reads=reads, seed=seed)
    elif sampler == "sqa":
        result = PathIntegralAnnealingSampler().sample(
            bqm, num_reads=reads, num_sweeps=1000, seed=seed
        )
    elif sampler == "tabu":
        result = TabuSampler().sample(bqm, num_reads=reads, seed=seed)
    else:
        raise ValueError(sampler)
    elapsed = (time.perf_counter() - begun) * 1e3
    best = result.first.sample
    bits = [int(best[i]) for i in range(problem.n_vars)]
    return bits, float(result.first.energy), elapsed, result


def exact_knapsack(costs_ms: list[float], benefits: list[float], budget_ms: float) -> tuple[list[int], float]:
    """Exact 0/1 knapsack by DP on 0.01 ms units."""
    unit = budget_ms / 200.0
    c = [max(1, int(round(v / unit))) for v in costs_ms]
    cap = int(round(budget_ms / unit))
    dp = [-math.inf] * (cap + 1)
    dp[0] = 0.0
    take = [[False] * (cap + 1) for _ in c]
    for i, (ci, bi) in enumerate(zip(c, benefits)):
        for w in range(cap, ci - 1, -1):
            value = dp[w - ci] + bi
            if value > dp[w]:
                dp[w] = value
                take[i][w] = True
    best_w = max(range(cap + 1), key=lambda w: dp[w])
    chosen = []
    w = best_w
    for i in range(len(c) - 1, -1, -1):
        if take[i][w]:
            chosen.append(i)
            w -= c[i]
    return sorted(chosen), dp[best_w]


def lpt_partition(costs: list[float], bins: int) -> tuple[list[int], float]:
    """Longest-processing-time list scheduling; the classical 4/3-1/(3B) bound."""
    loads = [0.0] * bins
    assign = [0] * len(costs)
    for i in sorted(range(len(costs)), key=lambda i: -costs[i]):
        b = min(range(bins), key=lambda b: loads[b])
        assign[i] = b
        loads[b] += costs[i]
    return assign, max(loads)


def exact_partition(costs: list[float], bins: int) -> tuple[list[int], float, bool]:
    """Exact min-makespan partition by DP over item subsets for small n."""
    n = len(costs)
    if n > 16:
        assign, makespan = lpt_partition(costs, bins)
        return assign, makespan, False
    best = (math.inf, None)

    def place(i: int, loads: list[float], assign: list[int]) -> None:
        nonlocal best
        if i == n:
            span = max(loads)
            if span < best[0]:
                best = (span, assign.copy())
            return
        seen = set()
        for b in range(bins):
            key = round(loads[b], 9)
            if key in seen:
                continue
            seen.add(key)
            if loads[b] + costs[i] >= best[0]:
                continue
            loads[b] += costs[i]
            assign.append(b)
            place(i + 1, loads, assign)
            assign.pop()
            loads[b] -= costs[i]

    place(0, [0.0] * bins, [])
    if best[1] is None:
        assign, makespan = lpt_partition(costs, bins)
        return assign, makespan, True
    return best[1], best[0], True


def plan_cost_stats(fn, *args):
    """Timed wrapper returning (value, ms)."""
    began = time.perf_counter()
    value = fn(*args)
    return value, (time.perf_counter() - began) * 1e3

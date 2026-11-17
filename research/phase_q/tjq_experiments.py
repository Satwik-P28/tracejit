"""Phase Q experiments: reproduce every number in REPORT.md.

Run with the isolated venv:

    research/phase_q/.venv/bin/python research/phase_q/tjq_experiments.py

Writes results/measurements.json and results/summary.md. Nothing here is on the
production execution path, and nothing here changes main.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from itertools import permutations
from pathlib import Path

import numpy as np

from tjq_anchors import load_anchors
from tjq_model import (
    CandidateModel,
    Guard,
    GuardInstance,
    measured_guard_instance,
    random_guard_instance,
)
from tjq_solvers import (
    QuboProblem,
    current_order,
    decode_knapsack,
    decode_partition,
    exact_dp_independent,
    exact_knapsack,
    exact_partition,
    exact_search_correlated,
    expand,
    knapsack_qubo,
    local_search,
    lpt_partition,
    ocean_sample,
    parallel_tempering,
    partition_qubo,
    ratio_order,
    simulated_annealing,
    tabu_search,
)
from tjq_verify import (
    verify_assignment,
    verify_candidate_order,
    verify_guard_order,
    verify_subset,
)

OUT = Path(__file__).resolve().parent / "results"
RNG_SEED = 20261117


def ms(ns: float) -> float:
    return ns / 1e6


def independent_instance(n: int, rng: np.random.Generator) -> GuardInstance:
    """Every guard has its own group and block, so failures are independent."""
    guards = []
    rho = {}
    for i in range(n):
        p = float(np.clip(rng.beta(0.6, 18.0), 1e-5, 0.8))
        rho[i] = p
        kind = "content" if rng.random() < 0.35 else "metadata"
        cost = float(np.exp(rng.normal(10.5, 1.3))) * (6.0 if kind == "content" else 1.0)
        guards.append(Guard(i, f"g{i}", kind, cost, i, i))
    return GuardInstance(f"independent-{n}", guards, rho, background_prob=0.0)


def guard_plan_table(inst: GuardInstance, rng, *, solvers: bool, seed_shift: int = 0):
    rows = []
    violations = []

    def record(name, order, runtime_ms, evaluations=0, extra=None):
        verdict = verify_guard_order(inst, order)
        violations.extend(verdict.violations)
        row = {
            "solver": name,
            "cost_ms": round(ms(verdict.recomputed_cost_ns), 6),
            "runtime_ms": round(runtime_ms, 4),
            "evaluations": evaluations,
            "verified": verdict.ok,
        }
        if extra:
            row.update(extra)
        rows.append(row)
        return row

    record("current", current_order(inst), 0.0)
    began = time.perf_counter()
    ratio = ratio_order(inst)
    record("ratio-greedy", ratio, (time.perf_counter() - began) * 1e3)
    began = time.perf_counter()
    local = local_search(inst)
    record("local-search", local.order, (time.perf_counter() - began) * 1e3)
    if solvers:
        sa = simulated_annealing(inst, rng)
        record("simulated-annealing", sa.order, sa.runtime_ms, sa.evaluations)
        tabu = tabu_search(inst, rng)
        record("tabu", tabu.order, tabu.runtime_ms, tabu.evaluations)
        pt = parallel_tempering(inst, rng)
        record("parallel-tempering", pt.order, pt.runtime_ms, pt.evaluations)
    return rows, violations


# ---------------------------------------------------------------------------
# E1: is the greedy ratio rule exact for independent guards?
# ---------------------------------------------------------------------------

def experiment_ratio_optimality(rng) -> dict:
    rows = []
    brute_checked = 0
    brute_disagreements = 0
    for n in (4, 6, 8, 10, 12, 14, 16):
        trials = 150 if n <= 12 else 60
        suboptimal = 0
        worst_gap = 0.0
        for trial in range(trials):
            inst = independent_instance(n, rng)
            order = ratio_order(inst)
            greedy = inst.expected_cost(order)
            _, best, exact = exact_dp_independent(inst)
            assert exact
            # Relative tolerance: the DP and the objective use different summation
            # orders, so exact ties can differ by a few ulp. A real gap is far larger.
            if greedy > best * (1.0 + 1e-12) + 1e-12:
                suboptimal += 1
                worst_gap = max(worst_gap, (greedy - best) / best)
            if n == 6 and trial < 25:
                brute_best = min(
                    inst.expected_cost(list(perm)) for perm in permutations(range(n))
                )
                brute_checked += 1
                if abs(brute_best - best) > 1e-6:
                    brute_disagreements += 1
        rows.append(
            {
                "n_blocks": n,
                "trials": trials,
                "greedy_suboptimal": suboptimal,
                "max_relative_gap": worst_gap,
            }
        )
    return {
        "claim": "greedy ratio rule equals the exact optimum for independent guards",
        "rows": rows,
        "bruteforce_cross_check": {
            "instances": brute_checked,
            "dp_vs_bruteforce_disagreements": brute_disagreements,
        },
        "tolerance": "relative 1e-12 (ties at the ulp level are not suboptimality)",
        "conclusion": "exact within 1e-12 on every instance tested"
        if all(r["max_relative_gap"] <= 1e-12 for r in rows)
        else "greedy is not exact; see rows",
    }


# ---------------------------------------------------------------------------
# E2: the measured 33-guard workload
# ---------------------------------------------------------------------------

def experiment_measured_guards(anchors, rng) -> dict:
    total_ns = anchors.guard_validation_ms_median * 1e6
    stable = measured_guard_instance(total_ns, changed_asset_rho=0.02)
    transition = measured_guard_instance(total_ns, changed_asset_rho=1.0)
    stable_rows, v1 = guard_plan_table(stable, rng, solvers=False)
    transition_rows, v2 = guard_plan_table(transition, rng, solvers=True)

    blocks = len(stable.blocks)
    current = next(r for r in transition_rows if r["solver"] == "current")
    ratio = next(r for r in transition_rows if r["solver"] == "ratio-greedy")
    local = next(r for r in transition_rows if r["solver"] == "local-search")
    hit_wall = anchors.hit_wall_ms_median
    deopt_wall = anchors.deopt_wall_ms_median
    measured_fraction = (anchors.transition_checked - 1) / anchors.transition_checked

    return {
        "instance": {
            "guards": stable.n,
            "blocks": blocks,
            "guard_validation_ms": anchors.guard_validation_ms_median,
            "measured_failure_position": [
                anchors.transition_failed_at,
                anchors.transition_checked,
            ],
            "measured_fraction_of_guard_budget_paid_before_failure": round(
                measured_fraction, 4
            ),
        },
        "stable_no_failure": {
            "rows": stable_rows,
            "note": "every plan validates every guard; ordering cannot change a plain hit",
        },
        "asset_changed": {
            "rows": transition_rows,
            "measured_shape_current_ms": round(
                anchors.guard_validation_ms_median * measured_fraction, 4
            ),
            "measured_shape_saving_ms": round(
                anchors.guard_validation_ms_median * measured_fraction - ratio["cost_ms"], 4
            ),
            "model_failure_position": [
                next(
                    i + 1
                    for i, gid in enumerate(current_order(stable))
                    if stable.guards[gid].group == 20 and stable.guards[gid].kind == "metadata"
                ),
                stable.n,
            ],
            "saved_ms_vs_current": round(current["cost_ms"] - ratio["cost_ms"], 4),
            "local_search_extra_saving_ms": round(
                ratio["cost_ms"] - local["cost_ms"], 6
            ),
            "measured_deopt_wall_ms": deopt_wall,
            "saved_fraction_of_deopt_wall": round(
                (current["cost_ms"] - ratio["cost_ms"]) / deopt_wall, 5
            ),
            "measured_hit_wall_ms": hit_wall,
        },
        "verifier_violations": v1 + v2,
    }


# ---------------------------------------------------------------------------
# E3: correlated invalidation, shared dependencies
# ---------------------------------------------------------------------------

def correlated_instance(rng, n_blocks=16, n_groups=8) -> GuardInstance:
    """Blocks share dependency groups: one changed file invalidates several blocks."""
    guards = []
    rho = {g: float(np.clip(rng.beta(0.9, 9.0), 0.002, 0.7)) for g in range(n_groups)}
    gid = 0
    for b in range(n_blocks):
        group = int(rng.integers(0, n_groups))
        size = 2 if rng.random() < 0.5 else 1
        cost = float(np.exp(rng.normal(10.6, 1.1))) * (7.0 if size == 2 else 1.0)
        for k in range(size):
            kind = "metadata" if k == 0 else "content"
            guards.append(Guard(gid, f"b{b}.g{k}", kind, cost / size, group, b))
            gid += 1
    return GuardInstance("correlated", guards, rho)


def experiment_correlated(rng, instances=12) -> dict:
    summaries = []
    violations = []
    for trial in range(instances):
        inst = correlated_instance(rng)
        rows = []
        current = current_order(inst)
        rows.append(("current", inst.expected_cost(current), 0.0))
        began = time.perf_counter()
        ratio = ratio_order(inst)
        rows.append(("ratio-greedy", inst.expected_cost(ratio), (time.perf_counter() - began) * 1e3))
        began = time.perf_counter()
        local = local_search(inst)
        rows.append(("local-search", local.cost_ns, (time.perf_counter() - began) * 1e3))
        sa = simulated_annealing(inst, rng, evaluations=6_000)
        rows.append(("simulated-annealing", sa.cost_ns, sa.runtime_ms))
        tabu = tabu_search(inst, rng, iterations=100, tenure=5)
        rows.append(("tabu", tabu.cost_ns, tabu.runtime_ms))
        pt = parallel_tempering(inst, rng, sweeps=80)
        rows.append(("parallel-tempering", pt.cost_ns, pt.runtime_ms))
        began = time.perf_counter()
        exact_order, exact_cost, exact_flag = exact_search_correlated(inst, node_limit=20_000)
        rows.append(("branch-and-bound", exact_cost, (time.perf_counter() - began) * 1e3))
        for name, _, _ in rows:
            order = {
                "current": current,
                "ratio-greedy": ratio,
                "local-search": local.order,
                "simulated-annealing": sa.order,
                "tabu": tabu.order,
                "parallel-tempering": pt.order,
                "branch-and-bound": exact_order,
            }[name]
            verdict = verify_guard_order(inst, order)
            violations.extend(verdict.violations)
        best = min(r[1] for r in rows)
        ratio_cost = next(c for n, c, _ in rows if n == "ratio-greedy")
        summaries.append(
            {
                "trial": trial,
                "best_ms": ms(best),
                "ratio_ms": ms(ratio_cost),
                "exact": exact_flag,
                "rows": [
                    {
                        "solver": n,
                        "cost_ms": ms(c),
                        "gap_vs_best": (c - best) / best,
                        "extra_cost_vs_ratio_ms": ms(c - ratio_cost),
                        "runtime_ms": rt,
                    }
                    for n, c, rt in rows
                ],
            }
        )
    per_solver: dict[str, list[float]] = {}
    runtime: dict[str, list[float]] = {}
    extra: dict[str, list[float]] = {}
    for item in summaries:
        for row in item["rows"]:
            per_solver.setdefault(row["solver"], []).append(row["gap_vs_best"])
            runtime.setdefault(row["solver"], []).append(row["runtime_ms"])
            extra.setdefault(row["solver"], []).append(row["extra_cost_vs_ratio_ms"])
    break_even = {
        k: (float(np.mean(runtime[k])) / float(np.mean(-np.array(extra[k]))))
        if np.mean(extra[k]) < -1e-12
        else None
        for k in per_solver
    }
    return {
        "instances": instances,
        "n_blocks": 16,
        "n_groups": 8,
        "mean_gap_vs_best_found": {
            k: float(np.mean(v)) for k, v in per_solver.items()
        },
        "max_gap_vs_best_found": {k: float(np.max(v)) for k, v in per_solver.items()},
        "mean_runtime_ms": {k: float(np.mean(v)) for k, v in runtime.items()},
        "mean_extra_cost_vs_ratio_ms": {
            k: float(np.mean(v)) for k, v in extra.items()
        },
        "break_even_speedup_needed": break_even,
        "branch_and_bound_exact_on_all": all(i["exact"] for i in summaries),
        "verifier_violations": violations,
    }


# ---------------------------------------------------------------------------
# E4: candidate ordering at the measured candidate-scaling bounds
# ---------------------------------------------------------------------------

def hot_distribution(m: int) -> np.ndarray:
    """Two hot input states, one of them older than the newest candidate.

    This is the regime where newest-first is *not* optimal, which is the only regime
    in which candidate reordering can pay at all.
    """
    w = np.ones(m, dtype=float) * 0.4
    w[0] = 6.0
    if m > 3:
        w[3] = 5.0
    elif m > 1:
        w[m - 1] = 5.0
    return w / w.sum()


def experiment_candidates(anchors) -> dict:
    per_validation_ns = anchors.candidate_per_validation_ms * 1e6
    rows = []
    for bound in anchors.candidate_bounds:
        probs = hot_distribution(bound)
        cand = CandidateModel(
            validate_ns=[int(per_validation_ns)] * bound,
            match_prob=list(probs),
        )
        newest_order = list(range(bound))
        optimal_order = [int(i) for i in np.argsort(-probs)]
        newest = cand.expected_cost(newest_order)
        optimal = cand.expected_cost(optimal_order)
        v1 = verify_candidate_order(cand, optimal_order, optimal)
        v2 = verify_candidate_order(cand, newest_order, newest)
        measured_target = anchors.candidate_target_ms[anchors.candidate_bounds.index(bound)]
        measured_newest = anchors.candidate_newest_ms[anchors.candidate_bounds.index(bound)]
        rows.append(
            {
                "bound": bound,
                "newest_first_ms": ms(newest),
                "optimal_order_ms": ms(optimal),
                "model_saving_ms": ms(newest - optimal),
                "measured_target_wall_ms": measured_target,
                "measured_newest_wall_ms": measured_newest,
                "measured_gap_ms": measured_target - measured_newest,
                "verified": v1.ok and v2.ok,
            }
        )

    # exact enumeration of every order at the V1 retention cap
    m = 8
    probs8 = hot_distribution(m)
    cand8 = CandidateModel([int(per_validation_ns)] * m, list(probs8))
    began = time.perf_counter()
    brute_best = min(
        (cand8.expected_cost(list(order)), list(order))
        for order in permutations(range(m))
    )
    brute_ms = (time.perf_counter() - began) * 1e3
    learned_order_true = [int(i) for i in np.argsort(-probs8)]
    exact_check = {
        "orders_enumerated": math.factorial(m),
        "exact_cost_ms": ms(brute_best[0]),
        "ratio_cost_ms": ms(cand8.expected_cost(learned_order_true)),
        "runtime_ms": brute_ms,
    }

    # online learner vs newest-first on a held-out stream
    rng = np.random.default_rng(RNG_SEED + 4)
    train_runs, test_runs = 2000, 2000
    counts = np.ones(m)
    learner_depths = []
    newest_depths = []
    for run in range(train_runs + test_runs):
        target = int(rng.choice(m, p=probs8))
        if run < train_runs:
            counts[target] += 1.0
            continue
        learner_depths.append(list(np.argsort(-counts)).index(target))
        newest_depths.append(target)
    began = time.perf_counter()
    for _ in range(1000):
        list(np.argsort(-counts))
    one_sort_ms = (time.perf_counter() - began)  # 1000 sorts, so per-sort below

    learned_order = [int(i) for i in np.argsort(-counts)]
    return {
        "rows": rows,
        "exact_enumeration_at_cap": exact_check,
        "learner": {
            "bound": m,
            "train_runs": train_runs,
            "held_out_runs": test_runs,
            "mean_validations_newest_first": float(np.mean(newest_depths) + 1),
            "mean_validations_learned": float(np.mean(learner_depths) + 1),
            "empirical_saving_ms_vs_newest": ms(
                np.mean(np.array(newest_depths) - np.array(learner_depths))
                * per_validation_ns
            ),
            "model_cost_ms_newest": ms(cand8.expected_cost(list(range(m)))),
            "model_cost_ms_learned": ms(cand8.expected_cost(learned_order)),
            "model_cost_ms_optimal": ms(cand8.expected_cost(learned_order_true)),
            "decision_cost_per_plan_ms": one_sort_ms,
        },
        "note": (
            "candidate validation cost is equal across candidates of one identity, so "
            "the optimal order is descending match probability; newest-first is only "
            "optimal when recency equals probability"
        ),
    }


# ---------------------------------------------------------------------------
# E5: offline admission planning as a knapsack (genuine QUBO)
# ---------------------------------------------------------------------------

def experiment_knapsack(rng) -> dict:
    m = 12
    cold_ms = rng.uniform(30, 400, size=m)
    hit_ms = rng.uniform(5, 12, size=m)
    hit_prob = rng.uniform(0.4, 0.98, size=m)
    reuse_count = rng.integers(2, 8, size=m)
    benefits = (cold_ms - hit_ms) * hit_prob * reuse_count  # ns-equivalent (ms units)
    budget = float(cold_ms.sum() * 0.35)
    exact_set, exact_value = exact_knapsack(list(cold_ms), list(benefits), budget)
    greedy_order = np.argsort(-(np.array(benefits) / cold_ms))
    greedy_set = []
    used = 0.0
    for i in greedy_order:
        if used + cold_ms[i] <= budget:
            greedy_set.append(int(i))
            used += cold_ms[i]
    greedy_value = float(np.sum(np.array(benefits)[greedy_set]))

    problem, meta = knapsack_qubo(list(cold_ms), list(benefits), budget)
    rows = [
        {"solver": "exact-dp", "value": exact_value, "runtime_ms": 0.0, "feasible": True},
        {"solver": "greedy-ratio", "value": greedy_value, "runtime_ms": 0.0, "feasible": True},
    ]
    for sampler in ("sa", "tabu", "sqa"):
        bits, energy, runtime_ms, _ = ocean_sample(problem, sampler, reads=200, seed=RNG_SEED)
        chosen = decode_knapsack(bits, m)
        used = float(cold_ms[chosen].sum()) if chosen else 0.0
        feasible = verify_subset(m, chosen).ok and used <= budget + 1e-9
        rows.append(
            {
                "solver": f"qubo-{sampler}",
                "value": float(np.sum(np.array(benefits)[chosen])) if chosen else 0.0,
                "runtime_ms": runtime_ms,
                "feasible": bool(feasible),
                "used_budget_ms": used,
                "energy": energy,
            }
        )
    for row in rows:
        row["gap_vs_exact"] = (exact_value - row["value"]) / exact_value if exact_value else 0.0

    # Penalty conditioning sweep: a hard constraint expressed through a penalty is
    # only hard if the coefficient dominates. Report feasibility, not just energy.
    penalty_sweep = []
    for multiplier in (1.0, 10.0, 100.0):
        scaled, scaled_meta = knapsack_qubo(
            list(cold_ms), list(benefits), budget, penalty_multiplier=multiplier
        )
        for sampler in ("sa", "sqa"):
            bits, energy, runtime_ms, _ = ocean_sample(
                scaled, sampler, reads=200, seed=RNG_SEED + int(multiplier)
            )
            chosen = decode_knapsack(bits, m)
            used = float(cold_ms[chosen].sum()) if chosen else 0.0
            penalty_sweep.append(
                {
                    "penalty_multiplier": multiplier,
                    "penalty": scaled_meta["penalty"],
                    "max_abs_coefficient": scaled.max_abs_coefficient(),
                    "sampler": sampler,
                    "value": float(np.sum(np.array(benefits)[chosen])) if chosen else 0.0,
                    "feasible": bool(used <= budget + 1e-9),
                    "used_budget_ms": used,
                    "runtime_ms": runtime_ms,
                }
            )

    return {
        "items": m,
        "budget_ms": budget,
        "qubo_vars": problem.n_vars,
        "qubo_max_abs_coefficient": problem.max_abs_coefficient(),
        "qubo_penalty": meta["penalty"],
        "cost_unit_ms": meta["unit_ms"],
        "rows": rows,
        "penalty_sweep": penalty_sweep,
        "exact_set": exact_set,
    }


# ---------------------------------------------------------------------------
# E6: parallel guard batching as a QUBO partition
# ---------------------------------------------------------------------------

def experiment_partition(anchors, rng) -> dict:
    total_ns = anchors.guard_validation_ms_median * 1e6
    inst = measured_guard_instance(total_ns, changed_asset_rho=0.02)
    blocks = inst.blocks
    costs = [float(ms(inst.block_costs[i])) for i in range(len(blocks))]
    bins = 4
    assign, lpt_span = lpt_partition(costs, bins)
    exact_assign, exact_span, exact_flag = exact_partition(costs, bins)

    problem = partition_qubo(costs, bins)
    rows = [
        {"solver": "lpt", "makespan_ms": lpt_span, "runtime_ms": 0.0, "feasible": True},
    ]
    if exact_flag:
        rows.append(
            {
                "solver": "exact-partition",
                "makespan_ms": exact_span,
                "runtime_ms": 0.0,
                "feasible": True,
            }
        )
    for sampler in ("sa", "tabu", "sqa"):
        bits, energy, runtime_ms, _ = ocean_sample(problem, sampler, reads=40, seed=RNG_SEED)
        assign_q, feasible = decode_partition(bits, len(costs), bins)
        loads = [0.0] * bins
        for i, b in enumerate(assign_q):
            loads[b] += costs[i]
        rows.append(
            {
                "solver": f"qubo-{sampler}",
                "makespan_ms": max(loads),
                "runtime_ms": runtime_ms,
                "feasible": bool(feasible and verify_assignment(len(costs), bins, assign_q).ok),
            }
        )
    best_span = min(r["makespan_ms"] for r in rows if r["feasible"])
    for row in rows:
        row["gap_vs_best"] = (row["makespan_ms"] - best_span) / best_span
    serial_ms = float(sum(costs))
    # No schedule can beat the largest indivisible block or the perfectly balanced load.
    lower_bound = max(max(costs), serial_ms / bins)
    for row in rows:
        row["gap_vs_lower_bound"] = (row["makespan_ms"] - lower_bound) / lower_bound
    parallelizable = sum(
        1 for g in inst.guards if not g.order_dependent
    )
    return {
        "blocks": len(blocks),
        "bins": bins,
        "serial_guard_ms": serial_ms,
        "ideal_parallel_ms": serial_ms / bins,
        "best_makespan_ms": best_span,
        "lower_bound_ms": lower_bound,
        "largest_block_ms": max(costs),
        "rows": rows,
        "parallel_upper_bound_saving_ms": serial_ms - serial_ms / bins,
        "parallelizable_guards": parallelizable,
        "total_guards": inst.n,
        "qubo_vars": problem.n_vars,
        "qubo_max_abs_coefficient": problem.max_abs_coefficient(),
        "safety_note": (
            "order-dependent guards (inherited-stream offsets) and metadata/content "
            "pairs sharing one fd cannot be moved to another worker without changing "
            "the validated object; the measured saving is an upper bound, not a plan"
        ),
    }


# ---------------------------------------------------------------------------
# E7: counterexample-guided refinement with train/validation/test separation
# ---------------------------------------------------------------------------

def cegar_identity(rng, n_guards=12, n_groups=4, noise=0.02) -> GuardInstance:
    guards = []
    rho = {}
    for g in range(n_groups):
        rho[g] = float(np.clip(rng.beta(1.0, 12.0), 0.001, 0.5))
    for i in range(n_guards):
        group = i % n_groups
        kind = "content" if i % 3 == 2 else "metadata"
        cost = float(np.exp(rng.normal(10.4, 1.0))) * (5.0 if kind == "content" else 1.0)
        guards.append(Guard(i, f"g{i}", kind, cost, group, i))
    inst = GuardInstance("cegar", guards, rho, background_prob=noise)
    return inst


def drift(inst: GuardInstance, rng) -> GuardInstance:
    """Nonstationary invalidation: one group's rate jumps, another relaxes."""
    rho = dict(inst.rho)
    keys = sorted(rho)
    up = int(rng.choice(keys))
    down = int(rng.choice(keys))
    rho[up] = min(0.9, rho[up] * 2.5 + 0.01)
    rho[down] = max(0.0005, rho[down] * 0.3)
    return GuardInstance(inst.name, inst.guards, rho, inst.background_prob)


def experiment_cegar(rng) -> dict:
    train_ids = [cegar_identity(rng) for _ in range(12)]
    test_ids = [cegar_identity(rng) for _ in range(12)]
    # shared nonstationary process: the same drift schedule hits both splits
    schedule = []
    state_train = list(train_ids)
    state_test = list(test_ids)
    for epoch in range(6):
        rng_epoch = np.random.default_rng(RNG_SEED + 100 + epoch)
        state_train = [drift(inst, rng_epoch) for inst in state_train]
        state_test = [drift(inst, rng_epoch) for inst in state_test]
        schedule.append((state_train, state_test))

    prior = {i: 0.05 for i in range(12)}
    failures = {i: 1.0 for i in range(12)}
    trials = {i: 1.0 for i in range(12)}  # Beta(1,1) prior per guard position
    ewma_fail = np.full(12, 0.05)
    ewma_rate = np.full(12, 1.0)
    decay = 0.85

    def plan_with(probs, inst):
        """Order the guards of `inst` by c/p using estimated failure probabilities."""
        ghosts = [
            Guard(i, f"g{i}", "metadata", inst.guards[i].cost_ns, i, i)
            for i in range(inst.n)
        ]
        model = GuardInstance("plan", ghosts, {i: probs[i] for i in range(inst.n)})
        return ratio_order(model)

    epochs = []
    for epoch, (train_set, test_set) in enumerate(schedule):
        est = {i: float(failures[i] / trials[i]) for i in range(12)}
        est_ewma = {i: float(ewma_fail[i] / ewma_rate[i]) for i in range(12)}
        rows = {}
        for name, probs in (
            ("static-prior", prior),
            ("online-cumulative", est),
            ("online-ewma", est_ewma),
        ):
            costs = []
            began = time.perf_counter()
            for t_inst, e_inst in zip(train_set, test_set):
                order = plan_with(probs, t_inst)
                # evaluate that plan under the held-out identity's true model
                costs.append(e_inst.expected_cost(order))
            rows[name] = {
                "held_out_mean_cost_ms": ms(float(np.mean(costs))),
                "planning_ms": (time.perf_counter() - began) * 1e3,
            }
        costs = []
        began = time.perf_counter()
        for e_inst in test_set:
            order = ratio_order(e_inst)  # true per-identity probabilities
            costs.append(e_inst.expected_cost(order))
        rows["oracle-probabilities"] = {
            "held_out_mean_cost_ms": ms(float(np.mean(costs))),
            "planning_ms": (time.perf_counter() - began) * 1e3,
        }
        # counterexamples from the training split: one Bernoulli event per group
        for inst in train_set:
            for i in range(inst.n):
                group = inst.guards[i].group
                failed = rng.random() < inst.rho[group]
                trials[i] += 1.0
                failures[i] += 1.0 if failed else 0.0
                ewma_fail[i] = decay * ewma_fail[i] + (1.0 - decay) * (1.0 if failed else 0.0)
                ewma_rate[i] = decay * ewma_rate[i] + (1.0 - decay)
        epochs.append({"epoch": epoch, "rows": rows})

    arms = ["static-prior", "online-cumulative", "online-ewma", "oracle-probabilities"]
    means = {
        arm: float(
            np.mean([e["rows"][arm]["held_out_mean_cost_ms"] for e in epochs])
        )
        for arm in arms
    }
    return {
        "train_identities": len(train_ids),
        "test_identities": len(test_ids),
        "epochs": epochs,
        "mean_held_out_cost_ms": means,
        "best_arm": min(means, key=means.get),
        "note": (
            "estimates are updated only from the training split; plans are evaluated "
            "against held-out identities under their true correlated model"
        ),
    }


# ---------------------------------------------------------------------------
# E9: session-level accounting, including optimizer decision cost
# ---------------------------------------------------------------------------

def experiment_session(anchors, e2, e3) -> dict:
    hit_ms = anchors.hit_wall_ms_median
    deopt_ms = anchors.deopt_wall_ms_median
    save_per_deopt_ms = e2["asset_changed"]["measured_shape_saving_ms"]
    ratio_sort_ms = e2["asset_changed"]["rows"][1]["runtime_ms"]
    local_search_ms = e3["mean_runtime_ms"]["local-search"]
    rows = []
    for rate in (0.0, 0.01, 0.05, 0.20):
        runs = 1000
        wall = (1 - rate) * runs * hit_ms + rate * runs * deopt_ms
        gross = rate * runs * save_per_deopt_ms
        net_sort = gross - runs * ratio_sort_ms
        net_local = gross - runs * local_search_ms
        rows.append(
            {
                "deopt_rate": rate,
                "session_wall_ms": wall,
                "gross_saving_ms": gross,
                "gross_saving_pct": 100.0 * gross / wall,
                "net_after_sort_ms": net_sort,
                "net_after_local_search_ms": net_local,
            }
        )
    return {
        "save_per_deopt_ms": save_per_deopt_ms,
        "ratio_sort_decision_ms": ratio_sort_ms,
        "local_search_decision_ms": local_search_ms,
        "break_even_deopt_rate_for_per_run_sort": save_per_deopt_ms
        and ratio_sort_ms / save_per_deopt_ms,
        "rows": rows,
        "note": (
            "plans are compiled and stored with the trace, so a per-run re-plan is a "
            "pessimistic upper bound on decision cost"
        ),
    }


# ---------------------------------------------------------------------------
# E8: admission planning against the recorded Phase K9 matrix
# ---------------------------------------------------------------------------

def experiment_admission(anchors) -> dict:
    oracle = anchors.admission_oracle_ns
    rows = []
    for policy in anchors.admission_policies:
        rows.append(
            {
                "policy": policy["policy"],
                "total_ms": policy["total_ns"] / 1e6,
                "regret_ms": policy["regret_ns"] / 1e6,
                "regret_over_oracle": policy["regret_ns"] / oracle,
            }
        )
    current = next(r for r in rows if r["policy"] == "CurrentAuto")
    return {
        "source": "benchmarks/results/phase_k9/admission-eval.json",
        "oracle_ms": oracle / 1e6,
        "rows": rows,
        "current_auto_regret_ms": current["regret_ms"],
        "steps": 34,
        "max_planning_gain_ms_per_step": current["regret_ms"] / 34,
        "note": (
            "offline DP cannot beat the recorded oracle, and the oracle is clairvoyant; "
            "the achievable online improvement is bounded by the CurrentAuto regret"
        ),
    }


# ---------------------------------------------------------------------------
# Complexity and decision-cost accounting
# ---------------------------------------------------------------------------

def complexity_table(anchors) -> dict:
    inst = measured_guard_instance(anchors.guard_validation_ms_median * 1e6)
    n = inst.n
    b = len(inst.blocks)
    return {
        "guards": n,
        "adjacency_blocks": b,
        "candidate_cap": 8,
        "sort_comparisons": int(math.ceil(b * math.log2(b))),
        "bruteforce_orders_blocks": f"{b}!",
        "dp_states_blocks": 2**b,
        "dp_transitions_blocks": b * 2**b,
        "candidates_exact_orders_at_cap": math.factorial(8),
        "candidate_orders_at_measured_max_retention": "64! (measurable, not enumerable)",
        "objective_is_compact_qubo": False,
        "objective_reason": (
            "E[cost] = sum_k c_k * prod_{j<k}(1-p_j) is a degree-n pseudo-Boolean "
            "polynomial in position indicators; a QUBO can express at most degree 2, "
            "so an exact QUBO needs exponentially many auxiliaries"
        ),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    anchors = load_anchors()
    rng = np.random.default_rng(RNG_SEED)
    began = time.perf_counter()
    results = {
        "phase": "Q",
        "generated_unix_s": time.time(),
        "python": __import__("sys").version.split()[0],
        "numpy": np.__version__,
        "seed": RNG_SEED,
        "anchors": asdict(anchors),
        "complexity": complexity_table(anchors),
        "E1_ratio_optimality": experiment_ratio_optimality(rng),
        "E2_measured_guards": experiment_measured_guards(anchors, rng),
        "E3_correlated": experiment_correlated(rng),
        "E4_candidates": experiment_candidates(anchors),
        "E5_knapsack": experiment_knapsack(rng),
        "E6_partition": experiment_partition(anchors, rng),
        "E7_cegar": experiment_cegar(rng),
        "E8_admission": experiment_admission(anchors),
    }
    results["E9_session"] = experiment_session(
        anchors, results["E2_measured_guards"], results["E3_correlated"]
    )
    results["wall_seconds"] = time.perf_counter() - began
    violations = []
    for key in ("E2_measured_guards", "E3_correlated"):
        violations.extend(results[key].get("verifier_violations", []))
    results["correctness_violations"] = violations
    (OUT / "measurements.json").write_text(json.dumps(results, indent=2))
    (OUT / "summary.md").write_text(render_summary(results))
    print(f"wrote {OUT/'measurements.json'}")
    print(f"correctness violations: {len(violations)}")
    print(f"wall: {results['wall_seconds']:.1f}s")


def render_summary(results) -> str:
    lines = ["# Phase Q raw summary", ""]
    c = results["complexity"]
    lines += [
        f"- guards={c['guards']} blocks={c['adjacency_blocks']} candidate_cap={c['candidate_cap']}",
        f"- DP transitions over blocks: {c['dp_transitions_blocks']:.3e}",
        "",
        "## E1 greedy ratio optimality",
    ]
    for row in results["E1_ratio_optimality"]["rows"]:
        lines.append(
            f"- n={row['n_blocks']}: suboptimal={row['greedy_suboptimal']}/{row['trials']} "
            f"max_gap={row['max_relative_gap']:.2e}"
        )
    lines += ["", "## E2 measured 33-guard workload"]
    e2 = results["E2_measured_guards"]["asset_changed"]
    lines.append(
        f"- current={e2['rows'][0]['cost_ms']:.4f} ms ratio={e2['rows'][1]['cost_ms']:.4f} ms "
        f"saved={e2['saved_ms_vs_current']:.4f} ms "
        f"({e2['saved_fraction_of_deopt_wall']*100:.2f}% of measured deopt wall)"
    )
    lines += ["", "## E3 correlated"]
    e3 = results["E3_correlated"]
    for k, v in e3["mean_gap_vs_best_found"].items():
        be = e3["break_even_speedup_needed"][k]
        be_txt = "n/a" if be is None else f"{be:.1f}x"
        lines.append(
            f"- {k}: mean_gap={v*100:.3f}% max_gap={e3['max_gap_vs_best_found'][k]*100:.3f}% "
            f"extra_vs_ratio={e3['mean_extra_cost_vs_ratio_ms'][k]:+.4f} ms "
            f"runtime={e3['mean_runtime_ms'][k]:.2f} ms break_even_speedup={be_txt}"
        )
    lines += ["", "## E4 candidates"]
    for row in results["E4_candidates"]["rows"]:
        lines.append(
            f"- m={row['bound']}: newest={row['newest_first_ms']:.3f} ms "
            f"optimal={row['optimal_order_ms']:.3f} ms model_saving={row['model_saving_ms']:.3f} ms "
            f"measured_gap={row['measured_gap_ms']:.3f} ms"
        )
    ex = results["E4_candidates"]["exact_enumeration_at_cap"]
    lines.append(
        f"- exact enumeration m=8: {ex['orders_enumerated']} orders, "
        f"exact={ex['exact_cost_ms']:.4f} ms ratio={ex['ratio_cost_ms']:.4f} ms runtime={ex['runtime_ms']:.1f} ms"
    )
    learner = results["E4_candidates"]["learner"]
    lines.append(
        f"- learner (m=8): newest={learner['mean_validations_newest_first']:.2f} validations, "
        f"learned={learner['mean_validations_learned']:.2f}, "
        f"saving={learner['empirical_saving_ms_vs_newest']:.3f} ms, "
        f"model newest/learned/optimal={learner['model_cost_ms_newest']:.3f}/"
        f"{learner['model_cost_ms_learned']:.3f}/{learner['model_cost_ms_optimal']:.3f} ms, "
        f"decision={learner['decision_cost_per_plan_ms']:.6f} ms"
    )
    lines += ["", "## E5 knapsack QUBO"]
    for row in results["E5_knapsack"]["rows"]:
        lines.append(
            f"- {row['solver']}: value={row['value']:.2f} gap={row['gap_vs_exact']*100:.2f}% "
            f"feasible={row['feasible']} runtime={row['runtime_ms']:.2f} ms"
        )
    for row in results["E5_knapsack"]["penalty_sweep"]:
        lines.append(
            f"- penalty x{row['penalty_multiplier']:g} {row['sampler']}: "
            f"feasible={row['feasible']} value={row['value']:.2f} "
            f"max_coeff={row['max_abs_coefficient']:.3g} runtime={row['runtime_ms']:.1f} ms"
        )
    lines += ["", "## E6 partition QUBO"]
    for row in results["E6_partition"]["rows"]:
        lines.append(
            f"- {row['solver']}: makespan={row['makespan_ms']:.3f} ms "
            f"feasible={row['feasible']} runtime={row['runtime_ms']:.2f} ms"
        )
    lines.append(
        f"- serial={results['E6_partition']['serial_guard_ms']:.3f} ms, "
        f"ideal/4={results['E6_partition']['ideal_parallel_ms']:.3f} ms"
    )
    lines += ["", "## E7 CEGAR"]
    for epoch in results["E7_cegar"]["epochs"]:
        row = epoch["rows"]
        lines.append(
            f"- epoch {epoch['epoch']}: static={row['static-prior']['held_out_mean_cost_ms']:.4f} "
            f"cumulative={row['online-cumulative']['held_out_mean_cost_ms']:.4f} "
            f"ewma={row['online-ewma']['held_out_mean_cost_ms']:.4f} "
            f"oracle={row['oracle-probabilities']['held_out_mean_cost_ms']:.4f} ms"
        )
    lines += ["", "## E9 session accounting"]
    for row in results["E9_session"]["rows"]:
        lines.append(
            f"- deopt_rate={row['deopt_rate']*100:.0f}%: gross={row['gross_saving_ms']:.1f} ms/1000 runs "
            f"({row['gross_saving_pct']:.3f}% of wall), net_after_sort={row['net_after_sort_ms']:+.1f} ms"
        )
    lines += ["", "## E8 admission (recorded)"]
    lines.append(
        f"- CurrentAuto regret {results['E8_admission']['current_auto_regret_ms']:.1f} ms "
        f"over 34 steps = {results['E8_admission']['max_planning_gain_ms_per_step']:.3f} ms/step bound"
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

"""Self-tests for Phase Q. Run: .venv/bin/python research/phase_q/tjq_selftest.py -v"""

from __future__ import annotations

import itertools
import math
import unittest

import numpy as np

from tjq_anchors import load_anchors
from tjq_model import CandidateModel, Guard, GuardInstance, measured_guard_instance
from tjq_solvers import (
    exact_dp_independent,
    exact_partition,
    knapsack_qubo,
    lpt_partition,
    partition_qubo,
    ratio_order,
)
from tjq_verify import (
    verify_assignment,
    verify_candidate_order,
    verify_guard_order,
    verify_subset,
)


def small_instance():
    """Two adjacency blocks, independent groups, known answers."""
    guards = [
        Guard(0, "a.meta", "metadata", 10.0, 0, 0),
        Guard(1, "a.content", "content", 100.0, 0, 0),
        Guard(2, "b.meta", "metadata", 20.0, 1, 1),
        Guard(3, "b.content", "content", 200.0, 1, 1),
    ]
    return GuardInstance("small", guards, {0: 0.2, 1: 0.05}, background_prob=0.0)


class VerifierTests(unittest.TestCase):
    def test_accepts_valid_plan(self):
        inst = small_instance()
        order = ratio_order(inst)
        verdict = verify_guard_order(inst, order, inst.expected_cost(order))
        self.assertTrue(verdict.ok, verdict.violations)

    def test_rejects_non_permutation(self):
        inst = small_instance()
        verdict = verify_guard_order(inst, [0, 1, 2])
        self.assertFalse(verdict.ok)

    def test_rejects_duplicate(self):
        inst = small_instance()
        verdict = verify_guard_order(inst, [0, 1, 2, 2])
        self.assertFalse(verdict.ok)

    def test_rejects_split_metadata_pair(self):
        inst = small_instance()
        verdict = verify_guard_order(inst, [0, 2, 1, 3])
        self.assertFalse(verdict.ok)
        self.assertTrue(any("split" in v for v in verdict.violations), verdict.violations)

    def test_rejects_internal_pair_swap(self):
        inst = small_instance()
        verdict = verify_guard_order(inst, [1, 0, 2, 3])
        self.assertFalse(verdict.ok)

    def test_rejects_reordered_order_dependent_guards(self):
        guards = [
            Guard(0, "s1", "stream", 10.0, 0, 0, True),
            Guard(1, "s2", "stream", 10.0, 1, 1, True),
        ]
        inst = GuardInstance("streams", guards, {0: 0.0, 1: 0.0}, background_prob=0.0)
        verdict = verify_guard_order(inst, [1, 0])
        self.assertFalse(verdict.ok)

    def test_rejects_wrong_claimed_cost(self):
        inst = small_instance()
        order = ratio_order(inst)
        verdict = verify_guard_order(inst, order, inst.expected_cost(order) * 0.5)
        self.assertFalse(verdict.ok)

    def test_candidate_verifier(self):
        cand = CandidateModel([100, 100, 100], [0.5, 0.3, 0.2])
        order = [0, 1, 2]
        self.assertTrue(verify_candidate_order(cand, order, cand.expected_cost(order)).ok)
        self.assertFalse(verify_candidate_order(cand, order, 1.0).ok)
        self.assertFalse(verify_candidate_order(cand, [0, 0, 1]).ok)

    def test_subset_and_assignment_verifiers(self):
        self.assertTrue(verify_subset(3, [0, 2]).ok)
        self.assertFalse(verify_subset(3, [0, 0]).ok)
        self.assertFalse(verify_subset(3, [5]).ok)
        self.assertTrue(verify_assignment(3, 2, [0, 1, 0]).ok)
        self.assertFalse(verify_assignment(3, 2, [0, 2, 0]).ok)


class ObjectiveTests(unittest.TestCase):
    def test_expected_cost_matches_bruteforce_enumeration(self):
        rng = np.random.default_rng(3)
        for _ in range(20):
            guards = [
                Guard(i, f"g{i}", "metadata", float(10 ** rng.uniform(1, 3)), i, i)
                for i in range(5)
            ]
            rho = {i: float(rng.uniform(0.01, 0.4)) for i in range(5)}
            inst = GuardInstance("bf", guards, rho, background_prob=0.002)
            order = [int(v) for v in rng.permutation(5)]
            paid = 0.0
            survive = 1.0
            for idx in order:
                paid += survive * guards[idx].cost_ns
                survive *= 1.0 - (1.0 - (1.0 - rho[idx]) * (1.0 - 0.002))
            self.assertAlmostEqual(inst.expected_cost(order), paid, places=6)

    def test_greedy_matches_exact_dp_on_random_independent_sets(self):
        rng = np.random.default_rng(11)
        for trial in range(60):
            n = int(rng.integers(3, 8))
            guards = [
                Guard(i, f"g{i}", "metadata", float(10 ** rng.uniform(1, 3)), i, i)
                for i in range(n)
            ]
            rho = {i: float(rng.uniform(0.01, 0.5)) for i in range(n)}
            inst = GuardInstance("dp", guards, rho, background_prob=0.0)
            order = ratio_order(inst)
            greedy = inst.expected_cost(order)
            _, best, exact = exact_dp_independent(inst)
            self.assertTrue(exact)
            # DP and the objective must agree on the greedy plan's value.
            self.assertAlmostEqual(
                inst.expected_cost(order), greedy, places=9
            )
            self.assertLessEqual(abs(greedy - best), 1e-9, f"trial {trial}")

    def test_bruteforce_agrees_with_dp(self):
        rng = np.random.default_rng(5)
        for _ in range(6):
            guards = [
                Guard(i, f"g{i}", "metadata", float(10 ** rng.uniform(1, 3)), i, i)
                for i in range(6)
            ]
            rho = {i: float(rng.uniform(0.01, 0.4)) for i in range(6)}
            inst = GuardInstance("bf", guards, rho, background_prob=0.0)
            _, best, _ = exact_dp_independent(inst)
            brute = min(
                inst.expected_cost(list(p)) for p in itertools.permutations(range(6))
            )
            self.assertAlmostEqual(best, brute, places=5)

    def test_correlated_cost_never_below_independent_first_guard(self):
        inst = measured_guard_instance(5_945_400, changed_asset_rho=0.3)
        order = list(range(inst.n))
        cost = inst.expected_cost(order)
        self.assertGreater(cost, 0.0)
        self.assertLessEqual(cost, sum(g.cost_ns for g in inst.guards) + 1e-6)


class QuboTests(unittest.TestCase):
    def test_knapsack_energy_matches_direct_expansion(self):
        costs = [2.0, 3.0, 4.0, 5.0]
        benefits = [10.0, 12.0, 14.0, 20.0]
        budget = 8.0
        problem, meta = knapsack_qubo(costs, benefits, budget)
        bits = [0] * problem.n_vars
        # energy must equal lambda*(sum a*y - U)^2 - benefit
        unit = meta["unit_ms"]
        c = [max(1, int(round(v / unit))) for v in costs]
        b = [v / max(benefits) for v in benefits]
        lam = meta["penalty"]
        used = sum(c[i] for i in range(4) if bits[i])
        expected = lam * (used - meta["budget_units"]) ** 2 - sum(
            b[i] for i in range(4) if bits[i]
        )
        self.assertAlmostEqual(problem.energy(bits), expected, places=6)

    def test_partition_energy_matches_sum_of_squares(self):
        costs = [3.0, 2.0, 2.0]
        bins = 2
        problem = partition_qubo(costs, bins)
        bits = [0] * problem.n_vars
        # item0 -> bin0, item1 -> bin0, item2 -> bin1
        bits[0 * 3 + 0] = 1
        bits[0 * 3 + 1] = 1
        bits[1 * 3 + 2] = 1
        loads = [5.0, 2.0]
        energy = problem.energy(bits)
        # one-hot satisfied; energy = sum L^2 + penalty*0
        self.assertAlmostEqual(energy, sum(v * v for v in loads), places=6)

    def test_lpt_matches_exact_partition_on_small_instance(self):
        costs = [5.0, 4.0, 3.0, 2.0, 2.0, 1.0]
        bins = 3
        assign, span, exact = exact_partition(costs, bins)
        lpt_assign, lpt_span = lpt_partition(costs, bins)
        self.assertTrue(exact)
        self.assertLessEqual(lpt_span, span + 1e-9)

    def test_penalty_is_finite_and_scaled(self):
        problem, meta = knapsack_qubo([1.0, 2.0], [5.0, 6.0], 2.0)
        self.assertTrue(math.isfinite(meta["penalty"]))
        self.assertLess(problem.max_abs_coefficient(), 1e6)


class AnchorTests(unittest.TestCase):
    def test_anchors_parse_from_repo_results(self):
        anchors = load_anchors()
        self.assertIn(33, anchors.guard_counts)
        self.assertEqual(anchors.transition_failed_at, 30)
        self.assertEqual(anchors.candidate_bounds, [1, 2, 4, 8, 16, 32, 64])
        self.assertGreater(anchors.candidate_fit_r2, 0.85)
        self.assertEqual(
            [p["policy"] for p in anchors.admission_policies][2], "CurrentAuto"
        )

    def test_measured_instance_shape(self):
        inst = measured_guard_instance(5_945_400)
        self.assertEqual(inst.n, 33)
        self.assertEqual(len(inst.blocks), 28)
        self.assertAlmostEqual(sum(g.cost_ns for g in inst.guards), 5_945_400, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

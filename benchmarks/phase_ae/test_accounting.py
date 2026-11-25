#!/usr/bin/env python3
"""Permanent regressions for the Phase AE competitive harness accounting.

These tests exist because Phase AD got this wrong three ways: it labelled a measured
invocation from a *different* invocation's decision, it verified only one warm observation,
and its session totals started from a pre-populated cache.  Every published row now has to
satisfy ``check_row`` and every break-even is recomputed here.

Run: ``python3 benchmarks/phase_ae/test_accounting.py``
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import competitive_matrix as matrix  # noqa: E402

RESULTS = REPO / "benchmarks" / "results" / "phaseae" / "matrix.json"


def row(**overrides) -> dict:
    base = {
        "arm": "tj-ae", "workload": "gzip-file", "mode": "cold", "size": 2,
        "all_correct": True, "cache_bytes_final": 0,
        "invocations": [
            {
                "index": 0, "wall_ns": 1_000_000, "decision": "executed",
                "decision_source": "tracejit-report", "hits": 0, "misses": 1,
                "uncacheable": 0, "restored": False, "exit": 0, "variant": 0,
                "correct": True, "stdout_sha256": "a", "expected_stdout_sha256": "a",
                "outputs_sha256": {}, "cache_bytes": 0, "error": None,
            },
            {
                "index": 1, "wall_ns": 500_000, "decision": "hit",
                "decision_source": "tracejit-report", "hits": 1, "misses": 0,
                "uncacheable": 0, "restored": True, "exit": 0, "variant": 0,
                "correct": True, "stdout_sha256": "a", "expected_stdout_sha256": "a",
                "outputs_sha256": {}, "cache_bytes": 10, "error": None,
            },
        ],
    }
    base.update(overrides)
    return base


class BreakEven(unittest.TestCase):
    def test_exact_ratio_is_not_inflated(self):
        # (cold - hit) / (direct - hit) = (110 - 10) / (60 - 10) = 2 exactly.
        self.assertEqual(matrix.break_even(110, 10, 60)["integer_invocations"], 2)

    def test_rounds_up_to_the_next_whole_invocation(self):
        # 90 / 50 = 1.8: two invocations are needed, not one.
        self.assertEqual(matrix.break_even(100, 10, 60)["integer_invocations"], 2)

    def test_three_when_one_hit_does_not_repay(self):
        # 1 MiB incompressible gzip in Phase AD: (56.7 - 7.7) / (29.9 - 7.7) = 2.2.
        self.assertEqual(matrix.break_even(56_700_000, 7_700_000, 29_900_000)["integer_invocations"], 3)

    def test_never_when_a_hit_costs_more(self):
        self.assertIsNone(matrix.break_even(35_600_000, 13_100_000, 3_200_000)["integer_invocations"])

    def test_noisy_negative_premium_is_two(self):
        self.assertEqual(matrix.break_even(900, 1_000, 2_000)["integer_invocations"], 2)


class RowInvariants(unittest.TestCase):
    def test_valid_row_passes(self):
        self.assertEqual(matrix.check_row(row()), [])

    def test_hit_without_engine_decision_is_rejected(self):
        bad = row()
        bad["invocations"][1]["decision_source"] = "none"
        self.assertTrue(any("without an engine decision" in p for p in matrix.check_row(bad)))

    def test_hit_without_restoration_evidence_is_rejected(self):
        bad = row()
        bad["invocations"][1]["restored"] = None
        self.assertTrue(any("restoration evidence" in p for p in matrix.check_row(bad)))

    def test_missing_output_verification_is_rejected(self):
        bad = row()
        del bad["invocations"][0]["correct"]
        self.assertTrue(any("without output verification" in p for p in matrix.check_row(bad)))

    def test_incorrect_output_is_rejected(self):
        bad = row()
        bad["invocations"][1]["correct"] = False
        bad["all_correct"] = False
        problems = matrix.check_row(bad)
        self.assertTrue(any("incorrect output" in p for p in problems))

    def test_cold_session_starting_with_a_hit_is_rejected(self):
        bad = row()
        bad["invocations"][0] = dict(bad["invocations"][1], index=0)
        self.assertTrue(any("cold session began with a hit" in p for p in matrix.check_row(bad)))

    def test_firebuild_row_without_stats_is_rejected(self):
        bad = row(arm="fb862-default")
        for record in bad["invocations"]:
            record["decision_source"] = "firebuild-stats"
            record["stats_parsed"] = False
        self.assertTrue(any("Firebuild stats missing" in p for p in matrix.check_row(bad)))

    def test_wrong_size_is_rejected(self):
        self.assertTrue(any("invocations for size" in p for p in matrix.check_row(row(size=5))))


class CacheFootprint(unittest.TestCase):
    def test_nested_cache_files_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "b").mkdir(parents=True)
            (root / "a" / "b" / "blob").write_bytes(b"x" * 10)
            (root / "top").write_bytes(b"y" * 5)
            self.assertEqual(matrix.tree_bytes(root), 15)

    def test_missing_cache_is_zero(self):
        self.assertEqual(matrix.tree_bytes(Path("/nonexistent/phase-ae-cache")), 0)


class PublishedResults(unittest.TestCase):
    """Every committed row must satisfy the same invariants as a fresh run."""

    def test_published_rows_are_accounted(self):
        if not RESULTS.is_file():
            self.skipTest("no published matrix yet")
        payload = json.loads(RESULTS.read_text())
        problems = []
        for published in payload["rows"]:
            problems.extend(matrix.check_row(published))
        self.assertEqual(problems, [], "\n".join(problems[:5]))

    def test_published_rows_carry_per_invocation_wall_times(self):
        if not RESULTS.is_file():
            self.skipTest("no published matrix yet")
        payload = json.loads(RESULTS.read_text())
        for published in payload["rows"]:
            self.assertEqual(len(published["invocations"]), published["size"])
            for record in published["invocations"]:
                self.assertGreater(record["wall_ns"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

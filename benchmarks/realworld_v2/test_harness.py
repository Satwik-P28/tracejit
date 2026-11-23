#!/usr/bin/env python3
"""Permanent self-tests for the Phase AA benchmark harness.

Two things are tested here that a passing benchmark run cannot prove on its own.

1. **The oracle actually rejects wrong replays.**  A comparison function that
   silently misses a stale output turns every "0 incorrect HITs" claim into a
   tautology, so each covered observation gets a deliberately wrong twin and the
   oracle must report the difference.  Advisory-only differences must *not* be
   reported as failures.

2. **The accounting closes.**  Every eligibility counter is recomputed from the
   rows; a hand-edited aggregate, a dropped row, a wrong rate or a HIT recorded
   without the decision that proves it must make ``validate.py`` fail.

Run with:

    python3 -m unittest discover -s benchmarks/realworld_v2 -p 'test_*.py'
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import oracle  # noqa: E402
import runner  # noqa: E402
import validate  # noqa: E402

RESULTS = HERE.parent / "results" / "phaseaa1" / "results.json"


def workspace(root: Path) -> dict:
    return oracle.observe_workspace(root)


def observation(root: Path, exit_status: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> dict:
    return oracle.process_observation(exit_status, stdout, stderr, workspace(root))


def covered_fields(diff: dict) -> set[str]:
    return {difference["field"] for difference in diff["covered_differences"]}


class OracleRejectsWrongReplay(unittest.TestCase):
    """A wrong replay must be rejected for every covered observation."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="tracejit-oracle-test-")
        self.root = Path(self._temporary.name)
        self.native = self.root / "native"
        self.traced = self.root / "traced"
        for directory in (self.native, self.traced):
            directory.mkdir()
            (directory / "out.txt").write_bytes(b"correct output\n")
            (directory / "sub").mkdir()
            (directory / "sub" / "data.bin").write_bytes(b"\x00\x01\x02")
        os.symlink("out.txt", self.native / "link")
        os.symlink("out.txt", self.traced / "link")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def assert_rejected(self, field: str) -> None:
        diff = oracle.compare(observation(self.native), observation(self.traced))
        self.assertFalse(diff["match"], f"{field}: a wrong replay was accepted")
        self.assertIn(field, covered_fields(diff), diff)

    def test_identical_twins_match(self) -> None:
        self.assertTrue(oracle.compare(observation(self.native), observation(self.traced))["match"])

    def test_stale_output_content_is_rejected(self) -> None:
        (self.traced / "out.txt").write_bytes(b"stale output\n")
        self.assert_rejected("entry")

    def test_missing_created_file_is_rejected(self) -> None:
        (self.traced / "sub" / "data.bin").unlink()
        self.assert_rejected("missing_path")

    def test_unexpected_file_is_rejected(self) -> None:
        (self.traced / "extra.txt").write_bytes(b"not produced by native\n")
        self.assert_rejected("unexpected_path")

    def test_deleted_file_that_native_kept_is_rejected(self) -> None:
        (self.traced / "out.txt").unlink()
        self.assert_rejected("missing_path")

    def test_mode_change_is_rejected(self) -> None:
        (self.traced / "out.txt").chmod(0o600)
        self.assert_rejected("entry")

    def test_symlink_retarget_is_rejected(self) -> None:
        (self.traced / "link").unlink()
        os.symlink("sub/data.bin", self.traced / "link")
        self.assert_rejected("entry")

    def test_symlink_replaced_by_file_is_rejected(self) -> None:
        (self.traced / "link").unlink()
        (self.traced / "link").write_bytes(b"out.txt")
        self.assert_rejected("entry")

    def test_broken_hardlink_group_is_rejected(self) -> None:
        (self.native / "alias").hardlink_to(self.native / "out.txt")
        (self.traced / "alias").write_bytes(b"correct output\n")
        diff = oracle.compare(observation(self.native), observation(self.traced))
        self.assertFalse(diff["match"], "a copied file is not a hard link")
        fields = covered_fields(diff)
        self.assertTrue(fields & {"entry", "hardlink_groups"}, diff)

    def test_directory_membership_change_is_rejected(self) -> None:
        (self.traced / "sub" / "new").mkdir()
        self.assert_rejected("unexpected_path")

    def test_stdout_difference_is_rejected(self) -> None:
        diff = oracle.compare(
            observation(self.native, stdout=b"one"), observation(self.traced, stdout=b"two")
        )
        self.assertFalse(diff["match"])
        self.assertIn("stdout_sha256", covered_fields(diff))

    def test_stderr_difference_is_rejected(self) -> None:
        diff = oracle.compare(
            observation(self.native, stderr=b"warn"), observation(self.traced, stderr=b"")
        )
        self.assertFalse(diff["match"])
        self.assertIn("stderr_sha256", covered_fields(diff))

    def test_exit_status_difference_is_rejected(self) -> None:
        diff = oracle.compare(observation(self.native, exit_status=1), observation(self.traced))
        self.assertFalse(diff["match"])
        self.assertIn("exit_status", covered_fields(diff))

    def test_advisory_only_difference_is_not_a_failure(self) -> None:
        os.utime(self.traced / "out.txt", ns=(1_000_000_000, 1_000_000_000))
        diff = oracle.compare(observation(self.native), observation(self.traced))
        self.assertTrue(diff["match"], diff)
        self.assertTrue(diff["out_of_contract_differences"], "mtime should be reported as advisory")

    def test_prestate_comparison_catches_different_starting_bytes(self) -> None:
        # The traced twin starts with a stale output. A final-state comparison
        # would happily match two runs that both "produced" the same bytes, but
        # the replay never had to restore anything.
        (self.traced / "out.txt").write_bytes(b"left over\n")
        prestate = oracle.compare_workspace_trees(workspace(self.native), workspace(self.traced))
        self.assertFalse(prestate["match"])
        self.assertEqual(covered_fields(prestate), {"entry"})


class HitAccounting(unittest.TestCase):
    def test_both_fields_must_agree(self) -> None:
        self.assertTrue(runner.is_hit({"kind": "Reused", "cache_decision": "Reused"}))
        self.assertFalse(runner.is_hit({"kind": "Reused", "cache_decision": "Executed"}))
        self.assertFalse(runner.is_hit({"kind": "Executed", "cache_decision": "Executed"}))
        self.assertFalse(runner.is_hit(None))
        self.assertTrue(
            runner.hit_accounting_disagrees({"kind": "Reused", "cache_decision": "Executed"})
        )
        self.assertFalse(
            runner.hit_accounting_disagrees({"kind": "Reused", "cache_decision": "Reused"})
        )


class PlainReportDecision(unittest.TestCase):
    """The timed arm reads TraceJIT's plain report; that parser must be exact."""

    def test_hit(self) -> None:
        decision = runner.parse_plain_decision(
            b"\nTraceJIT\n\nguards         3/3 passed\ncache          HIT\nruntime        12.3ms\n"
        )
        self.assertEqual(decision["kind"], "Reused")
        self.assertEqual(decision["cache_decision"], "Reused")
        self.assertTrue(runner.is_hit(decision))

    def test_miss_deopt_and_skip(self) -> None:
        for line, expected in (
            ("cache          MISS", "Ineligible"),
            ("cache          DEOPT", "Deoptimized"),
            ("cache          SKIP (admission policy)", "Skipped"),
        ):
            decision = runner.parse_plain_decision(f"\nTraceJIT\n\n{line}\n".encode())
            self.assertEqual(decision["cache_decision"], expected, line)
            self.assertFalse(runner.is_hit(decision), line)

    def test_no_cache_line_is_not_a_hit(self) -> None:
        decision = runner.parse_plain_decision(b"\nTraceJIT\n\nclassified     Unknown\n")
        self.assertIsNone(decision["cache_decision"])
        self.assertFalse(runner.is_hit(decision))

    def test_workload_cannot_forge_a_hit(self) -> None:
        # The child prints the marker and the hit line before TraceJIT's own
        # report; only the last banner block may be read.
        decision = runner.parse_plain_decision(
            b"cache          HIT\n\nTraceJIT\n\ncache          MISS\n"
        )
        self.assertFalse(runner.is_hit(decision))


class ManifestIsIndependentOfLocalState(unittest.TestCase):
    """The manifest must not depend on whether a vendor cache exists."""

    def test_vendor_presence_does_not_change_the_manifest(self) -> None:
        import corpus

        self.assertEqual(
            corpus.manifest_entries(None),
            corpus.manifest_entries(Path("/nonexistent/vendor")),
            "the manifest must be derivable without any local download cache",
        )

    def test_committed_manifest_names_this_corpus_source(self) -> None:
        import hashlib

        committed = json.loads((HERE / "manifest.json").read_text())
        self.assertEqual(
            committed["corpus_source_sha256"],
            hashlib.sha256((HERE / "corpus.py").read_bytes()).hexdigest(),
            "manifest.json is stale; regenerate it with --mode manifest",
        )


class AccountingCloses(unittest.TestCase):
    def setUp(self) -> None:
        if not RESULTS.is_file():
            self.skipTest(f"no committed evidence at {RESULTS}")
        self.results = json.loads(RESULTS.read_text())

    def test_committed_evidence_closes(self) -> None:
        errors = validate.accounting_errors(copy.deepcopy(self.results))
        self.assertEqual(errors, [])

    def test_dropped_row_is_rejected(self) -> None:
        broken = copy.deepcopy(self.results)
        broken["workloads"].pop()
        self.assertTrue(validate.accounting_errors(broken))

    def test_inflated_rate_is_rejected(self) -> None:
        broken = copy.deepcopy(self.results)
        cell = next(iter(broken["aggregate"]["eligibility_by_tier_and_policy"].values()))
        cell["rate"] = 0.99
        self.assertTrue(validate.semantic_errors(broken))

    def test_claimed_reuse_without_a_decision_is_rejected(self) -> None:
        broken = copy.deepcopy(self.results)
        for row in broken["workloads"]:
            if row["status"] == "refused":
                row["status"] = "reused"
                break
        self.assertTrue(validate.semantic_errors(broken))

    def test_extra_tool_unavailable_claim_is_rejected(self) -> None:
        broken = copy.deepcopy(self.results)
        cell = next(iter(broken["aggregate"]["eligibility_by_tier_and_policy"].values()))
        # Legacy cells (Phase AA) omit the field, so adding one can coincidentally
        # equal the truth (that cell really has one unavailable tool). Add two so
        # the claim is unambiguously inflated either way.
        cell["tool_unavailable"] = cell.get("tool_unavailable", 0) + 2
        self.assertTrue(validate.accounting_errors(broken))

    def test_hit_with_disagreeing_decision_is_rejected(self) -> None:
        broken = copy.deepcopy(self.results)
        for row in broken["workloads"]:
            if row["status"] == "reused":
                for decision in row["decisions"]:
                    if decision.get("kind") == "Reused":
                        decision["cache_decision"] = "Executed"
                        break
                break
        messages = validate.accounting_errors(broken)
        self.assertTrue(any("accounting disagreement" in message for message in messages), messages)

    def test_fabricated_hit_on_a_refused_row_is_rejected(self) -> None:
        broken = copy.deepcopy(self.results)
        for row in broken["workloads"]:
            if row["status"] == "refused":
                row["decisions"].append(
                    {"kind": "Reused", "cache_decision": "Reused", "step": "fabricated"}
                )
                break
        self.assertTrue(validate.accounting_errors(broken))


if __name__ == "__main__":
    unittest.main()

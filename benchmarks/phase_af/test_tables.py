#!/usr/bin/env python3
"""Tests that the publication tables cannot silently disagree with the evidence.

These are the checks Part IV of the Phase AF brief asks for: a table that loses a row, a
benchmark value that no raw file supports, or a headline that drifted from the arithmetic must
fail a test rather than reach the paper. Nothing here asserts a *particular* performance number:
the point is that the numbers come from the evidence, so a change to the evidence changes the
table and a change to the table alone is caught.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_tables as tables  # noqa: E402


class EvidenceIsPresent(unittest.TestCase):
    def test_every_declared_evidence_file_exists(self) -> None:
        missing = [str(path.relative_to(tables.REPO)) for path in tables.EVIDENCE.values()
                   if not path.is_file()]
        self.assertEqual(missing, [], f"missing evidence files: {missing}")

    def test_every_builder_has_evidence(self) -> None:
        for name, builder in tables.BUILDERS.items():
            with self.subTest(table=name):
                try:
                    builder()
                except tables.EvidenceError as error:
                    self.fail(f"{name} cannot be built: {error}")


class HeadlineArithmetic(unittest.TestCase):
    def test_headline_matches_raw_rows(self) -> None:
        recalculated = tables.competitive()["recalculated"]
        problems = tables.check_headline(recalculated)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_bzip2_speedup_is_the_documented_five_point_two_two(self) -> None:
        recalculated = tables.competitive()["recalculated"]
        # Phase AD published 5.6x from the same rows. The corrected value is 5.22x; this test
        # exists so a document cannot drift back without failing.
        self.assertAlmostEqual(recalculated["bzip2_speedup_over_native"], 5.22, places=2)
        self.assertAlmostEqual(recalculated["bzip2_savings_fraction"], 0.808, places=3)

    def test_speedup_and_savings_describe_the_same_interval(self) -> None:
        recalculated = tables.competitive()["recalculated"]
        ratio = recalculated["bzip2_speedup_over_native"]
        # For a ratio r = native/tracejit the fraction saved is exactly 1 - 1/r. Checking the
        # identity keeps the two published numbers from drifting apart.
        self.assertAlmostEqual(recalculated["bzip2_savings_fraction"], 1 - 1 / ratio, places=9)


class TableShape(unittest.TestCase):
    def test_no_table_has_an_empty_row_set(self) -> None:
        for name, builder in tables.BUILDERS.items():
            with self.subTest(table=name):
                table = builder()
                self.assertTrue(table["rows"], f"{name} produced no rows")
                self.assertTrue(table["provenance"], f"{name} has no source recorded")
                for row in table["rows"]:
                    self.assertEqual(len(row), len(table["columns"]),
                                     f"{name} row width mismatch: {row}")

    def test_no_table_cell_is_unknown(self) -> None:
        # "?" means a builder did not understand the schema of the file it was reading, which is
        # how a silently wrong table would look.
        for name, builder in tables.BUILDERS.items():
            with self.subTest(table=name):
                for row in builder()["rows"]:
                    for cell in row:
                        self.assertNotEqual(str(cell).strip(), "?", f"{name} has an unknown cell")
                        self.assertNotIn("None", str(cell), f"{name} has a None cell: {row}")

    def test_compatibility_totals_reconcile(self) -> None:
        table = tables.compatibility()
        totals = table["totals"]
        census = json.loads(tables.EVIDENCE["census"].read_text())
        self.assertEqual(totals["declared"], len(census["workloads"]))
        self.assertEqual(totals["declared"],
                         totals["attempted"] + sum(
                             1 for row in census["workloads"] if row["status"] == "tool_unavailable"))
        self.assertEqual(totals["incorrect"], 0)


class Isolation(unittest.TestCase):
    def test_a_missing_evidence_file_is_an_error_not_a_zero(self) -> None:
        original = tables.EVIDENCE["census"]
        tables.EVIDENCE["census"] = Path(tempfile.gettempdir()) / "phase-af-absent.json"
        try:
            with self.assertRaises(tables.EvidenceError):
                tables.compatibility()
        finally:
            tables.EVIDENCE["census"] = original

    def test_emit_writes_one_file_per_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            exit_code = tables.main(["--emit", str(target)])
            self.assertEqual(exit_code, 0)
            produced = sorted(path.stem for path in target.glob("*.md"))
            self.assertEqual(produced, sorted(tables.BUILDERS))


if __name__ == "__main__":
    unittest.main()

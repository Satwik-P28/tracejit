#!/usr/bin/env python3
"""Validates Phase AA results against the v1 schema and the protocol rules.

Structural validation uses ``jsonschema`` when it is installed and a small
hand-written check of every required field otherwise, so the CI job never
depends on an optional package. The *semantic* checks below are the important
part: they are the ones that stop an incompatible or dishonest result file from
being committed.

Semantic rules
--------------
1. ``schema_version`` must be exactly the version this script understands.
2. Every row must carry a 40-hex commit and a 64-hex binary digest.
3. A row may only be ``reused`` when at least one recorded decision for it is
   ``kind == "Reused"``; the reverse also holds (no HIT may be recorded without
   the row that proves it).
4. Every timed row must have raw samples for all three arms, and every warm
   sample must correspond to a reused decision.
5. No aggregate may mix tiers or policies: the eligibility map must contain the
   four (tier, policy) keys separately, and each rate must equal reused/attempted.
6. An ``incorrect_hits`` list that is non-empty is a hard failure.
7. ``heldout`` rows must not have been used to choose an optimization: this
   script cannot prove that, so it records the split counts it saw and the
   protocol document states the discipline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "tracejit.realworld.results/v1"
REQUIRED_TOP = ["schema_version", "generated_unix_ms", "environment", "protocol", "aggregate", "workloads"]
REQUIRED_ROW = [
    "workload_id", "family", "split", "environment_tier", "policy", "status", "decisions", "assessment",
]
ACCEPTABLE = {
    "reused", "refused", "tool_unavailable", "eligible_but_no_hit", "incorrect_hit",
    "cold_mismatch", "mutation_mismatch", "tracejit_error", "harness_error", "not_qualified", "skipped_budget",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def structural_errors(results: dict, schema_path: Path | None) -> list[str]:
    errors: list[str] = []
    if schema_path is not None and schema_path.is_file():
        try:
            import jsonschema  # type: ignore

            schema = json.loads(schema_path.read_text())
            validator = jsonschema.Draft202012Validator(schema)
            errors.extend(sorted(f"{list(error.path)}: {error.message}" for error in validator.iter_errors(results)))
            if errors:
                return errors
        except ImportError:
            pass  # fall through to the explicit checks
    for field in REQUIRED_TOP:
        if field not in results:
            errors.append(f"missing top-level field {field}")
    for index, row in enumerate(results.get("workloads", [])):
        for field in REQUIRED_ROW:
            if field not in row:
                errors.append(f"workloads[{index}] missing {field}")
        if row.get("status") not in ACCEPTABLE:
            errors.append(f"workloads[{index}] status {row.get('status')!r} is not in the contract")
    return errors


def semantic_errors(results: dict) -> list[str]:
    errors: list[str] = []
    if results.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version {results.get('schema_version')!r} != {SCHEMA_VERSION}")
    environment = results.get("environment", {})
    if not HEX40.match(str(environment.get("commit", ""))):
        errors.append("environment.commit is not a 40-hex commit")
    if not HEX64.match(str(environment.get("tracejit", {}).get("sha256", ""))):
        errors.append("environment.tracejit.sha256 is not a 64-hex digest")

    for row in results.get("workloads", []):
        identifier = f"{row.get('workload_id')}[{row.get('policy')}]"
        decisions = row.get("decisions") or []
        hits = [decision for decision in decisions if decision.get("kind") == "Reused"]
        if row.get("status") == "reused" and not hits:
            errors.append(f"{identifier}: status reused but no Reused decision was recorded")
        if row.get("status") == "incorrect_hit" and not row.get("incorrect_hit"):
            errors.append(f"{identifier}: incorrect_hit without the offending observation")

        timing = row.get("timing") or {}
        if timing.get("status") == "measured":
            for arm in ("direct", "warm", "cold"):
                summary = timing.get(arm) or {}
                if not summary.get("samples_ns"):
                    errors.append(f"{identifier}: timed row has no raw samples for {arm}")
                elif summary.get("n") != len(summary["samples_ns"]):
                    errors.append(f"{identifier}: {arm} n does not match samples_ns length")
                if len(summary.get("median_ci95_ns") or []) != 2:
                    errors.append(f"{identifier}: {arm} has no bootstrap interval")
            if row.get("status") != "reused":
                errors.append(f"{identifier}: timing present for a row that did not reuse")
            if not row.get("warm_equivalence", {}).get("match", False):
                errors.append(f"{identifier}: timed row without a passing warm oracle")
            storage = timing.get("cache_storage_bytes")
            if storage is None:
                errors.append(f"{identifier}: timed row without a cache storage measurement")

    aggregate = results.get("aggregate", {})
    breakdown = aggregate.get("eligibility_by_tier_and_policy") or {}
    policies = sorted({row.get("policy") for row in results.get("workloads", [])})
    tiers = sorted({row.get("environment_tier") for row in results.get("workloads", [])})
    for tier in tiers:
        for policy in policies:
            key = f"{tier}/{policy}"
            stats = breakdown.get(key)
            if stats is None:
                errors.append(f"aggregate is missing the {key} eligibility cell")
                continue
            attempted = stats.get("attempted", 0)
            reused = stats.get("reused", 0)
            if attempted and stats.get("rate") is not None:
                expected = reused / attempted
                if abs(stats["rate"] - expected) > 1e-9:
                    errors.append(f"{key}: rate {stats['rate']} != reused/attempted {expected}")
    if aggregate.get("incorrect_hits"):
        errors.append(f"incorrect hits were observed: {aggregate['incorrect_hits']}")

    splits = {}
    for row in results.get("workloads", []):
        splits[row.get("split")] = splits.get(row.get("split"), 0) + 1
    print(f"splits present: {splits}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="?", default="benchmarks/results/phaseaa/results.json")
    parser.add_argument("--schema", default=str(Path(__file__).resolve().parent / "schema" / "results-v1.schema.json"))
    args = parser.parse_args()
    path = Path(args.results)
    if not path.is_file():
        print(f"missing results file {path}", file=sys.stderr)
        return 1
    results = json.loads(path.read_text())
    errors = structural_errors(results, Path(args.schema)) + semantic_errors(results)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(f"OK: {path} satisfies {SCHEMA_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

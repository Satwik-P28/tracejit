#!/usr/bin/env python3
"""Compares a new Phase AA result file with a compatible baseline.

Designed for a noisy shared CI runner:

* **Correctness** regressions fail. A new incorrect hit, a row that stopped
  reusing without a recorded reason, or a malformed result file is an error.
* **Latency** changes are reported, never fail the build, unless a workload
  regressed by more than ``--fail-ratio`` (default 3.0) *and* the paired ratio
  interval is entirely on the wrong side.
* Results from an incompatible environment are refused as a comparison
  (``incompatible_environment``, exit 0); comparing a 2-vCPU VM with a 4-vCPU
  runner is not a regression measurement.

Exit status: 0 pass/incomparable, 1 correctness or hard-latency regression, 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def environment_key(results: dict) -> dict:
    environment = results.get("environment", {})
    return {
        "kernel": environment.get("kernel", {}).get("release"),
        "cpu_model": environment.get("cpu", {}).get("model"),
        "logical_count": environment.get("cpu", {}).get("logical_count"),
        "libc_build_id": (environment.get("libc") or {}).get("build_id"),
        "filesystem": (environment.get("filesystem") or "").splitlines()[0] if environment.get("filesystem") else None,
    }


def rows_by_key(results: dict) -> dict:
    return {
        (row["workload_id"], row["policy"]): row
        for row in results.get("workloads", [])
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--output", default="")
    parser.add_argument("--fail-ratio", type=float, default=3.0)
    args = parser.parse_args()

    baseline = load(Path(args.baseline))
    candidate = load(Path(args.candidate))
    if baseline.get("schema_version") != candidate.get("schema_version"):
        print("schema versions differ; refusing to compare", file=sys.stderr)
        return 2

    base_key, cand_key = environment_key(baseline), environment_key(candidate)
    report: dict = {
        "baseline_commit": baseline.get("environment", {}).get("commit"),
        "candidate_commit": candidate.get("environment", {}).get("commit"),
        "baseline_environment": base_key,
        "candidate_environment": cand_key,
        "correctness_regressions": [],
        "status_changes": [],
        "latency_changes": [],
        "warnings": [],
    }

    if base_key != cand_key:
        report["status"] = "incompatible_environment"
        report["warnings"].append(
            "environment fingerprints differ; latency comparison suppressed. "
            "Correctness checks still run."
        )
        compatible = False
    else:
        compatible = True

    baseline_rows = rows_by_key(baseline)
    candidate_rows = rows_by_key(candidate)
    for key, row in candidate_rows.items():
        before = baseline_rows.get(key)
        if row.get("status") == "incorrect_hit":
            report["correctness_regressions"].append({"row": list(key), "reason": "incorrect_hit"})
            continue
        if before is None:
            continue
        if before.get("status") == "reused" and row.get("status") != "reused":
            if not any(decision.get("step") == "warm" for decision in row.get("decisions", [])):
                report["correctness_regressions"].append(
                    {"row": list(key), "reason": "lost reuse without a recorded decision"}
                )
            else:
                report["status_changes"].append(
                    {"row": list(key), "from": before.get("status"), "to": row.get("status")}
                )
        if not compatible:
            continue
        base_timing = (before.get("timing") or {})
        cand_timing = (row.get("timing") or {})
        if base_timing.get("status") == "measured" and cand_timing.get("status") == "measured":
            base_warm = base_timing["warm"]["median_ns"]
            cand_warm = cand_timing["warm"]["median_ns"]
            ratio = cand_warm / base_warm if base_warm else None
            entry = {
                "row": list(key),
                "baseline_warm_ns": base_warm,
                "candidate_warm_ns": cand_warm,
                "candidate_over_baseline": ratio,
            }
            report["latency_changes"].append(entry)
            ci_low, ci_high = cand_timing.get("warm_ratio", {}).get("ratio_ci95", [1.0, 1.0])
            base_ci_low, base_ci_high = base_timing.get("warm_ratio", {}).get("ratio_ci95", [1.0, 1.0])
            if ratio and ratio > args.fail_ratio and base_ci_high < 1.0 and ci_high < 1.0:
                report["correctness_regressions"].append(
                    {
                        "row": list(key),
                        "reason": (
                            f"warm hit {ratio:.2f}x slower than baseline with non-overlapping "
                            "intervals on the wrong side"
                        ),
                    }
                )

    if not report["correctness_regressions"]:
        report["status"] = "pass" if compatible else report.get("status", "incompatible_environment")
    else:
        report["status"] = "fail"

    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n")
    return 0 if report["status"] in ("pass", "incompatible_environment") else 1


if __name__ == "__main__":
    raise SystemExit(main())

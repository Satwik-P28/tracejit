#!/usr/bin/env python3
"""Phase 3J phase-level profile of the canonical python-csv-json ETL.

The direct run is the program's wall time. The TraceJIT cold run includes
tracing and cache insertion. The warm runs reuse the record and report the
internal phase timings. Results are kept separate from benchmark assertions:
Timing a harness that verifies output would otherwise be attributed to the
trace/reuse path.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks/phase3i"))
import run as phase3i  # noqa: E402

RESULTS = ROOT / "benchmarks/results/phase3j"
CONTRACTS = ("python-runtime-v1", "python-runtime-v2")
DIRECT_RUNS = 12
COLD_RUNS = 10
WARM_RUNS = 15


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median_ns": int(statistics.median(values)),
        "p95_ns": int(percentile(values, 0.95)),
        "min_ns": int(min(values)),
        "max_ns": int(max(values)),
        "stdev_ns": int(statistics.pstdev(values)),
    }


def run(
    command: list[str], env: dict[str, str], timeout: int = 60
) -> subprocess.CompletedProcess:
    started = time.perf_counter_ns()
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=timeout,
        close_fds=True,
    )
    result.wall_ns = time.perf_counter_ns() - started
    return result


def report(result: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tracejit-phase3j-profile-"))
    sales, customers = phase3i.make_data(work)
    sales_original = sales.read_bytes()
    output = work / "summary.json"
    output.write_text("stale output")
    env = {
        **phase3i.TARGET_ENV,
        "TRACEJIT_CACHE_DIR": str(work / "cache"),
        "TRACEJIT_PHASE_TIMING": "1",
        "TRACEJIT_PHASE_TIMING_PATH": str(work / "phase.json"),
    }
    phase_file = work / "phase.json"
    result: dict = {
        "phase": "3J",
        "workload": str(ROOT / "benchmarks/realworld/workloads/etl.py"),
        "dataset": {"sales_rows": 400, "customer_rows": 12},
        "notes": [
            "direct wall includes CPython process startup",
            "warm runtime_ns starts after cache lookup and includes guard validation, CAS restore and presentation",
            "phase values are measured by TRACEJIT_PHASE_TIMING and are not additive across startup",
            "the benchmark harness is outside every measurement",
        ],
        "contracts": {},
    }

    try:
        direct_values = []
        for _ in range(DIRECT_RUNS):
            started = time.perf_counter_ns()
            direct = run(
                phase3i.direct_command(output, sales, customers),
                phase3i.TARGET_ENV,
            )
            direct_values.append(time.perf_counter_ns() - started)
            if direct.returncode != 0:
                raise RuntimeError(direct.stderr)
        result["direct"] = summary(direct_values)

        for contract in CONTRACTS:
            sales.write_bytes(sales_original)
            cache = work / f"cache-{contract}"
            contract_output = output
            cold_values = []
            cold_reports = []
            for index in range(COLD_RUNS):
                shutil.rmtree(cache, ignore_errors=True)
                if contract_output.exists():
                    contract_output.unlink()
                run_result = run(
                    phase3i.target_command(
                        contract_output, sales, customers, contract
                    ),
                    {**env, "TRACEJIT_CACHE_DIR": str(cache)},
                )
                parsed = report(run_result)
                cold_values.append(run_result.wall_ns)
                cold_reports.append(
                    {
                        "kind": parsed.get("kind"),
                        "runtime_ns": parsed.get("runtime_ns"),
                        "wall_ns": run_result.wall_ns,
                        "exit_code": parsed.get("exit_code"),
                    }
                )

            # Establish one reusable record, then measure steady-state hits. The
            # first hit can persist a decision row and is not steady-state.
            warm_first = run(
                phase3i.target_command(contract_output, sales, customers, contract),
                {**env, "TRACEJIT_CACHE_DIR": str(cache)},
            )
            first_parsed = report(warm_first)
            warm_values = []
            warm_reports = []
            phase_samples: list[dict] = []
            for _ in range(WARM_RUNS):
                if phase_file.exists():
                    phase_file.unlink()
                warm = run(
                    phase3i.target_command(contract_output, sales, customers, contract),
                    {**env, "TRACEJIT_CACHE_DIR": str(cache)},
                )
                parsed = report(warm)
                warm_values.append(parsed.get("runtime_ns", warm.wall_ns))
                phases = json.loads(phase_file.read_text()) if phase_file.exists() else {}
                phase_samples.append(phases)
                warm_reports.append(
                    {
                        "kind": parsed.get("kind"),
                        "runtime_ns": parsed.get("runtime_ns"),
                        "wall_ns": warm.wall_ns,
                        "guards": parsed.get("guards"),
                    }
                )

            # Invalidate a real input while leaving the output path alone.
            with sales.open("a", encoding="utf-8") as handle:
                handle.write("s9999,c999,1\n")
            invalidated = run(
                phase3i.target_command(contract_output, sales, customers, contract),
                {**env, "TRACEJIT_CACHE_DIR": str(cache)},
            )
            invalidated_report = report(invalidated)
            recovered = run(
                phase3i.target_command(contract_output, sales, customers, contract),
                {**env, "TRACEJIT_CACHE_DIR": str(cache)},
            )
            recovered_report = report(recovered)

            phase_names = sorted(
                {key for sample in phase_samples for key in sample}
            )
            phase_summary = {
                name: summary(
                    [
                        float(sample[name])
                        for sample in phase_samples
                        if name in sample
                    ]
                )
                for name in phase_names
            }
            result["contracts"][contract] = {
                "cold": {
                    "runs": cold_reports,
                    "wall": summary(cold_values),
                },
                "first_hit": {
                    "kind": first_parsed.get("kind"),
                    "runtime_ns": first_parsed.get("runtime_ns"),
                    "wall_ns": warm_first.wall_ns,
                    "decision_persist_ns": json.loads(
                        phase_file.read_text()
                    ).get("decision_persist_ns")
                    if phase_file.exists()
                    else None,
                },
                "warm": {
                    "runs": warm_reports,
                    "runtime": summary(warm_values),
                },
                "phases": phase_summary,
                "invalidation": {
                    "kind": invalidated_report.get("kind"),
                    "runtime_ns": invalidated_report.get("runtime_ns"),
                    "wall_ns": invalidated.wall_ns,
                    "recovered_kind": recovered_report.get("kind"),
                    "recovered_runtime_ns": recovered_report.get("runtime_ns"),
                },
            }

        # Restore the modified input so a second profile invocation starts from
        # the same dataset. The temporary directory is deleted below.
        destination = RESULTS / "profile.json"
        destination.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(destination)
        print(json.dumps(result["direct"], sort_keys=True))
        for contract, values in result["contracts"].items():
            print(
                contract,
                "cold",
                values["cold"]["wall"],
                "warm",
                values["warm"]["runtime"],
                "inv",
                values["invalidation"],
            )
            for name, value in values["phases"].items():
                print(" ", name, value)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Measure the controlled Python smoke path separately from the target workload.

This is a mechanism smoke test, not a `python-csv-json` result. It measures:
direct, controlled cold, controlled warm, and invalidation after the script changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACEJIT = ROOT / "target/release/tracejit"
PYTHON = Path("/usr/bin/python3.12")
RESULTS = ROOT / "benchmarks/results/phase3h"


def run(command, env=None):
    started = time.perf_counter_ns()
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        close_fds=True,
    )
    return result, time.perf_counter_ns() - started


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tracejit-p3h-smoke-") as directory:
        work = Path(directory)
        script = work / "smoke.py"
        script.write_text('print("controlled-smoke-v1")\n', encoding="utf-8")
        cache = work / "cache"
        env = {"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}

        direct_runs = []
        for _ in range(10):
            result, wall = run([str(PYTHON), "-S", str(script)], env)
            direct_runs.append((wall, result.stdout, result.returncode))

        cold_result, cold_wall = run(
            [
                str(TRACEJIT), "run", "--json", "--contract", "python-runtime-v1",
                "--", str(PYTHON), "-S", str(script),
            ],
            {**env, "TRACEJIT_CACHE_DIR": str(cache)},
        )
        cold_report = json.loads(cold_result.stdout)
        # The JSON report is the wrapper's stdout. A plain wrapper invocation is used below to
        # compare the command's cached stdout with a direct run.
        direct_expected = run([str(PYTHON), "-S", str(script)], env)[0].stdout

        warm_runs = []
        warm_reports = []
        for _ in range(10):
            result, wall = run(
                [
                    str(TRACEJIT), "run", "--json", "--contract", "python-runtime-v1",
                    "--", str(PYTHON), "-S", str(script),
                ],
                {**env, "TRACEJIT_CACHE_DIR": str(cache)},
            )
            warm_runs.append((wall, result.returncode))
            warm_reports.append(json.loads(result.stdout))

        warm_plain = run(
            [
                str(TRACEJIT), "run", "--contract", "python-runtime-v1",
                "--", str(PYTHON), "-S", str(script),
            ],
            {**env, "TRACEJIT_CACHE_DIR": str(cache)},
        )[0]

        script.write_text('print("controlled-smoke-v2")\n', encoding="utf-8")
        invalidated, invalidated_wall = run(
            [
                str(TRACEJIT), "run", "--json", "--contract", "python-runtime-v1",
                "--", str(PYTHON), "-S", str(script),
            ],
            {**env, "TRACEJIT_CACHE_DIR": str(cache)},
        )
        invalidated_report = json.loads(invalidated.stdout)
        invalidated_direct = run([str(PYTHON), "-S", str(script)], env)[0]
        invalidated_plain = run(
            [
                str(TRACEJIT), "run", "--contract", "python-runtime-v1",
                "--", str(PYTHON), "-S", str(script),
            ],
            {**env, "TRACEJIT_CACHE_DIR": str(cache)},
        )[0]

        document = {
            "phase": "3H",
            "kind": "controlled-python-smoke",
            "workload": "python -S smoke.py",
            "interpreter": {
                "path": str(PYTHON),
                "version": run([str(PYTHON), "-V"])[0].stdout.strip(),
            },
            "direct": {
                "median_wall_ns": statistics.median(run[0] for run in direct_runs),
                "stdout_sha256": digest(direct_expected),
                "status": direct_runs[0][2],
            },
            "cold": {
                "wall_ns": cold_wall,
                "report": cold_report,
            },
            "warm": {
                "median_wall_ns": statistics.median(run[0] for run in warm_runs),
                "reports": warm_reports,
                "cached_stdout_sha256": digest(warm_plain.stdout),
            },
            "invalidated": {
                "wall_ns": invalidated_wall,
                "report": invalidated_report,
                "direct_stdout_sha256": digest(invalidated_direct.stdout),
                "traced_stdout_sha256": digest(invalidated_plain.stdout),
            },
            "note": (
                "This smoke hit exercises only the versioned Python-runtime watchpoint. "
                "The target python-csv-json workload still deoptimizes on directory entry "
                "stream bytes; no target-workload hit is claimed."
            ),
        }
        destination = RESULTS / "contract-smoke.json"
        destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(destination)
        print("direct", document["direct"]["median_wall_ns"])
        print("cold", cold_wall, cold_report.get("cache_decision"))
        print("warm", document["warm"]["median_wall_ns"], [r.get("cache_decision") for r in warm_reports])
        print("invalidated", invalidated_wall, invalidated_report.get("cache_decision"))
        print("stdout", digest(direct_expected), digest(warm_plain.stdout))
        print("invalidated stdout", digest(invalidated_direct.stdout), digest(invalidated_plain.stdout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

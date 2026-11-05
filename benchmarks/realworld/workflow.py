#!/usr/bin/env python3
"""An ordinary developer workflow: filter, measure, verify, compress.

Isolated utility commands are a poor proxy for whether reuse pays. This runs four ordinary
commands over one real file, in order, and times the whole sequence:

  1. `sed -e s/alpha/ALPHA/g data.txt`   (a filter, large stdout)
  2. `wc -c data.txt`                    (a small report)
  3. `md5sum data.txt`                   (a checksum)
  4. `gzip -9 -c data.txt`               (compression, large stdout)

Direct mode runs the four commands natively. Controlled mode runs each through TraceJIT under
`--contract allocator-entropy-v1`, priming the cache once outside the measurement, then measures
the hit sequence. Every cached command's bytes are compared with the direct run.

Timing runs omit `--json`; serialising tens of megabytes of stdout as JSON integers would dominate
the measurement. The cache decision is verified separately with `--json` for each command.

Usage:
    python3 benchmarks/realworld/workflow.py [--reps N] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "target" / "debug" / "tracejit"
RELEASE = REPO / "target" / "release" / "tracejit"
CONTRACT = "allocator-entropy-v1"


def binary() -> Path:
    for candidate in (RELEASE, DEBUG):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary; run: cargo build --workspace")


def text_input(rows: int = 400_000) -> str:
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    return "".join(
        f"{index % 977} {words[index % len(words)]} {index * 7 % 1013}\n"
        for index in range(rows)
    )


STEPS = [
    ("sed", ["sed", "-e", "s/alpha/ALPHA/g", "data.txt"]),
    ("wc", ["wc", "-c", "data.txt"]),
    ("md5sum", ["md5sum", "data.txt"]),
    ("gzip", ["gzip", "-9", "-c", "data.txt"]),
]


def environment(cache: Path | None) -> dict:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(command, cwd, env):
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "ms": (time.perf_counter() - started) * 1000.0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit": completed.returncode,
    }


def traced(command, cwd, env):
    return run([str(binary()), "run", "--contract", CONTRACT, "--", *command], cwd, env)


def traced_json(command, cwd, env):
    result = run([str(binary()), "run", "--json", "--contract", CONTRACT, "--", *command], cwd, env)
    return json.loads(result["stdout"])


def median(values):
    return round(statistics.median(values), 2) if values else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--rows", type=int, default=400_000)
    parser.add_argument("--output-dir", default="benchmarks/results/phase2g/workflow")
    args = parser.parse_args()

    output_dir = REPO / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tracejit-workflow-"))
    work = root / "work"
    work.mkdir()
    (work / "data.txt").write_text(text_input(args.rows))
    data_bytes = (work / "data.txt").stat().st_size

    direct_env = environment(None)
    expected = {}
    for name, command in STEPS:
        result = run(command, work, direct_env)
        assert result["exit"] == 0, (name, result["stderr"])
        expected[name] = result["stdout"]

    # Direct workflow: the four commands, back to back, one rep at a time.
    direct_totals = []
    for _ in range(args.reps):
        started = time.perf_counter()
        for _, command in STEPS:
            result = run(command, work, direct_env)
            assert result["exit"] == 0
        direct_totals.append((time.perf_counter() - started) * 1000.0)

    cache = root / "cache"
    env = environment(cache)
    # Prime every entry outside the measurement.
    for _, command in STEPS:
        traced(command, work, env)
    # Verify each command is a real hit and returns the direct bytes.
    hits = {}
    for name, command in STEPS:
        report = traced_json(command, work, env)
        hits[name] = {
            "decision": report["cache_decision"],
            "contract": report.get("contract"),
            "output_matches_direct": bytes(report["stdout_bytes"]) == expected[name],
        }

    cached_totals = []
    per_step = {name: {"direct": [], "cached": []} for name, _ in STEPS}
    for _ in range(args.reps):
        started = time.perf_counter()
        for name, command in STEPS:
            result = run(command, work, direct_env)
            per_step[name]["direct"].append(result["ms"])
        direct_totals.append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        for name, command in STEPS:
            result = traced(command, work, env)
            assert result["stdout"] == expected[name], name
            per_step[name]["cached"].append(result["ms"])
        cached_totals.append((time.perf_counter() - started) * 1000.0)

    # The first loop above already contributed `reps` direct totals; keep exactly that many.
    direct_totals = direct_totals[: args.reps]
    result = {
        "generated_by": "benchmarks/realworld/workflow.py",
        "contract": CONTRACT,
        "input_bytes": data_bytes,
        "reps": args.reps,
        "steps": [name for name, _ in STEPS],
        "direct_total_median_ms": median(direct_totals),
        "cached_total_median_ms": median(cached_totals),
        "workflow_speedup": round(median(direct_totals) / median(cached_totals), 2),
        "per_step": {
            name: {
                "direct_median_ms": median(values["direct"]),
                "cached_median_ms": median(values["cached"]),
            }
            for name, values in per_step.items()
        },
        "hits": hits,
        "direct_samples_ms": [round(value, 2) for value in direct_totals],
        "cached_samples_ms": [round(value, 2) for value in cached_totals],
    }
    (output_dir / "workflow.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "input_bytes", "reps", "direct_total_median_ms", "cached_total_median_ms",
        "workflow_speedup", "per_step", "hits")}, indent=2))
    all_hits = all(hit["decision"] == "Reused" and hit["output_matches_direct"] for hit in hits.values())
    print("RESULT workflow PASS" if all_hits else "RESULT workflow FAIL")
    return 0 if all_hits else 1


if __name__ == "__main__":
    sys.exit(main())

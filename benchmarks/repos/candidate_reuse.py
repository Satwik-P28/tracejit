#!/usr/bin/env python3
"""Measure A -> B -> A reuse for a guarded file-copy fixture.

The lookup key deliberately excludes input contents; file contents are guards. A cache that
keeps only one record per lookup key loses A when B is traced. This harness runs both binaries
against fresh workspaces and records the third invocation's decision and wall time.

The fixture is the repository's existing `fixture_driver`; no synthetic repeat loop is used.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "fixture_driver.c"


def build_fixture(directory: Path) -> Path:
    binary = directory / "fixture-driver"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            str(FIXTURE),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


def run_session(binary: Path, fixture: Path, session: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="tracejit-candidate-") as temporary:
        root = Path(temporary)
        input_path = root / "input.txt"
        output_path = root / "output.txt"
        cache = root / "cache"
        env = {
            **os.environ,
            "TRACEJIT_CACHE_DIR": str(cache),
            "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        }
        records = []
        for state in ("one", "two", "one"):
            input_path.write_text(f"input {state}\n", encoding="utf-8")
            started = time.perf_counter_ns()
            completed = subprocess.run(
                [
                    str(binary),
                    "run",
                    "--json",
                    "--",
                    str(fixture),
                    "plain_file_read",
                    str(root),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            elapsed_ns = time.perf_counter_ns() - started
            if completed.returncode != 0:
                raise RuntimeError(
                    f"{binary} failed on {state}: {completed.returncode}\n{completed.stderr}"
                )
            report = json.loads(completed.stdout)
            records.append(
                {
                    "input": state,
                    "kind": report["kind"],
                    "classification": report["classification"],
                    "runtime_ns": report["runtime_ns"],
                    "wall_ns": elapsed_ns,
                    "output": output_path.read_text(encoding="utf-8"),
                }
            )
        return {"session": session, "binary": str(binary), "records": records}


def median(values: list[int]) -> float:
    return statistics.median(values) / 1_000_000


def summarize(sessions: list[dict]) -> dict:
    third = [session["records"][2] for session in sessions]
    return {
        "third_kind": sorted({record["kind"] for record in third}),
        "third_wall_ms_median": median([record["wall_ns"] for record in third]),
        "third_execution_ns_median": statistics.median(
            record["runtime_ns"] for record in third
        ),
        "all_outputs_correct": all(
            record["output"] == f"input {record['input']}\n"
            for session in sessions
            for record in session["records"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="tracejit-fixture-") as temporary:
        fixture = build_fixture(Path(temporary))
        current = args.binary.resolve()
        baseline = args.baseline.resolve()
        sessions = {"current": [], "baseline": []}
        for session in range(args.sessions):
            # Alternate order so a systematic thermal or cache-state effect does not favor one
            # binary across all sessions.
            order = [
                ("current", current),
                ("baseline", baseline),
            ]
            if session % 2:
                order.reverse()
            for name, binary in order:
                sessions[name].append(run_session(binary, fixture, session))

    result = {
        "schema": "tracejit.candidate-reuse.v1",
        "fixture": "tests/fixtures/fixture_driver.c:plain_file_read",
        "sequence": ["input one", "input two", "input one"],
        "sessions": args.sessions,
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "current_binary_sha256": subprocess.run(
            ["sha256sum", str(current)], capture_output=True, text=True, check=True
        ).stdout.split()[0],
        "baseline_binary_sha256": subprocess.run(
            ["sha256sum", str(baseline)], capture_output=True, text=True, check=True
        ).stdout.split()[0],
        "current": summarize(sessions["current"]),
        "baseline": summarize(sessions["baseline"]),
        "raw": sessions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("current", "baseline")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

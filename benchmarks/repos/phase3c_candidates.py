#!/usr/bin/env python3
"""Repeated candidate scaling for Phase 3C.

The Phase 3B harness measured one sample per bound. This wrapper reuses its fixture and
measurement routine, but runs independent fresh-cache sessions at 1, 2, 4, 8, 16, 32 and 64
candidates and reports median/p95/worst-case plus retained rows and cache bytes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = Path("/tmp/tracejit-phase3c-candidates")
BOUNDS = (1, 2, 4, 8, 16, 32, 64)


def load_phase3b():
    path = REPO / "benchmarks/repos/candidate_scaling.py"
    spec = importlib.util.spec_from_file_location("phase3b_candidates", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=20)[18] if len(values) > 1 else values[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--output", default=str(REPO / "benchmarks/results/phase3c/candidate-scaling.json"))
    args = parser.parse_args()
    module = load_phase3b()
    if not module.BINARY.is_file():
        raise SystemExit("missing target/release/tracejit; run cargo build --release --workspace")
    module.ROOT = ROOT
    module.BOUNDS = BOUNDS
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    work = ROOT / "work"
    work.mkdir()
    fixture = module.compile_fixture(ROOT)

    sessions = []
    for session in range(args.sessions):
        rows = []
        for bound in BOUNDS:
            row = module.measure(fixture, work, bound)
            rows.append(row)
            print(
                f"session={session} bound={bound} retained={row['retained_candidates']} "
                f"target={row['target_wall_ms']:.3f}ms miss={row['miss_wall_ms']:.3f}ms",
                file=sys.stderr,
            )
        sessions.append(rows)

    aggregate = []
    for index, bound in enumerate(BOUNDS):
        rows = [session[index] for session in sessions]
        newest = [row["newest_wall_ms"] for row in rows]
        target = [row["target_wall_ms"] for row in rows]
        miss = [row["miss_wall_ms"] for row in rows]
        aggregate.append(
            {
                "bound": bound,
                "sessions": len(rows),
                "retained_candidates": [row["retained_candidates"] for row in rows],
                "newest_ms_samples": newest,
                "newest_ms_median": statistics.median(newest),
                "newest_ms_p95": p95(newest),
                "newest_ms_worst": max(newest),
                "target_ms_samples": target,
                "target_ms_median": statistics.median(target),
                "target_ms_p95": p95(target),
                "target_ms_worst": max(target),
                "miss_ms_samples": miss,
                "miss_ms_median": statistics.median(miss),
                "miss_ms_p95": p95(miss),
                "miss_ms_worst": max(miss),
                "cache_bytes": max(row["cache_bytes"] for row in rows),
                "concurrent_all_reused": all(row["concurrent_all_reused"] for row in rows),
                "target_decisions": sorted({row["target_decision"] for row in rows}),
            }
        )

    report = {
        "phase": "3C",
        "experiment": "repeated candidate scaling",
        "repository": {
            "commit": subprocess.run(
                ["git", "-C", str(REPO), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "dirty": bool(
                subprocess.run(
                    ["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            ),
        },
        "binary": {"sha256": module.sha256(module.BINARY), "size": module.BINARY.stat().st_size},
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "cpus": os.cpu_count(),
            "memory": Path("/proc/meminfo").read_text().splitlines()[0],
        },
        "method": {
            "bounds": list(BOUNDS),
            "sessions": args.sessions,
            "target": "oldest of N retained input states, forcing newest-first evaluation",
            "selection": "lazy decode + full guards; first candidate whose guards pass wins",
            "fresh_cache": True,
        },
        "sessions": sessions,
        "bounds": aggregate,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                row["bound"]: {
                    "newest_median_ms": round(row["newest_ms_median"], 3),
                    "median_ms": round(row["target_ms_median"], 3),
                    "p95_ms": round(row["target_ms_p95"], 3),
                    "worst_ms": round(row["target_ms_worst"], 3),
                    "miss_median_ms": round(row["miss_ms_median"], 3),
                    "retained": row["retained_candidates"],
                }
                for row in aggregate
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase X workloads that are not the compiler: one real non-compiler program, one command whose
execution is cheaper than its own reuse overhead, and one that does nothing at all.

Each arm gets its own workspace and cache, is traced once, warmed, and then measured with the same
paired interleaving as `ab.py`. Every measured invocation's decision is recorded, so an arm that
cannot reuse is reported as such instead of being dressed up as a hit.

Usage:
  python3 benchmarks/phase_x/workloads.py \
      --baseline /tmp/tj-baseline --candidate /tmp/tj-final \
      --rounds 8 --output benchmarks/results/phasex/workloads.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def close_extra_fds_cmd(argv: list[str]) -> list[str]:
    inner = " ".join(f'"{a}"' if " " in a else a for a in argv)
    script = (
        "for e in /proc/self/fd/*; do f=${e##*/}; "
        'case "$f" in 0|1|2) ;; *) eval "exec ${f}>&-" 2>/dev/null || true ;; esac; '
        f"done; exec {inner}"
    )
    return ["bash", "-c", script]


def build_etl() -> Path:
    source = REPO / "benchmarks/workloads/c-etl/main.c"
    binary = Path("/tmp/tracejit-phase-x-etl")
    subprocess.run(
        ["cc", "-O2", "-o", str(binary), str(source)], check=True, capture_output=True
    )
    return binary


def write_workload(name: str, directory: Path, etl: Path) -> tuple[list[str], Path]:
    if name == "etl":
        # The ETL program uses fixed paths relative to the repository root, which is how the
        # existing benchmark harness runs it. It reads two CSV inputs and writes one JSON report;
        # no arguments.
        return [str(etl)], REPO
    if name == "sort-small":
        # Deliberately unprofitable: `sort` on a small file finishes faster than any reuse
        # bookkeeping can, so a hit can never repay itself here.
        rng = random.Random(7)
        (directory / "input.txt").write_text(
            "\n".join(str(rng.randrange(1_000_000)) for _ in range(2000)) + "\n"
        )
        return ["sort", "input.txt", "-o", "sorted.txt"], directory
    if name == "true":
        return ["true"], directory
    raise SystemExit(f"unknown workload {name}")


def run_once(
    binary: Path, directory: Path, cache: Path, argv: list[str]
) -> tuple[float, str]:
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "TRACEJIT_CACHE_DIR": str(cache),
    }
    started = time.perf_counter()
    completed = subprocess.run(
        close_extra_fds_cmd([str(binary), "run", "--", *argv]),
        cwd=directory,
        env=environment,
        capture_output=True,
    )
    elapsed_ms = (time.perf_counter() - started) * 1e3
    stderr = completed.stderr.decode(errors="replace")
    if completed.returncode != 0:
        raise SystemExit(f"{argv[0]} failed: {stderr[:600]}")
    decision = "unknown"
    for key in ("HIT", "DEOPT", "MISS", "SKIP"):
        if f"cache          {key}" in stderr or f"cache {key}" in stderr:
            decision = key.lower()
            break
    reason = ""
    for line in stderr.splitlines():
        if line.startswith("reason"):
            reason = line.strip()
            break
    return elapsed_ms, decision + (f" ({reason})" if reason else "")


def median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else float("nan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument(
        "--workloads", default="etl,sort-small,true"
    )
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default="/tmp/tracejit-phase-x-workloads")
    args = parser.parse_args()

    arms = [
        ("baseline", Path(args.baseline).resolve()),
        ("candidate", Path(args.candidate).resolve()),
    ]
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    etl = build_etl()

    payload: dict[str, object] = {"arms": {name: str(path) for name, path in arms}, "workloads": {}}
    for workload in args.workloads.split(","):
        directories = {}
        for name, binary in arms:
            workspace = root / workload / name / "work"
            cache = root / workload / name / "cache"
            workspace.mkdir(parents=True, exist_ok=True)
            argv, cwd = write_workload(workload, workspace, etl)
            directories[name] = (workspace, cache, cwd)
            for _ in range(3):
                run_once(binary, cwd, cache, argv)
        samples: dict[str, list[float]] = {name: [] for name, _ in arms}
        decisions: dict[str, list[str]] = {name: [] for name, _ in arms}
        for _ in range(args.rounds):
            for name, binary in arms:
                workspace, cache, cwd = directories[name]
                elapsed_ms, decision = run_once(binary, cwd, cache, argv)
                samples[name].append(elapsed_ms)
                decisions[name].append(decision)
        entry = {
            "argv": argv,
            "cwd": str(cwd),
            "arms": {
                name: {
                    "median_ms": round(median(samples[name]), 3),
                    "min_ms": round(min(samples[name]), 3),
                    "max_ms": round(max(samples[name]), 3),
                    "decisions": sorted(set(decisions[name])),
                    "samples_ms": [round(value, 3) for value in samples[name]],
                }
                for name, _ in arms
            },
        }
        base = median(samples["baseline"])
        candidate = median(samples["candidate"])
        entry["candidate_vs_baseline"] = round(base / candidate, 3) if candidate else None
        payload["workloads"][workload] = entry
        print(
            f"{workload:12s} baseline={base:8.3f}ms candidate={candidate:8.3f}ms "
            f"ratio={entry['candidate_vs_baseline']} decisions={entry['arms']['candidate']['decisions']}",
            file=sys.stderr,
        )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

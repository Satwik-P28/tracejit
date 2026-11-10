#!/usr/bin/env python3
"""Reproduce the Phase 2T bzip2 rerun transition and a stable third run.

The first build creates the `.bz2` outputs. The next invocation is the transition from an absent
output pre-state to a present one. The third invocation is a stable rerun with the output present.

Usage:
    cargo build --release --workspace
    python3 benchmarks/repos/phase3b_identical_rerun.py --label current \
      --output benchmarks/results/phase3b/identical-rerun-current.json
    python3 benchmarks/repos/phase3b_identical_rerun.py --label old --binary target/old/tracejit \
      --output benchmarks/results/phase3b/identical-rerun-old.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = Path("/tmp/tracejit-phase3b-rerun")
ASSETS = ("app.js", "vendor.js", "worker.js")
CONTRACT = "allocator-entropy-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_assets(assets: Path) -> None:
    assets.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(ASSETS):
        with (assets / name).open("w") as handle:
            for row in range(48_000):
                handle.write(
                    f"export const value_{index}_{row} = "
                    f"{(row * (index + 3) * 2654435761) % 1_000_000_007}; "
                    f"// bundle-{index}-{row:06d}\n"
                )


def environment(cache: Path, phase_path: Path) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "TRACEJIT_CACHE_DIR": str(cache),
        "TRACEJIT_PHASE_TIMING": "1",
        "TRACEJIT_PHASE_TIMING_PATH": str(phase_path),
    }


def read_phase(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("phases", data)


def verify_output(work: Path, name: str) -> bool:
    output = work / "assets" / f"{name}.bz2"
    if not output.is_file():
        return False
    decoded = subprocess.run(
        ["bzip2", "-dc", str(output)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return decoded.returncode == 0 and decoded.stdout == (work / "assets" / name).read_bytes()


def cache_failures(cache: Path) -> list[dict]:
    failures = []
    for path in sorted((cache / "executions").glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        decision = record.get("last_decision", {})
        failure = decision.get("guard_failure")
        if failure:
            failures.append(
                {
                    "file": path.name,
                    "decision": decision.get("decision"),
                    "reason": failure.get("reason"),
                    "guard": failure.get("guard"),
                    "expected": failure.get("expected"),
                    "actual": failure.get("actual"),
                }
            )
    return failures


def run_round(
    binary: Path, work: Path, cache: Path, phase_path: Path, label: str
) -> dict:
    started = time.perf_counter()
    decisions = []
    for name in ASSETS:
        completed = subprocess.run(
            [
                str(binary),
                "run",
                "--json",
                "--contract",
                CONTRACT,
                "--",
                "bzip2",
                "-9",
                "-k",
                "-f",
                f"assets/{name}",
            ],
            cwd=work,
            env=environment(cache, phase_path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            report = {
                "cache_decision": "NO_JSON",
                "decision_reason": completed.stderr.decode(errors="replace")[-400:],
            }
        decisions.append(
            {
                "asset": name,
                "decision": report.get("cache_decision"),
                "reason": report.get("decision_reason"),
                "guard_failure": report.get("guard_failure"),
                "exit": completed.returncode,
                "correct": verify_output(work, name),
            }
        )
    return {
        "label": label,
        "ms": round((time.perf_counter() - started) * 1000.0, 3),
        "decisions": decisions,
        "phases": read_phase(phase_path),
        "failures": cache_failures(cache),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    parser.add_argument("--binary", default=str(REPO / "target/release/tracejit"))
    parser.add_argument(
        "--output", default=str(REPO / "benchmarks/results/phase3b/identical-rerun.json")
    )
    args = parser.parse_args()
    binary = Path(args.binary).resolve()
    if not binary.is_file():
        raise SystemExit(f"missing binary: {binary}")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    work = ROOT / "work"
    cache = ROOT / "cache"
    write_assets(work / "assets")
    cache.mkdir()
    phase_path = ROOT / "phases.json"

    rounds = []
    rounds.append(run_round(binary, work, cache, phase_path, "first_build_outputs_absent"))
    rounds.append(run_round(binary, work, cache, phase_path, "identical_rerun_transition"))
    rounds.append(run_round(binary, work, cache, phase_path, "identical_rerun_stable"))
    for name in ASSETS:
        (work / "assets" / f"{name}.bz2").unlink(missing_ok=True)
    rounds.append(run_round(binary, work, cache, phase_path, "outputs_deleted"))
    with (work / "assets" / "app.js").open("a") as handle:
        handle.write("\n// phase 3b edit\n")
    rounds.append(run_round(binary, work, cache, phase_path, "one_input_modified"))

    report = {
        "phase": "3B",
        "experiment": "bzip2 identical-rerun transition",
        "label": args.label,
        "repository": {
            "commit": subprocess.run(
                ["git", "-C", str(REPO), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
        },
        "binary": {"path": str(binary), "sha256": sha256(binary), "size": binary.stat().st_size},
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "cpus": os.cpu_count(),
            "memory": Path("/proc/meminfo").read_text().splitlines()[0],
        },
        "contract": CONTRACT,
        "workload": "three 2.8 MB JavaScript assets compressed with bzip2 -9 -k -f",
        "rounds": rounds,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                round_["label"]: {
                    "ms": round_["ms"],
                    "decisions": [decision["decision"] for decision in round_["decisions"]],
                    "failures": len(round_["failures"]),
                }
                for round_ in rounds
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

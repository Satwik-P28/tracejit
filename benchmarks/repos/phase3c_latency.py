#!/usr/bin/env python3
"""Attribute the stable three-asset bzip2 workflow latency.

The stable workflow contains no bzip2 execution: every command must be a guarded reuse.
This harness measures each command separately, keeps a unique phase-timing file per
invocation, and compares separate parent invocations with a single shell batch. The
difference is harness overhead, not a TraceJIT batch mode.

Usage:
    cargo build --release --workspace
    python3 benchmarks/repos/phase3c_latency.py \
      --output benchmarks/results/phase3c/latency.json
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import os
import platform
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BINARY = REPO / "target/release/tracejit"
ROOT = Path("/tmp/tracejit-phase3c-latency")
ASSETS = ("app.js", "vendor.js", "worker.js")
CONTRACT = "allocator-entropy-v1"
PHASE_FIELDS = (
    "process_startup_ns",
    "cli_parse_ns",
    "identity_prepare_ns",
    "cache_prepare_ns",
    "sqlite_open_ns",
    "sqlite_schema_ns",
    "lookup_key_ns",
    "sqlite_query_ns",
    "record_decode_ns",
    "guard_validation_ns",
    "cas_restore_ns",
    "stdio_replay_ns",
    "decision_persist_ns",
    "present_ns",
)


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


def phase(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("phases", data)


def verify_output(work: Path, name: str) -> bool:
    output = work / "assets" / f"{name}.bz2"
    try:
        return bz2.decompress(output.read_bytes()) == (work / "assets" / name).read_bytes()
    except (OSError, OSError):
        return False


def command(binary: Path, name: str) -> list[str]:
    return [
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
    ]


def run_one(
    binary: Path, work: Path, cache: Path, name: str, phase_path: Path, verify: bool = True
) -> dict:
    phase_path.unlink(missing_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        command(binary, name),
        cwd=work,
        env=environment(cache, phase_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {
            "cache_decision": "NO_JSON",
            "decision_reason": completed.stderr.decode(errors="replace")[-500:],
        }
    phases = {field: int(phase(phase_path).get(field, 0)) for field in PHASE_FIELDS}
    accounted_ns = sum(phases.values())
    return {
        "asset": name,
        "exit": completed.returncode,
        "wall_ms": wall_ms,
        "report": report,
        "phases_ns": phases,
        "accounted_ms": accounted_ns / 1_000_000.0,
        "unaccounted_ms": wall_ms - accounted_ns / 1_000_000.0,
        "correct": verify_output(work, name) if verify else None,
    }


def run_round(
    binary: Path, work: Path, cache: Path, label: str, phase_path: Path
) -> dict:
    started = time.perf_counter()
    rows = []
    for name in ASSETS:
        rows.append(run_one(binary, work, cache, name, phase_path, verify=False))
    workflow_ms = (time.perf_counter() - started) * 1000.0
    verify_started = time.perf_counter()
    for row in rows:
        row["correct"] = verify_output(work, row["asset"])
    verification_ms = (time.perf_counter() - verify_started) * 1000.0
    return {
        "mode": "independent",
        "label": label,
        "wall_ms": workflow_ms,
        "verification_ms": verification_ms,
        "rows": rows,
    }


def run_batch(
    binary: Path, work: Path, cache: Path, label: str, shared_phase: Path
) -> dict:
    """Run the three commands from one shell invocation, still as three processes."""
    directory = shared_phase.parent / label
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["set -eu"]
    for name in ASSETS:
        phase_path = directory / f"{name}.phase.json"
        inner = (
            f"{shlex.quote(str(binary))} run --json --contract {CONTRACT} "
            f"-- bzip2 -9 -k -f assets/{shlex.quote(name)}"
        )
        lines.append(
            f"TRACEJIT_CACHE_DIR={shlex.quote(str(cache))} "
            f"TRACEJIT_PHASE_TIMING=1 "
            f"TRACEJIT_PHASE_TIMING_PATH={shlex.quote(str(shared_phase))} "
            f"{inner}"
        )
        lines.append(
            f"cp {shlex.quote(str(shared_phase))} {shlex.quote(str(phase_path))}"
        )
    script = "\n".join(lines)
    started = time.perf_counter()
    completed = subprocess.run(
        ["/bin/sh", "-c", script],
        cwd=work,
        env=environment(cache, directory / "unused.json"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    rows = []
    reports = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.startswith(b"{")
    ]
    for index, name in enumerate(ASSETS):
        phase_path = directory / f"{name}.phase.json"
        phases = {field: int(phase(phase_path).get(field, 0)) for field in PHASE_FIELDS}
        accounted_ns = sum(phases.values())
        report = reports[index] if index < len(reports) else {}
        rows.append(
            {
                "asset": name,
                "exit": completed.returncode,
                "phases_ns": phases,
                "accounted_ms": accounted_ns / 1_000_000.0,
                "unaccounted_ms": None,
                "report": report,
                "correct": verify_output(work, name),
            }
        )
    return {
        "mode": "shell-batch",
        "label": label,
        "exit": completed.returncode,
        "wall_ms": wall_ms,
        "rows": rows,
        "stderr": completed.stderr.decode(errors="replace")[-500:],
    }


def summarize(rows: list[dict]) -> dict:
    flat = [row for round_ in rows for row in round_["rows"]]
    walls = [row["wall_ms"] for row in flat if "wall_ms" in row]
    unaccounted = [row["unaccounted_ms"] for row in flat if row["unaccounted_ms"] is not None]
    phase_medians = {
        field: statistics.median(row["phases_ns"][field] for row in flat)
        for field in PHASE_FIELDS
    }
    return {
        "commands": len(flat),
        "all_correct": all(row["correct"] for row in flat),
        "decisions": sorted(
            {row["report"].get("cache_decision") or "NO_JSON" for row in flat}
        ),
        "wall_ms_median": statistics.median(walls) if walls else None,
        "wall_ms_p95": (
            statistics.quantiles(walls, n=20)[18]
            if len(walls) > 1
            else walls[0]
            if walls
            else None
        ),
        "wall_ms_worst": max(walls) if walls else None,
        "unaccounted_ms_median": statistics.median(unaccounted) if unaccounted else None,
        "phase_medians_ns": phase_medians,
        "accounted_ms_median": statistics.median(
            row["accounted_ms"] for row in flat
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default=str(REPO / "benchmarks/results/phase3c/latency.json")
    )
    parser.add_argument("--stable-rounds", type=int, default=5)
    parser.add_argument("--binary", default=str(BINARY))
    args = parser.parse_args()
    binary = Path(args.binary).resolve()
    if not binary.is_file():
        raise SystemExit(f"missing TraceJIT binary: {binary}")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    work = ROOT / "work"
    cache = ROOT / "cache"
    phases = ROOT / "phases"
    write_assets(work / "assets")
    cache.mkdir()
    phases.mkdir()

    shared_phase = phases / "phase.json"
    cold = run_round(binary, work, cache, "cold", shared_phase)
    transition = run_round(binary, work, cache, "transition", shared_phase)
    stable = [
        run_round(binary, work, cache, f"stable-{index}", shared_phase)
        for index in range(args.stable_rounds)
    ]
    batch = [
        run_batch(binary, work, cache, f"batch-{index}", shared_phase)
        for index in range(args.stable_rounds)
    ]

    report = {
        "phase": "3C",
        "experiment": "stable bzip2 workflow latency attribution",
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
        "binary": {"sha256": sha256(binary), "size": binary.stat().st_size},
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "cpus": os.cpu_count(),
            "memory": Path("/proc/meminfo").read_text().splitlines()[0],
        },
        "workload": "three 2.8 MB JavaScript assets, bzip2 -9 -k -f",
        "method": {
            "cold": "first trace, outputs absent",
            "transition": "first rerun, outputs present; expected deoptimization",
            "stable": "repeated reuse with all outputs present",
            "batch": "one /bin/sh process invokes three TraceJIT processes; no in-process batch mode",
            "unaccounted": "parent wall minus every TraceJIT phase; includes subprocess setup, JSON parse and scheduling",
        },
        "cold": cold,
        "transition": transition,
        "stable": stable,
        "batch": batch,
        "summary": {
            "cold": summarize([cold]),
            "transition": summarize([transition]),
            "stable_independent": summarize(stable),
            "stable_shell_batch": summarize(batch),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")

    print(
        json.dumps(
            {
                "cold_ms": round(cold["wall_ms"], 3),
                "transition_ms": round(transition["wall_ms"], 3),
                "stable_median_command_ms": round(
                    report["summary"]["stable_independent"]["wall_ms_median"], 3
                ),
                "stable_round_median_ms": round(
                    statistics.median(round_["wall_ms"] for round_ in stable), 3
                ),
                "batch_round_median_ms": round(
                    statistics.median(round_["wall_ms"] for round_ in batch), 3
                ),
                "stable_decisions": report["summary"]["stable_independent"]["decisions"],
                "stable_correct": report["summary"]["stable_independent"]["all_correct"],
                "phase_medians_ns": report["summary"]["stable_independent"][
                    "phase_medians_ns"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

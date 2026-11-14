#!/usr/bin/env python3
"""Phase K7 microbench: warm-hit wall + phase medians (measured, never invented).

Usage:
  cargo build -p tracejit-cli --release
  python3 scripts/phase_k7_perf_micro.py --label before --output benchmarks/results/phase_k7/before.json
  # apply change, rebuild
  python3 scripts/phase_k7_perf_micro.py --label after --output benchmarks/results/phase_k7/after.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BINARY = REPO / "target/release/tracejit"
WARMUPS = 5
RUNS = 30


def env_for(cache: Path, phase: Path) -> dict[str, str]:
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
        "TRACEJIT_PHASE_TIMING_PATH": str(phase),
    }


def close_extra_fds_cmd(argv: list[str]) -> list[str]:
    # Match demo/harness: close fds >2 before exec so CI/cargo descriptors do not refuse reuse.
    inner = " ".join(f'"{a}"' if " " in a else a for a in argv)
    script = (
        "for e in /proc/self/fd/*; do f=${e##*/}; "
        'case "$f" in 0|1|2) ;; *) eval "exec ${f}>&-" 2>/dev/null || true ;; esac; '
        f"done; exec {inner}"
    )
    return ["bash", "-c", script]


def median(xs: list[float]) -> float:
    return float(statistics.median(xs)) if xs else float("nan")


def compile_etl() -> Path:
    workload = REPO / "benchmarks/workloads/c-etl"
    binary = workload / "etl"
    subprocess.run(
        ["cc", "-O2", "-Wall", "-Wextra", "-o", str(binary), str(workload / "main.c")],
        cwd=REPO,
        check=True,
    )
    return binary


def compile_fixture(root: Path) -> Path:
    binary = root / "fixture-driver"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            str(REPO / "tests/fixtures/fixture_driver.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


def run_json(argv: list[str], cwd: Path, cache: Path, phase: Path) -> tuple[dict, dict, float]:
    if phase.exists():
        phase.unlink()
    started = time.perf_counter()
    completed = subprocess.run(
        close_extra_fds_cmd([str(BINARY), "run", "--json", "--", *argv]),
        cwd=cwd,
        env=env_for(cache, phase),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    report = json.loads(completed.stdout)
    phases = {}
    if phase.is_file():
        phases = json.loads(phase.read_text())
        if "phases" in phases:
            phases = phases["phases"]
    return report, phases, wall_ms


def measure_shape(name: str, prepare) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"tracejit-k7-{name}-") as tmp:
        root = Path(tmp)
        cache = root / "cache"
        phase = root / "phase.json"
        argv, cwd = prepare(root)
        # cold
        cold_report, _, cold_ms = run_json(argv, cwd, cache, phase)
        walls = []
        sqlite = []
        decode = []
        guard = []
        restore = []
        for i in range(WARMUPS + RUNS):
            report, phases, wall_ms = run_json(argv, cwd, cache, phase)
            decision = report.get("cache_decision") or report.get("kind")
            if decision not in ("Reused", "HIT", "Reused".lower()):
                # JSON uses kind / cache_decision variants
                kind = report.get("kind")
                if kind != "Reused" and report.get("cache_decision") != "Reused":
                    # tolerate string forms
                    blob = json.dumps(report)
                    if "Reused" not in blob and '"HIT"' not in blob:
                        raise SystemExit(f"{name}: expected warm reuse, got {report}")
            if i < WARMUPS:
                continue
            walls.append(wall_ms)
            if "sqlite_query_ns" in phases:
                sqlite.append(phases["sqlite_query_ns"] / 1e6)
            if "record_decode_ns" in phases:
                decode.append(phases["record_decode_ns"] / 1e6)
            if "guard_validation_ns" in phases:
                guard.append(phases["guard_validation_ns"] / 1e6)
            if "cas_restore_ns" in phases:
                restore.append(phases["cas_restore_ns"] / 1e6)
        return {
            "shape": name,
            "cold_ms": cold_ms,
            "cold_decision": cold_report.get("cache_decision") or cold_report.get("kind"),
            "warm_wall_ms_median": median(walls),
            "warm_wall_ms_p95": float(statistics.quantiles(walls, n=20)[18])
            if len(walls) >= 20
            else max(walls),
            "sqlite_query_ms_median": median(sqlite),
            "record_decode_ms_median": median(decode),
            "guard_validation_ms_median": median(guard),
            "cas_restore_ms_median": median(restore),
            "runs": RUNS,
            "warmups": WARMUPS,
        }


def prepare_etl(root: Path):
    etl = compile_etl()
    out = REPO / "benchmarks/workloads/c-etl/output"
    out.mkdir(parents=True, exist_ok=True)
    return [str(etl)], REPO


def prepare_plain(root: Path):
    fixture = compile_fixture(root)
    work = root / "work"
    work.mkdir()
    (work / "input.txt").write_text("phase-k7 plain file\n")
    return [str(fixture), "plain_file_read", str(work)], work


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not BINARY.is_file():
        raise SystemExit(f"missing {BINARY}; build release first")

    results = {
        "label": args.label,
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "binary_sha256": subprocess.check_output(
            ["sha256sum", str(BINARY)], text=True
        ).split()[0],
        "host": {
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
            "kernel": platform.release(),
        },
        "shapes": [
            measure_shape("c-etl", prepare_etl),
            measure_shape("plain_file_read", prepare_plain),
        ],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    print(f"RESULT phase-k7-perf label={args.label} wrote={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

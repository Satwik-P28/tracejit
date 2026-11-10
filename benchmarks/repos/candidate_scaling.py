#!/usr/bin/env python3
"""Measure candidate retention and selection at 1, 2, 4, 8, 16 and 32 records.

The fixture writes one output from one input. Different input states have the same command
identity but different guards, so each state adds one retained candidate. The target is the
oldest state, which makes the final lookup evaluate every retained candidate.

Usage:
    cargo build --release --workspace
    python3 benchmarks/repos/candidate_scaling.py --output benchmarks/results/phase3b/candidate-scaling.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BINARY = REPO / "target/release/tracejit"
ROOT = Path("/tmp/tracejit-phase3b-candidates")
BOUNDS = (1, 2, 4, 8, 16, 32)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def compile_fixture(root: Path) -> Path:
    binary = root / "fixture-driver"
    source = REPO / "tests/fixtures/fixture_driver.c"
    subprocess.run(
        ["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread", str(source), "-o", str(binary)],
        check=True,
    )
    return binary


def environment(cache: Path, bound: int, phase_path: Path) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "TRACEJIT_CACHE_DIR": str(cache),
        "TRACEJIT_CANDIDATE_BOUND": str(bound),
        "TRACEJIT_PHASE_TIMING": "1",
        "TRACEJIT_PHASE_TIMING_PATH": str(phase_path),
    }


def phase_timings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("phases", data)


def run_once(
    binary: Path,
    work: Path,
    cache: Path,
    bound: int,
    phase_path: Path,
    input_bytes: bytes,
) -> dict:
    (work / "input.txt").write_bytes(input_bytes)
    output = work / "output.txt"
    output.unlink(missing_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        [str(BINARY), "run", "--json", "--", str(binary), "plain_file_read", str(work)],
        cwd=work,
        env=environment(cache, bound, phase_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    report = json.loads(completed.stdout)
    phases = phase_timings(phase_path)
    return {
        "wall_ms": wall_ms,
        "report": report,
        "phases": phases,
        "output": output.read_bytes() if output.is_file() else None,
        "status": completed.returncode,
    }


def cache_rows(cache: Path) -> int:
    with sqlite3.connect(cache / "db.sqlite3") as connection:
        return int(connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0])


def cache_bytes(cache: Path) -> int:
    return sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())


def concurrent_readers(binary: Path, root: Path, payload: bytes) -> list[dict]:
    # Use a read-only command and a private workspace. Restoring one output from eight processes
    # is a fixture race, not a cache-reader race: one process can rename the destination while a
    # sibling is staging it. The integration suite already covers concurrent writers separately.
    work = root / "concurrent-work"
    cache = root / "concurrent-cache"
    work.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    (work / "input.txt").write_bytes(payload)
    phase_path = root / "concurrent-phases.json"
    environment_value = environment(cache, 8, phase_path)
    seed = subprocess.run(
        [str(BINARY), "run", "--json", "--", str(binary), "read_to_stdout", str(work)],
        cwd=work,
        env=environment_value,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert seed.returncode == 0, seed.stderr
    processes = [
        subprocess.Popen(
            [str(BINARY), "run", "--json", "--", str(binary), "read_to_stdout", str(work)],
            cwd=work,
            env=environment_value,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(8)
    ]
    results = []
    for process in processes:
        stdout, stderr = process.communicate()
        report = json.loads(stdout) if stdout.startswith(b"{") else {}
        results.append(
            {
                "status": process.returncode,
                "decision": report.get("cache_decision", "NO_JSON"),
                "reason": report.get("decision_reason"),
                "stderr": stderr.decode(errors="replace")[-240:],
            }
        )
    return results


def measure(binary: Path, work: Path, bound: int) -> dict:
    cache = ROOT / f"cache-{bound}"
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True)
    phase_path = ROOT / "phases.json"

    build = []
    for index in range(bound):
        payload = f"candidate-state-{index}\n".encode()
        row = run_once(binary, work, cache, bound, phase_path, payload)
        assert row["status"] == 0, row
        assert row["output"] == payload, (bound, index, row["output"])
        build.append(row["report"].get("cache_decision"))

    target = b"candidate-state-0\n"
    selected = run_once(binary, work, cache, bound, phase_path, target)
    assert selected["status"] == 0, selected
    assert selected["output"] == target, selected
    assert selected["report"].get("cache_decision") == "Reused", selected
    retained = cache_rows(cache)

    repeated = run_once(binary, work, cache, bound, phase_path, target)
    assert repeated["status"] == 0, repeated
    assert repeated["report"].get("cache_decision") == "Reused", repeated

    concurrent = concurrent_readers(binary, ROOT, target)

    miss_payload = f"candidate-miss-{bound}\n".encode()
    miss = run_once(binary, work, cache, bound, phase_path, miss_payload)
    assert miss["status"] == 0, miss
    assert miss["output"] == miss_payload, miss
    assert miss["report"].get("cache_decision") != "Reused", miss

    after_miss = cache_rows(cache)
    return {
        "bound": bound,
        "build_decisions": build,
        "retained_candidates": retained,
        "retained_after_miss": after_miss,
        "cache_bytes": cache_bytes(cache),
        "target_decision": selected["report"].get("cache_decision"),
        "target_wall_ms": round(selected["wall_ms"], 3),
        "target_phases": selected["phases"],
        "repeated_decision": repeated["report"].get("cache_decision"),
        "repeated_wall_ms": round(repeated["wall_ms"], 3),
        "miss_decision": miss["report"].get("cache_decision"),
        "miss_wall_ms": round(miss["wall_ms"], 3),
        "concurrent": concurrent,
        "concurrent_all_reused": all(
            row["status"] == 0 and row["decision"] == "Reused" for row in concurrent
        ),
    }


def measure_eviction(binary: Path, work: Path) -> dict:
    cache = ROOT / "cache-eviction"
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True)
    phase_path = ROOT / "eviction-phases.json"
    bound = 8
    for index in range(16):
        payload = f"eviction-state-{index}\n".encode()
        row = run_once(binary, work, cache, bound, phase_path, payload)
        assert row["status"] == 0 and row["output"] == payload, row
    retained = cache_rows(cache)
    evicted = run_once(
        binary, work, cache, bound, phase_path, b"eviction-state-0\n"
    )
    surviving = run_once(
        binary, work, cache, bound, phase_path, b"eviction-state-15\n"
    )
    return {
        "bound": bound,
        "states_written": 16,
        "retained_candidates": retained,
        "evicted_state_decision": evicted["report"].get("cache_decision"),
        "surviving_state_decision": surviving["report"].get("cache_decision"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default=str(REPO / "benchmarks/results/phase3b/candidate-scaling.json")
    )
    args = parser.parse_args()
    if not BINARY.is_file():
        raise SystemExit("missing target/release/tracejit; run cargo build --release --workspace")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    work = ROOT / "work"
    work.mkdir()
    binary = compile_fixture(ROOT)

    rows = []
    for bound in BOUNDS:
        row = measure(binary, work, bound)
        rows.append(row)
        print(
            f"bound={bound} retained={row['retained_candidates']} "
            f"target={row['target_decision']} {row['target_wall_ms']:.3f}ms "
            f"miss={row['miss_wall_ms']:.3f}ms",
            file=sys.stderr,
        )

    eviction = measure_eviction(binary, work)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "phase": "3B",
        "experiment": "candidate scaling",
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
        "binary": {"sha256": sha256(BINARY), "size": BINARY.stat().st_size},
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "cpus": os.cpu_count(),
            "memory": Path("/proc/meminfo").read_text().splitlines()[0],
        },
        "bounds": rows,
        "eviction": eviction,
        "method": {
            "candidate_creation": "one distinct input state per candidate",
            "target": "oldest retained state, forcing every candidate to be evaluated",
            "selection": "newest-first, stop at the first candidate whose guards pass",
            "repeat": "same target after it has become newest",
            "miss": "new input state not present in the cache",
            "concurrency": "eight simultaneous identical readers",
        },
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    summary = {
        row["bound"]: {
            "retained": row["retained_candidates"],
            "target_ms": row["target_wall_ms"],
            "miss_ms": row["miss_wall_ms"],
            "concurrent_all_reused": row["concurrent_all_reused"],
        }
        for row in rows
    }
    summary["eviction"] = eviction
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

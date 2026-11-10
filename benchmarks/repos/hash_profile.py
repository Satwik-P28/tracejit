#!/usr/bin/env python3
"""Profile strict guard hashing from one kilobyte through 256 MiB.

The fixture copies one input to one output. The first invocation traces; the following
invocations reuse and hash the input on every hit. `guard_validation_ns` is the measured
strict-validation phase, including metadata and content hashing.

Usage:
    cargo build --release --workspace
    python3 benchmarks/repos/hash_profile.py --output benchmarks/results/phase3b/hash-profile.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BINARY = REPO / "target/release/tracejit"
ROOT = Path("/tmp/tracejit-phase3b-hash")
SIZES = (1 << 10, 1 << 16, 1 << 20, 1 << 24, 1 << 26, 1 << 28)
BLOCK = b"tracejit-hash-profile-block\n" * 4096


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def write_payload(path: Path, size: int) -> None:
    with path.open("wb") as handle:
        remaining = size
        while remaining:
            chunk = BLOCK[: min(remaining, len(BLOCK))]
            handle.write(chunk)
            remaining -= len(chunk)


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


def phase_timings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("phases", data)


def run_once(binary: Path, work: Path, cache: Path, phase_path: Path) -> dict:
    started = time.perf_counter()
    completed = subprocess.run(
        [str(BINARY), "run", "--json", "--", str(binary), "plain_file_read", str(work)],
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
        report = {"cache_decision": "NO_JSON", "stderr": completed.stderr.decode(errors="replace")}
    return {
        "wall_ms": wall_ms,
        "report": report,
        "phases": phase_timings(phase_path),
        "status": completed.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default=str(REPO / "benchmarks/results/phase3b/hash-profile.json")
    )
    parser.add_argument("--hits", type=int, default=3)
    args = parser.parse_args()
    if not BINARY.is_file():
        raise SystemExit("missing target/release/tracejit; run cargo build --release --workspace")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    work = ROOT / "work"
    work.mkdir()
    binary = compile_fixture(ROOT)
    input_path = work / "input.txt"
    output_path = work / "output.txt"

    rows = []
    for size in SIZES:
        cache = ROOT / f"cache-{size}"
        cache.mkdir()
        write_payload(input_path, size)
        output_path.unlink(missing_ok=True)
        cold = run_once(binary, work, cache, ROOT / "phases.json")
        assert cold["status"] == 0, cold
        assert cold["report"].get("cache_decision") == "Executed", cold
        assert output_path.stat().st_size == size
        samples = []
        for _ in range(args.hits):
            hit = run_once(binary, work, cache, ROOT / "phases.json")
            assert hit["status"] == 0, hit
            assert hit["report"].get("cache_decision") == "Reused", hit
            samples.append(hit)
        guard = [sample["phases"].get("guard_validation_ns", 0) for sample in samples]
        restore = [sample["phases"].get("cas_restore_ns", 0) for sample in samples]
        wall = [sample["wall_ms"] for sample in samples]
        guard_median = statistics.median(guard)
        rows.append(
            {
                "input_bytes": size,
                "cold_ms": round(cold["wall_ms"], 3),
                "cold_phases": cold["phases"],
                "warm_ms_samples": [round(value, 3) for value in wall],
                "warm_ms_median": round(statistics.median(wall), 3),
                "guard_ns_samples": guard,
                "guard_ns_median": guard_median,
                "guard_mib_per_second": round(
                    (size / (1024 * 1024)) / (guard_median / 1_000_000_000), 2
                )
                if guard_median
                else None,
                "restore_ns_samples": restore,
                "restore_ns_median": statistics.median(restore),
                "hits": args.hits,
            }
        )
        print(
            f"size={size} cold={rows[-1]['cold_ms']:.3f}ms "
            f"warm={rows[-1]['warm_ms_median']:.3f}ms "
            f"guard={guard_median / 1_000_000:.3f}ms "
            f"{rows[-1]['guard_mib_per_second']} MiB/s",
            file=sys.stderr,
        )

    report = {
        "phase": "3B",
        "experiment": "strict dependency hashing",
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
        "method": {
            "fixture": "plain_file_read copies one input to one output",
            "sizes": list(SIZES),
            "cold": "first observed execution, including tracing and output capture",
            "warm": "guarded reuse, including metadata and content validation",
            "phase": "TRACEJIT_PHASE_TIMING guard_validation_ns",
            "disk": "input and restored output are resident in /tmp",
        },
        "rows": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({row["input_bytes"]: row["warm_ms_median"] for row in rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

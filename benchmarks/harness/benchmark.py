#!/usr/bin/env python3
"""Run reproducible TraceJIT timing samples and emit machine-readable facts."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = ROOT / "benchmarks" / "workloads" / "python-etl" / "main.py"


def timed(command: list[str], env: dict[str, str], require_reused: bool = False) -> int:
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command, cwd=ROOT, env=env, check=True, capture_output=True
    )
    elapsed = time.perf_counter_ns() - started
    if require_reused:
        diagnostic = completed.stderr.decode(errors="replace")
        if "cache          HIT" not in diagnostic:
            raise RuntimeError(f"cached benchmark sample did not reuse:\n{diagnostic}")
    return elapsed


def sample(
    command: list[str],
    env: dict[str, str],
    runs: int,
    require_reused: bool = False,
) -> dict[str, int]:
    values = [timed(command, env, require_reused) for _ in range(runs)]
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "runs": runs,
        "median_ns": int(statistics.median(values)),
        "p95_ns": ordered[p95_index],
    }


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def memory_description() -> str:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unavailable"


def filesystem_description() -> dict[str, object]:
    filesystem_type = subprocess.run(
        ["stat", "-f", "-c", "%T", str(ROOT)],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    return {
        "type": filesystem_type or "unavailable",
        "capacity": shutil.disk_usage(ROOT)._asdict(),
    }


def workload_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted((WORKLOAD.parent).glob("**/*")):
        if path.is_file() and "output" not in path.parts:
            digest.update(path.relative_to(WORKLOAD.parent).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--tracejit", default=str(ROOT / "target" / "release" / "tracejit"))
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")
    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")

    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="tracejit-benchmark-") as cache:
        traced_env = env | {"TRACEJIT_CACHE_DIR": cache}
        baseline = sample(["python3", str(WORKLOAD)], env, args.runs)
        first_trace = sample(
            [str(tracejit), "analyze", "--", "python3", str(WORKLOAD)],
            traced_env,
            args.runs,
        )
        subprocess.run(
            [str(tracejit), "run", "--", "python3", str(WORKLOAD)],
            cwd=ROOT,
            env=traced_env,
            check=True,
            capture_output=True,
        )
        cached = sample(
            [str(tracejit), "run", "--", "python3", str(WORKLOAD)],
            traced_env,
            args.runs,
            require_reused=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip() or "uncommitted"
        result = {
            "tracejit_commit": commit,
            "kernel": platform.release(),
            "cpu": cpu_model(),
            "memory": memory_description(),
            "filesystem": filesystem_description(),
            "workload": "benchmarks/workloads/python-etl",
            "workload_sha256": workload_hash(),
            "command": ["python3", str(WORKLOAD)],
            "state": "warm process and filesystem caches; isolated TraceJIT cache",
            "baseline": baseline,
            "traced": first_trace,
            "cached_end_to_end": cached,
        }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

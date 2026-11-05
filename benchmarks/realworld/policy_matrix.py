#!/usr/bin/env python3
"""Compare cache-admission policies over a 20-invocation developer workflow.

One invocation is the fixed sequence `sed -> wc -c -> md5sum -> gzip -9 -c` over a 5.4 MB file.
Cumulative wall time is recorded after 1, 2, 3, 5, 10 and 20 invocations. An unrelated file is
touched before invocation 6; the input is edited before invocation 11, so both invalidation and
steady-state reuse are exercised.

Policies: direct, never, always, auto-v1 (Phase 2H), auto (Phase 2I).

Usage:
    python3 benchmarks/realworld/policy_matrix.py [--session a] [--output-dir DIR] [--rows N]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "allocator-entropy-v1"
POLICIES = {
    "direct": None,
    "never": ["--contract", CONTRACT, "--admission", "never"],
    "always": ["--contract", CONTRACT],
    "auto-v1": ["--contract", CONTRACT, "--admission", "auto-v1"],
    "auto": ["--contract", CONTRACT, "--admission", "auto"],
}
CHECKPOINTS = (1, 2, 3, 5, 10, 20)


def binary() -> Path:
    for candidate in (REPO / "target" / "release" / "tracejit", REPO / "target" / "debug" / "tracejit"):
        if candidate.is_file():
            return candidate
    raise SystemExit("no tracejit binary")


def environment(cache: Path | None) -> dict:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "LC_ALL": "C", "TZ": "UTC"}
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(command, cwd, env):
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert completed.returncode == 0, command
    return (time.perf_counter() - started) * 1000.0


STEPS = [
    ["sed", "-e", "s/alpha/ALPHA/g", "data.txt"],
    ["wc", "-c", "data.txt"],
    ["md5sum", "data.txt"],
    ["gzip", "-9", "-c", "data.txt"],
]


def prepare(root: Path, rows: int) -> None:
    words = ["alpha", "beta", "gamma", "delta"]
    (root / "data.txt").write_text(
        "".join(f"{i} {words[i % 4]} {i * 7 % 1013}\n" for i in range(rows))
    )
    (root / "unrelated.txt").write_text("not an input\n")
    os.utime(root / "unrelated.txt")


def session(root: Path, policy: str, cache_root: Path, invocations: int, rows: int) -> dict:
    # The edit at invocation 11 mutates the corpus, so every policy must start from the same one.
    prepare(root, rows)
    flags = POLICIES[policy]
    cache = cache_root / policy
    env = environment(cache if flags is not None else None)
    elapsed = []
    total = 0.0
    marks: dict[str, float] = {}
    for index in range(1, invocations + 1):
        if index == 6:
            os.utime(root / "unrelated.txt")
        if index == 11:
            (root / "data.txt").write_text(
                "".join(f"{i} edited epsilon\n" for i in range(40_000))
            )
        for step in STEPS:
            command = step if flags is None else [str(binary()), "run", *flags, "--", *step]
            total += run(command, root, env)
        if index in CHECKPOINTS:
            marks[str(index)] = round(total, 2)
    return {"total_ms": round(total, 2), "cumulative_ms": marks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="a")
    parser.add_argument("--rows", type=int, default=400_000)
    parser.add_argument("--output-dir", default="benchmarks/results/phase2i/policy")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="tracejit-policy-"))
    prepare(root, args.rows)
    cache_root = root / "cache"
    results = {"session": args.session, "invocations": 20, "policies": {}}
    for policy in POLICIES:
        results["policies"][policy] = session(root, policy, cache_root, 20, args.rows)
    direct = results["policies"]["direct"]["total_ms"]
    for policy, entry in results["policies"].items():
        entry["speedup"] = round(direct / entry["total_ms"], 2)
        entry["slowdown"] = round(entry["total_ms"] / direct, 2)
    output_dir = REPO / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"policy-{args.session}.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({name: {"total_ms": entry["total_ms"], "speedup": entry["speedup"],
                             "slowdown": entry["slowdown"], "cumulative_ms": entry["cumulative_ms"]}
                      for name, entry in results["policies"].items()}, indent=2))
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

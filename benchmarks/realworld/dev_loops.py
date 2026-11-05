#!/usr/bin/env python3
"""Fixed developer-loop suite for Phase 2H.

Every scenario is deterministic and uses only tools present on this host. Each is run in three
modes over the same inputs:

  direct  - ordinary execution, no TraceJIT
  always  - ``tracejit run --contract allocator-entropy-v1`` (trace/cache every invocation)
  auto    - the same plus ``--admission auto`` (measure first; trace only if a hit can repay)

Scenarios cover a multi-stage transform, repeated compilation, code generation, a short command
next to an expensive one, and an edit between runs. Totals include tracing, validation, fallback
and restoration, so a scenario where nothing reuses is reported as a slowdown rather than hidden.

Usage:
    python3 benchmarks/realworld/dev_loops.py [--reps N] [--output-dir DIR] [--session NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "allocator-entropy-v1"
GENERATED = "".join(
    f"int value_{index}(void) {{ return {index * 7 % 97}; }}\n" for index in range(2000)
)


def binary() -> Path:
    for candidate in (REPO / "target" / "release" / "tracejit", REPO / "target" / "debug" / "tracejit"):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary; run: cargo build --release -p tracejit-cli")


def environment(cache: Path | None) -> dict:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(command, cwd, env):
    started = time.perf_counter()
    completed = subprocess.run(
        command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return {
        "ms": (time.perf_counter() - started) * 1000.0,
        "stdout": completed.stdout,
        "exit": completed.returncode,
    }


def traced(command, cwd, env, admission, as_json=False):
    prefix = [str(binary()), "run"]
    if as_json:
        prefix.append("--json")
    prefix += ["--contract", CONTRACT]
    if admission != "always":
        prefix += ["--admission", admission]
    return run([*prefix, "--", *command], cwd, env)


def prepare(root: Path) -> None:
    data = "".join(f"{i} alpha beta gamma delta\n" for i in range(60_000))
    (root / "data.txt").write_text(data)
    (root / "watch.txt").write_text("alpha beta\n" * 2000)
    source = "\n".join(f"int f{index}(void) {{ return {index}; }}" for index in range(300))
    (root / "unit.c").write_text(source + "\n")
    (root / "template.txt").write_text(GENERATED.replace("value_", "generated_"))


SCENARIOS = [
    (
        "transform",
        [["sed", "-e", "s/alpha/ALPHA/g", "data.txt"], ["wc", "-c", "data.txt"]],
        "filter a changed word, then measure the file",
    ),
    (
        "compile",
        [["cc", "-c", "-O2", "unit.c", "-o", "unit.o"], ["cc", "-c", "-O2", "unit.c", "-o", "unit.o"]],
        "compile the same translation unit twice",
    ),
    (
        "codegen",
        [["sed", "-e", "s/generated_/value_/g", "template.txt"], ["cc", "-c", "-O2", "unit.c", "-o", "unit.o"]],
        "render generated source, then compile",
    ),
    (
        "mixed",
        [["wc", "-c", "watch.txt"], ["gzip", "-9", "-c", "data.txt"], ["md5sum", "data.txt"]],
        "a short command beside an expensive one",
    ),
    (
        "edit",
        [["md5sum", "watch.txt"], ["sed", "-i", "s/beta/BETA/g", "watch.txt"], ["md5sum", "watch.txt"]],
        "edit an input between two invocations",
    ),
]


def median(values):
    return round(statistics.median(values), 2) if values else None


def measure_scenario(root: Path, steps, mode: str, reps: int, cache_root: Path):
    env = environment(cache_root if mode != "direct" else None)
    admission = "always" if mode == "direct" else ("always" if mode == "always" else "auto")
    if mode != "direct":
        # `auto` measures the direct cost on the first invocation and traces on the second.
        for _ in range(2 if mode == "auto" else 1):
            for step in steps:
                traced(step, root, env, admission)
    samples = []
    for _ in range(reps):
        started = time.perf_counter()
        for step in steps:
            if mode == "direct":
                result = run(step, root, env)
            else:
                result = traced(step, root, env, admission)
            assert result["exit"] == 0, (mode, step, result["exit"])
        samples.append((time.perf_counter() - started) * 1000.0)
    decisions = []
    if mode != "direct":
        for step in steps:
            result = traced(step, root, env, admission, as_json=True)
            try:
                report = json.loads(result["stdout"])
            except json.JSONDecodeError:
                decisions.append({"command": " ".join(step), "decision": "unparsed"})
                continue
            decisions.append({
                "command": " ".join(step),
                "decision": report.get("cache_decision") or report.get("kind"),
                "classification": report.get("classification"),
            })
    return samples, decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--session", default="a")
    parser.add_argument("--output-dir", default="benchmarks/results/phase2h/dev-loops")
    args = parser.parse_args()

    output_dir = REPO / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="tracejit-develoops-"))
    root = scratch / "work"
    root.mkdir()
    prepare(root)

    results = {
        "generated_by": "benchmarks/realworld/dev_loops.py",
        "session": args.session,
        "contract": CONTRACT,
        "reps": args.reps,
        "scenarios": [],
    }
    for name, steps, description in SCENARIOS:
        entry = {"name": name, "description": description, "steps": [" ".join(step) for step in steps]}
        for mode in ("direct", "always", "auto"):
            cache = scratch / f"cache-{name}-{mode}"
            samples, decisions = measure_scenario(root, steps, mode, args.reps, cache)
            entry[mode] = {
                "median_ms": median(samples),
                "samples_ms": [round(value, 2) for value in samples],
                "decisions": decisions,
            }
        always = entry["always"]["median_ms"]
        auto = entry["auto"]["median_ms"]
        direct = entry["direct"]["median_ms"]
        entry["always_vs_direct"] = round(always / direct, 2) if direct else None
        entry["auto_vs_direct"] = round(auto / direct, 2) if direct else None
        results["scenarios"].append(entry)

    always_totals = [entry["always"]["median_ms"] for entry in results["scenarios"]]
    auto_totals = [entry["auto"]["median_ms"] for entry in results["scenarios"]]
    direct_totals = [entry["direct"]["median_ms"] for entry in results["scenarios"]]
    results["totals"] = {
        "direct_ms": round(sum(direct_totals), 2),
        "always_ms": round(sum(always_totals), 2),
        "auto_ms": round(sum(auto_totals), 2),
        "always_vs_direct": round(sum(always_totals) / sum(direct_totals), 2),
        "auto_vs_direct": round(sum(auto_totals) / sum(direct_totals), 2),
        "slowdowns_always": sum(1 for entry in results["scenarios"] if entry["always_vs_direct"] > 1.0),
        "slowdowns_auto": sum(1 for entry in results["scenarios"] if entry["auto_vs_direct"] > 1.0),
    }
    output = output_dir / f"dev-loops-{args.session}.json"
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["totals"], indent=2))
    for entry in results["scenarios"]:
        print(
            f"{entry['name']:10} direct={entry['direct']['median_ms']:8.2f} "
            f"always={entry['always']['median_ms']:8.2f} ({entry['always_vs_direct']}x) "
            f"auto={entry['auto']['median_ms']:8.2f} ({entry['auto_vs_direct']}x)"
        )
    shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

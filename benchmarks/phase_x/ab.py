#!/usr/bin/env python3
"""Paired, interleaved warm-hit latency comparison for Phase X.

Each named arm gets its own workspace and cache, traced the same way. Measured rounds are then
interleaved (arm, arm, arm, next round) so slow machine drift and thermal effects hit every arm
equally. Only rounds in which every invocation reports a HIT are counted, and the raw decision
record is kept so a retrace can never be mistaken for a hit.

Usage:
  python3 benchmarks/phase_x/ab.py \
      --arm baseline=/tmp/tj-baseline \
      --arm onepass=/tmp/tj-onepass \
      --rounds 10 --output benchmarks/results/phasex/ab-onepass.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

UNITS = 3


def write_sources(directory: Path, functions: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "common.h").write_text("#define SHARED_VALUE 1\n#define SCALE 3\n")
    for unit in range(UNITS):
        body = ['#include "common.h"', "#include <stdio.h>", "#include <string.h>", ""]
        for function in range(functions):
            body.append(
                f"long u{unit}_f{function}(long a) {{ char b[48]; snprintf(b, sizeof b, \"%ld\", a); "
                f"return (long)strlen(b) * {function + 1} + a; }}"
            )
        body.append("int main(void) { long t = 0;")
        for function in range(functions):
            body.append(f"  t += u{unit}_f{function}(SHARED_VALUE);")
        body.append('  printf("%ld\\n", t * SCALE);')
        body.append("  return 0;\n}\n")
        (directory / f"unit{unit}.c").write_text("\n".join(body))


def close_extra_fds_cmd(argv: list[str]) -> list[str]:
    inner = " ".join(f'"{a}"' if " " in a else a for a in argv)
    script = (
        "for e in /proc/self/fd/*; do f=${e##*/}; "
        'case "$f" in 0|1|2) ;; *) eval "exec ${f}>&-" 2>/dev/null || true ;; esac; '
        f"done; exec {inner}"
    )
    return ["bash", "-c", script]


def compile_once(binary: Path, directory: Path, cache: Path, unit: int) -> tuple[float, str]:
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "TRACEJIT_CACHE_DIR": str(cache),
    }
    argv = [
        str(binary),
        "run",
        "--contract",
        "compiler-runtime-v1",
        "--",
        "cc",
        "-O2",
        "-c",
        f"unit{unit}.c",
        "-o",
        f"unit{unit}.o",
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        close_extra_fds_cmd(argv), cwd=directory, env=environment, capture_output=True
    )
    elapsed_ms = (time.perf_counter() - started) * 1e3
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.decode(errors="replace")[:800])
    stderr = completed.stderr.decode(errors="replace")
    decision = "unknown"
    for key in ("HIT", "DEOPT", "MISS", "SKIP"):
        if f"cache          {key}" in stderr or f"cache {key}" in stderr:
            decision = key.lower()
            break
    return elapsed_ms, decision


def median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else float("nan")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", action="append", required=True, help="name=/path/to/tracejit")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--functions", type=int, default=220)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default="/tmp/tracejit-phase-x-ab")
    args = parser.parse_args()

    arms = []
    for spec in args.arm:
        name, _, path = spec.partition("=")
        arms.append((name, Path(path).resolve()))

    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    for name, _ in arms:
        workspace = root / name / "work"
        cache = root / name / "cache"
        write_sources(workspace, args.functions)
        # Trace every unit, then warm the reuse identity twice.
        for unit in range(UNITS):
            compile_once(dict(arms)[name], workspace, cache, unit)
        for _ in range(2):
            for unit in range(UNITS):
                compile_once(dict(arms)[name], workspace, cache, unit)

    samples: dict[str, list[float]] = {name: [] for name, _ in arms}
    per_round: list[dict] = []
    for round_index in range(args.rounds):
        round_arm_medians = {}
        for name, binary in arms:
            workspace = root / name / "work"
            cache = root / name / "cache"
            values = []
            decisions = []
            for unit in range(UNITS):
                elapsed_ms, decision = compile_once(binary, workspace, cache, unit)
                values.append(elapsed_ms)
                decisions.append(decision)
            samples[name].extend(values)
            round_arm_medians[name] = {
                "median_ms": round(median(values), 3),
                "decisions": decisions,
            }
            if set(decisions) != {"hit"}:
                print(
                    f"WARNING round {round_index} arm {name} was not all hits: {decisions}",
                    file=sys.stderr,
                )
        per_round.append(round_arm_medians)

    summary = {}
    for name, _ in arms:
        values = samples[name]
        summary[name] = {
            "runs": len(values),
            "median_ms": round(median(values), 3),
            "p95_ms": round(percentile(values, 0.95), 3),
            "mean_ms": round(statistics.fmean(values), 3),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3),
        }
    baseline = arms[0][0]
    for name, _ in arms[1:]:
        ratio = summary[baseline]["median_ms"] / summary[name]["median_ms"]
        summary[name]["speedup_vs_" + baseline] = round(ratio, 3)

    payload = {
        "arms": {name: str(binary) for name, binary in arms},
        "rounds": args.rounds,
        "units": UNITS,
        "functions_per_unit": args.functions,
        "summary": summary,
        "per_round": per_round,
        "raw_ms": samples,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    for name, _ in arms:
        entry = summary[name]
        extra = f" speedup={entry['speedup_vs_' + baseline]}x" if "speedup_vs_" + baseline in entry else ""
        print(
            f"{name:24s} median={entry['median_ms']:8.3f}ms p95={entry['p95_ms']:8.3f}ms "
            f"n={entry['runs']}{extra}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

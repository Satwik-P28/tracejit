#!/usr/bin/env python3
"""Phase X guard-cost profiler.

Measures, never estimates. This harness:

1. Builds a synthetic C workload (three translation units behind one shared header).
2. Traces each unit once with `tracejit run --contract compiler-runtime-v1`.
3. Runs further identical invocations and records `TRACEJIT_PHASE_TIMING` output for each.
4. Dumps the stored record with `tracejit explain --json` for offline dependency analysis.
5. Reports medians and the raw samples.

Usage:
  cargo build --release -p tracejit-cli
  python3 benchmarks/phase_x/profile.py \
      --tracejit "$PWD/target/release/tracejit" \
      --workload edits --rounds 6 --output benchmarks/results/phasex/profile-baseline.json
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
HEADER_STATES = (1, 2)


def write_sources(directory: Path, functions: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_header(directory, 1)
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


def write_header(directory: Path, value: int) -> None:
    (directory / "common.h").write_text(
        f"#define SHARED_VALUE {value}\n#define SCALE 3\n"
    )


def close_extra_fds_cmd(argv: list[str]) -> list[str]:
    """Close descriptors above stderr before exec so the reused run sees a clean table."""
    inner = " ".join(f'"{a}"' if " " in a else a for a in argv)
    script = (
        "for e in /proc/self/fd/*; do f=${e##*/}; "
        'case "$f" in 0|1|2) ;; *) eval "exec ${f}>&-" 2>/dev/null || true ;; esac; '
        f"done; exec {inner}"
    )
    return ["bash", "-c", script]


def base_environment(cache: Path) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "TRACEJIT_CACHE_DIR": str(cache),
    }


def compile_argv(unit: int, flags: list[str]) -> list[str]:
    return ["cc", *flags, "-c", f"unit{unit}.c", "-o", f"unit{unit}.o"]


def run_traced(
    binary: Path,
    directory: Path,
    cache: Path,
    unit: int,
    flags: list[str],
    phase_path: Path | None,
    guard_profile: bool = False,
) -> dict:
    environment = base_environment(cache)
    if phase_path is not None:
        environment["TRACEJIT_PHASE_TIMING"] = "1"
        environment["TRACEJIT_PHASE_TIMING_PATH"] = str(phase_path)
    if guard_profile:
        environment["TRACEJIT_GUARD_PROFILE"] = "1"
    argv = [
        str(binary),
        "run",
        "--contract",
        "compiler-runtime-v1",
        "--",
        *compile_argv(unit, flags),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        close_extra_fds_cmd(argv),
        cwd=directory,
        env=environment,
        capture_output=True,
    )
    elapsed_ns = int((time.perf_counter() - started) * 1e9)
    stderr = completed.stderr.decode(errors="replace")
    if completed.returncode != 0:
        raise SystemExit(f"tracejit run failed: {stderr[:800]}")
    decision = "unknown"
    for key in ("HIT", "DEOPT", "MISS", "SKIP"):
        if f"cache          {key}" in stderr or f"cache {key}" in stderr:
            decision = key.lower()
            break
    phases = None
    if phase_path is not None and phase_path.exists():
        phases = json.loads(phase_path.read_text())
        phase_path.unlink()
    return {"wall_ns": elapsed_ns, "decision": decision, "phases": phases}


def median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else float("nan")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return float(ordered[index])


def dump_record(binary: Path, cache: Path, directory: Path, output: Path) -> dict | None:
    """Dump the newest stored record (the last traced unit) as JSON."""
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "TRACEJIT_CACHE_DIR": str(cache),
    }
    completed = subprocess.run(
        [str(binary), "explain", "--json"],
        cwd=directory,
        env=environment,
        capture_output=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(completed.stdout)
    return json.loads(completed.stdout)


def summarize(samples: list[dict]) -> dict:
    walls = [sample["wall_ns"] / 1e6 for sample in samples]
    phase_keys = sorted(
        {
            key
            for sample in samples
            if sample["phases"]
            for key, value in sample["phases"].items()
            if isinstance(value, int)
        }
    )
    phases = {
        key: {
            "median_ms": round(
                median(
                    [
                        sample["phases"].get(key, 0) / 1e6
                        for sample in samples
                        if sample["phases"]
                    ]
                ),
                3,
            )
        }
        for key in phase_keys
    }
    profiles = [
        sample["phases"]["guard_profile"]
        for sample in samples
        if sample["phases"] and sample["phases"].get("guard_profile")
    ]
    profile_summary = None
    if profiles:
        numeric_fields = sorted(
            {
                field
                for profile in profiles
                for single_pass in profile["passes"]
                for field, value in single_pass.items()
                if isinstance(value, int)
            }
        )
        by_pass = []
        for pass_index in range(max(len(profile["passes"]) for profile in profiles)):
            entry = {"pass": pass_index + 1}
            for field in numeric_fields:
                values = [
                    profile["passes"][pass_index][field]
                    for profile in profiles
                    if len(profile["passes"]) > pass_index
                    and isinstance(profile["passes"][pass_index].get(field), int)
                ]
                if values:
                    entry[f"{field}_median"] = round(median(values), 3)
            by_pass.append(entry)
        profile_summary = {
            "runs_with_profile": len(profiles),
            "passes_median": by_pass,
            "guards_by_kind": profiles[-1].get("guards_by_kind"),
            "unique_paths_by_kind": profiles[-1].get("unique_paths_by_kind"),
            "peak_rss_kb_median": round(
                median([profile.get("peak_rss_kb", 0) for profile in profiles]), 1
            ),
            "samples": profiles,
        }
    return {
        "runs": len(samples),
        "decisions": {
            decision: sum(1 for sample in samples if sample["decision"] == decision)
            for decision in sorted({sample["decision"] for sample in samples})
        },
        "wall_ms": {
            "median": round(median(walls), 3),
            "p95": round(percentile(walls, 0.95), 3),
            "samples": [round(value, 3) for value in walls],
        },
        "phases_ms": phases,
        "guard_profile": profile_summary,
        "raw_phases": [sample["phases"] for sample in samples],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument(
        "--workload", default="edits", choices=["repeat", "edits"]
    )
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--functions", type=int, default=220)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--guard-profile",
        action="store_true",
        help="enable TRACEJIT_GUARD_PROFILE=1 for the measured runs",
    )
    parser.add_argument("--root", default="/tmp/tracejit-phase-x-profile")
    args = parser.parse_args()

    binary = Path(args.tracejit).resolve()
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    workspace = root / "work"
    cache = root / "cache"
    write_sources(workspace, args.functions)

    # 1. Trace every unit (cold), then confirm a warm hit.
    cold = []
    for unit in range(UNITS):
        cold.append(run_traced(binary, workspace, cache, unit, ["-O2"], None))
    # Warm up with exactly the environment the measured rounds use. The trace run itself reads
    # every input, so the first repeat can miss once on a fresh atime, and the measurement
    # variables (`TRACEJIT_PHASE_TIMING`, `TRACEJIT_GUARD_PROFILE`) are part of the recorded
    # environment identity, so a run without them does not warm the identity a measured run
    # looks up. Both would otherwise appear as a retrace inside the measured window.
    for unit in range(UNITS):
        run_traced(binary, workspace, cache, unit, ["-O2"], None)
    for unit in range(UNITS):
        run_traced(
            binary,
            workspace,
            cache,
            unit,
            ["-O2"],
            root / "phase.json",
            guard_profile=args.guard_profile,
        )

    record = dump_record(binary, cache, workspace, root / "record.json")

    # 2. Warm-hit samples with phase timing.
    if args.workload == "edits":
        write_header(workspace, HEADER_STATES[1])
    samples = []
    for round_index in range(args.rounds):
        for unit in range(UNITS):
            phase_path = root / "phase.json"
            samples.append(
                run_traced(
                    binary,
                    workspace,
                    cache,
                    unit,
                    ["-O2"],
                    phase_path,
                    guard_profile=args.guard_profile,
                )
            )

    payload = {
        "tracejit": str(binary),
        "workload": args.workload,
        "rounds": args.rounds,
        "units": UNITS,
        "functions_per_unit": args.functions,
        "cold": cold,
        "warm": summarize(samples),
        "record_path": str(root / "record.json"),
        "record": record,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    warm = payload["warm"]
    print(
        f"warm: n={warm['runs']} median={warm['wall_ms']['median']}ms "
        f"p95={warm['wall_ms']['p95']}ms decisions={warm['decisions']}",
        file=sys.stderr,
    )
    if set(warm["decisions"]) != {"hit"}:
        print(
            f"WARNING: measured rounds were not all hits: {warm['decisions']}",
            file=sys.stderr,
        )
    for key in (
        "guard_validation_ns",
        "guard_recheck_ns",
        "cas_restore_ns",
        "stdio_replay_ns",
        "record_decode_ns",
    ):
        value = warm["phases_ms"].get(key, {}).get("median_ms")
        if value is not None:
            print(f"  {key:24s} {value:8.3f}ms", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

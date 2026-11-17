#!/usr/bin/env python3
"""Phase S: warm-hit phase attribution across input sizes.

For each size, runs the guarded fixture cold once, then 15 warm runs with
TRACEJIT_PHASE_TIMING enabled, and reports median phase times. Also runs the
fixture directly (no TraceJIT) for the same size as the floor.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZES = [4 * 1024, 64 * 1024, 1024 * 1024, 4 * 1024 * 1024, 64 * 1024 * 1024]
PHASES = [
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
    "process_startup_ns",
]


def run_binary(binary: Path, args, cwd: Path, env_extra=None, timeout=120):
    env = dict(os.environ)
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    if env_extra:
        env.update(env_extra)
    started = time.perf_counter()
    proc = subprocess.run(
        [str(binary), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        timeout=timeout,
        close_fds=True,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return proc, elapsed_ms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--output", default=str(ROOT / "research/phase_s/results/phases.json"))
    args = parser.parse_args()
    binary = ROOT / "target/release/tracejit"
    results = []
    with tempfile.TemporaryDirectory(prefix="tj-phase-s-") as tmp:
        tmp = Path(tmp)
        fixture = tmp / "fixture"
        subprocess.run(
            ["gcc", "-O2", "-o", str(fixture), str(ROOT / "tests/fixtures/fixture_driver.c")],
            check=True,
        )
        for size in SIZES:
            work = tmp / f"size-{size}"
            (work / "cache").mkdir(parents=True)
            (work / "input.txt").write_bytes(os.urandom(size))
            (work / "output.txt").unlink(missing_ok=True)
            phase_path = work / "phases.json"
            args_ = ["run", "--json", "--", str(fixture), "plain_file_read", str(work)]
            env = {
                "TRACEJIT_CACHE_DIR": str(work / "cache"),
                "TRACEJIT_PHASE_TIMING": "1",
                "TRACEJIT_PHASE_TIMING_PATH": str(phase_path),
            }
            cold, cold_ms = run_binary(binary, args_, work, env)
            if cold.returncode != 0:
                raise SystemExit(f"cold failed {size}: {cold.stderr.decode()}")
            cold_kind = json.loads(cold.stdout)["kind"]
            days = {phase: [] for phase in PHASES}
            walls = []
            kinds = []
            for _ in range(args.runs):
                proc, wall = run_binary(binary, args_, work, env)
                if proc.returncode != 0:
                    raise SystemExit(f"warm failed {size}: {proc.stderr.decode()}")
                kinds.append(json.loads(proc.stdout)["kind"])
                walls.append(wall)
                data = json.loads(phase_path.read_text())
                for phase in PHASES:
                    days[phase].append(data.get(phase, 0) / 1e6)
            # Direct floor: the same fixture, no TraceJIT.
            direct = []
            for _ in range(max(3, args.runs // 3)):
                proc, wall = run_binary(fixture, ["plain_file_read", str(work)], work)
                direct.append(wall)
            row = {
                "size_bytes": size,
                "cold_kind": cold_kind,
                "cold_ms": cold_ms,
                "warm_median_ms": statistics.median(walls),
                "warm_p95_ms": sorted(walls)[int(0.95 * len(walls)) - 1],
                "direct_median_ms": statistics.median(direct),
                "kinds": kinds,
                "phases_median_ms": {
                    phase: statistics.median(values) for phase, values in days.items()
                },
            }
            row["tracejit_overhead_ms"] = row["warm_median_ms"] - row["direct_median_ms"]
            results.append(row)
            print(
                f"{size/1024:>8.0f} KiB warm={row['warm_median_ms']:7.3f} "
                f"direct={row['direct_median_ms']:7.3f} "
                f"guard={row['phases_median_ms']['guard_validation_ns']:6.3f} "
                f"restore={row['phases_median_ms']['cas_restore_ns']:6.3f} "
                f"sqlite={row['phases_median_ms']['sqlite_open_ns']:6.3f} "
                f"lookup={row['phases_median_ms']['sqlite_query_ns']:6.3f} "
                f"persist={row['phases_median_ms']['decision_persist_ns']:6.3f} "
                f"present={row['phases_median_ms']['present_ns']:6.3f}"
            )
            if set(kinds) != {"Reused"}:
                print(f"  WARNING: unexpected kinds {set(kinds)}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"environment": environment(), "results": results}, indent=2))
    print(f"wrote {output}")


def environment():
    uname = os.uname()
    return {
        "kernel": uname.release,
        "machine": uname.machine,
        "nproc": os.cpu_count(),
        "filesystem": subprocess.run(
            ["stat", "-f", "-c", "%T", "."], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip(),
        "tracejit_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip(),
    }


if __name__ == "__main__":
    main()

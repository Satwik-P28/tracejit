#!/usr/bin/env python3
"""Measure cache-hit overhead and the runtime where guarded reuse wins."""

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PHASE_PATH = ROOT / "benchmarks" / "results" / "phase-sample.json"
TARGETS_NS = [
    1_000_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
    250_000_000,
    500_000_000,
    1_000_000_000,
    2_000_000_000,
    5_000_000_000,
]
PHASE_FIELDS = [
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
]


def checked(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout.decode(errors='replace')}\n"
            f"stderr:\n{completed.stderr.decode(errors='replace')}"
        )
    return completed


def timed(command: list[str], env: dict[str, str]) -> tuple[int, subprocess.CompletedProcess[bytes]]:
    started = time.perf_counter_ns()
    completed = checked(command, env)
    return time.perf_counter_ns() - started, completed


def percentile_95(values: list[int]) -> int:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def summarize(values: list[int]) -> dict[str, object]:
    return {
        "runs": len(values),
        "median_ns": int(statistics.median(values)),
        "p95_ns": percentile_95(values),
        "minimum_ns": min(values),
        "maximum_ns": max(values),
        "standard_deviation_ns": statistics.pstdev(values),
        "samples_ns": values,
    }


def text_command(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
    return (completed.stdout + completed.stderr).strip()


def environment() -> dict[str, object]:
    commands = {
        "uname -a": text_command(["uname", "-a"]),
        "lscpu": text_command(["lscpu"]),
        "free -h": text_command(["free", "-h"]),
        "df -T .": text_command(["df", "-T", "."]),
        "python3 --version": text_command(["python3", "--version"]),
        "rustc --version": text_command(["rustc", "--version"]),
        "git rev-parse HEAD": text_command(["git", "rev-parse", "HEAD"]),
    }
    return {
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu": next(
            (
                line.split(":", 1)[1].strip()
                for line in commands["lscpu"].splitlines()
                if line.startswith("Model name:")
            ),
            "unavailable",
        ),
        "ram": commands["free -h"],
        "filesystem": commands["df -T ."],
        "python": commands["python3 --version"],
        "rustc": commands["rustc --version"],
        "commands": commands,
    }


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    env["MALLOC_ARENA_MAX"] = "1"
    return env


def trace_env(env: dict[str, str], cache: str) -> dict[str, str]:
    return env | {
        "TRACEJIT_CACHE_DIR": cache,
        "TRACEJIT_PHASE_TIMING": "1",
        "TRACEJIT_PHASE_TIMING_PATH": str(PHASE_PATH),
    }


def run_json(tracejit: Path, command: list[str], env: dict[str, str]) -> dict[str, object]:
    completed = checked([str(tracejit), "run", "--json", "--", *command], env)
    return json.loads(completed.stdout)


def assert_text(completed: subprocess.CompletedProcess[bytes], hit: bool) -> None:
    diagnostic = completed.stderr.decode(errors="replace")
    if hit:
        if "cache          HIT" not in diagnostic:
            raise RuntimeError(f"cache-hit sample did not reuse:\n{diagnostic}")
    elif "classified     GUARDED" not in diagnostic or "cache          HIT" in diagnostic:
        raise RuntimeError(f"cold run was not a guarded miss:\n{diagnostic}")


def measure_guarded(
    tracejit: Path,
    command: list[str],
    env: dict[str, str],
    output: Path | None,
    warmups: int,
    runs: int,
) -> dict[str, object]:
    baseline_values = []
    for index in range(warmups + runs):
        elapsed, completed = timed(command, env)
        if output is not None and index == warmups:
            direct_output = output.read_bytes()
            direct_stdout = completed.stdout
            direct_stderr = completed.stderr
            direct_code = completed.returncode
        if index >= warmups:
            baseline_values.append(elapsed)
    baseline = summarize(baseline_values)

    cold_values = []
    for _ in range(warmups + runs):
        with tempfile.TemporaryDirectory(prefix="tracejit-cold-") as cache:
            elapsed, completed = timed(
                [str(tracejit), "run", "--", *command],
                trace_env(env, cache),
            )
            assert_text(completed, hit=False)
            cold_values.append(elapsed)
    cold_values = cold_values[warmups:]

    phase_samples: list[dict[str, int]] = []
    with tempfile.TemporaryDirectory(prefix="tracejit-hit-") as cache:
        hit_env = trace_env(env, cache)
        primed, primed_process = timed([str(tracejit), "run", "--", *command], hit_env)
        assert_text(primed_process, hit=False)
        del primed
        hit_values = []
        for index in range(warmups + runs):
            if PHASE_PATH.exists():
                PHASE_PATH.unlink()
            elapsed, completed = timed([str(tracejit), "run", "--", *command], hit_env)
            assert_text(completed, hit=True)
            if index >= warmups:
                hit_values.append(elapsed)
                if PHASE_PATH.is_file():
                    phase_samples.append(json.loads(PHASE_PATH.read_text()))
        equivalence = None
        if output is not None:
            restored = output.read_bytes()
            report = run_json(tracejit, command, hit_env)
            equivalence = {
                "passed": report.get("kind") == "Reused"
                and report.get("exit_code") == direct_code
                and bytes(report["stdout_bytes"]) == direct_stdout
                and bytes(report["stderr_bytes"]) == direct_stderr
                and restored == direct_output,
            }
            if not equivalence["passed"]:
                raise RuntimeError(f"observable outputs differ: {equivalence}")

    cached = summarize(hit_values)
    cold = summarize(cold_values)
    baseline_median = int(baseline["median_ns"])
    cached_median = int(cached["median_ns"])
    cold_median = int(cold["median_ns"])
    return {
        "command": command,
        "baseline": baseline,
        "traced_cold": cold,
        "cached": cached,
        "tracing_overhead_percent": (cold_median - baseline_median) / baseline_median * 100,
        "speedup": baseline_median / cached_median,
        "time_saved_ns": baseline_median - cached_median,
        "phase_medians_ns": phase_medians(phase_samples, cached_median),
        "equivalence": equivalence,
    }


def phase_medians(samples: list[dict[str, int]], wall_median: int) -> dict[str, object]:
    if not samples:
        return {"samples": 0}
    medians = {
        field: int(statistics.median(sample[field] for sample in samples if field in sample))
        for field in PHASE_FIELDS
    }
    accounted = sum(medians.values())
    return {
        "samples": len(samples),
        "phases_ns": medians,
        "accounted_ns": accounted,
        "unaccounted_including_exit_ns": wall_median - accounted,
        "sqlite_open_and_query_ns": medians["sqlite_open_ns"]
        + medians["sqlite_schema_ns"]
        + medians["sqlite_query_ns"],
        "candidate_lookup_ns": medians["lookup_key_ns"] + medians["record_decode_ns"],
    }


def classify(tracejit: Path, command: list[str], env: dict[str, str]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="tracejit-class-") as cache:
        report = run_json(tracejit, command, trace_env(env, cache))
    reasons = report.get("reasons")
    return {
        "command": command,
        "classification": report.get("classification"),
        "eligible_for_reuse": report.get("eligible_for_reuse"),
        "reasons": reasons if isinstance(reasons, list) else [],
    }


def compile_binary(source: Path, binary: Path) -> None:
    checked(["cc", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], os.environ.copy())


def calibrate(binary: Path, env: dict[str, str]) -> dict[str, object]:
    output = ROOT / "benchmarks" / "workloads" / "sweep" / "output" / "calibration.txt"
    command = [str(binary), "5000000", str(output)]
    samples = [timed(command, env)[0] for _ in range(5)]
    median = int(statistics.median(samples))
    return {
        "rounds": 5_000_000,
        "samples_ns": samples,
        "median_ns": median,
        "ns_per_round": median / 5_000_000,
    }


def rounds_for(ns_per_round: float, target_ns: int) -> int:
    if ns_per_round <= 0:
        raise RuntimeError("calibration produced a nonpositive per-round cost")
    return max(1, int(round(target_ns / ns_per_round)))


def markdown(result: dict[str, object]) -> str:
    lines = [
        "# TraceJIT break-even",
        "",
        f"Commit: `{result['commit']}`",
        "",
        "TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands. The earlier 7 ms C ETL result remains in `benchmarks/results/latest.md`.",
        "",
        "## Sweep",
        "",
        "| Target | Baseline median | Baseline p95 | Traced cold median | Traced cold p95 | Cache hit median | Cache hit p95 | Tracing overhead | Speedup | Time saved |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["sweep"]:
        lines.append(
            " | ".join(
                [
                    "",
                    f"{row['target_ns'] / 1_000_000:.0f} ms",
                    f"{row['baseline']['median_ns'] / 1_000_000:.3f} ms",
                    f"{row['baseline']['p95_ns'] / 1_000_000:.3f} ms",
                    f"{row['traced_cold']['median_ns'] / 1_000_000:.3f} ms",
                    f"{row['traced_cold']['p95_ns'] / 1_000_000:.3f} ms",
                    f"{row['cached']['median_ns'] / 1_000_000:.3f} ms",
                    f"{row['cached']['p95_ns'] / 1_000_000:.3f} ms",
                    f"{row['tracing_overhead_percent']:.2f}%",
                    f"{row['speedup']:.3f}x",
                    f"{row['time_saved_ns'] / 1_000_000:.3f} ms",
                    "",
                ]
            ).strip()
        )
    crossing = result["break_even"]
    lines.extend(
        [
            "",
            "## Break-even",
            "",
            crossing["statement"],
            "",
            "## Fixed overhead",
            "",
            "Phase medians are from cache-hit samples of the short C ETL. Unaccounted time includes process exit and any gap between timed regions. These medians are not summed into a smoothed curve.",
            "",
        ]
    )
    phases = result["short_c_etl"]["phase_medians_ns"]
    if "phases_ns" in phases:
        lines.extend(
            [
                "| Phase | Median |",
                "| --- | ---: |",
            ]
        )
        labels = {
            "process_startup_ns": "Process startup",
            "cli_parse_ns": "CLI parsing",
            "identity_prepare_ns": "Identity, executable hash, filesystem discovery",
            "cache_prepare_ns": "Cache directory initialization",
            "sqlite_open_ns": "SQLite open",
            "sqlite_schema_ns": "SQLite schema and pragmas",
            "lookup_key_ns": "Lookup-key hash",
            "sqlite_query_ns": "SQLite candidate query",
            "record_decode_ns": "Candidate JSON decode",
            "guard_validation_ns": "Guard validation",
            "cas_restore_ns": "CAS restore",
            "stdio_replay_ns": "Cached stdout/stderr load",
            "decision_persist_ns": "Decision persist",
            "present_ns": "Stdout/stderr replay to the terminal",
        }
        for field, label in labels.items():
            lines.append(f"| {label} | {phases['phases_ns'][field] / 1_000_000:.3f} ms |")
        lines.append(f"| Unaccounted, including process exit | {phases['unaccounted_including_exit_ns'] / 1_000_000:.3f} ms |")
    lines.extend(["", "## Real workloads", ""])
    for row in result["real_workloads"]:
        if "speedup" in row:
            lines.append(
                f"- `{row['name']}`: baseline {row['baseline']['median_ns'] / 1_000_000:.3f} ms, cache hit {row['cached']['median_ns'] / 1_000_000:.3f} ms, speedup {row['speedup']:.3f}x, saved {row['time_saved_ns'] / 1_000_000:.3f} ms."
            )
        else:
            reasons = "; ".join(row.get("reasons") or [])
            lines.append(
                f"- `{row['name']}`: classification `{row.get('classification')}`, reuse {'yes' if row.get('eligible_for_reuse') else 'no'}. {reasons}"
            )
    lines.extend(
        [
            "",
            "## Daemon",
            "",
            result["daemon"]["reason"],
            "",
            "## Python",
            "",
            f"Classification: `{result['python']['classification']}`.",
            "",
            "PYTHONHASHSEED=0 disables CPython hash-seed randomization. `gettid` still runs while the interpreter binds its main thread and is observable as the native thread id. A remaining `getrandom` is still randomness. Neither call was whitelisted.",
            "",
            "Reasons:",
            "",
        ]
    )
    for reason in result["python"]["reasons"]:
        lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            "## Negative short-command result",
            "",
            f"Short C ETL baseline median {result['short_c_etl']['baseline']['median_ns'] / 1_000_000:.3f} ms, cache hit {result['short_c_etl']['cached']['median_ns'] / 1_000_000:.3f} ms, speedup {result['short_c_etl']['speedup']:.3f}x.",
            "",
            "The previously published result in `benchmarks/results/latest.md` is unchanged.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def break_even_statement(rows: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(rows, key=lambda row: int(row["baseline"]["median_ns"]))
    winners = [row for row in ordered if int(row["time_saved_ns"]) > 0]
    losers = [row for row in ordered if int(row["time_saved_ns"]) <= 0]
    if not winners:
        statement = "No measured sweep point had a cache-hit median faster than its direct baseline."
    elif not losers:
        statement = "Every measured sweep point had a cache-hit median faster than its direct baseline."
    else:
        slowest_loss = max(int(row["baseline"]["median_ns"]) for row in losers)
        fastest_win = min(int(row["baseline"]["median_ns"]) for row in winners)
        statement = (
            f"The slowest measured loss had direct baseline median {slowest_loss / 1_000_000:.3f} ms. "
            f"The fastest measured win had direct baseline median {fastest_win / 1_000_000:.3f} ms. "
            "No curve was fit between those points."
        )
    return {
        "statement": statement,
        "winning_baseline_medians_ns": [int(row["baseline"]["median_ns"]) for row in winners],
        "losing_baseline_medians_ns": [int(row["baseline"]["median_ns"]) for row in losers],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--tracejit", default=str(ROOT / "target" / "release" / "tracejit"))
    parser.add_argument("--output-dir", default=str(ROOT / "benchmarks" / "results"))
    args = parser.parse_args()
    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    env = base_env()
    sweep_binary = ROOT / "benchmarks" / "workloads" / "sweep" / "sweep"
    transform_binary = ROOT / "benchmarks" / "workloads" / "c-transform" / "transform"
    etl_binary = ROOT / "benchmarks" / "workloads" / "c-etl" / "etl"
    compile_binary(ROOT / "benchmarks" / "workloads" / "sweep" / "main.c", sweep_binary)
    compile_binary(ROOT / "benchmarks" / "workloads" / "c-transform" / "main.c", transform_binary)
    compile_binary(ROOT / "benchmarks" / "workloads" / "c-etl" / "main.c", etl_binary)
    calibration = calibrate(sweep_binary, env)
    sweep = []
    for target in TARGETS_NS:
        rounds = rounds_for(float(calibration["ns_per_round"]), target)
        output = ROOT / "benchmarks" / "workloads" / "sweep" / "output" / f"{target}.txt"
        row = measure_guarded(
            tracejit,
            [str(sweep_binary), str(rounds), str(output)],
            env,
            output,
            args.warmups,
            args.runs,
        )
        row["target_ns"] = target
        row["rounds"] = rounds
        sweep.append(row)
    short = measure_guarded(
        tracejit,
        [str(etl_binary)],
        env,
        ROOT / "benchmarks" / "workloads" / "c-etl" / "output" / "report.json",
        args.warmups,
        args.runs,
    )
    short["name"] = "short-c-etl"
    real = []
    transform = measure_guarded(
        tracejit,
        [str(transform_binary)],
        env,
        ROOT / "benchmarks" / "workloads" / "c-transform" / "output" / "report.txt",
        args.warmups,
        args.runs,
    )
    transform["name"] = "c-transform"
    real.append(transform)
    for name, command, output in [
        (
            "shell-pipeline",
            ["sh", "benchmarks/workloads/shell-pipeline/run.sh"],
            None,
        ),
        (
            "build-sample",
            [
                "cc",
                "-O2",
                "-c",
                "benchmarks/workloads/build-sample/sample.c",
                "-o",
                "benchmarks/workloads/build-sample/sample.o",
            ],
            ROOT / "benchmarks" / "workloads" / "build-sample" / "sample.o",
        ),
    ]:
        probed = classify(tracejit, command, env)
        probed["name"] = name
        if probed["eligible_for_reuse"] is True and probed["classification"] == "Guarded":
            measured = measure_guarded(tracejit, command, env, output, args.warmups, args.runs)
            measured["name"] = name
            real.append(measured)
        else:
            real.append(probed)
    python = classify(tracejit, ["python3", "benchmarks/workloads/python-etl/main.py"], env)
    result = {
        "commit": text_command(["git", "rev-parse", "HEAD"]),
        "environment": environment(),
        "calibration": calibration,
        "daemon": {
            "implemented": False,
            "reason": "A persistent daemon was not added. The cache-hit phase profile is the input to that decision.",
        },
        "short_c_etl": short,
        "sweep": sweep,
        "break_even": break_even_statement(sweep),
        "real_workloads": real,
        "python": python,
        "kept_negative_result": "benchmarks/results/latest.md",
    }
    (output_dir / "break-even.json").write_text(json.dumps(result, indent=2) + "\n")
    (output_dir / "break-even.md").write_text(markdown(result))
    print(result["break_even"]["statement"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Benchmark TraceJIT on the committed deterministic Python ETL workload."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
WORKLOAD_DIR = ROOT / "benchmarks" / "workloads" / "python-etl"
WORKLOAD = WORKLOAD_DIR / "main.py"
INPUT = WORKLOAD_DIR / "inputs" / "sales.csv"
OUTPUT = WORKLOAD_DIR / "output" / "report.json"
COMMAND = ["python3", "benchmarks/workloads/python-etl/main.py"]


def run_command(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, check=False)


def checked(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    completed = run_command(command, env)
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


def measure(probe: Callable[[], int], warmups: int, runs: int) -> dict[str, object]:
    for _ in range(warmups):
        probe()
    return summarize([probe() for _ in range(runs)])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workload_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(WORKLOAD_DIR.glob("**/*")):
        if path.is_file() and "output" not in path.parts:
            digest.update(path.relative_to(WORKLOAD_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def text_command(command: list[str]) -> str:
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=True
    )
    return (completed.stdout + completed.stderr).strip()


def environment() -> dict[str, object]:
    commands = {
        "uname -a": text_command(["uname", "-a"]),
        "uname -m": text_command(["uname", "-m"]),
        "cat /etc/os-release": text_command(["cat", "/etc/os-release"]),
        "lscpu": text_command(["lscpu"]),
        "free -h": text_command(["free", "-h"]),
        "df -T .": text_command(["df", "-T", "."]),
        "python3 --version": text_command(["python3", "--version"]),
        "rustc --version": text_command(["rustc", "--version"]),
        "cargo --version": text_command(["cargo", "--version"]),
        "git rev-parse HEAD": text_command(["git", "rev-parse", "HEAD"]),
    }
    return {
        "commands": commands,
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
        "cargo": commands["cargo --version"],
    }


def trace_command(tracejit: Path, json_output: bool = False) -> list[str]:
    command = [str(tracejit), "run"]
    if json_output:
        command.append("--json")
    return command + ["--", *COMMAND]


def report_json(completed: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"TraceJIT did not emit valid JSON: {error}\n"
            f"stdout:\n{completed.stdout.decode(errors='replace')}\n"
            f"stderr:\n{completed.stderr.decode(errors='replace')}"
        ) from error


def assert_cold(completed: subprocess.CompletedProcess[bytes]) -> None:
    diagnostic = completed.stderr.decode(errors="replace")
    if "cache          HIT" in diagnostic or "classified     GUARDED" not in diagnostic:
        raise RuntimeError(f"cold run was not a guarded cache miss:\n{diagnostic}")


def assert_hit(completed: subprocess.CompletedProcess[bytes]) -> None:
    diagnostic = completed.stderr.decode(errors="replace")
    if "cache          HIT" not in diagnostic:
        raise RuntimeError(f"cache-hit sample did not reuse:\n{diagnostic}")


def bytes_from_report(report: dict[str, object], key: str) -> bytes:
    value = report.get(key)
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise RuntimeError(f"missing byte array {key} in TraceJIT report")
    return bytes(value)


def explain(tracejit: Path, env: dict[str, str]) -> str:
    return checked([str(tracejit), "explain"], env).stdout.decode()


def format_ms(value_ns: float) -> str:
    return f"{value_ns / 1_000_000:.6f} ms"


def markdown(result: dict[str, object]) -> str:
    baseline = result["baseline"]
    cold = result["traced_cold"]
    guard = result["guard_check"]
    cached = result["cached"]
    commands = result["environment"]["commands"]
    lines = [
        "# TraceJIT benchmark result",
        "",
        f"Measured commit: `{result['commit']}`",
        "",
        "## Methodology",
        "",
        f"The committed Python ETL workload was measured with {result['runs']['warmups']} warmups and {result['runs']['measured']} recorded runs per stable condition. Baseline runs execute Python directly. Every traced-cold sample uses a fresh TraceJIT cache. Cached samples use an unchanged guarded entry and must report a cache hit. All timings are wall-clock process times except guard-check timings, which are TraceJIT's internal guard validation, output restoration, and cached-stream loading duration.",
        "",
        "The workload ran with `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`, and `MALLOC_ARENA_MAX=1`. It does not import hashlib. CPU frequency, neighboring runner activity, and warm operating-system filesystem caches were not controlled.",
        "",
        "## Commands",
        "",
        "```text",
        "cargo build --workspace --release",
        "cargo fmt --all -- --check",
        "cargo clippy --workspace --all-targets --all-features -- -D warnings",
        "cargo test --workspace",
        "python3 benchmarks/harness/benchmark.py --runs 30 --warmups 5",
        "```",
        "",
        "## Results",
        "",
        "| Condition | Median | p95 | Minimum | Maximum | Standard deviation | Runs |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, stats in [
        ("Baseline", baseline),
        ("Traced cold", cold),
        ("Guard check", guard),
        ("Cached end-to-end", cached),
    ]:
        lines.append(
            f"| {label} | {format_ms(stats['median_ns'])} | {format_ms(stats['p95_ns'])} | {format_ms(stats['minimum_ns'])} | {format_ms(stats['maximum_ns'])} | {format_ms(stats['standard_deviation_ns'])} | {stats['runs']} |"
        )
    lines.extend(
        [
            "",
            f"Tracing overhead: `{result['tracing_overhead_percent']:.6f}%`",
            "",
            f"Cache-hit speedup: `{result['speedup']:.6f}x`",
            "",
            f"Median time saved: `{format_ms(result['time_saved_ns'])}`",
            "",
            "## Correctness",
            "",
            f"Output equivalence: `{'PASS' if result['output_equivalent'] else 'FAIL'}`",
            "",
            f"Mutation/deopt: `{'PASS' if result['deopt']['passed'] else 'FAIL'}`",
            "",
            f"Changed dependency: `{result['deopt']['changed_dependency']}`",
            "",
            f"Explanation identified dependency: `{'yes' if result['deopt']['explanation_correct'] else 'no'}`",
            "",
            "The equivalence check compares workload exit status, captured stdout, captured stderr, output bytes, and output SHA-256 across baseline, traced, and cache-hit execution.",
            "",
            "## Environment",
            "",
        ]
    )
    for command, output in commands.items():
        lines.extend([f"### `{command}`", "", "```text", output, "```", ""])
    lines.extend(
        [
            "## Limitations",
            "",
            "These measurements cover one small deterministic Python ETL workload on one ephemeral GitHub-hosted runner. They are not evidence of universal speedups, production readiness, or performance on other workloads or machines.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--tracejit", default=str(ROOT / "target" / "release" / "tracejit"))
    parser.add_argument("--output-dir", default=str(ROOT / "benchmarks" / "results"))
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")
    if args.warmups < 0:
        parser.error("--warmups must be nonnegative")
    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    # These are workload settings, not classifier exceptions. They stop CPython and glibc
    # from drawing entropy or querying CPU count during startup. OpenSSL is avoided by
    # keeping hashlib out of the workload.
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    env["MALLOC_ARENA_MAX"] = "1"
    input_original = INPUT.read_bytes()
    output_original = OUTPUT.read_bytes() if OUTPUT.exists() else None

    try:
        baseline = measure(lambda: timed(COMMAND, env)[0], args.warmups, args.runs)

        def cold_probe() -> int:
            with tempfile.TemporaryDirectory(prefix="tracejit-cold-") as cache:
                cold_env = env | {"TRACEJIT_CACHE_DIR": cache}
                elapsed, completed = timed(trace_command(tracejit), cold_env)
                try:
                    assert_cold(completed)
                except RuntimeError as error:
                    diagnostic = checked(
                        [str(tracejit), "analyze", "--verbose", "--", *COMMAND],
                        cold_env,
                    )
                    raise RuntimeError(
                        f"{error}\nclassification diagnostic:\n"
                        f"{diagnostic.stdout.decode(errors='replace')}\n"
                        f"{diagnostic.stderr.decode(errors='replace')}"
                    ) from error
                return elapsed

        traced_cold = measure(cold_probe, args.warmups, args.runs)

        with tempfile.TemporaryDirectory(prefix="tracejit-cached-") as cache:
            cached_env = env | {"TRACEJIT_CACHE_DIR": cache}
            primed = checked(trace_command(tracejit), cached_env)
            assert_cold(primed)

            def cached_probe() -> int:
                elapsed, completed = timed(trace_command(tracejit), cached_env)
                assert_hit(completed)
                return elapsed

            cached = measure(cached_probe, args.warmups, args.runs)

            def guard_probe() -> int:
                completed = checked(trace_command(tracejit, json_output=True), cached_env)
                report = report_json(completed)
                if report.get("kind") != "Reused":
                    raise RuntimeError(f"guard sample did not reuse: {report}")
                runtime = report.get("runtime_ns")
                if not isinstance(runtime, int):
                    raise RuntimeError("guard sample has no integer runtime_ns")
                return runtime

            guard_check = measure(guard_probe, args.warmups, args.runs)

        baseline_probe = checked(COMMAND, env)
        baseline_output = OUTPUT.read_bytes()
        baseline_observation = {
            "exit_status": baseline_probe.returncode,
            "stdout_sha256": hashlib.sha256(baseline_probe.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(baseline_probe.stderr).hexdigest(),
            "output_sha256": hashlib.sha256(baseline_output).hexdigest(),
        }

        with tempfile.TemporaryDirectory(prefix="tracejit-equivalence-") as cache:
            equivalent_env = env | {"TRACEJIT_CACHE_DIR": cache}
            cold_report_process = checked(trace_command(tracejit, json_output=True), equivalent_env)
            cold_report = report_json(cold_report_process)
            cold_output = OUTPUT.read_bytes()
            OUTPUT.unlink()
            hit_report_process = checked(trace_command(tracejit, json_output=True), equivalent_env)
            hit_report = report_json(hit_report_process)
            hit_output = OUTPUT.read_bytes()
            if hit_report.get("kind") != "Reused":
                raise RuntimeError(f"equivalence cache run did not reuse: {hit_report}")
            observations_equal = (
                cold_report.get("exit_code") == baseline_probe.returncode
                and hit_report.get("exit_code") == baseline_probe.returncode
                and bytes_from_report(cold_report, "stdout_bytes") == baseline_probe.stdout
                and bytes_from_report(hit_report, "stdout_bytes") == baseline_probe.stdout
                and bytes_from_report(cold_report, "stderr_bytes") == baseline_probe.stderr
                and bytes_from_report(hit_report, "stderr_bytes") == baseline_probe.stderr
                and cold_output == baseline_output
                and hit_output == baseline_output
            )
            equivalence = {
                "passed": observations_equal,
                "baseline": baseline_observation,
                "traced": {
                    "exit_status": cold_report.get("exit_code"),
                    "stdout_sha256": hashlib.sha256(bytes_from_report(cold_report, "stdout_bytes")).hexdigest(),
                    "stderr_sha256": hashlib.sha256(bytes_from_report(cold_report, "stderr_bytes")).hexdigest(),
                    "output_sha256": hashlib.sha256(cold_output).hexdigest(),
                },
                "cached": {
                    "exit_status": hit_report.get("exit_code"),
                    "stdout_sha256": hashlib.sha256(bytes_from_report(hit_report, "stdout_bytes")).hexdigest(),
                    "stderr_sha256": hashlib.sha256(bytes_from_report(hit_report, "stderr_bytes")).hexdigest(),
                    "output_sha256": hashlib.sha256(hit_output).hexdigest(),
                },
            }
            if not observations_equal:
                raise RuntimeError(f"observable outputs differ: {equivalence}")

        with tempfile.TemporaryDirectory(prefix="tracejit-deopt-") as cache:
            deopt_env = env | {"TRACEJIT_CACHE_DIR": cache}
            checked(trace_command(tracejit), deopt_env)
            hit = checked(trace_command(tracejit), deopt_env)
            assert_hit(hit)
            hit_explanation = explain(tracejit, deopt_env)
            (output_dir / "explain-cache-hit.txt").write_text(hit_explanation, encoding="utf-8")
            original_hash = sha256(OUTPUT)
            INPUT.write_bytes(input_original + b"s999,c001,1\n")
            elapsed, deoptimized_process = timed(trace_command(tracejit, json_output=True), deopt_env)
            deoptimized = report_json(deoptimized_process)
            deopt_explanation = explain(tracejit, deopt_env)
            (output_dir / "explain-deopt.txt").write_text(deopt_explanation, encoding="utf-8")
            changed_hash = sha256(OUTPUT)
            explanation_correct = "sales.csv" in deopt_explanation and "deopt" in deopt_explanation
            deopt_passed = (
                deoptimized.get("kind") == "Executed"
                and deoptimized.get("cache_decision") == "Deoptimized"
                and original_hash != changed_hash
                and explanation_correct
            )
            deopt = {
                "passed": deopt_passed,
                "runtime_ns": elapsed,
                "changed_dependency": "benchmarks/workloads/python-etl/inputs/sales.csv",
                "cache_decision": deoptimized.get("cache_decision"),
                "execution_kind": deoptimized.get("kind"),
                "original_output_sha256": original_hash,
                "mutated_output_sha256": changed_hash,
                "explanation_correct": explanation_correct,
            }
            if not deopt_passed:
                raise RuntimeError(f"mutation/deopt verification failed: {deopt}")

        commit = text_command(["git", "rev-parse", "HEAD"])
        tracing_overhead = (
            (traced_cold["median_ns"] - baseline["median_ns"])
            / baseline["median_ns"]
            * 100
        )
        speedup = baseline["median_ns"] / cached["median_ns"]
        result = {
            "commit": commit,
            "environment": environment(),
            "workload": "benchmarks/workloads/python-etl",
            "workload_sha256": workload_hash(),
            "command": COMMAND,
            "methodology": "warm OS caches; fresh TraceJIT cache per cold sample; isolated stable cache for hits",
            "baseline": baseline,
            "traced_cold": traced_cold,
            "guard_check": guard_check,
            "cached": cached,
            "deopt": deopt,
            "tracing_overhead_percent": tracing_overhead,
            "speedup": speedup,
            "time_saved_ns": baseline["median_ns"] - cached["median_ns"],
            "output_equivalent": True,
            "output_equivalence": equivalence,
            "runs": {"warmups": args.warmups, "measured": args.runs},
        }
        (output_dir / "latest.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "latest.md").write_text(markdown(result), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        INPUT.write_bytes(input_original)
        if output_original is None:
            OUTPUT.unlink(missing_ok=True)
        else:
            OUTPUT.write_bytes(output_original)


if __name__ == "__main__":
    main()

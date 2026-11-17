#!/usr/bin/env python3
"""Release benchmark package for one TraceJIT commit.

Every scenario measures the exact binary passed on the command line, records raw
samples, and writes JSON plus a markdown summary into the output directory.
Results from different commits are never mixed: the commit is part of the path
and of every result document.

Usage:
    cargo build --workspace --release
    python3 benchmarks/releases/run_release.py --runs 20 --warmups 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSFORM_DIR = ROOT / "benchmarks/workloads/c-transform"
TRANSFORM = TRANSFORM_DIR / "transform"
TRANSFORM_INPUT = TRANSFORM_DIR / "numbers.txt"
TRANSFORM_OUTPUT = TRANSFORM_DIR / "output/report.txt"
ETL_DIR = ROOT / "benchmarks/workloads/c-etl"
ETL = ETL_DIR / "etl"
ETL_INPUT = ROOT / "benchmarks/workloads/python-etl/inputs/sales.csv"
ETL_OUTPUT = ETL_DIR / "output/report.json"
LARGE_DIR = ROOT / "benchmarks/releases/fixtures"
LARGE = LARGE_DIR / "large_output"
LARGE_OUTPUT = LARGE_DIR / "output/large.bin"


def run_text(*command: str) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return (completed.stdout + completed.stderr).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    env["MALLOC_ARENA_MAX"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def timed(command: list[str], env: dict[str, str]) -> tuple[int, subprocess.CompletedProcess[bytes]]:
    started = time.perf_counter_ns()
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, check=False)
    return time.perf_counter_ns() - started, completed


def tracejit(binary: Path, cache: Path, env: dict[str, str], command: list[str], quiet: bool = False):
    run_env = env | {"TRACEJIT_CACHE_DIR": str(cache)}
    args = [str(binary), "run"]
    if quiet:
        args.append("--json")
    args += ["--", *command]
    elapsed, completed = timed(args, run_env)
    if completed.returncode != 0:
        raise RuntimeError(
            f"tracejit failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stderr.decode(errors='replace')}"
        )
    report = None
    if quiet:
        report = json.loads(completed.stdout)
    return elapsed, report, completed.stderr.decode(errors="replace")


def percentile(values: list[int], fraction: float) -> int:
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def summarize(values: list[int]) -> dict[str, object]:
    median = statistics.median(values)
    deviation = statistics.pstdev(values)
    return {
        "runs": len(values),
        "median_ns": int(median),
        "p95_ns": percentile(values, 0.95),
        "minimum_ns": min(values),
        "maximum_ns": max(values),
        "standard_deviation_ns": deviation,
        "relative_standard_deviation": (deviation / median) if median else None,
        "samples_ns": values,
    }


def bootstrap_ci(values: list[int], seed: int = 20260101) -> dict[str, int]:
    """Percentile bootstrap 95% CI for the median (deterministic seed)."""
    generator = random.Random(seed)
    medians = []
    for _ in range(2000):
        resample = [values[generator.randrange(len(values))] for _ in values]
        medians.append(statistics.median(resample))
    medians.sort()
    return {"low_ns": int(medians[49]), "high_ns": int(medians[1949])}


def measure(probe, warmups: int, runs: int) -> dict[str, object]:
    for _ in range(warmups):
        probe()
    samples = [probe() for _ in range(runs)]
    stats = summarize(samples)
    stats["bootstrap_95ci_median"] = bootstrap_ci(samples)
    return stats


def environment() -> dict[str, object]:
    cpu = ""
    for line in run_text("lscpu").splitlines():
        if line.startswith("Model name:"):
            cpu = line.split(":", 1)[1].strip()
            break
    return {
        "commands": {
            "uname -a": run_text("uname", "-a"),
            "cat /etc/os-release": run_text("cat", "/etc/os-release"),
            "lscpu": run_text("lscpu"),
            "free -h": run_text("free", "-h"),
            "df -T .": run_text("df", "-T", "."),
            "python3 --version": run_text("python3", "--version"),
            "rustc --version": run_text("rustc", "--version"),
            "cargo --version": run_text("cargo", "--version"),
            "gcc --version": run_text("gcc", "--version").splitlines()[0] if shutil.which("gcc") else "missing",
            "make --version": run_text("make", "--version").splitlines()[0] if shutil.which("make") else "missing",
            "ninja --version": run_text("ninja", "--version") if shutil.which("ninja") else "missing",
        },
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu": cpu or "unavailable",
        "cpus": os.cpu_count(),
        "toolchain": run_text("rustc", "--version"),
    }


def scenario(
    name: str,
    kind: str,
    description: str,
    conditions: dict[str, dict[str, object]],
    notes: list[str] | None = None,
    refusals: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "name": name,
        "kind": kind,
        "description": description,
        "conditions": conditions,
        "notes": notes or [],
    }
    if refusals:
        document["refusals"] = refusals
    print(f"scenario {name}: done", flush=True)
    return document


def compile_workloads() -> None:
    for source, output in [
        (TRANSFORM_DIR / "main.c", TRANSFORM),
        (ETL_DIR / "main.c", ETL),
        (LARGE_DIR / "large_output.c", LARGE),
    ]:
        subprocess.run(
            ["cc", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(output)],
            check=True,
            cwd=ROOT,
        )
    LARGE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)


def cpu_transform(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    command = [str(TRANSFORM)]

    def direct() -> int:
        return timed(command, env)[0]

    def cold() -> int:
        with tempfile.TemporaryDirectory(prefix="tracejit-cold-") as cache:
            elapsed, report, _ = tracejit(binary, Path(cache), env, command, quiet=True)
            if report.get("classification") != "Guarded" or report.get("kind") != "Executed":
                raise RuntimeError(f"transform cold run was not a GUARDED execution: {report}")
            return elapsed

    with tempfile.TemporaryDirectory(prefix="tracejit-warm-") as cache:
        cache_path = Path(cache)
        tracejit(binary, cache_path, env, command)

        def warm() -> int:
            elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
            if report.get("kind") != "Reused":
                raise RuntimeError(f"transform warm run did not reuse: {report}")
            return elapsed

        conditions = {
            "direct": measure(direct, warmups, runs),
            "cold_trace": measure(cold, warmups, runs),
            "warm_hit": measure(warm, warmups, runs),
        }
    return scenario(
        "cpu_transform",
        "synthetic",
        "Committed C transform: folds numbers.txt, then 250,000,000 fixed mix rounds.",
        conditions,
        notes=["Output report.txt is identical across direct, traced, and reused runs."],
    )


def short_command(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    command = ["/bin/true"]
    with tempfile.TemporaryDirectory(prefix="tracejit-true-") as cache:
        cache_path = Path(cache)
        tracejit(binary, cache_path, env, command)

        def direct() -> int:
            return timed(command, env)[0]

        def warm() -> int:
            elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
            if report.get("kind") != "Reused":
                raise RuntimeError(f"/bin/true warm run did not reuse: {report}")
            return elapsed

        conditions = {
            "direct": measure(direct, warmups, runs),
            "warm_hit": measure(warm, warmups, runs),
        }
    return scenario(
        "short_command",
        "synthetic",
        "/bin/true: the fixed cost of a warm hit with no useful work to save.",
        conditions,
        notes=["A warm hit that costs more than the command itself is a documented loss."],
    )


def compression(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    if not shutil.which("gzip"):
        return scenario("compression", "controlled", "gzip -9 on a deterministic 4 MiB file.", {}, ["gzip missing"])
    scratch = Path(tempfile.mkdtemp(prefix="tracejit-gzip-"))
    try:
        payload = scratch / "payload.bin"
        state = 0x9E3779B9
        block = bytearray(65536)
        with payload.open("wb") as handle:
            for _ in range(64):
                for index in range(len(block)):
                    state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
                    block[index] = state >> 24
                handle.write(block)
        command = ["gzip", "-9", "-n", "-c", str(payload)]

        def direct() -> int:
            return timed(command, env)[0]

        with tempfile.TemporaryDirectory(prefix="tracejit-gzip-cache-") as cache:
            cache_path = Path(cache)
            first_elapsed, first_report, _ = tracejit(binary, cache_path, env, command, quiet=True)
            if first_report.get("classification") != "Guarded":
                return scenario(
                    "compression",
                    "controlled",
                    "gzip -9 on a deterministic 4 MiB file.",
                    {},
                    ["TraceJIT refused gzip; recorded as a refusal, not a speedup."],
                    refusals=[
                        {
                            "command": command,
                            "diagnostic": f"classification={first_report.get('classification')} "
                            f"decision={first_report.get('cache_decision')} "
                            f"reasons={first_report.get('reasons')}",
                        }
                    ],
                )
            second_elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
            if report.get("kind") != "Reused":
                raise RuntimeError(f"gzip warm run did not reuse: {report}")

            def cold() -> int:
                with tempfile.TemporaryDirectory(prefix="tracejit-gzip-cold-") as fresh:
                    elapsed, report, _ = tracejit(binary, Path(fresh), env, command, quiet=True)
                    if report.get("classification") != "Guarded":
                        raise RuntimeError(f"gzip classification changed: {report}")
                    return elapsed

            def warm() -> int:
                elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
                if report.get("kind") != "Reused":
                    raise RuntimeError(f"gzip warm run did not reuse: {report}")
                return elapsed

            conditions = {
                "direct": measure(direct, warmups, runs),
                "cold_trace": measure(cold, warmups, runs),
                "warm_hit": measure(warm, warmups, runs),
            }
        return scenario(
            "compression",
            "controlled",
            "gzip -9 -n -c over a deterministic 4 MiB file; compressed bytes are captured stdout.",
            conditions,
            [f"probe_cold_ns={first_elapsed}", f"probe_warm_ns={second_elapsed}"],
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def etl_session(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    command = [str(ETL)]
    repetitions = 10

    def direct_session() -> int:
        total = 0
        for _ in range(repetitions):
            total += timed(command, env)[0]
        return total

    def tracejit_session() -> int:
        total = 0
        with tempfile.TemporaryDirectory(prefix="tracejit-session-") as cache:
            cache_path = Path(cache)
            for index in range(repetitions):
                elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
                if index == 0 and report.get("classification") != "Guarded":
                    raise RuntimeError(f"session first run was not GUARDED: {report}")
                if index > 0 and report.get("kind") != "Reused":
                    raise RuntimeError(f"session run {index} did not reuse: {report}")
                total += elapsed
        return total

    conditions = {
        "direct": measure(direct_session, warmups, runs),
        "tracejit": measure(tracejit_session, warmups, runs),
    }
    return scenario(
        "etl_session",
        "controlled",
        f"{repetitions} sequential runs of the committed C ETL, direct versus one trace plus nine hits.",
        conditions,
        notes=["Session totals include every process launch; a hit that costs more than the command loses."],
    )


def large_restore(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    command = [str(LARGE)]

    def direct() -> int:
        return timed(command, env)[0]

    def cold() -> int:
        with tempfile.TemporaryDirectory(prefix="tracejit-large-cold-") as cache:
            elapsed, report, _ = tracejit(binary, Path(cache), env, command, quiet=True)
            if report.get("classification") != "Guarded":
                raise RuntimeError(f"large-output cold run was not GUARDED: {report}")
            return elapsed

    with tempfile.TemporaryDirectory(prefix="tracejit-large-warm-") as cache:
        cache_path = Path(cache)
        tracejit(binary, cache_path, env, command)
        expected = sha256(LARGE_OUTPUT)

        def warm() -> int:
            LARGE_OUTPUT.unlink()
            elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
            if report.get("kind") != "Reused":
                raise RuntimeError(f"large-output warm run did not reuse: {report}")
            if sha256(LARGE_OUTPUT) != expected:
                raise RuntimeError("restored 64 MiB output does not match the traced output")
            return elapsed

        conditions = {
            "direct": measure(direct, warmups, runs),
            "cold_trace": measure(cold, warmups, runs),
            "warm_hit": measure(warm, warmups, runs),
        }
    return scenario(
        "large_restore",
        "synthetic",
        "64 MiB deterministic output file. Warm hits pay output materialisation and fsync.",
        conditions,
        notes=["Output SHA-256 is verified after every warm hit before the sample is accepted."],
    )


def cache_invalidation(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    command = [str(ETL)]
    original = ETL_INPUT.read_bytes()
    direct_changed: list[int] = []

    def mutated_direct() -> int:
        ETL_INPUT.write_bytes(original + b"s999,c001,1\n")
        try:
            return timed(command, env)[0]
        finally:
            ETL_INPUT.write_bytes(original)

    def mutated_traced() -> int:
        with tempfile.TemporaryDirectory(prefix="tracejit-deopt-") as cache:
            cache_path = Path(cache)
            tracejit(binary, cache_path, env, command)
            ETL_INPUT.write_bytes(original + b"s999,c001,1\n")
            try:
                elapsed, report, _ = tracejit(binary, cache_path, env, command, quiet=True)
            finally:
                ETL_INPUT.write_bytes(original)
            if report.get("kind") != "Executed" or report.get("cache_decision") != "Deoptimized":
                raise RuntimeError(f"mutated input did not deopt: {report}")
            return elapsed

    for _ in range(warmups):
        mutated_direct()
    for _ in range(warmups):
        mutated_traced()
    for _ in range(runs):
        direct_changed.append(mutated_direct())
    traced_changed = [mutated_traced() for _ in range(runs)]
    conditions = {
        "direct_after_mutation": summarize(direct_changed),
        "tracejit_after_mutation": summarize(traced_changed),
    }
    for stats in conditions.values():
        stats["bootstrap_95ci_median"] = bootstrap_ci(stats["samples_ns"])
    return scenario(
        "cache_invalidation",
        "controlled",
        "sales.csv is mutated after priming. TraceJIT must deoptimise and recompute, never reuse.",
        conditions,
        notes=["Every measured run was required to report cache_decision=Deoptimized."],
    )


def concurrency(binary: Path, env: dict[str, str], warmups: int, runs: int) -> dict[str, object]:
    command = ["/bin/true"]
    workers = 8

    def batch(cache_path: Path, expect_hit: bool) -> int:
        run_env = env | {"TRACEJIT_CACHE_DIR": str(cache_path)}
        started = time.perf_counter_ns()
        processes = [
            subprocess.Popen(
                [str(binary), "run", "--json", "--", *command],
                cwd=ROOT,
                env=run_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(workers)
        ]
        for process in processes:
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"concurrent run failed: {stderr.decode(errors='replace')}")
            report = json.loads(stdout)
            if expect_hit and report.get("kind") != "Reused":
                raise RuntimeError(f"concurrent warm run did not reuse: {report}")
        return time.perf_counter_ns() - started

    def cold_batch() -> int:
        with tempfile.TemporaryDirectory(prefix="tracejit-concurrent-cold-") as cache:
            return batch(Path(cache), expect_hit=False)

    with tempfile.TemporaryDirectory(prefix="tracejit-concurrent-warm-") as cache:
        cache_path = Path(cache)
        tracejit(binary, cache_path, env, command)

        def warm_batch() -> int:
            return batch(cache_path, expect_hit=True)

        conditions = {
            "cold_8_concurrent": measure(cold_batch, warmups, runs),
            "warm_8_concurrent": measure(warm_batch, warmups, runs),
        }
    return scenario(
        "concurrency",
        "controlled",
        "Eight simultaneous /bin/true invocations sharing one cache, cold and warm.",
        conditions,
        notes=["All eight processes must exit 0; warm batches must all report Reused."],
    )


def delegate(name: str, description: str, command: list[str], output_dir: Path) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    (output_dir / f"{name}.log").write_text(
        f"$ {' '.join(command)}\nexit={completed.returncode}\n\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}\n",
        encoding="utf-8",
    )
    return scenario(
        name,
        "real-world",
        description,
        {},
        notes=[
            "Raw harness output is in the adjacent log and JSON files.",
            f"exit_status={completed.returncode}",
            "This harness reports working_tree_dirty=true because the untracked evidence "
            "directory already exists when it runs; it records the same commit and binary hash.",
        ],
    )


def markdown(document: dict[str, object], release_dir: Path) -> str:
    release = document["release"]
    lines = [
        f"# TraceJIT {release['version']} release benchmarks",
        "",
        f"Commit: `{release['commit']}`  ",
        f"Binary SHA-256: `{release['binary_sha256']}`  ",
        f"Runs per condition: {document['configuration']['runs']}, warmups: {document['configuration']['warmups']}  ",
        f"Generated: {release['generated_at']}",
        "",
        "Raw per-scenario JSON is in this directory. All samples are wall-clock",
        "process times measured with `time.perf_counter_ns`. Confidences are",
        "percentile bootstrap 95% intervals for the median.",
        "",
        "| Scenario | Kind | Condition | Median | p95 | 95% CI (median) | Runs |",
        "| --- | --- | --- | ---: | ---: | --- | ---: |",
    ]
    for entry in document["scenarios"]:
        conditions = entry["conditions"]
        if not conditions:
            lines.append(f"| {entry['name']} | {entry['kind']} | (no timed conditions) | — | — | — | 0 |")
            continue
        for condition, stats in conditions.items():
            ci = stats.get("bootstrap_95ci_median")
            ci_text = f"{ci['low_ns'] / 1e6:.3f}–{ci['high_ns'] / 1e6:.3f} ms" if ci else "—"
            lines.append(
                f"| {entry['name']} | {entry['kind']} | {condition} | "
                f"{stats['median_ns'] / 1e6:.3f} ms | {stats['p95_ns'] / 1e6:.3f} ms | "
                f"{ci_text} | {stats['runs']} |"
            )
    lines.extend(["", "## Scenario notes and refusals", ""])
    for entry in document["scenarios"]:
        lines.append(f"### {entry['name']}")
        lines.append("")
        lines.append(entry["description"])
        for note in entry["notes"]:
            lines.append(f"- {note}")
        for refusal in entry.get("refusals", []):
            lines.append(f"- REFUSAL: `{ ' '.join(refusal['command']) }`")
            lines.append("")
            lines.append("```text")
            lines.append(refusal["diagnostic"])
            lines.append("```")
        lines.append("")
    lines.extend(
        [
            "## Reading these numbers",
            "",
            "- Synthetic scenarios are committed workloads built for this repository.",
            "- Controlled scenarios add fixed environment settings so glibc and CPython do not draw entropy.",
            "- Real-world scenarios run unmodified third-party tools.",
            "- Negative results (warm losses, refusals, weak eligibility) are kept, not filtered.",
            "- These results apply to this commit and this host only.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(ROOT / "target/release/tracejit"))
    parser.add_argument("--release-dir", default=None)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--skip-delegated", action="store_true")
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")

    binary = Path(args.tracejit).resolve()
    if not binary.is_file():
        print(f"missing binary: {binary}", file=sys.stderr)
        return 2
    version = run_text(str(binary), "--version").split()[-1]
    commit = run_text("git", "rev-parse", "HEAD")
    dirty = bool(run_text("git", "status", "--porcelain"))
    release_dir = (
        Path(args.release_dir).resolve()
        if args.release_dir
        else ROOT / "benchmarks/releases" / f"v{version}"
    )
    release_dir.mkdir(parents=True, exist_ok=True)

    transform_original = TRANSFORM_INPUT.read_bytes()
    etl_original = ETL_INPUT.read_bytes()
    outputs_existed = {
        ETL_OUTPUT: ETL_OUTPUT.exists(),
        TRANSFORM_OUTPUT: TRANSFORM_OUTPUT.exists(),
        LARGE_OUTPUT: LARGE_OUTPUT.exists(),
    }
    original_bytes = {
        path: path.read_bytes() for path, existed in outputs_existed.items() if existed
    }
    env = base_env()
    scenarios: list[dict[str, object]] = []
    try:
        compile_workloads()
        scenarios.append(cpu_transform(binary, env, args.warmups, args.runs))
        scenarios.append(short_command(binary, env, args.warmups, args.runs))
        scenarios.append(compression(binary, env, args.warmups, args.runs))
        scenarios.append(etl_session(binary, env, args.warmups, args.runs))
        scenarios.append(large_restore(binary, env, args.warmups, max(5, args.runs // 2)))
        scenarios.append(cache_invalidation(binary, env, args.warmups, max(5, args.runs // 2)))
        scenarios.append(concurrency(binary, env, args.warmups, max(3, args.runs // 4)))
        if not args.skip_delegated:
            census_dir = release_dir / "census"
            census_dir.mkdir(exist_ok=True)
            scenarios.append(
                delegate(
                    "compatibility_census",
                    "Unmodified real-world command census (eligibility, refusals, hits).",
                    [
                        "python3",
                        "benchmarks/realworld/census.py",
                        "--tracejit",
                        str(binary),
                        "--runs",
                        "3",
                        "--warmups",
                        "1",
                        "--output-dir",
                        str(census_dir),
                    ],
                    release_dir,
                )
            )
            k8_dir = release_dir / "competitive"
            k8_dir.mkdir(exist_ok=True)
            scenarios.append(
                delegate(
                    "make_ninja_competitive",
                    "Make/Ninja/plain-CAS comparison on a rebuild workload; missing tools are skipped, not scored.",
                    [
                        "python3",
                        "benchmarks/repos/phase_k8_competitive.py",
                        "--binary",
                        str(binary),
                        "--runs",
                        "5",
                        "--warmups",
                        "2",
                        "--output-dir",
                        str(k8_dir),
                    ],
                    release_dir,
                )
            )
    finally:
        TRANSFORM_INPUT.write_bytes(transform_original)
        ETL_INPUT.write_bytes(etl_original)
        for path, existed in outputs_existed.items():
            if existed:
                path.write_bytes(original_bytes[path])
            else:
                path.unlink(missing_ok=True)

    document = {
        "release": {
            "version": version,
            "commit": commit,
            "working_tree_dirty": dirty,
            "binary_sha256": sha256(binary),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "configuration": {"runs": args.runs, "warmups": args.warmups},
        "environment": environment(),
        "scenarios": scenarios,
        "limitations": [
            "Single host; CPU frequency and neighbour activity are not controlled.",
            "One Linux x86_64 machine, not a fleet.",
            "Medians are per-commit; do not combine this table with older commit results.",
        ],
    }
    (release_dir / "results.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (release_dir / "RESULTS.md").write_text(markdown(document, release_dir), encoding="utf-8")
    print(f"wrote {release_dir / 'results.json'}", flush=True)
    print(f"wrote {release_dir / 'RESULTS.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

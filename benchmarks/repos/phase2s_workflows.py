#!/usr/bin/env python3
"""Phase 2S: realistic recurrence and complete-workflow measurements.

Every workflow is a sequence a developer or operator would actually run, not an artificial
identical-command loop. Native and controlled arms use the same inputs, output preconditions and
environment; each controlled arm has a fresh cache and includes its cold trace in the session
total. Per-run speedup is native median / controlled median; session speedup is total native
session / total controlled session; net savings is the difference.

Usage:
    cargo build --release --workspace
    python3 benchmarks/repos/phase2s_workflows.py [--reps N] [--output-dir DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TJ = REPO / "target/release/tracejit"
ROOT = Path("/tmp/tjq/phase2s")
CONTRACT = "allocator-entropy-v1"
RESULTS = REPO / "benchmarks/results/phase2s"
OUTPUT_TEXT = ["big.txt", "app.log", "assets", "release.tar", "sales.csv", "customers.csv"]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "sha256": sha(path),
        "size": stat.st_size,
        "mode": oct(stat.st_mode & 0o7777),
        "mtime_ns": stat.st_mtime_ns,
        "uid": stat.st_uid,
        "gid": stat.st_gid,
    }


def summarize(samples: list[float]) -> dict:
    return {
        "samples_ms": [round(value, 2) for value in samples],
        "median_ms": round(statistics.median(samples), 2) if samples else None,
        "total_ms": round(sum(samples), 2),
    }


def base_env(cache: Path | None, timing: Path) -> dict:
    values = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        # Keeps the allocator probe shape identical to the attribution and Phase 2R runs.
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "TRACEJIT_PHASE_TIMING": "1",
        "TRACEJIT_PHASE_TIMING_PATH": str(timing),
    }
    if cache is not None:
        values["TRACEJIT_CACHE_DIR"] = str(cache)
    return values


def run_native(command: list[str], cwd: Path, env: dict, stdin_bytes: bytes | None = None) -> dict:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=stdin_bytes,
        stdin=subprocess.DEVNULL if stdin_bytes is None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = (time.perf_counter() - started) * 1000
    return {
        "ms": elapsed,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit": completed.returncode,
    }


def run_traced(command: list[str], cwd: Path, env: dict, stdin_bytes: bytes | None = None) -> dict:
    started = time.perf_counter()
    completed = subprocess.run(
        [str(TJ), "run", "--json", "--contract", CONTRACT, "--", *command],
        cwd=cwd,
        env=env,
        input=stdin_bytes,
        stdin=subprocess.DEVNULL if stdin_bytes is None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = (time.perf_counter() - started) * 1000
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {"kind": "NO_JSON", "stderr": completed.stderr[-800:].decode(errors="replace")}
    output = report.get("stdout_bytes")
    if isinstance(output, list):
        output = bytes(output)
    return {
        "ms": elapsed,
        "report": report,
        "stdout": output if isinstance(output, bytes) else b"",
        "stderr": completed.stderr,
        "exit": completed.returncode,
    }


def cache_bytes(cache: Path) -> int:
    return sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())


def reset_root() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)
    (ROOT / "work").mkdir(parents=True)
    (ROOT / "work" / "stdin.txt").write_bytes(b"")
    RESULTS.mkdir(parents=True, exist_ok=True)


def build_fixture() -> None:
    work = ROOT / "work"
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    with (work / "big.txt").open("w") as handle:
        for index in range(140_000):
            handle.write(" ".join(words[(index + offset) % len(words)] for offset in range(6)))
            handle.write(f" {index:08d}\n")
    # A realistic set of three production assets, each large enough that compression cost is
    # visible against process startup.
    assets = work / "assets"
    assets.mkdir()
    for index in range(3):
        with (assets / f"asset-{index}.js").open("w") as handle:
            for row in range(45_000):
                handle.write(f"export const value{index}_{row} = {row * (index + 3)};\n")
    shutil.copy(work / "big.txt", work / "app.log")
    shutil.copy(work / "big.txt", work / "release.tar")

    with (work / "customers.csv").open("w") as handle:
        handle.write("customer_id,region\n")
        for index in range(1_000):
            handle.write(f"{index},R{index % 8}\n")
    with (work / "sales.csv").open("w") as handle:
        handle.write("sale_id,customer_id,amount_cents\n")
        for index in range(160_000):
            handle.write(f"{index},{index % 1000},{(index * 37) % 10_000}\n")


def bzip2_scenarios(reps: int) -> dict:
    """The three output-state scenarios for the unlocked bzip2 workload."""
    work = ROOT / "work"
    source = work / "big.txt"
    output = work / "big.txt.bz2"
    scenario_cache = ROOT / "bzip2-cache"
    timing = ROOT / "bzip2-timing.json"
    env = base_env(scenario_cache, timing)
    command = ["bzip2", "-9", "-k", "-f", "big.txt"]
    result = {}

    def reset_output(remove: bool) -> None:
        if remove:
            output.unlink(missing_ok=True)

    # A: output removed before every invocation. Capture the output once to establish the
    # writable-file pre-state, then remove it for the measured native and controlled runs.
    reset_output(False)
    if not output.exists():
        assert run_native(command, work, env)["exit"] == 0
    native_a = []
    for _ in range(reps):
        reset_output(True)
        native_a.append(run_native(command, work, env)["ms"])
    native_a_fp = fingerprint(output)
    shutil.rmtree(scenario_cache, ignore_errors=True)
    reset_output(True)
    cold_a = run_traced(command, work, env)
    warm_a = []
    warm_a_reports = []
    for _ in range(reps):
        reset_output(True)
        record = run_traced(command, work, env)
        warm_a.append(record["ms"])
        warm_a_reports.append(record["report"].get("cache_decision"))
    result["A_output_removed"] = {
        "command": command,
        "native": summarize(native_a),
        "cold": {"ms": round(cold_a["ms"], 2), "decision": cold_a["report"].get("cache_decision")},
        "warm": summarize(warm_a),
        "warm_decisions": warm_a_reports,
        "per_run_speedup": round(statistics.median(native_a) / statistics.median(warm_a), 2),
        "session_speedup": round(sum(native_a) / (cold_a["ms"] + sum(warm_a)), 2),
        "net_savings_ms": round(sum(native_a) - (cold_a["ms"] + sum(warm_a)), 2),
        "correctness_reference": native_a_fp,
        "warm_output": fingerprint(output),
        "output_matches_native": fingerprint(output)["sha256"] == native_a_fp["sha256"],
        "cache_bytes": cache_bytes(scenario_cache),
    }
    with source.open("ab") as handle:
        handle.write(b"\nscenario-a-edit\n")

    # B: output retained between invocations. This is the common repeated rebuild case.
    reset_output(False)
    assert run_native(command, work, env)["exit"] == 0
    native_b = [run_native(command, work, env)["ms"] for _ in range(reps)]
    native_b_fp = fingerprint(output)
    shutil.rmtree(scenario_cache, ignore_errors=True)
    cold_b = run_traced(command, work, env)
    cold_b_fp = fingerprint(output)
    warm_b = []
    warm_b_decisions = []
    for _ in range(reps):
        record = run_traced(command, work, env)
        warm_b.append(record["ms"])
        warm_b_decisions.append(record["report"].get("cache_decision"))
    result["B_output_retained"] = {
        "command": command,
        "native": summarize(native_b),
        "cold": {"ms": round(cold_b["ms"], 2), "decision": cold_b["report"].get("cache_decision")},
        "warm": summarize(warm_b),
        "warm_decisions": warm_b_decisions,
        "per_run_speedup": round(statistics.median(native_b) / statistics.median(warm_b), 2),
        "session_speedup": round(sum(native_b) / (cold_b["ms"] + sum(warm_b)), 2),
        "net_savings_ms": round(sum(native_b) - (cold_b["ms"] + sum(warm_b)), 2),
        "native_output": native_b_fp,
        "cold_output": cold_b_fp,
        "warm_output": fingerprint(output),
        "output_matches_native": fingerprint(output)["sha256"] == native_b_fp["sha256"],
        "output_matches_cold_metadata": fingerprint(output) == cold_b_fp,
    }

    # C: a realistic regenerated output: the input changes before each invocation, so reuse must
    # refuse and the new output must match native. Both arms start from the same source bytes and
    # apply the same edit sequence, otherwise the comparison would be between different inputs.
    base_source = source.read_bytes()
    native_c = []
    for index in range(reps):
        with source.open("ab") as handle:
            handle.write(f"\nscenario-c-{index}\n".encode())
        record = run_native(command, work, env)
        assert record["exit"] == 0
        native_c.append(record["ms"])
    native_c_fp = fingerprint(output)
    source.write_bytes(base_source)
    reset_output(True)
    shutil.rmtree(scenario_cache, ignore_errors=True)
    reset_output(False)
    controlled_c = []
    controlled_c_decisions = []
    for index in range(reps):
        with source.open("ab") as handle:
            handle.write(f"\nscenario-c-{index}\n".encode())
        record = run_traced(command, work, env)
        controlled_c.append(record["ms"])
        controlled_c_decisions.append(record["report"].get("cache_decision"))
    result["C_regenerated"] = {
        "command": command,
        "native": summarize(native_c),
        "controlled": summarize(controlled_c),
        "decisions": controlled_c_decisions,
        "per_run_speedup": round(statistics.median(native_c) / statistics.median(controlled_c), 2),
        "session_speedup": round(sum(native_c) / sum(controlled_c), 2),
        "net_savings_ms": round(sum(native_c) - sum(controlled_c), 2),
        "native_output": native_c_fp,
        "controlled_output": fingerprint(output),
        "output_matches_native": fingerprint(output)["sha256"] == native_c_fp["sha256"],
    }
    # Restore the canonical large input for the workflow measurements below.
    with source.open("wb") as handle:
        handle.write((work / "release.tar").read_bytes())
    return result


def workflow_log_archive(reps: int) -> dict:
    work = ROOT / "work"
    log = work / "app.log"
    output = work / "app.log.bz2"
    cache = ROOT / "log-cache"
    timing = ROOT / "log-timing.json"
    command = ["bzip2", "-9", "-k", "-f", "app.log"]
    native_env = base_env(None, timing)

    def append(index: int) -> None:
        with log.open("ab") as handle:
            handle.write(f"request={index} status=200 bytes={index * 17 % 4096}\n".encode())

    # Native: edit then compress on each iteration.
    base_log = log.read_bytes()
    native = []
    for index in range(reps):
        append(index)
        result = run_native(command, work, native_env)
        assert result["exit"] == 0
        native.append(result["ms"])
    native_fp = fingerprint(output)

    # The controlled arm must apply exactly the same edits from the same base bytes.
    log.write_bytes(base_log)
    output.unlink(missing_ok=True)
    shutil.rmtree(cache, ignore_errors=True)
    controlled_env = base_env(cache, timing)
    controlled = []
    decisions = []
    for index in range(reps):
        append(index)
        result = run_traced(command, work, controlled_env)
        controlled.append(result["ms"])
        decisions.append(result["report"].get("cache_decision"))
    controlled_fp = fingerprint(output)
    return {
        "id": "log_archive",
        "description": "append a log record and recompress the growing log",
        "command": command,
        "repetitions": reps,
        "native": summarize(native),
        "controlled": summarize(controlled),
        "decisions": decisions,
        "native_output": native_fp,
        "controlled_output": controlled_fp,
        "output_matches_native": native_fp["sha256"] == controlled_fp["sha256"],
        "per_run_speedup": round(statistics.median(native) / statistics.median(controlled), 2),
        "session_speedup": round(sum(native) / sum(controlled), 2),
        "net_savings_ms": round(sum(native) - sum(controlled), 2),
    }


def workflow_assets(reps: int) -> dict:
    work = ROOT / "work"
    assets = sorted((work / "assets").glob("*.js"))
    cache = ROOT / "asset-cache"
    timing = ROOT / "asset-timing.json"
    native_env = base_env(None, timing)

    def commands() -> list[list[str]]:
        return [
            ["bzip2", "-9", "-k", "-f", str(asset.relative_to(work))] for asset in assets
        ]

    def run_sequence(traced: bool, env: dict) -> tuple[float, list[dict]]:
        started = time.perf_counter()
        decisions = []
        for command in commands():
            result = run_traced(command, work, env) if traced else run_native(command, work, env)
            assert result["exit"] == 0, result["stderr"][-500:]
            decisions.append(
                result["report"].get("cache_decision") if traced else "native"
            )
        return (time.perf_counter() - started) * 1000, decisions

    native = []
    for _ in range(reps):
        total, _ = run_sequence(False, native_env)
        native.append(total)
    native_fps = {asset.name: fingerprint(Path(f"{asset}.bz2")) for asset in assets}

    shutil.rmtree(cache, ignore_errors=True)
    controlled_env = base_env(cache, timing)
    cold_ms, cold_decisions = run_sequence(True, controlled_env)
    controlled = []
    decisions = [cold_decisions]
    for _ in range(reps):
        total, sequence_decisions = run_sequence(True, controlled_env)
        controlled.append(total)
        decisions.append(sequence_decisions)
    controlled_fps = {asset.name: fingerprint(Path(f"{asset}.bz2")) for asset in assets}
    return {
        "id": "static_assets",
        "description": "precompress three stable production JavaScript assets",
        "commands": commands(),
        "repetitions": reps,
        "native": summarize(native),
        "controlled": summarize(controlled),
        "cold_workflow_ms": round(cold_ms, 2),
        "cold_decisions": cold_decisions,
        "decisions": decisions,
        "native_outputs": native_fps,
        "controlled_outputs": controlled_fps,
        "output_matches_native": {
            name: native_fps[name]["sha256"] == controlled_fps[name]["sha256"] for name in native_fps
        },
        "per_run_speedup": round(statistics.median(native) / statistics.median(controlled), 2),
        "session_speedup": round(sum(native) / (cold_ms + sum(controlled)), 2),
        "net_savings_ms": round(sum(native) - (cold_ms + sum(controlled)), 2),
    }


def workflow_release_gzip(reps: int) -> dict:
    work = ROOT / "work"
    source = work / "release.tar"
    output = work / "release.tar.gz"
    cache = ROOT / "release-cache"
    timing = ROOT / "release-timing.json"
    command = ["gzip", "-9", "-c", "release.tar"]
    native_env = base_env(None, timing)

    def native_run() -> dict:
        result = run_native(command, work, native_env)
        output.write_bytes(result["stdout"])
        return result

    native = []
    for _ in range(reps):
        native.append(native_run()["ms"])
    native_fp = fingerprint(output)
    shutil.rmtree(cache, ignore_errors=True)
    controlled_env = base_env(cache, timing)
    cold = run_traced(command, work, controlled_env)
    output.write_bytes(cold["stdout"])
    cold_ms = cold["ms"]
    controlled = []
    decisions = []
    for _ in range(reps):
        record = run_traced(command, work, controlled_env)
        output.write_bytes(record["stdout"])
        controlled.append(record["ms"])
        decisions.append(record["report"].get("cache_decision"))
    controlled_fp = fingerprint(output)
    return {
        "id": "release_stream",
        "description": "compress the release tar stream to release.tar.gz",
        "command": command,
        "repetitions": reps,
        "native": summarize(native),
        "controlled": summarize(controlled),
        "cold_ms": round(cold_ms, 2),
        "cold_decision": cold["report"].get("cache_decision"),
        "decisions": decisions,
        "native_output": native_fp,
        "controlled_output": controlled_fp,
        "output_matches_native": native_fp["sha256"] == controlled_fp["sha256"],
        "per_run_speedup": round(statistics.median(native) / statistics.median(controlled), 2),
        "session_speedup": round(sum(native) / (cold_ms + sum(controlled)), 2),
        "net_savings_ms": round(sum(native) - (cold_ms + sum(controlled)), 2),
    }


def workflow_etl(reps: int) -> dict:
    work = ROOT / "work"
    output = work / "report.json"
    script = REPO / "benchmarks/realworld/workloads/etl.py"
    cache = ROOT / "etl-cache"
    timing = ROOT / "etl-timing.json"
    command = ["python3", str(script), "sales.csv", "customers.csv", "report.json"]
    stdin_path = work / "stdin.txt"

    def invoke(traced: bool, env: dict) -> dict:
        with stdin_path.open("rb") as handle:
            if traced:
                started = time.perf_counter()
                completed = subprocess.run(
                    [str(TJ), "run", "--json", "--contract", CONTRACT, "--", *command],
                    cwd=work,
                    env=env,
                    stdin=handle,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                elapsed = (time.perf_counter() - started) * 1000
                report = json.loads(completed.stdout)
                return {"ms": elapsed, "exit": completed.returncode, "report": report}
            started = time.perf_counter()
            completed = subprocess.run(
                command,
                cwd=work,
                env=env,
                stdin=handle,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return {
                "ms": (time.perf_counter() - started) * 1000,
                "exit": completed.returncode,
                "stdout": completed.stdout,
            }

    native_env = base_env(None, timing)
    native = []
    for _ in range(reps):
        output.unlink(missing_ok=True)
        native.append(invoke(False, native_env)["ms"])
    native_fp = fingerprint(output)
    shutil.rmtree(cache, ignore_errors=True)
    controlled_env = base_env(cache, timing)
    output.unlink(missing_ok=True)
    cold = invoke(True, controlled_env)
    controlled = []
    decisions = []
    for _ in range(reps):
        output.unlink(missing_ok=True)
        record = invoke(True, controlled_env)
        controlled.append(record["ms"])
        decisions.append(record["report"].get("cache_decision"))
    return {
        "id": "csv_etl",
        "description": "aggregate sales CSV into a regional JSON report",
        "command": command,
        "repetitions": reps,
        "native": summarize(native),
        "controlled": summarize(controlled),
        "cold_ms": round(cold["ms"], 2),
        "cold_decision": cold["report"].get("cache_decision"),
        "cold_reasons": cold["report"].get("reasons", [])[:6],
        "decisions": decisions,
        "native_output": native_fp,
        "controlled_output": fingerprint(output),
        "output_matches_native": native_fp["sha256"] == fingerprint(output)["sha256"],
        "per_run_speedup": round(statistics.median(native) / statistics.median(controlled), 2),
        "session_speedup": round(sum(native) / (cold["ms"] + sum(controlled)), 2),
        "net_savings_ms": round(sum(native) - (cold["ms"] + sum(controlled)), 2),
    }


def main() -> int:
    global RESULTS
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--output-dir", default=str(RESULTS))
    args = parser.parse_args()
    RESULTS = Path(args.output_dir)
    if not TJ.is_file():
        sys.exit("build target/release/tracejit first")
    random.seed(20261109)
    reset_root()
    build_fixture()
    result = {
        "generated_by": "benchmarks/repos/phase2s_workflows.py",
        "contract": CONTRACT,
        "binary": str(TJ),
        "binary_sha256": sha(TJ),
        "repetitions": args.reps,
        "host": {
            "os": os.uname().sysname,
            "release": os.uname().release,
            "machine": os.uname().machine,
            "glibc": subprocess.run(["ldd", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        },
        "bzip2_scenarios": bzip2_scenarios(args.reps),
    }
    workflows = [
        workflow_log_archive(args.reps),
        workflow_assets(args.reps),
        workflow_release_gzip(args.reps),
        workflow_etl(args.reps),
    ]
    result["workflows"] = workflows
    output = RESULTS / "workflows.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "bzip2": result["bzip2_scenarios"],
        "workflows": [
            {
                key: workflow[key]
                for key in ("id", "per_run_speedup", "session_speedup", "net_savings_ms",
                            "decisions", "output_matches_native")
            }
            for workflow in workflows
        ],
    }, indent=2)[:8000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase F hit-path profile: attribute warm reuse cost with TRACEJIT_PHASE_TIMING.

Records cold + warm wall times and phase medians for:
  - c-etl (official short deterministic C workload with file output)
  - fixture plain_file_read (small content-hash + restore path)
  - /bin/true under allocator-entropy-v1 when reusable, else native always path

Does not invent numbers. Writes JSON + markdown under --output-dir.
perf/PMU and strace availability are recorded as host facts, not assumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BINARY = REPO / "target/release/tracejit"
PHASE_KEYS = (
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
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_facts() -> dict:
    perf_path = shutil.which("perf")
    strace_path = shutil.which("strace")
    pmu_devices = []
    pmu_root = Path("/sys/bus/event_source/devices")
    if pmu_root.is_dir():
        pmu_devices = sorted(entry.name for entry in pmu_root.iterdir())
    paranoid = None
    paranoid_path = Path("/proc/sys/kernel/perf_event_paranoid")
    if paranoid_path.is_file():
        paranoid = paranoid_path.read_text().strip()
    return {
        "kernel": platform.release(),
        "platform": platform.platform(),
        "cpus": os.cpu_count(),
        "perf_available": perf_path is not None,
        "perf_path": perf_path,
        "strace_available": strace_path is not None,
        "strace_path": strace_path,
        "perf_event_paranoid": paranoid,
        "pmu_devices": pmu_devices,
        "hardware_cpu_pmu_present": "cpu" in pmu_devices,
        "filesystem": subprocess.check_output(
            ["findmnt", "-no", "FSTYPE,TARGET", "-T", str(REPO)],
            text=True,
        ).strip(),
    }


def compile_c_etl() -> Path:
    workload = REPO / "benchmarks/workloads/c-etl"
    binary = workload / "etl"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-o",
            str(binary),
            str(workload / "main.c"),
        ],
        cwd=REPO,
        check=True,
    )
    return binary


def compile_fixture(root: Path) -> Path:
    binary = root / "fixture-driver"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            str(REPO / "tests/fixtures/fixture_driver.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


def phase_ms(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    data = raw.get("phases", raw)
    out = {}
    for key in PHASE_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)):
            out[key] = round(value / 1e6, 3)
    return out


def env_for(cache: Path, phase_path: Path | None) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "TRACEJIT_CACHE_DIR": str(cache),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    if phase_path is not None:
        env["TRACEJIT_PHASE_TIMING"] = "1"
        env["TRACEJIT_PHASE_TIMING_PATH"] = str(phase_path)
    return env


def run_tracejit(
    binary: Path,
    argv_tail: list[str],
    *,
    cwd: Path,
    cache: Path,
    phase_path: Path | None,
    stdin_path: Path | None = None,
) -> tuple[float, dict]:
    cmd = [
        str(binary),
        "run",
        "--json",
        "--admission",
        "always",
        "--",
        *argv_tail,
    ]
    phase_path and phase_path.unlink(missing_ok=True)
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=env_for(cache, phase_path),
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    finally:
        if stdin_path:
            stdin.close()
    wall_ms = (time.perf_counter() - started) * 1000.0
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {
            "kind": "NO_JSON",
            "returncode": completed.returncode,
            "stderr": completed.stderr.decode(errors="replace")[:2000],
        }
    report["_wall_ms"] = wall_ms
    report["_phases"] = phase_ms(phase_path) if phase_path else {}
    report["_status"] = completed.returncode
    return wall_ms, report


def summarize(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "runs": len(samples),
        "median_ms": round(statistics.median(samples), 3),
        "min_ms": round(min(samples), 3),
        "p95_ms": round(ordered[max(0, int(len(samples) * 0.95) - 1)], 3),
        "samples_ms": [round(value, 3) for value in samples],
    }


def phase_medians(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = sorted({key for row in rows for key in row})
    out = {}
    for key in keys:
        values = [row[key] for row in rows if key in row]
        if values:
            out[key] = round(statistics.median(values), 3)
    return out


def measure_shape(
    name: str,
    binary: Path,
    argv_tail: list[str],
    *,
    cwd: Path,
    warmups: int,
    runs: int,
    stdin_path: Path | None = None,
) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"phase-f-{name}-"))
    cache = root / "cache"
    phase_path = root / "phases.json"
    try:
        cold_ms, cold_report = run_tracejit(
            binary,
            argv_tail,
            cwd=cwd,
            cache=cache,
            phase_path=None,
            stdin_path=stdin_path,
        )
        warm_samples = []
        warm_phases = []
        warm_kinds = []
        for index in range(warmups + runs):
            wall_ms, report = run_tracejit(
                binary,
                argv_tail,
                cwd=cwd,
                cache=cache,
                phase_path=phase_path,
                stdin_path=stdin_path,
            )
            if index < warmups:
                continue
            warm_samples.append(wall_ms)
            warm_phases.append(report.get("_phases") or {})
            warm_kinds.append(report.get("kind") or report.get("cache_decision"))
        return {
            "name": name,
            "argv": argv_tail,
            "cold_ms": round(cold_ms, 3),
            "cold_kind": cold_report.get("kind") or cold_report.get("cache_decision"),
            "warm": summarize(warm_samples),
            "warm_kinds": warm_kinds,
            "phases_median_ms": phase_medians(warm_phases),
            "all_warm_reused": all(kind == "Reused" for kind in warm_kinds),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def rank_phases(phases: dict[str, float]) -> list[dict]:
    ranked = sorted(phases.items(), key=lambda item: item[1], reverse=True)
    total = sum(phases.values()) or 1.0
    return [
        {
            "phase": name,
            "median_ms": value,
            "share_of_summed_phases": round(value / total, 4),
        }
        for name, value in ranked
        if value > 0
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        default=str(REPO / "benchmarks/results/phase_f"),
    )
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    if not binary.is_file():
        print(f"missing binary: {binary}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
    ).strip()
    etl = compile_c_etl()
    work = Path(tempfile.mkdtemp(prefix="phase-f-work-"))
    try:
        fixture = compile_fixture(work)
        (work / "input.txt").write_text("phase-f-input\n")
        large = work / "large"
        large.mkdir()
        # 4 MiB input so guard hashing and CAS restore are above the timer floor.
        (large / "input.txt").write_bytes(b"phase-f-large\n" * ((4 << 20) // 14 + 1))
        shapes = [
            measure_shape(
                "c-etl",
                binary,
                [str(etl)],
                cwd=REPO / "benchmarks/workloads/c-etl",
                warmups=args.warmups,
                runs=args.runs,
            ),
            measure_shape(
                "plain_file_read",
                binary,
                [str(fixture), "plain_file_read", str(work)],
                cwd=work,
                warmups=args.warmups,
                runs=args.runs,
            ),
            measure_shape(
                "large_file_read",
                binary,
                [str(fixture), "plain_file_read", str(large)],
                cwd=large,
                warmups=args.warmups,
                runs=args.runs,
            ),
            measure_shape(
                "bin_true",
                binary,
                ["/bin/true"],
                cwd=work,
                warmups=args.warmups,
                runs=args.runs,
            ),
        ]
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for shape in shapes:
        shape["phase_rank"] = rank_phases(shape["phases_median_ms"])

    document = {
        "label": args.label,
        "commit": commit,
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
        "warmups": args.warmups,
        "runs": args.runs,
        "host": host_facts(),
        "shapes": shapes,
    }
    json_path = output_dir / f"profile-{args.label}.json"
    json_path.write_text(json.dumps(document, indent=2) + "\n")

    lines = [
        f"# Phase F profile ({args.label})",
        "",
        f"Commit `{commit}` · binary `{document['binary_sha256'][:16]}` · "
        f"{args.warmups} warmups + {args.runs} runs.",
        "",
        "## Host tooling",
        "",
        f"- perf available: `{document['host']['perf_available']}`",
        f"- strace available: `{document['host']['strace_available']}`",
        f"- perf_event_paranoid: `{document['host']['perf_event_paranoid']}`",
        f"- PMU devices: `{', '.join(document['host']['pmu_devices']) or '(none)'}`",
        f"- hardware cpu PMU present: `{document['host']['hardware_cpu_pmu_present']}`",
        "",
        "## Wall times",
        "",
        "| Shape | cold ms | warm median | warm p95 | all reused |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for shape in shapes:
        warm = shape["warm"]
        lines.append(
            f"| {shape['name']} | {shape['cold_ms']} | {warm['median_ms']} | "
            f"{warm['p95_ms']} | {shape['all_warm_reused']} |"
        )
    lines += ["", "## Phase rank (warm median ms)", ""]
    for shape in shapes:
        lines.append(f"### {shape['name']}")
        lines.append("")
        lines.append("| Phase | median ms | share of summed phases |")
        lines.append("| --- | ---: | ---: |")
        for row in shape["phase_rank"]:
            lines.append(
                f"| {row['phase']} | {row['median_ms']} | {row['share_of_summed_phases']} |"
            )
        lines.append("")
    md_path = output_dir / f"profile-{args.label}.md"
    md_path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

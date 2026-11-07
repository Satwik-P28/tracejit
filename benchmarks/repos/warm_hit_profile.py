#!/usr/bin/env python3
"""Warm-hit latency profile for TraceJIT.

The wrap experiment measured ~30 ms per cached child while the synthetic transform workload
measured ~4 ms. This harness isolates the shapes that differ instead of comparing totals:

  native gzip to a file / to /dev/null      (does redirection change native cost?)
  tracejit, plain stdout to a file          (the normal CLI)
  tracejit, plain stdout to /dev/null       (no file restoration, no output write)
  tracejit --json to a report file          (reporting cost, including captured stdout bytes)
  tracejit inside a Makefile recipe         (make/sh wrapper overhead)
  native make with native gzip              (make/sh overhead control)
  tracejit /bin/true                        (startup + open + lookup with no payload)

Every TraceJIT shape gets its own fresh cache so a record written for one stdout target cannot be
read by another. Cold cost is reported separately from warm cost; iterations are interleaved in
rounds so a slow period cannot sit entirely inside one shape.

Usage:
  python3 benchmarks/repos/warm_hit_profile.py --iterations 25 \
      --output-dir benchmarks/results/phase2n/warm-hit
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
    "direct_run_ns",
    "trace_ns",
    "classify_ns",
    "store_ns",
    "total_ns",
)
TRACE_ARGS = ["run", "--admission", "always", "--contract", "allocator-entropy-v1"]


def blake3less_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_payload(path: Path, rows: int = 120_000) -> None:
    with open(path, "w") as handle:
        for index in range(rows):
            handle.write(
                f"{index * 2654435761 % 1000000007:010d} {index % 9973} "
                "alpha beta gamma delta epsilon zeta eta theta\n"
            )


class Shapes:
    """One shape is a self-contained command plus the files it reads and writes."""

    def __init__(self, root: Path, binary: Path):
        self.root = root
        self.binary = binary
        self.input = root / "input.bin"
        make_payload(self.input)

    def env(self, cache: Path, phase_path: Path | None) -> dict:
        env = dict(os.environ)
        env["TRACEJIT_CACHE_DIR"] = str(cache)
        env.pop("TRACEJIT_PHASE_TIMING_PATH", None)
        if phase_path is not None:
            env["TRACEJIT_PHASE_TIMING"] = "1"
            env["TRACEJIT_PHASE_TIMING_PATH"] = str(phase_path)
        return env

    def definitions(self) -> dict:
        return {
            "native_file": self._native("out.gz"),
            "native_devnull": self._native(os.devnull),
            "tracejit_file": self._tracejit("out.gz", json_report=False),
            "tracejit_devnull": self._tracejit(os.devnull, json_report=False),
            "tracejit_json": self._tracejit("report.json", json_report=True),
            "tracejit_make": self._tracejit_make(),
            "native_make": self._native_make(),
            "tracejit_true": self._tracejit_true(),
        }

    def _native(self, destination: str) -> dict:
        return {
            "kind": "native",
            "argv": ["gzip", "-n", "-9", "-c"],
            "stdout": destination,
            "stdin": self.input,
            "cwd": str(self.root),
        }

    def _tracejit(self, destination: str, *, json_report: bool) -> dict:
        argv = [str(self.binary), *TRACE_ARGS]
        if json_report:
            argv.append("--json")
        argv += ["--", "gzip", "-n", "-9", "-c"]
        return {
            "kind": "tracejit",
            "argv": argv,
            "stdout": destination,
            "stdin": self.input,
            "cwd": str(self.root),
        }

    def _tracejit_make(self) -> dict:
        makefile = self.root / "Makefile.tracejit"
        makefile.write_text(
            "COMPRESS ?= gzip\n"
            "data.gz: input.bin FORCE\n"
            f"\t{self.binary} run --admission always --contract allocator-entropy-v1 -- "
            "gzip -n -9 -c < $< > $@\n"
            ".PHONY: FORCE\n"
            "FORCE:\n"
        )
        return {
            "kind": "tracejit",
            "argv": ["make", "-f", str(makefile), "data.gz"],
            "stdout": os.devnull,
            "stdin": None,
            "cwd": str(self.root),
        }

    def _native_make(self) -> dict:
        makefile = self.root / "Makefile.native"
        makefile.write_text(
            "data.gz: input.bin FORCE\n\tgzip -n -9 -c < $< > $@\n"
            ".PHONY: FORCE\n"
            "FORCE:\n"
        )
        return {
            "kind": "native",
            "argv": ["make", "-f", str(makefile), "data.gz"],
            "stdout": os.devnull,
            "stdin": None,
            "cwd": str(self.root),
        }

    def _tracejit_true(self) -> dict:
        return {
            "kind": "tracejit",
            "argv": [str(self.binary), *TRACE_ARGS, "--", "/bin/true"],
            "stdout": os.devnull,
            "stdin": None,
            "cwd": str(self.root),
        }


def one_run(shape: dict, env: dict, stdout_path: str) -> tuple[float, subprocess.CompletedProcess]:
    source = open(shape["stdin"], "rb") if shape["stdin"] else subprocess.DEVNULL
    sink = subprocess.DEVNULL if stdout_path == os.devnull else open(stdout_path, "wb")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            shape["argv"],
            cwd=shape["cwd"],
            env=env,
            stdin=source,
            stdout=sink,
            stderr=subprocess.PIPE,
            timeout=600,
        )
    finally:
        if shape["stdin"]:
            source.close()
        if sink is not subprocess.DEVNULL:
            sink.close()
    return (time.perf_counter() - started) * 1000.0, completed


def phase_ms(phase_path: Path) -> dict:
    try:
        raw = json.loads(phase_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        key: round(raw[key] / 1e6, 3)
        for key in PHASE_KEYS
        if isinstance(raw.get(key), (int, float))
    }


def measure(binary: Path, root: Path, iterations: int, strace: bool) -> dict:
    shapes = Shapes(root, binary)
    definitions = shapes.definitions()
    state: dict[str, dict] = {}
    for name, shape in definitions.items():
        directory = root / name
        directory.mkdir()
        cache = directory / "cache"
        phases = directory / "phases.json"
        state[name] = {
            "shape": shape,
            "dir": directory,
            "cache": cache,
            "phase_path": phases,
            "stdout_path": (
                os.devnull if shape["stdout"] == os.devnull else str(directory / shape["stdout"])
            ),
            "cold_ms": None,
            "samples": [],
            "phases": [],
            "report_bytes": [],
        }
        env = shapes.env(cache, None)
        elapsed, completed = one_run(shape, env, state[name]["stdout_path"])
        if completed.returncode != 0:
            raise SystemExit(
                f"{name} cold run failed with {completed.returncode}: "
                f"{completed.stderr.decode(errors='replace')[:500]}"
            )
        state[name]["cold_ms"] = round(elapsed, 3)

    for _ in range(iterations):
        for name, entry in state.items():
            entry["phase_path"].unlink(missing_ok=True)
            env = shapes.env(entry["cache"], entry["phase_path"])
            elapsed, completed = one_run(entry["shape"], env, entry["stdout_path"])
            if completed.returncode != 0:
                raise SystemExit(f"{name} warm run failed: {completed.stderr[:500]!r}")
            entry["samples"].append(round(elapsed, 3))
            entry["phases"].append(phase_ms(entry["phase_path"]))
            destination = Path(entry["stdout_path"])
            if destination.is_file():
                entry["report_bytes"].append(destination.stat().st_size)

    result = {}
    for name, entry in state.items():
        samples = entry["samples"]
        phases = [p for p in entry["phases"] if p]
        aggregate = {}
        keys = sorted({key for phase in phases for key in phase})
        for key in keys:
            values = [phase[key] for phase in phases if key in phase]
            if values:
                aggregate[key] = round(statistics.median(values), 3)
        result[name] = {
            "cold_ms": entry["cold_ms"],
            "median_ms": round(statistics.median(samples), 3),
            "min_ms": round(min(samples), 3),
            "p95_ms": round(sorted(samples)[max(0, int(len(samples) * 0.95) - 1)], 3),
            "samples_ms": samples,
            "phases_median_ms": aggregate,
            "phase_sum_median_ms": round(
                sum(aggregate.get(key, 0.0) for key in aggregate), 3
            ),
            "output_bytes": statistics.median(entry["report_bytes"])
            if entry["report_bytes"]
            else None,
        }

    if strace:
        name = "tracejit_file"
        entry = state[name]
        env = shapes.env(entry["cache"], None)
        trace_path = root / "strace.txt"
        with open(trace_path, "w") as trace:
            subprocess.run(
                ["strace", "-f", "-c", "-o", str(trace_path)]
                + entry["shape"]["argv"],
                env=env,
                stdin=open(entry["shape"]["stdin"], "rb"),
                stdout=open(entry["stdout_path"], "wb"),
                stderr=subprocess.DEVNULL,
                timeout=600,
            )
        result[name]["strace"] = trace_path.read_text()[:6000]

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--output-dir", default="benchmarks/results/phase2n/warm-hit")
    parser.add_argument("--strace", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    if not binary.is_file():
        print(f"missing binary: {binary}", file=sys.stderr)
        return 2
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tracejit-warm-hit-"))
    try:
        results = measure(binary, root, args.iterations, args.strace)
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)

    document = {
        "binary": str(binary),
        "binary_sha256": blake3less_sha256(binary),
        "iterations": args.iterations,
        "environment": {
            "kernel": platform.release(),
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
            "contract": "allocator-entropy-v1",
            "admission": "always",
            "guard_mode": "strict",
        },
        "shapes": results,
    }
    json_path = output_dir / "warm-hit.json"
    json_path.write_text(json.dumps(document, indent=2) + "\n")

    lines = [
        "# Warm-hit latency profile",
        "",
        f"Binary `{document['binary_sha256'][:16]}` · {args.iterations} interleaved warm runs per shape.",
        "",
        "| Shape | cold ms | median ms | min ms | p95 ms | sum of phases ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, entry in results.items():
        lines.append(
            f"| {name} | {entry['cold_ms']} | {entry['median_ms']} | {entry['min_ms']} "
            f"| {entry['p95_ms']} | {entry['phase_sum_median_ms']} |"
        )
    lines += ["", "## Median phases (ms)", ""]
    keys = sorted({key for entry in results.values() for key in entry["phases_median_ms"]})
    lines.append("| Shape | " + " | ".join(keys) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in keys) + " |")
    for name, entry in results.items():
        cells = [str(entry["phases_median_ms"].get(key, "")) for key in keys]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    (output_dir / "warm-hit.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

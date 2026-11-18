#!/usr/bin/env python3
"""Paired end-to-end economics of reuse for real command-line workloads.

For each workload this measures, on the same host with randomized pairwise order:

  direct      the command run natively
  cold        the first TraceJIT run (trace + record)
  warm        a TraceJIT run against a complete record (HIT)

and derives the economic break-even repetition count

  k* = (cold - warm) / (direct - warm)

which is the number of identical invocations at which the traced path has spent
the same wall time as running the command natively every time.

Every workload is a real tool doing real work on generated inputs; nothing here
is a synthetic spin loop. Outputs are compared byte for byte and the native
decision reason is recorded so an ineligible workload cannot be reported as a
reusable one.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

TRACEJIT = None
CACHE_HIT = "cache          HIT"


def run_once(argv: list[str], cwd: Path, env: dict[str, str], stdin=None) -> tuple[float, subprocess.CompletedProcess]:
    start = time.perf_counter()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return time.perf_counter() - start, completed


def traced(
    cache: Path,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    contract: str | None = None,
) -> tuple[float, subprocess.CompletedProcess]:
    environment = dict(env)
    environment["TRACEJIT_CACHE_DIR"] = str(cache)
    prefix = ["--contract", contract] if contract else []
    return run_once(
        [TRACEJIT, "run", "--json", *prefix, "--", *argv], cwd, environment
    )


def report(output: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(output.stdout or b"{}")
    except json.JSONDecodeError:
        return {}


def program_stdout(value: dict) -> bytes:
    return bytes(value.get("stdout_bytes") or [])


def workspace_digest(directory: Path, ignore: set[str]) -> str:
    """Content hash of everything the command produced, inputs excluded."""
    import hashlib

    digest = hashlib.blake2b(digest_size=16)
    for entry in sorted(directory.iterdir(), key=lambda path: path.name):
        if entry.name in ignore or not entry.is_file():
            continue
        digest.update(entry.name.encode())
        digest.update(entry.read_bytes())
    return digest.hexdigest()


def prepare(source: Path) -> dict[str, list[str]]:
    source.mkdir(parents=True, exist_ok=True)
    # A translation unit large enough that compilation dominates process startup.
    unit = ["#include <stdio.h>", "#include <string.h>", "#include <stdlib.h>", ""]
    for index in range(600):
        unit.append(
            "long fn_{0}(long a, long b) {{ char buffer[64]; snprintf(buffer, sizeof buffer, \"{0}:%ld\", a); "
            "return (long)strlen(buffer) + a * {1} + b; }}".format(index, index + 1)
        )
    unit.append("int main(void) { long total = 0;")
    for index in range(600):
        unit.append("    total += fn_{0}({0}, {0} + 1);".format(index))
    unit.append("    printf(\"%ld\\n\", total);")
    unit.append("    return 0;\n}")
    (source / "unit.c").write_text("\n".join(unit) + "\n")

    # 8 MiB of compressible but non-trivial data, plus a small input.
    data = bytearray()
    state = 0x1234_5678
    for index in range(8 * 1024 * 1024):
        state = (state * 1103515245 + 12345) & 0xFFFF_FFFF
        data.append(0x61 + (state >> 16) % 26)
    (source / "data.bin").write_bytes(bytes(data))
    (source / "small.bin").write_bytes(bytes(data[:64 * 1024]))
    lines = [f"line {index} value {(index * 7919) % 100003}" for index in range(300_000)]
    (source / "lines.txt").write_text("\n".join(lines) + "\n")

    return {
        "cc_o2_compile": ["cc", "-O2", "-c", "unit.c", "-o", "unit.o"],
        "gzip_9_small": ["gzip", "-9", "-c", "small.bin"],
        "gzip_9_8mib": ["gzip", "-9", "-c", "data.bin"],
        "sort_300k_lines": ["sort", "lines.txt"],
        "sha256sum_8mib": ["sha256sum", "data.bin"],
        "tar_source_tree": ["tar", "-cf", "tree.tar", "unit.c", "lines.txt", "small.bin"],
        "strip_object": ["strip", "-o", "unit.stripped.o", "unit.o"],
        "md5sum_8mib": ["md5sum", "data.bin"],
        "sed_rewrite_8mib": ["sed", "s/a/b/g", "data.bin"],
        "wc_bytes_8mib": ["wc", "-c", "data.bin"],
    }


def summarise(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "median_ms": round(statistics.median(samples) * 1000, 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))] * 1000, 3),
        "min_ms": round(ordered[0] * 1000, 3),
        "max_ms": round(ordered[-1] * 1000, 3),
        "stdev_ms": round(statistics.stdev(samples) * 1000, 3) if len(samples) > 1 else 0.0,
    }


def measure(
    name: str,
    argv: list[str],
    workspace: Path,
    cache: Path,
    reps: int,
    rng: random.Random,
    contract: str | None = None,
    native_inputs: tuple[str, ...] = (),
) -> dict:
    environment = {key: value for key, value in os.environ.items() if key != "TRACEJIT_CACHE_DIR"}
    environment["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"

    # Native output for the equivalence check, plus the first observation.
    _, native = run_once(argv, workspace, environment)
    if native.returncode != 0:
        raise SystemExit(f"{name}: native run failed: {native.stderr.decode(errors='replace')[:400]}")

    shutil.rmtree(cache, ignore_errors=True)
    cold_time, cold = traced(cache, argv, workspace, environment, contract)
    cold_report = report(cold)
    warm_time, warm = traced(cache, argv, workspace, environment, contract)
    warm_report = report(warm)
    warm_hit = warm_report.get("cache_decision") == "Reused"
    if not warm_hit:
        # Not reusable: report the refusal reason instead of inventing a hit.
        return {
            "workload": name,
            "argv": argv,
            "contract": contract,
            "classification": cold_report.get("classification"),
            "reusable": False,
            "reasons": cold_report.get("reasons"),
            "decision_reason": warm_report.get("decision_reason"),
            "direct": summarise([run_once(argv, workspace, environment)[0] for _ in range(3)]),
            "cold": {"trace_ms": round(cold_time * 1000, 3)},
        }

    direct_samples: list[float] = []
    warm_samples: list[float] = []
    for _ in range(reps):
        if rng.random() < 0.5:
            direct_samples.append(run_once(argv, workspace, environment)[0])
            warm_samples.append(traced(cache, argv, workspace, environment, contract)[0])
        else:
            warm_samples.append(traced(cache, argv, workspace, environment, contract)[0])
            direct_samples.append(run_once(argv, workspace, environment)[0])

    # Every warm run must have been a HIT, and its restored result must equal the native one:
    # same program stdout, same exit status, same produced files.
    inputs = set(native_inputs)
    expected_digest = workspace_digest(workspace, inputs)
    for _ in range(3):
        _, again = traced(cache, argv, workspace, environment, contract)
        again_report = report(again)
        decision = again_report.get("cache_decision")
        if decision != "Reused":
            raise SystemExit(
                f"{name}: expected a HIT after the warmup, got {decision}: "
                f"{again.stderr.decode(errors='replace')[:400]}"
            )
        if program_stdout(again_report) != native.stdout:
            raise SystemExit(f"{name}: cached stdout differs from native")
        if again_report.get("exit_code") != native.returncode:
            raise SystemExit(f"{name}: cached exit differs from native")
        if workspace_digest(workspace, inputs) != expected_digest:
            raise SystemExit(f"{name}: restored files differ from the native run")

    direct = summarise(direct_samples)
    warm_stats = summarise(warm_samples)
    break_even = None
    if direct["median_ms"] > warm_stats["median_ms"]:
        break_even = (cold_time * 1000 - warm_stats["median_ms"]) / (
            direct["median_ms"] - warm_stats["median_ms"]
        )
    return {
        "workload": name,
        "argv": argv,
        "contract": contract,
        "classification": cold_report.get("classification"),
        "reusable": True,
        "direct": direct,
        "cold": {"trace_ms": round(cold_time * 1000, 3)},
        "warm": warm_stats,
        "hit_share_of_direct": round(100 * warm_stats["median_ms"] / direct["median_ms"], 1),
        "break_even_repetitions": None if break_even is None else round(break_even, 2),
        "session_savings_ms": {
            str(k): round(k * direct["median_ms"] - (cold_time * 1000 + (k - 1) * warm_stats["median_ms"]), 1)
            for k in (2, 5, 10, 50, 200)
        },
    }


def main() -> int:
    global TRACEJIT
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir", default="/tmp/tracejit-phase-v")
    parser.add_argument("--reps", type=int, default=15)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    TRACEJIT = str(Path(args.tracejit).resolve())
    root = Path(args.work_dir)
    shutil.rmtree(root, ignore_errors=True)
    (root / "work").mkdir(parents=True)
    workloads = prepare(root / "work")
    contracts = {
        "cc_o2_compile": "compiler-runtime-v1",
        "sha256sum_8mib": "allocator-entropy-v1",
        "strip_object": "allocator-entropy-v1",
        "md5sum_8mib": "allocator-entropy-v1",
        "sed_rewrite_8mib": "allocator-entropy-v1",
        "wc_bytes_8mib": "allocator-entropy-v1",
    }

    rng = random.Random(args.seed)
    results = []
    for name, argv in workloads.items():
        contract = contracts.get(name)
        cache = Path("/tmp/tracejit-phase-v-cache") / name
        try:
            result = measure(
                name,
                argv,
                root / "work",
                cache,
                args.reps,
                rng,
                contract,
                ("data.bin", "small.bin", "lines.txt", "unit.c"),
            )
        except SystemExit as error:
            result = {"workload": name, "argv": argv, "contract": contract, "error": str(error)}
        results.append(result)
        print(json.dumps(result), flush=True)

    payload = {
        "tracejit": TRACEJIT,
        "seed": args.seed,
        "reps": args.reps,
        "host": {
            "cpus": os.cpu_count(),
            "kernel": os.uname().release,
        },
        "results": results,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

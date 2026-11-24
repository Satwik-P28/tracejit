#!/usr/bin/env python3
"""Warm-hit overhead profile with disjoint intervals.

Phase AA1 established *what* a warm hit costs in total but estimated the
pre-runtime band from a tick-quantised `/proc/self/stat` sample. This harness
measures the pieces TraceJIT already records on disjoint intervals and, for the
band the process cannot see, derives it from a measured total instead of a tick:

* ``startup`` = wall of ``tracejit --version`` — dynamic linking, argument
  parsing, and exit, with no cache open. It is the part of a hit that happens
  before any identity work.
* ``identity_prepare``, ``cache_prepare`` (SQLite open + schema), ``lookup_key``,
  ``sqlite_query``, ``record_decode``, ``guard_validation``, ``cas_restore``,
  ``stdio_replay``, ``decision_persist`` and ``present``: TraceJIT's own phase
  marks, each on its own interval.
* ``runtime_ns``: the core's measured span, from just before candidate lookup to
  just after restoration.
* ``unaccounted`` = wall - (startup + runtime_ns - startup_overlap) ... computed
  only where the intervals are known to be disjoint. The version wall is *not*
  subtracted from the hit: a hit does more than print a version. It is reported
  beside the hit so the reader can see the floor that no cache change can remove.

Every sample is a real hit: the harness asserts ``kind == "Reused"`` and records
the phase file TraceJIT wrote, never a reconstructed one.

Usage::

    python3 benchmarks/phase_ab/hit_profile.py --tracejit target/release/tracejit \
        --workloads readelf-header,cut-columns,gzip-6-stdout,gcc-cc-small-tu \
        --vendor /tmp/ab-vendor --output benchmarks/results/phaseab/hit_profile.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "realworld_v2"))

import corpus  # noqa: E402

CONTRACTS = {
    "native": None,
    "allocator-entropy-v1": "allocator-entropy-v1",
    "compiler-runtime-v1": "compiler-runtime-v1",
}

PHASES = [
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


def wall_ns(argv: list[str], cwd: Path, env: dict) -> int:
    started = time.perf_counter_ns()
    subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False)
    return time.perf_counter_ns() - started


def version_floor(tracejit: Path, repeats: int) -> dict:
    samples = [wall_ns([str(tracejit), "--version"], Path.cwd(), dict(os.environ))
               for _ in range(repeats)]
    return {"samples_ms": [round(value / 1e6, 3) for value in samples],
            "median_ms": round(statistics.median(samples) / 1e6, 3)}


def profile_workload(tracejit: Path, workload, ctx: dict, root: Path, policy: str,
                     samples: int) -> dict:
    workspace = root / "ws"
    cache = root / "cache"
    corpus.prepare(workspace, ctx, workload)
    command = workload.command(workspace, ctx)
    # The inherited environment is part of the execution identity, so every sample — cold and
    # warm — must carry exactly the same instrumentation variables or no lookup can match. The
    # phase path is therefore constant, and the file is removed before each run.
    phase_file = root / "phases.json"
    env = dict(os.environ, TRACEJIT_CACHE_DIR=str(cache), TRACEJIT_PHASE_TIMING="1",
               TRACEJIT_PHASE_TIMING_PATH=str(phase_file), **workload.env)
    prefix = [str(tracejit), "run"]
    contract = CONTRACTS[policy]
    if contract:
        prefix += ["--contract", contract]

    cold_started = time.perf_counter_ns()
    cold = subprocess.run([*prefix, "--", *command], cwd=workspace, env=env, capture_output=True)
    cold_ns = time.perf_counter_ns() - cold_started
    if cold.returncode != 0:
        return {"workload": workload.id, "policy": policy, "error": "cold run failed",
                "stderr": cold.stderr.decode(errors="replace")[:400]}

    hit_samples = []
    for index in range(samples):
        phase_file.unlink(missing_ok=True)
        started = time.perf_counter_ns()
        completed = subprocess.run([*prefix, "--", *command], cwd=workspace, env=env,
                                   capture_output=True)
        elapsed = time.perf_counter_ns() - started
        # Plain mode writes the program's stdout to stdout and the report block to stderr.
        # A hit is asserted from the report's own cache line, never inferred from timing.
        reused = b"cache          HIT" in completed.stderr
        decision_reason = next((line.decode() for line in completed.stderr.splitlines()
                                if line.startswith(b"reuse disabled:")), None)
        phases = {}
        if phase_file.exists():
            phases = json.loads(phase_file.read_text())
        hit_samples.append({
            "wall_ns": elapsed,
            "phases": phases,
            "reused": reused,
            "decision_reason": decision_reason,
            "stdout_bytes": len(completed.stdout),
            "stderr_bytes": len(completed.stderr),
        })

    # Authoritative core span and identity fields, from a separate JSON hit that is never timed:
    # `runtime_ns` is a RunReport field, not part of PhaseTimings, and the timer must not pay for
    # serialising the cached streams (Phase AA1's defect).
    probe = subprocess.run([str(tracejit), "run", "--json", *(["--contract", contract] if contract else []),
                            "--", *command], cwd=workspace, env=env, capture_output=True)
    try:
        probe_report = json.loads(probe.stdout)
    except json.JSONDecodeError:
        probe_report = {}

    def median_phase(name: str):
        values = [sample["phases"].get(name, 0) or 0 for sample in hit_samples]
        return round(statistics.median(values) / 1e6, 3) if values else None

    walls = [sample["wall_ns"] for sample in hit_samples]
    runtimes = [sample["phases"].get("runtime_ns", 0) or 0 for sample in hit_samples]
    reuses = sum(1 for sample in hit_samples if sample["reused"])
    return {
        "workload": workload.id,
        "policy": policy,
        "command": command,
        "cold_ms": round(cold_ns / 1e6, 3),
        "warm_wall_ms": round(statistics.median(walls) / 1e6, 3),
        "warm_wall_ci95": [round(sorted(walls)[max(0, len(walls) // 20)] / 1e6, 3),
                           round(sorted(walls)[-max(1, len(walls) // 20) - 1] / 1e6, 3)],
        "runtime_ms": round(statistics.median(runtimes) / 1e6, 3),
        "calibration": {
            "kind": probe_report.get("kind"),
            "runtime_ns": probe_report.get("runtime_ns"),
            "baseline_runtime_ns": probe_report.get("baseline_runtime_ns"),
            "process_count": probe_report.get("process_count"),
            "dependency_count": probe_report.get("dependency_count"),
        },
        "phases_ms": {name: median_phase(name) for name in PHASES},
        "hit_count": reuses,
        "samples": len(hit_samples),
        "sample_details": [{k: v for k, v in sample.items() if k != "phases"} for sample in hit_samples],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--workloads", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--policy", default="auto")
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args(argv)

    tracejit = Path(args.tracejit).resolve()
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="tracejit-hit-profile-"))
    scratch.mkdir(parents=True, exist_ok=True)
    shared = scratch / "shared"
    shared.mkdir(exist_ok=True)
    ctx = corpus.materialize_shared(shared, Path(args.vendor))
    by_id = corpus.by_id()

    rows = []
    for name in args.workloads.split(","):
        workload = by_id[name.strip()]
        policy = args.policy
        if policy == "auto":
            policy = ("compiler-runtime-v1" if "gcc" in (workload.requires or ())
                      else "allocator-entropy-v1")
        root = scratch / f"{workload.id}-{policy}"
        root.mkdir(exist_ok=True)
        row = profile_workload(tracejit, workload, ctx, root, policy, args.samples)
        rows.append(row)
        print(json.dumps({key: row.get(key) for key in
                          ("workload", "policy", "cold_ms", "warm_wall_ms", "runtime_ms",
                           "hit_count", "samples", "error")}, default=str), flush=True)

    payload = {
        "tracejit": str(tracejit),
        "samples": args.samples,
        "version_floor": version_floor(tracejit, 20),
        "rows": rows,
        "scratch": str(scratch),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["version_floor"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

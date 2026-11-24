#!/usr/bin/env python3
"""Interleaved A/B warm-hit measurement for two TraceJIT binaries.

A before/after comparison taken on one machine but in two separate runs can be
moved by anything else that happened in between, so this harness is paired and
interleaved: for every round it runs A then B (or B then A, alternating) against
the same workload, in twin workspaces, with separate caches, and verifies that
both produced byte-identical stdout and both report a HIT. The reported effect is
the median of paired differences with a bootstrap confidence interval; a
difference whose interval spans zero is reported as indistinguishable from noise.

Usage::

    python3 benchmarks/phase_ab/ab_hits.py --a /tmp/ab-baseline/tracejit \
        --b target/release/tracejit --workloads readelf-header,gzip-6-stdout \
        --vendor /tmp/ab-vendor --output benchmarks/results/phaseab/ab_hits.json
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
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "realworld_v2"))

import corpus  # noqa: E402

POLICIES = {
    "native": None,
    "allocator-entropy-v1": "allocator-entropy-v1",
    "compiler-runtime-v1": "compiler-runtime-v1",
}


def bootstrap_ci(values: list[float], resamples: int = 2000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    generator = random.Random(20261123)
    means = []
    for _ in range(resamples):
        sample = [values[generator.randrange(len(values))] for _ in values]
        means.append(statistics.median(sample))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1])


def prepare(tracejit: Path, workload, ctx: dict, root: Path, policy: str) -> dict:
    workspace = root / "ws"
    cache = root / "cache"
    corpus.prepare(workspace, ctx, workload)
    command = workload.command(workspace, ctx)
    env = dict(os.environ, TRACEJIT_CACHE_DIR=str(cache), **workload.env)
    argv = [str(tracejit), "run"]
    if POLICIES[policy]:
        argv += ["--contract", POLICIES[policy]]
    argv += ["--", *command]
    return {"workspace": workspace, "cache": cache, "command": command, "env": env, "argv": argv}


def timed(argv: list[str], cwd: Path, env: dict) -> tuple[int, bytes, bytes]:
    started = time.perf_counter_ns()
    completed = subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
    return (time.perf_counter_ns() - started, completed.stdout, completed.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, help="baseline binary")
    parser.add_argument("--b", required=True, help="candidate binary")
    parser.add_argument("--workloads", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--policy", default="auto")
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args(argv)

    a, b = Path(args.a).resolve(), Path(args.b).resolve()
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="phaseab-ab-"))
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
        row: dict = {"workload": workload.id, "policy": policy}
        sides, results = {}, {}
        for label, binary in (("a", a), ("b", b)):
            root = scratch / f"{workload.id}-{policy}-{label}"
            root.mkdir(exist_ok=True)
            sides[label] = prepare(binary, workload, ctx, root, policy)
            # Warm the cache and assert the warm run really is a hit before timing anything.
            timed(sides[label]["argv"], sides[label]["workspace"], sides[label]["env"])
            _, stdout, stderr = timed(sides[label]["argv"], sides[label]["workspace"],
                                      sides[label]["env"])
            if b"cache          HIT" not in stderr:
                row["error"] = f"{label} did not hit"
                break
            results[label] = stdout
        if "error" in row:
            rows.append(row)
            print(json.dumps(row))
            continue
        row["stdout_identical"] = results["a"] == results["b"]
        samples = {"a": [], "b": []}
        for index in range(args.rounds):
            order = ["a", "b"] if index % 2 == 0 else ["b", "a"]
            for label in order:
                side = sides[label]
                elapsed, stdout, stderr = timed(side["argv"], side["workspace"], side["env"])
                if b"cache          HIT" not in stderr:
                    row.setdefault("misses", []).append(f"{label}:{index}")
                samples[label].append(elapsed / 1e6)
        differences = [pair_a - pair_b for pair_a, pair_b in zip(samples["a"], samples["b"])]
        low, high = bootstrap_ci(differences)
        row.update({
            "a_median_ms": round(statistics.median(samples["a"]), 3),
            "b_median_ms": round(statistics.median(samples["b"]), 3),
            "median_diff_ms": round(statistics.median(differences), 3),
            "diff_ci95": [round(low, 3), round(high, 3)],
            "a_samples_ms": [round(value, 3) for value in samples["a"]],
            "b_samples_ms": [round(value, 3) for value in samples["b"]],
            "distinguishable": not (low <= 0.0 <= high),
        })
        rows.append(row)
        print(json.dumps({key: row.get(key) for key in
                          ("workload", "policy", "a_median_ms", "b_median_ms",
                           "median_diff_ms", "diff_ci95", "distinguishable",
                           "stdout_identical")}), flush=True)

    payload = {
        "a": {"path": str(a), "sha256": subprocess.run(["sha256sum", str(a)], capture_output=True,
                                                       text=True).stdout.split()[0]},
        "b": {"path": str(b), "sha256": subprocess.run(["sha256sum", str(b)], capture_output=True,
                                                       text=True).stdout.split()[0]},
        "rounds": args.rounds,
        "rows": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

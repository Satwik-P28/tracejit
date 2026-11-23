#!/usr/bin/env python3
"""Measures whether a workload's classification is stable across cold traces.

Phase AA observed `gcc-cc-small-tu` classified `Guarded` in two full-suite runs
and `Nondeterministic` in one, with an identical binary and corpus.  A single
classification per workload cannot distinguish "the harness is inconsistent" from
"the traced program sometimes issues an unguardable observation", and the two
have opposite consequences: the first is a defect to fix, the second is a real
compatibility limit that must be reported.

For each trial this runs the command with a **fresh cache** (so every trial is a
cold trace), the same argv, the same cwd and the same environment, and records
TraceJIT's own classification and first reason.  Any nondeterministic trial is
reported as such; nothing is retried until a favourable classification appears.

Usage::

    python3 benchmarks/realworld_v2/classification_stability.py \
        --tracejit target/release/tracejit \
        --workloads gcc-cc-small-tu --policies compiler-runtime-v1 \
        --repeats 100 --output benchmarks/results/phaseaa1/classification_stability.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
POLICIES = {
    "native": None,
    "allocator-entropy-v1": "allocator-entropy-v1",
    "compiler-runtime-v1": "compiler-runtime-v1",
}


def trial(tracejit: Path, workload, policy: str, ctx: dict, root: Path, index: int) -> dict:
    workspace = root / "workspace"
    cache = root / f"cache-{index}"
    corpus.prepare(workspace, ctx, workload)
    env = dict(os.environ, TRACEJIT_CACHE_DIR=str(cache), **workload.env)
    prefix = [str(tracejit), "run", "--json"]
    contract = POLICIES[policy]
    if contract:
        prefix += ["--contract", contract]
    started = time.perf_counter_ns()
    completed = subprocess.run(
        [*prefix, "--", *workload.command(workspace, ctx)],
        cwd=workspace,
        env=env,
        capture_output=True,
        check=False,
    )
    elapsed = time.perf_counter_ns() - started
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "trial": index,
            "classification": "unparseable-report",
            "eligible": None,
            "reasons": [completed.stdout[:200].decode(errors="replace")],
            "wall_ns": elapsed,
        }
    return {
        "trial": index,
        "classification": report.get("classification"),
        "eligible": report.get("eligible_for_reuse"),
        "first_reason": (report.get("reasons") or [None])[0],
        "kind": report.get("kind"),
        "cache_decision": report.get("cache_decision"),
        "exit_code": report.get("exit_code"),
        "wall_ns": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(REPO / "target" / "release" / "tracejit"))
    parser.add_argument("--workloads", required=True)
    parser.add_argument("--policies", default="compiler-runtime-v1")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", default="")
    parser.add_argument("--vendor", default=str(Path(tempfile.gettempdir()) / "tracejit-realworld-v2" / "vendor"))
    args = parser.parse_args()

    tracejit = Path(args.tracejit).resolve()
    workloads = [item.strip() for item in args.workloads.split(",") if item.strip()]
    policies = [item.strip() for item in args.policies.split(",") if item.strip()]
    unknown = [policy for policy in policies if policy not in POLICIES]
    if unknown:
        parser.error(f"unknown policies {unknown}")
    catalog = corpus.by_id()
    missing = [identifier for identifier in workloads if identifier not in catalog]
    if missing:
        parser.error(f"unknown workloads {missing}")

    root = Path(tempfile.mkdtemp(prefix="tracejit-classification-"))
    ctx = corpus.materialize_shared(root / "shared", Path(args.vendor))
    payload: dict = {
        "tool": str(tracejit),
        "repeats": args.repeats,
        "design": (
            "each trial uses a fresh cache, the same argv, cwd and environment; "
            "every trial is a cold trace and no trial is retried until it looks favourable"
        ),
        "results": [],
    }
    unstable = []
    for identifier in workloads:
        workload = catalog[identifier]
        for policy in policies:
            trials = [
                trial(tracejit, workload, policy, ctx, root, index)
                for index in range(args.repeats)
            ]
            counts: dict[str, int] = {}
            for entry in trials:
                counts[str(entry["classification"])] = counts.get(str(entry["classification"]), 0) + 1
            stable = len(counts) == 1
            entry = {
                "workload_id": identifier,
                "policy": policy,
                "split": workload.split,
                "classification_counts": counts,
                "stable": stable,
                "eligible_trials": sum(1 for item in trials if item["eligible"]),
                "trials": trials,
            }
            if not stable:
                unstable.append(
                    {
                        "workload_id": identifier,
                        "policy": policy,
                        "classification_counts": counts,
                        "verdict": (
                            "the traced program issued an unguardable observation on some runs; "
                            "refusal is correct and the workload must be reported as unstable, "
                            "not retried until eligible"
                        ),
                    }
                )
            payload["results"].append(entry)
            print(f"{identifier:24} {policy:20} {counts} stable={stable}", flush=True)
    payload["unstable"] = unstable
    payload["summary"] = {
        "workload_policy_cells": len(payload["results"]),
        "unstable_cells": len(unstable),
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

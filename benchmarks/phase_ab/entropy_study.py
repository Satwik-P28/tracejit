#!/usr/bin/env python3
"""Separates "the syscall is sometimes absent" from "the tracer sometimes refuses it".

Two independent counters over the same workload, interleaved:

* **presence** — the command runs natively under ``strace`` with only
  ``getrandom`` selected, so no TraceJIT code is in the loop. This counts runs
  in which *any* process in the tree issues ``getrandom``, plus each call's raw
  buffer address and instruction pointer.
* **classification** — the same command runs under TraceJIT with a fresh cache
  (a cold trace) and the declared contract. This counts how often TraceJIT
  refuses to reuse.

If presence is intermittent at the same rate as refusal, the classifier is
agreeing with the program and the instability is the program's own behaviour.
If presence is constant and refusal is not, the admission rule is the
nondeterministic component and must be investigated as a defect.

Usage::

    python3 benchmarks/phase_ab/entropy_study.py \
        --workload gcc-cc-small-tu --trials 200 --vendor /tmp/ab-vendor \
        --output benchmarks/results/phaseab/entropy_study.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "realworld_v2"))

import corpus  # noqa: E402

RAW_RE = re.compile(r"^(?P<pid>\d+)\s+getrandom\((?P<args>.*)\)\s+=\s+(?P<ret>.*)$")


def parse_raw(lines: list[str]) -> list[dict]:
    events = []
    for line in lines:
        match = RAW_RE.match(line.strip())
        if not match:
            continue
        args = match.group("args")
        events.append({"pid": int(match.group("pid")), "args": args, "return": match.group("ret")})
    return events


def presence_trial(workload, ctx, index: int, scratch: Path) -> dict:
    workspace = scratch / f"presence-{index}"
    corpus.prepare(workspace, ctx, workload)
    command = workload.command(workspace, ctx)
    log = scratch / f"presence-{index}.log"
    completed = subprocess.run(
        ["strace", "-f", "-qq", "-e", "trace=getrandom", "-e", "raw=getrandom",
         "-o", str(log), "--", *command],
        cwd=workspace, env=dict(os.environ, **workload.env), capture_output=True, check=False,
    )
    events = parse_raw(log.read_text(errors="replace").splitlines())
    return {
        "trial": index,
        "returncode": completed.returncode,
        "events": events,
        "pids": sorted({event["pid"] for event in events}),
    }


def classification_trial(tracejit: Path, workload, ctx, contract: str, index: int,
                         scratch: Path) -> dict:
    workspace = scratch / f"classify-{index}"
    cache = scratch / f"cache-{index}"
    corpus.prepare(workspace, ctx, workload)
    env = dict(os.environ, TRACEJIT_CACHE_DIR=str(cache), **workload.env)
    prefix = [str(tracejit), "run", "--json"]
    if contract:
        prefix += ["--contract", contract]
    started = time.perf_counter_ns()
    completed = subprocess.run([*prefix, "--", *workload.command(workspace, ctx)],
                               cwd=workspace, env=env, capture_output=True, check=False)
    elapsed = time.perf_counter_ns() - started
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"trial": index, "classification": "unparseable", "wall_ns": elapsed,
                "stdout_head": completed.stdout[:200].decode(errors="replace"),
                "stderr_head": completed.stderr[:500].decode(errors="replace")}
    return {
        "trial": index,
        "classification": report.get("classification"),
        "eligible": report.get("eligible_for_reuse"),
        "kind": report.get("kind"),
        "reasons": report.get("reasons"),
        "effect_counts": report.get("effect_counts"),
        "process_count": report.get("process_count"),
        "dependency_count": report.get("dependency_count"),
        "wall_ns": elapsed,
        "exit_code": completed.returncode,
    }


def summarize_classification(records: list[dict]) -> dict:
    counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    walls = []
    for record in records:
        counts[str(record.get("classification"))] = counts.get(str(record.get("classification")), 0) + 1
        for reason in record.get("reasons") or []:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        walls.append(record["wall_ns"])
    return {
        "classifications": counts,
        "reasons": dict(sorted(reason_counts.items(), key=lambda item: -item[1])),
        "wall_ms_median": round(statistics.median(walls) / 1e6, 3) if walls else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", default="gcc-cc-small-tu")
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--contract", default="compiler-runtime-v1")
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--scratch", default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    tracejit = Path(args.tracejit).resolve()
    workload = corpus.by_id()[args.workload]
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="tracejit-entropy-study-"))
    scratch.mkdir(parents=True, exist_ok=True)
    shared = scratch / "shared"
    shared.mkdir(exist_ok=True)
    ctx = corpus.materialize_shared(shared, Path(args.vendor))

    presence, classification = [], []
    started = time.time()
    for index in range(args.trials):
        presence.append(presence_trial(workload, ctx, index, scratch))
        classification.append(classification_trial(tracejit, workload, ctx, args.contract, index, scratch))
        if (index + 1) % 25 == 0:
            with_events = sum(1 for record in presence if record["events"])
            refused = sum(1 for record in classification
                          if record.get("classification") not in {"Guarded", "Proven"})
            print(f"{index + 1}/{args.trials}: presence {with_events}, refused {refused}, "
                  f"{time.time() - started:.0f}s", flush=True)

    presence_runs = sum(1 for record in presence if record["events"])
    # A tcache seed that glibc issues once per process: group by pid to count processes,
    # and by address to confirm the destination is constant.
    seeds = [event for record in presence for event in record["events"]]
    addresses: dict[str, int] = {}
    for event in seeds:
        # raw getrandom prints "0xADDR, 8, GRND_NONBLOCK"
        address = event["args"].split(",")[0].strip()
        addresses[address] = addresses.get(address, 0) + 1
    payload = {
        "workload": args.workload,
        "trials": args.trials,
        "contract": args.contract,
        "tracejit": str(tracejit),
        "tracejit_sha256": hashlib.sha256(tracejit.read_bytes()).hexdigest(),
        "presence": {
            "runs_with_getrandom": presence_runs,
            "runs_without_getrandom": args.trials - presence_runs,
            "rate": round(presence_runs / args.trials, 4),
            "total_events": len(seeds),
            "distinct_pids_per_run": sorted({len(record["pids"]) for record in presence}),
            "distinct_buffer_addresses": len(addresses),
            "records": presence,
        },
        "classification": {
            **summarize_classification(classification),
            "refused": sum(1 for record in classification
                           if record.get("classification") not in {"Guarded", "Proven"}),
            "records": classification,
        },
        "cross_tab": {
            "presence_and_refused": sum(
                1 for p, c in zip(presence, classification)
                if p["events"] and c.get("classification") not in {"Guarded", "Proven"}),
            "presence_and_accepted": sum(
                1 for p, c in zip(presence, classification)
                if p["events"] and c.get("classification") in {"Guarded", "Proven"}),
            "no_presence_and_refused": sum(
                1 for p, c in zip(presence, classification)
                if not p["events"] and c.get("classification") not in {"Guarded", "Proven"}),
            "no_presence_and_accepted": sum(
                1 for p, c in zip(presence, classification)
                if not p["events"] and c.get("classification") in {"Guarded", "Proven"}),
        },
        "elapsed_s": round(time.time() - started, 1),
        "scratch": str(scratch),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "presence_rate": payload["presence"]["rate"],
        "runs_without_getrandom": payload["presence"]["runs_without_getrandom"],
        "classifications": payload["classification"]["classifications"],
        "cross_tab": payload["cross_tab"],
        "reasons": payload["classification"]["reasons"],
    }, indent=2))
    if not args.keep:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

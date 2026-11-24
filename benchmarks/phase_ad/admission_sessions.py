#!/usr/bin/env python3
"""Phase AD: total cost of a realistic mixed session under each admission policy.

The metric is the wall time of the whole session, not the HIT rate.  A policy that traces a
command six times and hits twice can be worse than one that never traces it, and a policy
that refuses an expensive repeated command loses savings it could have had.

The session deliberately mixes the classes Part IV asks for:

* expensive repeated compression (bzip2 -9 on 2 MiB, output file deleted each time),
* a cheap repeated filter (gzip -n -c of 256 KiB text to stdout),
* cheap inspection (sha256sum of a small file),
* a large deterministic text transformation (sed over 200k lines),
* commands whose input changes before every invocation,
* a permanently ineligible command (a clock read),
* a one-shot expensive command with no repetition.

Arms: direct execution, ``--admission never``, ``always``, the production ``auto``, and
Phase 2H's ``auto-v1``.  The retrospective oracle is computed from the measured per-step
costs of the ``always`` and direct arms: it may use a HIT wherever one was actually produced,
but it pays direct execution everywhere else.  It is an upper bound that knows the future and
is not attainable online.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "realworld_v2"))

import runner  # noqa: E402

CONTRACT = "allocator-entropy-v1"


def build_workspace(root: Path) -> None:
    root.mkdir(parents=True)
    state = 0x2545F4914F6CDD1D
    blob = bytearray()
    while len(blob) < (2 << 20):
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        blob.extend(state.to_bytes(8, "little"))
    (root / "blob.bin").write_bytes(bytes(blob))
    (root / "blob2.bin").write_bytes(bytes(blob)[:1 << 20])
    (root / "small.bin").write_bytes(b"pinned small input\n" * 64)
    (root / "lines.txt").write_bytes(
        b"".join(f"row-{i:07d} key={(i * 7919) % 100003}\n".encode() for i in range(200_000))
    )
    (root / "text.txt").write_bytes(b"upstream text line with some words\n" * 8000)


def text_variant(root: Path, index: int) -> None:
    (root / "text.txt").write_bytes(
        b"".join(f"variant {index} line {i}\n".encode() for i in range(12_000))
    )


def steps() -> list[dict]:
    """The session script. ``setup`` runs immediately before the step is timed."""

    plan = []
    for _ in range(5):
        plan.append({"label": "bzip2-9-2MiB", "argv": ["bzip2", "-9", "-k", "-f", "blob.bin"],
                     "outputs": ["blob.bin.bz2"], "setup": None})
    for _ in range(6):
        plan.append({"label": "gzip-text-stdout", "argv": ["gzip", "-9", "-n", "-c", "text.txt"],
                     "outputs": [], "setup": None})
    for _ in range(4):
        plan.append({"label": "sha256sum-small", "argv": ["sha256sum", "small.bin"],
                     "outputs": [], "setup": None})
    for _ in range(3):
        plan.append({"label": "sed-200k", "argv": ["sed", "s/key=/k=/g", "lines.txt"],
                     "outputs": [], "setup": None})
    for index in range(3):
        plan.append({"label": "gzip-changing-input",
                     "argv": ["gzip", "-9", "-n", "-c", "text.txt"], "outputs": [],
                     "setup": lambda root, index=index: text_variant(root, index)})
    for _ in range(2):
        plan.append({"label": "clock-ineligible",
                     "argv": ["python3", "-c", "import time; print(time.time_ns())"],
                     "outputs": [], "setup": None})
    plan.append({"label": "bzip2-oneshot", "argv": ["bzip2", "-9", "-k", "-f", "blob2.bin"],
                 "outputs": ["blob2.bin.bz2"], "setup": None})
    return plan


def run_traced(tracejit: Path, argv: list[str], ws: Path, env: dict, admission: str):
    """`tracejit run` with an explicit admission policy, decision read from plain stderr."""

    prefix = [str(tracejit), "run", "--contract", CONTRACT, "--admission", admission]
    completed = subprocess.run(
        [*prefix, "--", *argv], cwd=ws, env=env, capture_output=True, check=False
    )
    return completed, runner.parse_plain_decision(completed.stderr)


def prepare(root: Path, step: dict) -> None:
    for name in step["outputs"]:
        (root / name).unlink(missing_ok=True)
    if step["setup"]:
        step["setup"](root)


def run_arm(arm: str, root: Path, tracejit: Path, base_env: dict, plan: list[dict]) -> dict:
    shutil.rmtree(root, ignore_errors=True)
    build_workspace(root)
    cache = root.parent / "cache"
    shutil.rmtree(cache, ignore_errors=True)

    env = dict(base_env)
    records = []
    started = time.perf_counter_ns()
    for step in plan:
        prepare(root, step)
        if arm == "direct":
            at = time.perf_counter_ns()
            completed = subprocess.run(step["argv"], cwd=root, env=env, capture_output=True, check=False)
            elapsed = time.perf_counter_ns() - at
            records.append({"label": step["label"], "ns": elapsed, "hit": False,
                            "decision": "Executed", "exit": completed.returncode})
            continue
        traced_env = runner.cache_env(dict(env), cache)
        at = time.perf_counter_ns()
        completed, decision = run_traced(tracejit, step["argv"], root, traced_env, arm)
        elapsed = time.perf_counter_ns() - at
        records.append({
            "label": step["label"],
            "ns": elapsed,
            "hit": runner.is_hit(decision),
            "decision": decision.get("cache_decision"),
            "exit": completed.returncode,
        })
    total = time.perf_counter_ns() - started
    cache_bytes = sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()) if cache.exists() else 0
    return {"arm": arm, "total_ns": total, "records": records, "cache_bytes": cache_bytes,
            "hits": sum(1 for r in records if r["hit"])}


def oracle(direct: dict, always: dict) -> dict:
    """Retrospective per-step minimum, using only HITs the always arm actually produced."""

    total = 0
    for direct_step, always_step in zip(direct["records"], always["records"]):
        if always_step["hit"]:
            total += min(direct_step["ns"], always_step["ns"])
        else:
            total += direct_step["ns"]
    return {"arm": "oracle", "total_ns": total,
            "hits": sum(1 for r in always["records"] if r["hit"])}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=runner.REPO / ".phasead-admission")
    parser.add_argument("--output", type=Path,
                        default=HERE.parent / "results/phasead/admission_sessions.json")
    parser.add_argument("--arms", default="direct,never,always,auto,auto-v1")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args(argv)

    tracejit = args.tracejit.resolve()
    plan = steps()
    base_env = dict(os.environ)
    base_env.pop("TRACEJIT_CACHE_DIR", None)
    payload = {"session": [{"label": s["label"], "argv": s["argv"]} for s in plan], "runs": []}
    shutil.rmtree(args.scratch, ignore_errors=True)

    for repeat in range(args.repeats):
        results = {}
        for arm in [a for a in args.arms.split(",") if a]:
            result = run_arm(arm, args.scratch / f"{repeat}-{arm}" / "ws", tracejit, base_env, plan)
            results[arm] = result
            payload["runs"].append(result)
            print(f"repeat {repeat} {arm:8s} total={result['total_ns']/1e6:8.1f}ms "
                  f"hits={result['hits']:2d} cache={result['cache_bytes']/1e6:.2f}MB", flush=True)
        if "direct" in results and "always" in results:
            payload.setdefault("oracle", []).append(oracle(results["direct"], results["always"]))

    # Median over repeats per arm, plus per-step decisions from the last repeat.
    summary = {}
    for arm in {r["arm"] for r in payload["runs"]}:
        totals = sorted(r["total_ns"] for r in payload["runs"] if r["arm"] == arm)
        summary[arm] = {"median_total_ns": totals[len(totals) // 2], "totals_ns": totals}
    payload["summary"] = summary
    shutil.rmtree(args.scratch, ignore_errors=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

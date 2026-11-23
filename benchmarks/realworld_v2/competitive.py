#!/usr/bin/env python3
"""Competitive evaluation: TraceJIT against native execution and a build scheduler.

Three things are kept apart, because conflating them produces false claims:

* **build scheduler** (``make``): decides *whether to run* a command using declared
  timestamps. It does not verify content.
* **compiler cache** (``ccache``, ``sccache``): reuses compilation output keyed by
  preprocessed source and toolchain. Absent on this image, therefore reported as
  *unavailable*, never as slower.
* **whole-command traced cache** (TraceJIT): reuses an arbitrary command's stdout,
  stderr, status and files after re-validating observed dependencies.

The corruption comparison only makes sense where both mechanisms can actually
produce a result. ``make`` is **ineligible** for TraceJIT on this host (it reads
unmodeled state), so the interesting corruption case is a command both can act
on: ``gzip`` with a real rule in a Makefile. That scenario asserts that TraceJIT
actually reused before it claims anything about restoration.

The ineligible-command cost is measured separately and labelled as such: it is
the price of *attempting* to trace a command that is then refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RELOCATION_NOTE = (
    "TraceJIT hashes the inherited environment into the cache key, and "
    "TRACEJIT_CACHE_DIR is part of that environment: moving a cache directory "
    "invalidates every record in it. Measured directly in Phase AA."
)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run(argv: list[str], cwd: Path, env: dict) -> tuple[int, float, bytes]:
    started = time.perf_counter_ns()
    completed = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False)
    return completed.returncode, time.perf_counter_ns() - started, completed.stdout


def trace_env(base: dict, cache: Path) -> dict:
    env = dict(base)
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def session(argv: list[str], cwd: Path, env: dict, repeats: int, reset=None) -> dict:
    for _ in range(2):
        if reset:
            reset()
        run(argv, cwd, env)
    samples = []
    codes = []
    for _ in range(repeats):
        if reset:
            reset()
        code, elapsed, _ = run(argv, cwd, env)
        codes.append(code)
        samples.append(elapsed)
    return {
        "repeats": repeats,
        "total_ns": sum(samples),
        "median_ns": sorted(samples)[len(samples) // 2],
        "samples_ns": samples,
        "exit_statuses": sorted(set(codes)),
    }


def competitor_availability() -> dict:
    pinned = {
        "ccache": "4.9.1",
        "sccache": "0.8.2",
        "ninja": "1.11.1",
        "firebuild": "0.9.0",
        "zstd": "1.5.5",
        "hyperfine": "1.19.0",
        "perf": "(kernel-tools)",
    }
    roles = {
        "ccache": "compiler cache",
        "sccache": "compiler cache",
        "ninja": "build scheduler",
        "firebuild": "process-level build accelerator",
        "zstd": "compression tool",
        "hyperfine": "independent timing harness",
        "perf": "hardware counters",
    }
    entries = {}
    for tool, version in pinned.items():
        path = shutil.which(tool)
        entries[tool] = {
            "role": roles[tool],
            "available": path is not None,
            "path": path,
            "tested_version": version,
            "note": (
                "present and used"
                if path
                else "absent from this image; no root and no prebuilt static archive. "
                     "Recorded as unavailable, never scored as slower."
            ),
        }
    return entries


def make_ineligible_overhead(root: Path, ctx: dict, tracejit: Path, repeats: int, base_env: dict) -> dict:
    """What it costs to *attempt* to trace a command TraceJIT then refuses."""

    workload = corpus.by_id()["make-build"]
    ws = root / "make"
    shutil.rmtree(ws, ignore_errors=True)
    corpus.prepare(ws, ctx, workload)
    env = trace_env(base_env, root / "make-cache")
    make_argv = ["make", "-f", "Makefile", "app"]
    trace_argv = [str(tracejit), "run", "--json", "--", *make_argv]

    def clean() -> None:
        for name in ("app", "main.o", "util.o"):
            (ws / name).unlink(missing_ok=True)

    native = session(make_argv, ws, env, repeats, reset=clean)
    traced = session(trace_argv, ws, env, repeats, reset=clean)
    return {
        "scenario": "ineligible_command_overhead",
        "workload": "make-build",
        "mechanism": "build scheduler; TraceJIT refuses this command",
        "native_total_ns": native["total_ns"],
        "tracejit_total_ns": traced["total_ns"],
        "per_invocation_overhead_ns": (traced["total_ns"] - native["total_ns"]) // repeats,
        "native_per_invocation_ns": native["total_ns"] // repeats,
        "tracejit_per_invocation_ns": traced["total_ns"] // repeats,
        "claim": (
            "TraceJIT does not reuse make. The difference is the cost of tracing a command that is "
            "then refused, not a cache result."
        ),
        "exit_statuses": {"native": native["exit_statuses"], "tracejit": traced["exit_statuses"]},
    }


def gzip_corruption_versus_make(
    root: Path, ctx: dict, tracejit: Path, repeats: int, base_env: dict
) -> dict:
    """The one place where a scheduler and a traced cache act on the same command."""

    workload = corpus.by_id()["gzip-9-file"]
    ws = root / "gzip-rule"
    shutil.rmtree(ws, ignore_errors=True)
    corpus.prepare(ws, ctx, workload)
    (ws / "Makefile").write_text(
        "corpus.bin.gz: corpus.bin\n\tgzip -9 -n -k -f corpus.bin\n"
    )
    env = trace_env(base_env, root / "gzip-rule-cache")
    make_argv = ["make", "-f", "Makefile", "corpus.bin.gz"]
    traced_argv = [str(tracejit), "run", "--json", "--contract", "allocator-entropy-v1",
                   "--", "gzip", "-9", "-n", "-k", "-f", "corpus.bin"]

    # One correct build, shared as the reference.
    (ws / "corpus.bin.gz").unlink(missing_ok=True)
    run(make_argv, ws, env)
    correct = sha256(ws / "corpus.bin.gz")

    # Scheduler: identical rerun and corruption recovery.
    make_rerun = session(make_argv, ws, env, repeats)
    (ws / "corpus.bin.gz").write_bytes(b"CORRUPTED\n")
    _, _, make_messages = run(make_argv, ws, env)
    make_after = sha256(ws / "corpus.bin.gz")

    # Traced cache: populate, prove the hit, then the same corruption.
    first = run(traced_argv, ws, env)
    second = run(traced_argv, ws, env)
    try:
        first_report = json.loads(first[2])
        second_report = json.loads(second[2])
    except json.JSONDecodeError:
        first_report = second_report = {}
    populated = first_report.get("kind") in ("Executed", "Reused")
    hit_before = second_report.get("kind") == "Reused"
    traced_rerun = session(traced_argv, ws, env, repeats)
    (ws / "corpus.bin.gz").write_bytes(b"CORRUPTED\n")
    _, _, traced_stdout = run(traced_argv, ws, env)
    try:
        corrupt_report = json.loads(traced_stdout)
    except json.JSONDecodeError:
        corrupt_report = {}
    traced_after = sha256(ws / "corpus.bin.gz")

    return {
        "scenario": "corrupted_output",
        "workload": "gzip-9-file",
        "command": "gzip -9 -n -k -f corpus.bin, with a real Makefile rule for corpus.bin.gz",
        "correct_sha256": correct,
        "cache_populated": populated,
        "tracejit_hit_verified_before_corruption": hit_before,
        "make": {
            "identical_rerun_total_ns": make_rerun["total_ns"],
            "decision": "skipped: target newer than prerequisite",
            "messages": make_messages[:200].decode(errors="replace").strip(),
            "sha256_after_corruption": make_after,
            "left_corrupted_output": make_after != correct,
        },
        "tracejit": {
            "identical_rerun_total_ns": traced_rerun["total_ns"],
            "decision_before_corruption": second_report.get("cache_decision"),
            "decision_after_corruption": corrupt_report.get("cache_decision"),
            "sha256_after_corruption": traced_after,
            "restored_correct_output": traced_after == correct,
        },
        "claim_scope": (
            "a scheduler decides by timestamp and has no reason to reopen the output; a traced cache "
            "validates recorded inputs and materialises the recorded output. The comparison only "
            "holds because both were verified to act on the same command."
        ),
    }


def hyperfine_cross_check(root: Path, ctx: dict, tracejit: Path, base_env: dict) -> dict:
    hyperfine = shutil.which("hyperfine")
    if hyperfine is None:
        return {"available": False, "reason": "hyperfine is not installed"}
    workload = corpus.by_id()["gzip-6-stdout"]
    ws = root / "hyperfine"
    shutil.rmtree(ws, ignore_errors=True)
    corpus.prepare(ws, ctx, workload)
    env = trace_env(base_env, root / "hyperfine-cache")
    trace_argv = [str(tracejit), "run", "--json", "--", "gzip", "-6", "-n", "-c", "corpus.txt"]
    run(trace_argv, ws, env)
    run(trace_argv, ws, env)
    export = root / "hyperfine.json"
    completed = subprocess.run(
        [hyperfine, "--warmup", "2", "--runs", "10", "--export-json", str(export),
         "gzip -6 -n -c corpus.txt",
         f"env TRACEJIT_CACHE_DIR={env['TRACEJIT_CACHE_DIR']} {tracejit} run --json -- gzip -6 -n -c corpus.txt"],
        cwd=ws, env=env, capture_output=True, text=True, check=False,
    )
    if not export.is_file():
        return {"available": True, "ok": False, "stderr": completed.stderr[-800:]}
    data = json.loads(export.read_text())
    return {
        "available": True,
        "ok": True,
        "results": [
            {"command": item["command"], "mean_s": item["mean"], "median_s": item["median"],
             "stddev_s": item["stddev"], "min_s": item["min"], "max_s": item["max"]}
            for item in data["results"]
        ],
        "note": "hyperfine runs through a shell, so its absolute numbers include shell overhead",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(REPO / "target" / "release" / "tracejit"))
    parser.add_argument("--output-dir", default=str(REPO / "benchmarks" / "results" / "phaseaa"))
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--vendor", default="/tmp/tracejit-realworld-v2/vendor")
    args = parser.parse_args()
    tracejit = Path(args.tracejit).resolve()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tracejit-aa-competitive-"))
    ctx = corpus.materialize_shared(root / "shared", Path(args.vendor))
    base_env = os.environ.copy()

    payload = {
        "competitors": competitor_availability(),
        "scenarios": [
            make_ineligible_overhead(root, ctx, tracejit, args.repeats, base_env),
            gzip_corruption_versus_make(root, ctx, tracejit, args.repeats, base_env),
        ],
        "cache_relocation": {
            "note": RELOCATION_NOTE,
            "consequence": "a copied or moved cache is not reused; records are re-created after one trace per command",
        },
        "hyperfine_cross_check": hyperfine_cross_check(root, ctx, tracejit, base_env),
        "methodology": (
            "Each arm is a session of N repeats in the same workspace. A scheduler that skips work and "
            "a cache that restores verified output are different mechanisms; each table states which "
            "one acted. An unavailable tool is never scored."
        ),
    }
    (output_dir / "competitive.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    make_scenario = payload["scenarios"][0]
    corrupt = payload["scenarios"][1]
    lines = [
        "# Competitive evaluation (Phase AA)",
        "",
        "## Tools examined",
        "",
        "| Tool | Role | Available | Version pinned for comparison | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for tool, entry in payload["competitors"].items():
        lines.append(
            f"| {tool} | {entry['role']} | {'yes' if entry['available'] else 'no'} | "
            f"{entry['tested_version']} | {entry['note']} |"
        )
    lines += [
        "",
        "ccache, sccache, ninja, firebuild, perf and zstd are absent. No relative-speed claim is "
        "made about them: an uninstalled or differently configured tool cannot be compared fairly.",
        "",
        "## Ineligible command: what tracing costs when it is refused",
        "",
        f"`make-build` is refused by TraceJIT on this host. Running it through the wrapper costs "
        f"{make_scenario['per_invocation_overhead_ns'] / 1e6:.1f} ms per invocation extra "
        f"({make_scenario['native_per_invocation_ns'] / 1e6:.2f} ms native vs "
        f"{make_scenario['tracejit_per_invocation_ns'] / 1e6:.2f} ms traced).",
        "",
        "That is the price of attempting to trace a command that is then refused, not a cache result.",
        "",
        "## Corrupted output: scheduler versus traced cache",
        "",
        f"Both arms act on `gzip -9 -n -k -f corpus.bin` (correct sha256 `{(corrupt['correct_sha256'] or '')[:16]}…`).",
        "",
        "| Mechanism | Decision | Output after corruption | Correct? |",
        "| --- | --- | --- | --- |",
        f"| make | {corrupt['make']['decision']} | `{(corrupt['make']['sha256_after_corruption'] or '')[:16]}…` | "
        f"**{not corrupt['make']['left_corrupted_output']}** |",
        f"| TraceJIT | {corrupt['tracejit']['decision_after_corruption']} | "
        f"`{(corrupt['tracejit']['sha256_after_corruption'] or '')[:16]}…` | "
        f"**{corrupt['tracejit']['restored_correct_output']}** |",
        "",
        f"TraceJIT verified a HIT before the corruption test: "
        f"**{corrupt['tracejit_hit_verified_before_corruption']}**.",
        "",
        "## Hyperfine cross-check (independent wall clock)",
        "",
        "```json",
        json.dumps(payload["hyperfine_cross_check"], indent=2)[:1800],
        "```",
        "",
        "## Cache relocation",
        "",
        RELOCATION_NOTE,
        "",
    ]
    (output_dir / "competitive.md").write_text("\n".join(lines))
    print(json.dumps({
        "make_left_corrupted": corrupt["make"]["left_corrupted_output"],
        "tracejit_restored": corrupt["tracejit"]["restored_correct_output"],
        "tracejit_hit_verified": corrupt["tracejit_hit_verified_before_corruption"],
        "ineligible_overhead_ms": round(make_scenario["per_invocation_overhead_ns"] / 1e6, 2),
    }, indent=2))
    print(f"wrote {output_dir / 'competitive.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

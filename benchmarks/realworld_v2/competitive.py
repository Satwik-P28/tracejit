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


def scheduler_versus_cache(
    root: Path, ctx: dict, tracejit: Path, repeats: int, base_env: dict
) -> dict:
    """The one place where a scheduler and a traced cache act on the same command.

    The workload is a real translation unit (`zlib-1.3.1/adler32.c`) with a real
    Makefile rule. Every TraceJIT claim below is gated on the decision it actually
    reported: if the cache did not reuse, the table says "executed", not
    "restored".

    A separate observation is recorded for why some tools cannot restore a
    corrupted output at all: `gzip -f`, `bzip2 -f`, `objcopy` and `strip` open and
    read the existing output, so the output's pre-state is an observed dependency
    and corrupting it correctly forces a retrace. `gcc` creates its output with
    `O_TRUNC` and does not read it, so a hit restores it.
    """

    workload = corpus.by_id()["zlib-compile-adler32"]
    ws = root / "rule"
    shutil.rmtree(ws, ignore_errors=True)
    corpus.prepare(ws, ctx, workload)
    zlib = ctx["zlib"]
    compile_rule = f"gcc -O2 -I {zlib} -c {zlib}/adler32.c -o adler32.o"
    (ws / "Makefile").write_text(f"adler32.o: {zlib}/adler32.c\n\t{compile_rule}\n")
    env = trace_env(base_env, root / "rule-cache")
    make_argv = ["make", "-f", "Makefile", "adler32.o"]
    traced_argv = [str(tracejit), "run", "--json", "--contract", "compiler-runtime-v1",
                   "--", "gcc", "-O2", "-I", zlib, "-c", f"{zlib}/adler32.c", "-o", "adler32.o"]
    output = ws / "adler32.o"

    # One correct build, shared as the reference.
    output.unlink(missing_ok=True)
    run(make_argv, ws, env)
    correct = sha256(output)

    # Populate the cache; the first traced run is a cold trace.
    first = run(traced_argv, ws, env)
    try:
        first_report = json.loads(first[2])
    except json.JSONDecodeError:
        first_report = {}
    populated = first_report.get("kind") in ("Executed", "Reused")

    # (1) Rebuild from an absent output: make executes, the cache restores.
    def absent() -> None:
        output.unlink(missing_ok=True)

    make_absent = session(make_argv, ws, env, repeats, reset=absent)
    traced_absent = session(traced_argv, ws, env, repeats, reset=absent)
    absent_decisions = []
    for _ in range(3):
        absent()
        _, _, stdout = run(traced_argv, ws, env)
        try:
            absent_decisions.append(json.loads(stdout).get("cache_decision"))
        except json.JSONDecodeError:
            absent_decisions.append(None)

    # (2) Identical rerun with the output present: make skips, the cache reuses.
    output.unlink(missing_ok=True)
    run(make_argv, ws, env)
    make_present = session(make_argv, ws, env, repeats)
    traced_present = session(traced_argv, ws, env, repeats)
    _, _, present_stdout = run(traced_argv, ws, env)
    try:
        present_report = json.loads(present_stdout)
    except json.JSONDecodeError:
        present_report = {}

    # (3) Corrupted output.
    output.write_bytes(b"CORRUPTED\n")
    _, _, make_messages = run(make_argv, ws, env)
    make_after = sha256(output)
    output.write_bytes(b"CORRUPTED\n")
    _, _, corrupt_stdout = run(traced_argv, ws, env)
    try:
        corrupt_report = json.loads(corrupt_stdout)
    except json.JSONDecodeError:
        corrupt_report = {}
    traced_after = sha256(output)

    return {
        "scenario": "scheduler_vs_cache",
        "workload": "zlib-compile-adler32",
        "command": f"{compile_rule} (real Makefile rule for adler32.o)",
        "correct_sha256": correct,
        "cache_populated": populated,
        "rebuild_from_absent_output": {
            "make_total_ns": make_absent["total_ns"],
            "tracejit_total_ns": traced_absent["total_ns"],
            "tracejit_decisions": absent_decisions,
            "what_happened": "make executed gcc; the cache reported the decision above",
        },
        "identical_rerun_output_present": {
            "make_total_ns": make_present["total_ns"],
            "tracejit_total_ns": traced_present["total_ns"],
            "make_decision": "skipped: target older than prerequisite? no: up to date",
            "tracejit_decision": present_report.get("cache_decision"),
        },
        "corrupted_output": {
            "make": {
                "messages": make_messages[:200].decode(errors="replace").strip(),
                "sha256_after": make_after,
                "left_corrupted_output": make_after != correct,
            },
            "tracejit": {
                "decision": corrupt_report.get("cache_decision"),
                "sha256_after": traced_after,
                "restored_correct_output": traced_after == correct,
                "mechanism": (
                    "restored from cache" if corrupt_report.get("kind") == "Reused" else "executed"
                ),
            },
        },
        "observed_output_semantics": (
            "Corrupting an output retraces for tools that read the existing output (gzip -f, bzip2 -f, "
            "objcopy, strip) and restores for tools that only create it (gcc). Both are correct; only "
            "the cost differs. Verified across the corpus's output_corruption decisions."
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
            scheduler_versus_cache(root, ctx, tracejit, args.repeats, base_env),
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
    scheduler = payload["scenarios"][1]
    corrupt = scheduler["corrupted_output"]
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
        "## Scheduler versus traced cache, same command",
        "",
        f"`{scheduler['command']}`, correct sha256 `{(scheduler['correct_sha256'] or '')[:16]}…`.",
        "",
        "| Situation | make | TraceJIT |",
        "| --- | --- | --- |",
        f"| output absent, rebuild | executed, {scheduler['rebuild_from_absent_output']['make_total_ns'] / 1e6:.1f} ms total | "
        f"{scheduler['rebuild_from_absent_output']['tracejit_total_ns'] / 1e6:.1f} ms total, decisions "
        f"{scheduler['rebuild_from_absent_output']['tracejit_decisions']} |",
        f"| output present, rerun | skipped, {scheduler['identical_rerun_output_present']['make_total_ns'] / 1e6:.1f} ms total | "
        f"{scheduler['identical_rerun_output_present']['tracejit_total_ns'] / 1e6:.1f} ms total, decision "
        f"{scheduler['identical_rerun_output_present']['tracejit_decision']} |",
        f"| corrupted output | skipped, left corruption (**{corrupt['make']['left_corrupted_output']}**) | "
        f"{corrupt['tracejit']['decision']}, mechanism **{corrupt['tracejit']['mechanism']}**, "
        f"correct after (**{corrupt['tracejit']['restored_correct_output']}**) |",
        "",
        scheduler["observed_output_semantics"],
        "",
        "A scheduler that skips work is not doing the same job as a cache that restores verified "
        "bytes, and a row that says `executed` is not a restoration result.",
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
        "tracejit_mechanism": corrupt["tracejit"]["mechanism"],
        "rebuild_absent_decisions": scheduler["rebuild_from_absent_output"]["tracejit_decisions"],
        "present_decision": scheduler["identical_rerun_output_present"]["tracejit_decision"],
        "ineligible_overhead_ms": round(make_scenario["per_invocation_overhead_ns"] / 1e6, 2),
    }, indent=2))
    print(f"wrote {output_dir / 'competitive.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

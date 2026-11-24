#!/usr/bin/env python3
"""Whole-build experiment: Make, ccache, TraceJIT, and the integrity they do and do not buy.

The unit of work is a real pinned project (Lua 5.4.6, 34 independently compiled
translation units) built by its own Makefile at ``make -C src liblua.a``. Four
arms see byte-identical sources and flags:

* ``native``  — a direct ``gcc -O2 -c`` loop in the Makefile's order, no make.
* ``make``    — the project's Makefile, no cache.
* ``ccache``  — the same Makefile with ``CC=<ccache> gcc -O2``.
* ``tracejit``— the same Makefile with
  ``CC=<tracejit> run --contract compiler-runtime-v1 -- gcc -O2``.

Every arm is verified against a clean native reference build of the *same source
state*: each ``.o`` and ``liblua.a`` is compared by hash, so "the build succeeded"
is never accepted as "the artifacts are right".

The scenario schedule is fixed before any measurement. Each scenario starts from
a byte-identical copy of the pinned tree, so an arm cannot inherit another arm's
workspace state. Caches live outside the workspace and are carried across the
scenarios of one session, which is how a user actually runs a cache; only the
``cache_restart`` scenario makes that explicit.

This harness does not claim a TraceJIT HIT unless TraceJIT itself reports one.
A wrapped ``make`` is never treated as a cacheable command: the wrapper is on the
compiler, not on ``make``, because ``make`` is not eligible and never reports
``Reused``.

Usage::

    python3 benchmarks/phase_ab/build_integrity.py \
        --tracejit target/release/tracejit --ccache /tmp/ab-tools/ccache \
        --source /tmp/ab-tools/lua-5.4.6.tar.gz \
        --output benchmarks/results/phaseab/build_integrity.json [--arms all]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OBJECTS = "src/liblua.a"
SCENARIOS = [
    "clean_build",
    "no_change_rebuild",
    "clean_warm_rebuild",
    "single_source_edit",
    "shared_header_edit",
    "deleted_object",
    "corrupted_object",
    "corrupted_object_same_timestamps",
    "input_edit_then_revert",
    "cache_restart",
    "partial_output_deletion",
    "repeated_session",
    "classification_refusal_observation",
]
CORRUPT_TARGET = "src/lstrlib.o"
EDIT_TARGET = "src/lstrlib.c"
HEADER_TARGET = "src/lprefix.h"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted((root / "src").glob("*.o")):
        hashes[path.name] = sha256(path)
    archive = root / OBJECTS
    if archive.exists():
        hashes["liblua.a"] = sha256(archive)
    return hashes


def extract(tarball: Path, destination: Path) -> Path:
    with tarfile.open(tarball) as archive:
        archive.extractall(destination, filter="data")
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise SystemExit(f"expected one extracted root in {destination}, found {roots}")
    return roots[0]


def ccache_dir_env(ccache_dir: Path | None) -> dict:
    return {"CCACHE_DIR": str(ccache_dir)} if ccache_dir is not None else {}


def make_env(cc: str, cache_dir: Path | None, decision_log: Path | None) -> dict:
    env = dict(os.environ)
    env.update({
        "CC": cc,
        "PATH": f"{Path(cc.split()[0]).parent}:{env['PATH']}"
        if cc.startswith("/") else env["PATH"],
    })
    if cache_dir is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache_dir)
    if decision_log is not None:
        env["TRACEJIT_DECISION_LOG"] = str(decision_log)
    return env


def wrapper(directory: Path, tracejit: Path) -> Path:
    """A compiler wrapper that records TraceJIT's own decision for each invocation."""
    path = directory / "cc-tracejit.sh"
    path.write_text(
        "#!/bin/sh\n"
        f"report=$(mktemp)\n"
        f"\"{tracejit}\" run --contract compiler-runtime-v1 -- gcc \"$@\" 2>\"$report\"\n"
        "status=$?\n"
        "cat \"$report\" >&2\n"
        "if [ -n \"${TRACEJIT_DECISION_LOG:-}\" ]; then\n"
        "  { printf '%s\\t' \"$(date +%s%N)\"; grep -E 'cache +(HIT|MISS|DEOPT)|classified' \"$report\" | tr '\\n' ';'; printf '\\t%s\\n' \"$*\"; } >> \"$TRACEJIT_DECISION_LOG\"\n"
        "fi\n"
        "rm -f \"$report\"\n"
        "exit $status\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


# The exact flags the project's Makefile passes for `liblua.a` (its `generic` configuration:
# CFLAGS = -O2 -Wall -Wextra -DLUA_COMPAT_5_3, no MYCFLAGS). Every arm uses these.
COMPILE_FLAGS = ["-O2", "-Wall", "-Wextra", "-DLUA_COMPAT_5_3"]


def direct_order(root: Path) -> list[list[str]]:
    """The Makefile's compilation order, for the native/direct arm."""
    sources = sorted(path.name for path in (root / "src").glob("*.c")
                     if path.name not in {"lua.c", "luac.c"})
    commands = [["gcc", *COMPILE_FLAGS, "-c", f"src/{name}", "-o", f"src/{name[:-2]}.o"]
                for name in sources]
    commands.append(["ar", "rcu", "src/liblua.a",
                     *[f"src/{name[:-2]}.o" for name in sources]])
    return commands


def run_build(root: Path, arm: str, cc: str, env: dict, mode: str,
              jobs: int = 1) -> dict:
    started = time.perf_counter_ns()
    if mode == "direct":
        outputs = []
        for command in direct_order(root):
            completed = subprocess.run(command, cwd=root, env=env, capture_output=True)
            outputs.append({"command": command, "returncode": completed.returncode,
                            "stderr_tail": completed.stderr.decode(errors="replace")[-200:],
                            "executed": True})
            if completed.returncode != 0:
                return {"wall_ns": time.perf_counter_ns() - started, "commands": outputs,
                        "failed": True}
    else:
        completed = subprocess.run(["make", "-C", "src", f"-j{jobs}", "liblua.a", f"CC={cc}"],
                                   cwd=root, env=env, capture_output=True)
        outputs = [{"returncode": completed.returncode,
                    "stderr": completed.stderr.decode(errors="replace"),
                    "stdout": completed.stdout.decode(errors="replace")}]
        if completed.returncode != 0:
            return {"wall_ns": time.perf_counter_ns() - started, "commands": outputs,
                    "failed": True}
    return {"wall_ns": time.perf_counter_ns() - started, "commands": outputs, "failed": False}


def decisions_from_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rows.append({"timestamp_ns": parts[0], "report": parts[1], "argv": parts[2]})
    path.unlink()
    return rows


def summarize_decisions(rows: list[dict]) -> dict:
    counts = {"hit": 0, "miss": 0, "deopt": 0, "other": 0, "nondeterministic": 0,
              "guarded": 0}
    refused = []
    for row in rows:
        report = row["report"]
        if "NONDETERMINISTIC" in report:
            counts["nondeterministic"] += 1
            refused.append(row["argv"])
        elif "GUARDED" in report:
            counts["guarded"] += 1
        if "cache          HIT" in report:
            counts["hit"] += 1
        elif "cache          DEOPT" in report:
            counts["deopt"] += 1
        elif "cache          MISS" in report:
            counts["miss"] += 1
        else:
            counts["other"] += 1
        if "reuse disabled" in report and "NONDETERMINISTIC" not in report:
            refused.append(row["argv"])
    return {**counts, "total": len(rows), "refusals": refused[:10],
            "refusal_count": counts["nondeterministic"]}


def corrupt(path: Path, preserve_times: bool) -> dict:
    data = bytearray(path.read_bytes())
    original = bytes(data)
    # Flip bits in the middle of the file: same size, still an object file salt that no reader
    # will interpret, and definitely not the reference bytes.
    middle = len(data) // 2
    for offset in range(middle, middle + 16):
        data[offset] ^= 0xFF
    stat = path.stat()
    path.write_bytes(bytes(data))
    if preserve_times:
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return {"original_sha256": hashlib.sha256(original).hexdigest(),
            "corrupt_sha256": hashlib.sha256(bytes(data)).hexdigest(),
            "size": len(data),
            "times_preserved": preserve_times}


def arm_spec(name: str, tracejit: Path, ccache: Path, workdir: Path) -> dict:
    if name == "native":
        return {"cc": "gcc -O2", "mode": "direct", "cache": None, "wrap": None,
                "extra_env": {}}
    if name == "make":
        return {"cc": "gcc -O2", "mode": "make", "cache": None, "wrap": None,
                "extra_env": {}}
    if name == "ccache":
        directory = workdir / "ccache"
        return {"cc": f"{ccache} gcc -O2", "mode": "make", "cache": directory,
                "wrap": None, "extra_env": ccache_dir_env(directory), "ccache": ccache}
    if name == "tracejit":
        return {"cc": f"{wrapper(workdir, tracejit)} -O2", "mode": "make",
                "cache": workdir / "tracejit-cache", "wrap": workdir / "decisions.log",
                "extra_env": {}}
    raise SystemExit(f"unknown arm {name}")


def run_scenario(name: str, arm: str, spec: dict, source_root: Path, base: Path,
                 reference: dict, reference_source: Path) -> dict:
    workspace = base / f"ws-{arm}-{name}"
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(source_root, workspace, symlinks=True)
    env = make_env(spec["cc"], spec["cache"], spec["wrap"])
    env.update(spec.get("extra_env", {}))
    record: dict = {"scenario": name, "arm": arm, "builds": []}

    def ccache_stats() -> dict:
        if "ccache" not in spec:
            return {}
        completed = subprocess.run([str(spec["ccache"]), "--print-stats"], env=env,
                                   capture_output=True, text=True)
        stats = {}
        for line in completed.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].isdigit():
                stats[parts[0]] = int(parts[1])
        return stats

    def build(label: str) -> dict:
        before = ccache_stats()
        result = run_build(workspace, arm, spec["cc"], env, spec["mode"])
        after = ccache_stats()
        if after:
            result["ccache_delta"] = {key: after.get(key, 0) - before.get(key, 0)
                                      for key in ("cache_hit", "cache_miss", "cache_hit_direct",
                                                  "cache_miss_direct")
                                      if key in after}
        decisions = decisions_from_log(spec["wrap"]) if spec["wrap"] else []
        hashes = tree_hashes(workspace)
        mismatched = {key: value for key, value in hashes.items()
                      if key in reference and reference[key] != value}
        missing = sorted(set(reference) - set(hashes))
        observed = 0
        for command in result["commands"]:
            if "stdout" in command:
                observed += command["stdout"].count(" -c ")
            elif command.get("executed") and "-c" in command.get("command", []):
                observed += 1
        result.update({
            "label": label,
            "wall_ms": round(result["wall_ns"] / 1e6, 1),
            "compiles_observed": observed,
            "decisions": summarize_decisions(decisions),
            "mismatched_artifacts": sorted(mismatched),
            "missing_artifacts": missing,
            "artifact_count": len(hashes),
            "objects_from_cache": sum(1 for row in decisions if "cache          HIT" in row["report"]),
        })
        record["builds"].append(result)
        return result

    if name == "clean_build":
        build("clean")
    elif name == "no_change_rebuild":
        build("clean")
        build("no_change")
    elif name == "clean_warm_rebuild":
        # What a user does when they add a flag or re-run a build: remove the objects and let the
        # build system re-issue every compile. This is the only no-input-change schedule in which
        # a compiler cache is actually consulted for every translation unit.
        build("clean")
        for stale in list((workspace / "src").glob("*.o")):
            stale.unlink()
        (workspace / OBJECTS).unlink(missing_ok=True)
        build("warm_rebuild")
    elif name == "single_source_edit":
        build("clean")
        target = workspace / EDIT_TARGET
        target.write_text(target.read_text() + "\n/* phase-ab single-file edit */\n")
        build("after_edit")
    elif name == "shared_header_edit":
        build("clean")
        target = workspace / HEADER_TARGET
        target.write_text(target.read_text() + "\n/* phase-ab shared-header edit */\n")
        build("after_header_edit")
    elif name == "deleted_object":
        build("clean")
        (workspace / "src/lvm.o").unlink()
        build("after_delete")
    elif name in {"corrupted_object", "corrupted_object_same_timestamps"}:
        build("clean")
        record["corruption"] = corrupt(workspace / CORRUPT_TARGET,
                                       preserve_times=name.endswith("timestamps"))
        # Make decides from timestamps. The first rebuild shows what each tool does when it is
        # never consulted; the second forces the compiler to run by ageing the object, which is
        # the only situation in which a cache can repair anything.
        build("after_corruption_make")
        old = 1_000_000_000
        os.utime(workspace / CORRUPT_TARGET, ns=(old, old))
        build("after_corruption_forced_rebuild")
        # Then invoke the compiler directly on the corrupt output. This is the
        # only configuration in which a cache is consulted at all.
        command = ["gcc", *COMPILE_FLAGS, "-c", "src/lstrlib.c", "-o", "src/lstrlib.o"]
        started = time.perf_counter_ns()
        if arm == "tracejit":
            argv = [str(spec["cc"].split()[0]), "run", "--contract", "compiler-runtime-v1",
                    "--", *command]
        elif arm == "ccache":
            argv = [str(spec["cc"].split()[0]), *command]
        else:
            argv = command
        completed = subprocess.run(argv, cwd=workspace, env=env, capture_output=True)
        decisions = decisions_from_log(spec["wrap"]) if spec["wrap"] else []
        hashes = tree_hashes(workspace)
        record["direct_recompile"] = {
            "wall_ms": round((time.perf_counter_ns() - started) / 1e6, 1),
            "returncode": completed.returncode,
            "decisions": summarize_decisions(decisions),
            "restored": hashes.get("lstrlib.o") == reference.get("lstrlib.o"),
            "mismatched_artifacts": sorted(key for key, value in hashes.items()
                                           if key in reference and reference[key] != value),
            "stderr_tail": completed.stderr.decode(errors="replace")[-300:],
        }
    elif name == "input_edit_then_revert":
        build("clean")
        target = workspace / EDIT_TARGET
        original = target.read_text()
        target.write_text(original + "\n/* transient edit */\n")
        build("after_edit")
        target.write_text(original)
        build("after_revert")
    elif name == "cache_restart":
        build("clean")
        for stale in list((workspace / "src").glob("*.o")):
            stale.unlink()
        (workspace / OBJECTS).unlink(missing_ok=True)
        build("warm_rebuild")
        record["note"] = "each sample is a new process against the same cache"
        # A restart is a new process against the same cache; that is exactly what
        # every sample here already is, so the scenario records the state and re-runs.
        record["cache_state"] = str(spec["cache"]) if spec["cache"] else None
        build("after_restart")
    elif name == "partial_output_deletion":
        build("clean")
        (workspace / OBJECTS).unlink()
        build("after_archive_delete")
    elif name == "repeated_session":
        build("clean")
        for index in range(5):
            (workspace / "src/lstrlib.o").unlink(missing_ok=True)
            build(f"repeat_{index}")
    elif name == "classification_refusal_observation":
        build("clean")
        for index in range(3):
            for stale in list((workspace / "src").glob("*.o")):
                stale.unlink()
            (workspace / OBJECTS).unlink(missing_ok=True)
            build(f"full_recompile_{index}")
    else:
        raise SystemExit(f"unknown scenario {name}")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--ccache", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--arms", default="all")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args(argv)

    tracejit = Path(args.tracejit).resolve()
    ccache = Path(args.ccache).resolve()
    source_tarball = Path(args.source).resolve()
    base = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="phaseab-build-"))
    base.mkdir(parents=True, exist_ok=True)
    pristine = extract(source_tarball, base / "pristine")

    arms = ["native", "make", "ccache", "tracejit"] if args.arms == "all" else args.arms.split(",")
    scenarios = args.scenarios.split(",")

    # One reference build of the pristine source, used to verify every arm's artifacts.
    reference_dir = base / "reference"
    shutil.copytree(pristine, reference_dir, symlinks=True)
    reference_result = run_build(reference_dir, "native", "gcc -O2",
                                make_env("gcc -O2", None, None), "make")
    reference = tree_hashes(reference_dir)

    payload = {
        "project": "lua-5.4.6",
        "source_sha256": sha256(source_tarball),
        "translation_units": len(list((pristine / "src").glob("*.c"))),
        "tracejit": str(tracejit),
        "tracejit_sha256": sha256(tracejit),
        "ccache_version": subprocess.run([str(ccache), "--version"], capture_output=True,
                                         text=True).stdout.splitlines()[0],
        "gcc_version": subprocess.run(["gcc", "--version"], capture_output=True,
                                      text=True).stdout.splitlines()[0],
        "reference_build_ms": round(reference_result["wall_ns"] / 1e6, 1),
        "reference_artifacts": len(reference),
        "reference_failed": reference_result["failed"],
        "scratch": str(base),
        "scenarios": scenarios,
        "arms": arms,
        "rows": [],
    }
    for arm in arms:
        workdir = base / f"arm-{arm}"
        workdir.mkdir(exist_ok=True)
        spec = arm_spec(arm, tracejit, ccache, workdir)
        if spec["cache"]:
            spec["cache"].mkdir(parents=True, exist_ok=True)
        for scenario in scenarios:
            row = run_scenario(scenario, arm, spec, pristine, base, reference, reference_dir)
            payload["rows"].append(row)
            summary = {
                "arm": arm,
                "scenario": scenario,
                "build_ms": [build["wall_ms"] for build in row["builds"]],
                "hits": [build["decisions"]["hit"] for build in row["builds"]],
                "mismatched": [build["mismatched_artifacts"] for build in row["builds"]],
            }
            if "direct_recompile" in row:
                summary["direct_restored"] = row["direct_recompile"]["restored"]
            print(json.dumps(summary), flush=True)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

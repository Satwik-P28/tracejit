#!/usr/bin/env python3
"""Cumulative-session benchmark: TraceJIT against compiler caches and build schedulers.

Every arm compiles the same three translation units with the same edit schedule, so the only
difference is the reuse mechanism:

  native        `cc` directly, no cache
  tracejit      `target/release/tracejit run --contract compiler-runtime-v1`
  ccache        `ccache cc`
  sccache       `sccache cc`
  make          GNU make, header listed as an explicit prerequisite
  ninja         ninja with the compiler's `-MD` depfile

Scenarios (`--scenario`):

  repeat   no edits; every round repeats identical commands
  edits    the shared header changes at `--edit-rounds`
  toggle   the header alternates between two previously seen states
  delete   a recorded output is deleted before some rounds
  corrupt  a recorded output is appended to before some rounds
  flags    the optimisation flag changes for one round and changes back
  env      an unrelated environment variable changes for one round and changes back

The harness reports cumulative wall time, per-arm decision counts where the mechanism exposes
them, cache storage, and whether the final objects are byte-identical to a native build of the
same final sources. It never compares mechanisms by claim; it compares measured sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

UNITS = 3
HEADER_STATES = ("A", "B")


def write_sources(directory: Path, functions: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_header(directory, 1)
    for unit in range(UNITS):
        body = ['#include "common.h"', "#include <stdio.h>", "#include <string.h>", ""]
        for function in range(functions):
            body.append(
                f"long u{unit}_f{function}(long a) {{ char b[48]; snprintf(b, sizeof b, \"%ld\", a); "
                f"return (long)strlen(b) * {function + 1} + a; }}"
            )
        body.append("int main(void) { long t = 0;")
        for function in range(functions):
            body.append(f"  t += u{unit}_f{function}(SHARED_VALUE);")
        body.append('  printf("%ld\\n", t * SCALE);')
        body.append("  return 0;\n}")
        (directory / f"unit{unit}.c").write_text("\n".join(body) + "\n")


def write_header(directory: Path, value: int) -> None:
    (directory / "common.h").write_text(f"#define SHARED_VALUE {value}\n#define SCALE 3\n")


def digest(path: Path) -> str | None:
    flags = os.O_RDONLY | getattr(os, "O_NOATIME", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except PermissionError:
        descriptor = os.open(path, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as handle:
        return hashlib.blake2b(handle.read(), digest_size=16).hexdigest()


def object_digests(directory: Path) -> dict[str, str | None]:
    return {
        f"unit{unit}.o": digest(directory / f"unit{unit}.o") for unit in range(UNITS)
    }


def build_makefile(directory: Path) -> None:
    (directory / "Makefile").write_text(
        "CFLAGS = -O2\n"
        "UNITS = " + " ".join(f"unit{unit}.o" for unit in range(UNITS)) + "\n"
        "all: $(UNITS)\n"
        + "".join(
            f"unit{unit}.o: unit{unit}.c common.h\n\t$(CC) $(CFLAGS) -c unit{unit}.c -o unit{unit}.o\n"
            for unit in range(UNITS)
        )
    )


def build_ninja(directory: Path) -> None:
    (directory / "build.ninja").write_text(
        "rule cc\n"
        "  command = cc -O2 -MD -MF $out.d -c $in -o $out\n"
        "  depfile = $out.d\n"
        "  deps = gcc\n"
        "\n"
        + "".join(f"build unit{unit}.o: cc unit{unit}.c\n" for unit in range(UNITS))
        + "\n"
        + "build all: phony "
        + " ".join(f"unit{unit}.o" for unit in range(UNITS))
        + "\n"
    )


def compile_argv(flags: list[str], unit: int) -> list[str]:
    return ["cc", *flags, "-c", f"unit{unit}.c", "-o", f"unit{unit}.o"]


class Arm:
    def __init__(self, name: str, args: argparse.Namespace, directory: Path, cache: Path):
        self.name = name
        self.args = args
        self.directory = directory
        self.cache = cache
        self.decisions: dict[str, int] = {}
        self.note: list[str] = []

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        if self.name.startswith("tracejit"):
            environment["TRACEJIT_CACHE_DIR"] = str(self.cache)
            environment["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
        elif self.name == "ccache":
            environment["CCACHE_DIR"] = str(self.cache)
        elif self.name == "sccache":
            environment["SCCACHE_DIR"] = str(self.cache)
            environment["SCCACHE_CACHE_SIZE"] = "512M"
        return environment

    def compile_one(self, unit: int, flags: list[str]) -> None:
        environment = self.environment()
        if self.name == "native":
            argv = compile_argv(flags, unit)
        elif self.name.startswith("tracejit"):
            argv = [
                self.args.tracejit,
                "run",
                "--contract",
                "compiler-runtime-v1",
                "--",
                *compile_argv(flags, unit),
            ]
        elif self.name in ("ccache", "sccache"):
            argv = [self.args.tool(self.name), *compile_argv(flags, unit)]
        else:  # make / ninja compile the unit set once
            return
        completed = subprocess.run(
            argv,
            cwd=self.directory,
            env=environment,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise SystemExit(f"{self.name} failed: {completed.stderr.decode()[:400]}")
        if self.name.startswith("tracejit"):
            record_decision(self.decisions, completed.stderr.decode(), self.name)

    def compile_round(self, flags: list[str]) -> None:
        if self.name == "make":
            completed = subprocess.run(
                ["make", "all"],
                cwd=self.directory,
                env=self.environment(),
                capture_output=True,
            )
            if completed.returncode != 0:
                raise SystemExit(f"make failed: {completed.stderr.decode()[:400]}")
            rebuilds = sum(
                1 for line in completed.stdout.splitlines() if b" -c " in line
            )
            record_decision(self.decisions, "rebuild" if rebuilds else "up-to-date", "make")
            return
        if self.name == "ninja":
            completed = subprocess.run(
                [self.args.ninja, "-j1", "all"],
                cwd=self.directory,
                env=self.environment(),
                capture_output=True,
            )
            if completed.returncode != 0:
                raise SystemExit(f"ninja failed: {completed.stderr.decode()[:400]}")
            output = completed.stdout.decode()
            record_decision(
                self.decisions, "rebuild" if "[1/" in output else "up-to-date", "ninja"
            )
            return
        for unit in range(UNITS):
            self.compile_one(unit, flags)

    def cache_bytes(self) -> int:
        if not self.cache.exists():
            return 0
        return sum(
            path.stat().st_size for path in self.cache.rglob("*") if path.is_file()
        )


def record_decision(counts: dict[str, int], stderr: str, prefix: str) -> None:
    if "cache          HIT" in stderr:
        key = "hit"
    elif "cache          DEOPT" in stderr:
        key = "deopt"
    elif "cache          MISS" in stderr:
        key = "miss"
    elif "cache          SKIP" in stderr:
        key = "skip"
    else:
        key = "rebuild" if "rebuild" in stderr else "up-to-date"
    counts[key] = counts.get(key, 0) + 1


def scenario_schedule(args: argparse.Namespace) -> list[dict]:
    """Per-round state changes applied before compiling."""
    schedule = []
    for round_index in range(args.rounds):
        step = {"flags": ["-O2"], "env": {}, "header": None, "output": None}
        if args.scenario == "edits" and round_index in args.edit_rounds:
            step["header"] = 1 + round_index
        elif args.scenario == "toggle":
            step["header"] = 1 if round_index % 2 else 2
        elif args.scenario == "delete" and round_index in args.edit_rounds:
            step["output"] = "delete"
        elif args.scenario == "corrupt" and round_index in args.edit_rounds:
            step["output"] = "corrupt"
        elif args.scenario == "flags" and round_index in args.edit_rounds:
            step["flags"] = ["-O1"]
        elif args.scenario == "env" and round_index in args.edit_rounds:
            step["env"] = {"PHASE_W_MARK": str(round_index)}
        schedule.append(step)
    return schedule


def run_arm(name: str, args: argparse.Namespace, root: Path) -> dict:
    directory = root / name / "work"
    cache = root / name / "cache"
    shutil.rmtree(root / name, ignore_errors=True)
    write_sources(directory, args.functions)
    if name == "make":
        build_makefile(directory)
    if name == "ninja":
        build_ninja(directory)
    arm = Arm(name, args, directory, cache)
    os.environ.pop("PHASE_W_MARK", None)
    if name == "sccache":
        # The server outlives a client and keeps the cache directory it was started with, so a
        # previous arm's server would otherwise answer for this one.
        subprocess.run([args.sccache, "--stop-server"], capture_output=True)
    schedule = scenario_schedule(args)
    started = time.perf_counter()
    for step in schedule:
        if step["header"] is not None:
            write_header(directory, step["header"])
        if step["output"] == "delete":
            (directory / "unit0.o").unlink(missing_ok=True)
        elif step["output"] == "corrupt":
            with open(directory / "unit0.o", "ab") as handle:
                handle.write(b"\0corrupted-by-phase-w\n")
        if step["env"]:
            os.environ.update(step["env"])
        elif args.scenario == "env":
            os.environ.pop("PHASE_W_MARK", None)
        arm.compile_round(step["flags"])
    elapsed = time.perf_counter() - started
    if name == "ccache":
        stats = subprocess.run(
            [args.ccache, "-s"], env=arm.environment(), capture_output=True
        ).stdout.decode()
        arm.note.append(stats.strip())
    elif name == "sccache":
        stats = subprocess.run(
            [args.sccache, "--show-stats"], env=arm.environment(), capture_output=True
        ).stdout.decode()
        for line in stats.splitlines():
            if line.strip().startswith(("Cache hits ", "Cache misses ", "Compile requests ")):
                arm.note.append(line.strip())
        subprocess.run([args.sccache, "--stop-server"], capture_output=True)
    return {
        "arm": name,
        "seconds": round(elapsed, 3),
        "decisions": arm.decisions,
        "objects": object_digests(directory),
        "cache_bytes": arm.cache_bytes(),
        "tool_stats": arm.note,
    }


def native_reference(args: argparse.Namespace, root: Path) -> dict[str, str | None]:
    directory = root / "reference"
    shutil.rmtree(directory, ignore_errors=True)
    write_sources(directory, args.functions)
    schedule = scenario_schedule(args)
    final_header = 1
    for step in schedule:
        if step["header"] is not None:
            final_header = step["header"]
    write_header(directory, final_header)
    for unit in range(UNITS):
        completed = subprocess.run(
            compile_argv(["-O2"], unit), cwd=directory, capture_output=True
        )
        if completed.returncode != 0:
            raise SystemExit(f"reference compile failed: {completed.stderr.decode()[:400]}")
    return object_digests(directory)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--ccache", default=shutil.which("ccache") or "ccache")
    parser.add_argument("--sccache", default=shutil.which("sccache") or "sccache")
    parser.add_argument("--ninja", default=shutil.which("ninja") or "ninja")
    parser.add_argument(
        "--arms",
        default="native,tracejit-main,tracejit-fix,ccache,sccache,make,ninja",
    )
    parser.add_argument(
        "--scenario",
        default="edits",
        choices=["repeat", "edits", "toggle", "delete", "corrupt", "flags", "env"],
    )
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--functions", type=int, default=220)
    parser.add_argument("--edit-rounds", default="7,12")
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default="/tmp/tracejit-phase-w-session")
    args = parser.parse_args()
    args.edit_rounds = tuple(int(v) for v in args.edit_rounds.split(",") if v)
    args.tracejit_fix = args.tracejit

    def tool(name: str) -> str:
        return getattr(args, name)

    args.tool = tool

    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    reference = native_reference(args, root)
    main_binary = os.environ.get("TRACEJIT_MAIN_BINARY")

    payload = {
        "scenario": args.scenario,
        "rounds": args.rounds,
        "units": UNITS,
        "functions_per_unit": args.functions,
        "edit_rounds": list(args.edit_rounds),
        "total_invocations": args.rounds * UNITS,
        "reference_objects": reference,
        "arms": {},
    }
    for name in args.arms.split(","):
        if name == "tracejit-main":
            if not main_binary:
                payload["arms"][name] = {"skipped": "TRACEJIT_MAIN_BINARY is not set"}
                continue
            args.tracejit = main_binary
        else:
            args.tracejit = args.tracejit_fix
        result = run_arm(name, args, root)
        result["objects_match_native"] = result["objects"] == reference
        payload["arms"][name] = result
        print(
            f"{name:14s} {result['seconds']:8.3f}s  "
            f"match={result['objects_match_native']}  "
            f"cache={result['cache_bytes'] / 1e6:.1f}MB  {result['decisions']}",
            file=sys.stderr,
        )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({name: arm.get("seconds") for name, arm in payload["arms"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

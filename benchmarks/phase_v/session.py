#!/usr/bin/env python3
"""End-to-end session economics for one real workflow: a repeated C rebuild.

Three translation units share a header. The header changes every third round, which is what an
incremental build looks like: most rounds repeat the exact same compiler invocation, and the
rounds after an edit must recompile. The direct session and the traced session run the same
commands in the same order, so the difference is the caching layer and nothing else.

The compiler contract (`--contract compiler-runtime-v1`) is used for the traced arm because stock
gcc reads its own resource usage and the process's limits, which TraceJIT refuses to replay
without an audited-toolchain contract. The direct arm is plain native execution, so the reported
saving is a saving against native behavior, not against a weakened baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROUNDS = 9
UNITS = 3


def build_sources(directory: Path) -> None:
    header = directory / "common.h"
    header.write_text("#define SHARED_VALUE 1\n#define SCALE 3\n")
    for unit in range(UNITS):
        body = [
            f'#include "common.h"',
            "#include <stdio.h>",
            "#include <string.h>",
            "",
        ]
        for function in range(220):
            body.append(
                f"long u{unit}_f{function}(long a) {{ char b[48]; snprintf(b, sizeof b, \"%ld\", a); "
                f"return (long)strlen(b) * {function + 1} + a; }}"
            )
        body.append("int main(void) { long t = 0;")
        for function in range(220):
            body.append(f"  t += u{unit}_f{function}(SHARED_VALUE);")
        body.append(f"  printf(\"%ld\\n\", t * SCALE);")
        body.append("  return 0;\n}")
        (directory / f"unit{unit}.c").write_text("\n".join(body) + "\n")


def edit_header(directory: Path, round_index: int) -> None:
    (directory / "common.h").write_text(
        f"#define SHARED_VALUE {1 + round_index}\n#define SCALE 3\n"
    )


def commands() -> list[list[str]]:
    return [[
        "cc", "-O2", "-c", f"unit{unit}.c", "-o", f"unit{unit}.o"
    ] for unit in range(UNITS)]


def digest(directory: Path) -> str:
    hasher = hashlib.blake2b(digest_size=16)
    for unit in range(UNITS):
        hasher.update((directory / f"unit{unit}.o").read_bytes())
    return hasher.hexdigest()


def run_direct(directory: Path, rounds: int, edit_rounds: tuple[int, ...]) -> tuple[float, str]:
    environment = dict(os.environ)
    started = time.perf_counter()
    for round_index in range(rounds):
        # Same edit schedule as the traced arm, so both sessions compile the same sources.
        if round_index in edit_rounds:
            edit_header(directory, round_index)
        for argv in commands():
            completed = subprocess.run(argv, cwd=directory, env=environment, capture_output=True)
            if completed.returncode != 0:
                raise SystemExit(f"direct compile failed: {completed.stderr.decode()[:400]}")
    return time.perf_counter() - started, digest(directory)


def run_traced(
    directory: Path, cache: Path, tracejit: str, rounds: int, edit_rounds: tuple[int, ...]
) -> tuple[float, str, dict[str, int]]:
    environment = dict(os.environ)
    environment["TRACEJIT_CACHE_DIR"] = str(cache)
    environment["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    counts: dict[str, int] = {}
    started = time.perf_counter()
    for round_index in range(rounds):
        # The header is edited *before* compiling, exactly as a build system would see the edit.
        if round_index in edit_rounds:
            edit_header(directory, round_index)
        for argv in commands():
            completed = subprocess.run(
                [
                    tracejit,
                    "run",
                    "--json",
                    "--contract",
                    "compiler-runtime-v1",
                    "--",
                    *argv,
                ],
                cwd=directory,
                env=environment,
                capture_output=True,
            )
            if completed.returncode != 0:
                raise SystemExit(f"traced compile failed: {completed.stderr.decode()[:400]}")
            try:
                report = json.loads(completed.stdout or b"{}")
            except json.JSONDecodeError:
                report = {}
            decision = str(report.get("cache_decision"))
            counts[decision] = counts.get(decision, 0) + 1
            if report.get("cache_decision") == "Reused":
                continue
    return time.perf_counter() - started, digest(directory), counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default="/tmp/tracejit-phase-v-session")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument(
        "--edit-rounds",
        default="3,6",
        help="comma-separated rounds that change the shared header before compiling",
    )
    args = parser.parse_args()
    edit_rounds = tuple(int(value) for value in args.edit_rounds.split(",") if value)

    tracejit = str(Path(args.tracejit).resolve())
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)

    direct_dir = root / "direct"
    traced_dir = root / "traced"
    direct_dir.mkdir(parents=True)
    traced_dir.mkdir(parents=True)
    build_sources(direct_dir)
    build_sources(traced_dir)

    direct_seconds, direct_digest = run_direct(direct_dir, args.rounds, edit_rounds)
    traced_seconds, traced_digest, counts = run_traced(
        traced_dir, root / "cache", tracejit, args.rounds, edit_rounds
    )

    payload = {
        "rounds": args.rounds,
        "edit_rounds": list(edit_rounds),
        "compiles_per_round": UNITS,
        "total_invocations": args.rounds * UNITS,
        "direct_seconds": round(direct_seconds, 3),
        "traced_seconds": round(traced_seconds, 3),
        "speedup": round(direct_seconds / traced_seconds, 2),
        "saved_seconds": round(direct_seconds - traced_seconds, 3),
        "saved_percent": round(100 * (direct_seconds - traced_seconds) / direct_seconds, 1),
        "traced_decisions": counts,
        "objects_match_native": direct_digest == traced_digest,
        "contract": "compiler-runtime-v1",
        "tracejit": tracejit,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

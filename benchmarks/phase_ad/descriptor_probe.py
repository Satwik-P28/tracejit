#!/usr/bin/env python3
"""Phase AD: capture the `fcntl` calls that block stock `tar` and `xz`.

For each command the harness records two independent things:

1. Every `fcntl` the stock program issues, with the descriptor number, the command, the
   return value and -- from strace's `-y` annotation -- what the descriptor refers to.
   Correlating `open*` return values separates descriptors the program created from those
   it inherited across `exec`.
2. What TraceJIT decides about the same command, and which of its refusal reasons name a
   descriptor at all.  This keeps "the program calls fcntl" and "TraceJIT refuses because of
   fcntl" as separate claims.

The output is the raw evidence behind ``docs/INHERITED_DESCRIPTOR_SEMANTICS.md``; it is
regenerated rather than transcribed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "realworld_v2"))

import runner  # noqa: E402

FCNTL = re.compile(r"^(?P<pid>\d+)\s+fcntl(?:64)?\((?P<fd>-?\d+)(?:<(?P<target>[^>]*)>)?,\s*(?P<rest>.*)$")
OPEN = re.compile(r"^(?P<pid>\d+)\s+\w*open(?:at|at2)?\(.*\)\s+=\s+(?P<fd>\d+)")
COMMANDS = {
    "F_GETFD": 1, "F_GETFL": 3, "F_SETFL": 4, "F_GETOWN": 9, "F_SETFD": 2,
    "F_DUPFD": 0, "F_DUPFD_CLOEXEC": 1030,
}
NAMES = {value: name for name, value in COMMANDS.items()}


def parse_strace(path: Path) -> list[dict]:
    opened: set[int] = set()
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        open_match = OPEN.match(line)
        if open_match and int(open_match.group("fd")) > 2:
            opened.add(int(open_match.group("fd")))
            continue
        match = FCNTL.match(line)
        if not match:
            continue
        rest = match.group("rest")
        name = re.match(r"\s*([A-Z_0-9]+)", rest)
        command = name.group(1) if name else rest.split(",")[0].strip()
        returned = rest.rsplit("=", 1)[-1].strip() if "=" in rest else ""
        fd = int(match.group("fd"))
        rows.append({
            "fd": fd,
            "command": command,
            "target": match.group("target"),
            "returned": returned,
            "origin": "process" if fd in opened else ("inherited-stdio" if 0 <= fd <= 2 else "unclassified"),
        })
    return rows


def strace_command(ws: Path, argv: list[str], label: str) -> list[dict]:
    log = ws.parent / f"{label}.strace"
    subprocess.run(
        ["strace", "-f", "-y", "-e", "trace=fcntl,fcntl64,open,openat,openat2", "-o", str(log), "--", *argv],
        cwd=ws, check=False, capture_output=True,
    )
    return parse_strace(log)


def tracejit_view(tracejit: Path, ws: Path, argv: list[str], contract: str) -> list[dict]:
    env = runner.cache_env(dict(os.environ), ws.parent / "cache")
    views = []
    for _ in range(2):
        _, decision, report, _, _ = runner.run_traced(tracejit, argv, ws, env, contract)
        views.append({
            "cache_decision": (report or {}).get("cache_decision"),
            "classification": (report or {}).get("classification"),
            "eligible_for_reuse": (report or {}).get("eligible_for_reuse"),
            "reasons": (report or {}).get("reasons"),
            "effects": (report or {}).get("effect_counts"),
        })
    return views


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=runner.REPO / ".phasead-descriptors")
    parser.add_argument("--output", type=Path,
                        default=HERE.parent / "results/phasead/descriptor_probe.json")
    args = parser.parse_args(argv)

    shutil.rmtree(args.scratch, ignore_errors=True)
    args.scratch.mkdir(parents=True)
    tracejit = args.tracejit.resolve()
    payload = {"rows": []}

    cases = [
        ("tar-create", ["tar", "-cf", "out.tar", "src"], "allocator-entropy-v1"),
        ("tar-stdout", ["tar", "-cf", "-", "src"], "allocator-entropy-v1"),
        ("xz-stdout", ["xz", "-9", "-c", "blob.bin"], "allocator-entropy-v1"),
        ("xz-file", ["xz", "-9", "-k", "-f", "blob.bin"], "allocator-entropy-v1"),
        ("gzip-stdout", ["gzip", "-9", "-n", "-c", "text.txt"], "allocator-entropy-v1"),
    ]

    for label, command, contract in cases:
        ws = args.scratch / label / "ws"
        ws.mkdir(parents=True)
        (ws / "src").mkdir()
        (ws / "src" / "a.txt").write_text("alpha\n")
        (ws / "src" / "b.txt").write_text("beta\n")
        (ws / "text.txt").write_bytes(b"upstream text line\n" * 8000)
        (ws / "blob.bin").write_bytes(bytes(range(256)) * 3000)

        fcntl_calls = strace_command(ws, command, label)
        payload["rows"].append({
            "case": label,
            "argv": command,
            "fcntl": fcntl_calls,
            "tracejit": tracejit_view(tracejit, ws, command, contract),
        })
        print(f"{label:12s} fcntl calls={len(fcntl_calls)} "
              f"{[ (c['fd'], c['command'], c['origin']) for c in fcntl_calls ]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    shutil.rmtree(args.scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Provenance probe for the intermittent compiler entropy observation.

Phase AA1 found that a nominally identical ``gcc -c`` invocation occasionally
issues an unabsorbed ``getrandom`` from the gcc driver before ``cc1`` runs.
This probe reproduces that natively (no TraceJIT in the loop) and captures, for
every occurrence:

* the full syscall line and its return value,
* the user-space stack trace (``strace -k``),
* the process/thread identity and the syscall's sequence position,
* the executable and library identities.

It is deliberately independent of TraceJIT: if the call does not appear here it
is not the tracer's invention, and if it does appear without TraceJIT attached
it cannot be an artefact of ptrace-based classification.

Usage::

    python3 benchmarks/phase_ab/entropy_probe.py \
        --workload gcc-cc-small-tu --trials 60 --vendor /tmp/vendor \
        --output benchmarks/results/phaseab/entropy_probe.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "realworld_v2"))

import corpus  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SYSCALL_RE = re.compile(r"^(?P<pid>\d+)\s+(?P<call>[a-z_0-9]+)\((?P<args>.*)\)\s+=\s+(?P<ret>.*)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def library_map() -> list[dict]:
    """Libraries a gcc driver loads, with their build identity."""
    completed = subprocess.run(
        ["gcc", "-print-file-name=libc.so.6"], capture_output=True, text=True, check=False
    )
    libs = []
    for line in subprocess.run(["ldd", "/usr/bin/gcc"], capture_output=True, text=True, check=False).stdout.splitlines():
        parts = line.split()
        for part in parts:
            if part.startswith("/") and Path(part).exists():
                libs.append({"path": part, "sha256": sha256(Path(part))})
                break
    return libs


def run_trial(workload, ctx: dict, trial: int, trace_file: Path, stderr_file: Path) -> dict:
    workspace = trace_file.parent / f"ws-{trial}"
    corpus.prepare(workspace, ctx, workload)
    command = workload.command(workspace, ctx)
    strace = [
        "strace",
        "-f",
        "-k",
        "-qq",
        "-s",
        "256",
        "-o",
        str(trace_file),
        "--",
        *command,
    ]
    completed = subprocess.run(strace, cwd=workspace, env=dict(os.environ, **workload.env),
                               capture_output=True, text=True, check=False)
    stderr_file.write_text(completed.stderr)
    return {
        "trial": trial,
        "command": command,
        "returncode": completed.returncode,
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        "workspace": str(workspace),
    }


def parse_trace(trace_file: Path) -> dict:
    """Return entropy events plus the position context of a syscall trace."""
    lines = trace_file.read_text(errors="replace").splitlines()
    total_syscalls = 0
    events: list[dict] = []
    pending: list[str] = []
    for index, line in enumerate(lines):
        if line.startswith("---") or line.startswith("+++"):
            continue
        match = SYSCALL_RE.match(line)
        if match:
            total_syscalls += 1
            call = match.group("call")
            if call in {"getrandom", "getentropy", "openat", "execve"}:
                # strace -k emits the user stack on following indented lines.
                stack = []
                for follow in lines[index + 1:]:
                    stripped = follow.strip()
                    if not stripped.startswith(">"):
                        break
                    stack.append(stripped[1:].strip())
                if call in {"getrandom", "getentropy"}:
                    events.append({
                        "pid": int(match.group("pid")),
                        "call": line[len(match.group("pid")):].strip(),
                        "args": match.group("args"),
                        "return": match.group("ret"),
                        "position": total_syscalls,
                        "stack": stack,
                        "preceding": pending[-12:],
                    })
            pending.append(f"{match.group('pid')} {line[len(match.group('pid')):].strip()}")
    return {"events": events, "total_syscalls": total_syscalls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", default="gcc-cc-small-tu")
    parser.add_argument("--trials", type=int, default=60)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args(argv)

    workload = corpus.by_id()[args.workload]
    vendor = Path(args.vendor)
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="tracejit-entropy-"))
    scratch.mkdir(parents=True, exist_ok=True)
    shared = scratch / "shared"
    shared.mkdir(exist_ok=True)
    ctx = corpus.materialize_shared(shared, vendor)

    trials = []
    aggregate: list[dict] = []
    for trial in range(args.trials):
        trace_file = scratch / f"trace-{trial}.log"
        stderr_file = scratch / f"gcc-stderr-{trial}.txt"
        record = run_trial(workload, ctx, trial, trace_file, stderr_file)
        parsed = parse_trace(trace_file)
        record["entropy_events"] = parsed["events"]
        record["syscalls"] = parsed["total_syscalls"]
        record["trace_sha256"] = sha256(trace_file)
        aggregate.extend({"trial": trial, **event} for event in parsed["events"])
        trials.append(record)
        if parsed["events"]:
            print(f"trial {trial}: {len(parsed['events'])} entropy event(s) at "
                  f"position(s) {[e['position'] for e in parsed['events']]} of {parsed['total_syscalls']}",
                  flush=True)

    agreeing = all(record["stderr_sha256"] == trials[0]["stderr_sha256"] for record in trials)
    payload = {
        "workload": args.workload,
        "command": workload.command(Path("WS"), ctx),
        "trials": args.trials,
        "trials_with_entropy": sum(1 for record in trials if record["entropy_events"]),
        "event_count": len(aggregate),
        "stderr_identical_across_trials": agreeing,
        "environment": {
            "gcc": subprocess.run(["gcc", "--version"], capture_output=True, text=True,
                                  check=False).stdout.splitlines()[0],
            "libc": subprocess.run(["ldd", "--version"], capture_output=True, text=True,
                                   check=False).stdout.splitlines()[0],
            "gcc_binary_sha256": sha256(Path("/usr/bin/x86_64-linux-gnu-gcc-13"))
            if Path("/usr/bin/x86_64-linux-gnu-gcc-13").exists() else None,
            "libraries": library_map(),
            "kernel": os.uname().release,
            "cpu_count": os.cpu_count(),
        },
        "events": aggregate,
        "records": trials,
        "scratch": str(scratch),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in (
        "workload", "trials", "trials_with_entropy", "event_count",
        "stderr_identical_across_trials")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

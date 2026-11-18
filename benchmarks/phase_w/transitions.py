#!/usr/bin/env python3
"""Record the complete state-transition sequence of a repeated C rebuild.

For every invocation this harness records:

  * the input state before the run (content digest of the shared header and every unit source);
  * the output pre-state before the run (content digest of every object file);
  * the cache decision and the reason the core reported;
  * every cache record retained for the command identity, decoded from SQLite, with its guards
    and its output artifacts;
  * the output post-state after the run.

That is the full transition the Phase W analysis needs: input state -> output pre-state ->
cache record -> output post-state. It deliberately does not interpret anything; the analysis
lives in docs/PHASE_W_REPORT.md.

The compiler contract (`--contract compiler-runtime-v1`) is used, matching Phase V: stock gcc
reads its own resource usage, which TraceJIT refuses to replay without an audited-toolchain
contract. The harness never weakens the default contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

UNITS = 3


def sha(path: Path) -> str | None:
    """Digest a path without updating its access time.

    Reading an object normally updates atime, and a recorded FileMetadata guard includes it, so a
    harness that hashed outputs between invocations would deoptimise every record by itself. The
    measurements must not perturb the state they measure.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOATIME", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except PermissionError:
        descriptor = os.open(path, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as handle:
        return hashlib.blake2b(handle.read(), digest_size=8).hexdigest()


def failure_guard(report: dict) -> dict | None:
    guards = report.get("guards")
    if not isinstance(guards, dict):
        return None
    failure = guards.get("failure")
    if not isinstance(failure, dict):
        return None
    return {
        "reason": failure.get("reason"),
        "expected": str(failure.get("expected"))[:64],
        "actual": str(failure.get("actual"))[:64],
        "guard": guard_summary(failure.get("guard")),
    }


def build_sources(directory: Path, functions: int) -> None:
    (directory / "common.h").write_text("#define SHARED_VALUE 1\n#define SCALE 3\n")
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


def edit_header(directory: Path, round_index: int) -> None:
    (directory / "common.h").write_text(
        f"#define SHARED_VALUE {1 + round_index}\n#define SCALE 3\n"
    )


def guard_summary(guard: dict) -> dict:
    """Keep only the fields that decide whether a guard can be reused."""
    if not isinstance(guard, dict):
        return {"kind": str(guard)}
    for name, value in guard.items():
        if isinstance(value, dict):
            summary = {"kind": name, "path": value.get("path")}
            for key in (
                "expected",
                "start_offset",
                "end_offset",
                "mode",
                "errno",
                "key",
            ):
                if key in value:
                    summary[key] = value[key]
            return summary
    return {"kind": str(guard)}


def record_summary(record: dict) -> dict:
    outputs = []
    for output in record.get("outputs", []):
        content = output.get("content")
        if isinstance(content, dict):
            content = content.get("hex") or content.get("bytes")
        outputs.append(
            {
                "path": str(output.get("path")),
                "kind": output.get("kind"),
                "content": content,
            }
        )
    return {
        "execution_id": record.get("id"),
        "decision": (record.get("last_decision") or {}).get("decision"),
        "reason": (record.get("last_decision") or {}).get("reason"),
        "classification": record.get("classification"),
        "contract": record.get("contract"),
        "guards": [guard_summary(guard) for guard in record.get("guards", [])],
        "outputs": outputs,
    }


def cache_snapshot(cache: Path) -> list[dict]:
    database = cache / "db.sqlite3"
    if not database.exists():
        return []
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT execution_id, lookup_key, updated_unix_ms, record_json FROM executions "
            "ORDER BY CAST(updated_unix_ms AS INTEGER) ASC, execution_id ASC"
        ).fetchall()
    finally:
        connection.close()
    snapshot = []
    for execution_id, lookup_key, updated, payload in rows:
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            snapshot.append({"execution_id": execution_id, "malformed": True})
            continue
        summary = record_summary(record)
        summary["lookup_key"] = lookup_key
        summary["updated_unix_ms"] = updated
        summary["command"] = record.get("command")
        snapshot.append(summary)
    return snapshot


def run_session(args: argparse.Namespace) -> dict:
    tracejit = str(Path(args.tracejit).resolve())
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    work = root / "work"
    cache = root / "cache"
    work.mkdir(parents=True)
    build_sources(work, args.functions)

    environment = dict(os.environ)
    environment["TRACEJIT_CACHE_DIR"] = str(cache)
    environment["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"

    timeline = []
    for round_index in range(args.rounds):
        if round_index in args.edit_rounds:
            edit_header(work, round_index)
        for unit in range(UNITS):
            argv = ["cc", "-O2", "-c", f"unit{unit}.c", "-o", f"unit{unit}.o"]
            object_path = work / f"unit{unit}.o"
            inputs = {
                "common.h": sha(work / "common.h"),
                f"unit{unit}.c": sha(work / f"unit{unit}.c"),
            }
            before = sha(object_path)
            before_records = cache_snapshot(cache)
            started = time.perf_counter()
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
                cwd=work,
                env=environment,
                capture_output=True,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            if completed.returncode != 0:
                raise SystemExit(
                    f"tracejit run failed ({completed.returncode}): "
                    f"{completed.stderr.decode()[:400]}"
                )
            try:
                report = json.loads(completed.stdout or b"{}")
            except json.JSONDecodeError:
                report = {}
            after = sha(object_path)
            after_records = cache_snapshot(cache)
            timeline.append(
                {
                    "round": round_index,
                    "unit": unit,
                    "argv": argv,
                    "inputs": inputs,
                    "pre_state": before,
                    "post_state": after,
                    "decision": report.get("cache_decision"),
                    "decision_reason": report.get("decision_reason"),
                    "execution_id": report.get("execution_id"),
                    "kind": report.get("kind"),
                    "classification": report.get("classification"),
                    "runtime_ns": report.get("runtime_ns"),
                    "elapsed_ms": round(elapsed_ms, 3),
                    "guards": report.get("guards"),
                    "failure": failure_guard(report),
                    "records_before": before_records,
                    "records_after": after_records,
                }
            )

    decisions: dict[str, int] = {}
    for entry in timeline:
        key = str(entry["decision"])
        decisions[key] = decisions.get(key, 0) + 1
    objects = {f"unit{unit}.o": sha(work / f"unit{unit}.o") for unit in range(UNITS)}
    return {
        "rounds": args.rounds,
        "edit_rounds": list(args.edit_rounds),
        "units": UNITS,
        "functions_per_unit": args.functions,
        "contract": "compiler-runtime-v1",
        "decisions": decisions,
        "final_objects": objects,
        "timeline": timeline,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default="/tmp/tracejit-phase-w-transitions")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--functions", type=int, default=220)
    parser.add_argument(
        "--edit-rounds",
        default="2,4",
        help="comma-separated rounds that change the shared header before compiling",
    )
    args = parser.parse_args()
    args.edit_rounds = tuple(int(value) for value in args.edit_rounds.split(",") if value)

    payload = run_session(args)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    summary = {
        "decisions": payload["decisions"],
        "final_objects": payload["final_objects"],
        "sequence": [
            f"r{entry['round']}u{entry['unit']} {entry['decision']} "
            f"{entry['decision_reason']}"
            for entry in payload["timeline"]
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

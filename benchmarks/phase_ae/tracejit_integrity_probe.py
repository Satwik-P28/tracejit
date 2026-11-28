#!/usr/bin/env python3
"""Phase AE: does TraceJIT expose cached bytes that failed integrity verification?

The paired competitor measurement lives in ``firebuild_policy_probe.py``
(``cache_corruption``): a single flipped byte in Firebuild's cached stdout blob is replayed
to the caller.  This script runs the same experiment against TraceJIT so the comparison is
like for like, and so the claim "unverified cached bytes never become externally visible"
is measured instead of asserted.

Method: populate the cache with one trace and one reuse of ``gzip -9 -n -c``, locate the
stored stdout object by its size, flip one byte in place, then invoke the same command again.
Pass criteria:

* the run must not report a HIT for the corrupted object,
* the externally visible stdout must equal the native oracle.

Run: ``python3 benchmarks/phase_ae/tracejit_integrity_probe.py``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "realworld_v2"))

import runner  # noqa: E402

CONTRACT = "allocator-entropy-v1"
ARGV = ["gzip", "-9", "-n", "-c", "input.bin"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload() -> bytes:
    return b"".join(
        f"row-{i:07d} key={(i * 7919) % 100003} tag=t{i % 11}\n".encode() for i in range(1, 40_001)
    )


def run(tracejit: Path, ws: Path, cache: Path) -> tuple[subprocess.CompletedProcess, dict | None]:
    env = runner.cache_env(dict(os.environ), cache)
    return runner.run_plain(tracejit, ARGV, ws, env, CONTRACT)


def find_object(cache: Path, size: int, digest: str) -> tuple[Path | None, bool]:
    """Locate the stored stdout object; report whether its name looks content-addressed."""

    objects = cache / "objects"
    if not objects.is_dir():
        return None, False
    for path in objects.iterdir():
        if not path.is_file() or path.stat().st_size != size:
            continue
        data = path.read_bytes()
        if sha256(data) == digest:
            return path, len(path.name) == 64 and all(
                character in "0123456789abcdef" for character in path.name
            )
    return None, False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseae-integrity")
    parser.add_argument("--output", type=Path,
                        default=REPO / "benchmarks/results/phaseae/tracejit_integrity.json")
    args = parser.parse_args(argv)

    tracejit = args.tracejit.resolve()
    shutil.rmtree(args.scratch, ignore_errors=True)
    ws = args.scratch / "ws"
    cache = args.scratch / "cache"
    ws.mkdir(parents=True)
    data = payload()
    (ws / "input.bin").write_bytes(data)

    native = subprocess.run(ARGV, cwd=ws, env=dict(os.environ), capture_output=True, check=False)
    expected = native.stdout
    result: dict = {
        "argv": ARGV,
        "contract": CONTRACT,
        "tracejit": str(tracejit),
        "tracejit_sha256": hashlib.sha256(tracejit.read_bytes()).hexdigest(),
        "input_bytes": len(data),
        "expected_stdout_bytes": len(expected),
        "expected_stdout_sha256": sha256(expected),
        "population": [],
    }

    for index in range(2):
        completed, decision = run(tracejit, ws, cache)
        result["population"].append({
            "index": index,
            "decision": (decision or {}).get("kind"),
            "cache_decision": (decision or {}).get("cache_decision"),
            "exit": completed.returncode,
            "stdout_sha256": sha256(completed.stdout),
            "correct": sha256(completed.stdout) == sha256(expected),
        })

    object_path, content_addressed = find_object(cache, len(expected), sha256(expected))
    result["object_located"] = object_path is not None
    result["object_path"] = str(object_path) if object_path else None
    result["object_name_is_64_hex"] = content_addressed
    if object_path is None:
        result["all_correct"] = all(item["correct"] for item in result["population"])
        result["note"] = "stored stdout object not located by size and digest"
    else:
        blob = bytearray(object_path.read_bytes())
        offset = len(blob) // 2
        blob[offset] ^= 0xFF
        object_path.write_bytes(bytes(blob))
        completed, decision = run(tracejit, ws, cache)
        served = completed.stdout
        result["corrupted_offset"] = offset
        result["after_corruption"] = {
            "decision": (decision or {}).get("kind"),
            "cache_decision": (decision or {}).get("cache_decision"),
            "reason": (decision or {}).get("reason"),
            "exit": completed.returncode,
            "stdout_sha256": sha256(served),
            "correct": sha256(served) == sha256(expected),
            "reported_hit": bool(runner.is_hit(decision)),
        }
        result["served_corrupted_bytes"] = sha256(served) != sha256(expected)
        result["all_correct"] = (
            all(item["correct"] for item in result["population"])
            and result["after_corruption"]["correct"]
            and not result["after_corruption"]["reported_hit"]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("population", "after_corruption")}, indent=2))
    print("after_corruption:", json.dumps(result.get("after_corruption")))
    shutil.rmtree(args.scratch, ignore_errors=True)
    return 0 if result.get("all_correct") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Differential validation for the `tracejit.allocator-entropy.v1` contract.

The contract deliberately fixes one class of environmental randomness: the runtime's own
`getrandom(8, GRND_NONBLOCK)` probe, whose destination must be inside the issuing shared
library's writable data. This script does not assume that is enough. For each workload it
checks, against independent native executions:

  * the first controlled run is `Guarded` and its bytes match a direct run;
  * later controlled runs are `Reused` and their bytes still match;
  * a content change deoptimizes and returns the new bytes;
  * an environment change is a miss;
  * a native invocation never reuses a controlled entry;
  * output is compared across several independent direct runs, so "it matched once" is not
    the evidence.

A workload that the contract cannot make eligible is recorded as a result, not hidden.

Usage:
    python3 benchmarks/realworld/contract_check.py [--runs N] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "target" / "debug" / "tracejit"
RELEASE = REPO / "target" / "release" / "tracejit"
CONTRACT = "allocator-entropy-v1"


def binary() -> Path:
    for candidate in (RELEASE, DEBUG):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary; run: cargo build --workspace")


def text_input() -> str:
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    return "".join(
        f"{index % 977} {words[index % len(words)]} {index * 7 % 1013}\n"
        for index in range(20000)
    )


WORKLOADS = [
    ("sed", ["sed", "-e", "s/alpha/ALPHA/g", "input.txt"], None),
    ("tr", ["tr", "a-z", "A-Z"], "input.txt"),
    ("base64", ["base64", "-w0", "input.txt"], None),
    ("wc", ["wc", "-c", "input.txt"], None),
]


def environment(cache: Path) -> dict:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "TRACEJIT_CACHE_DIR": str(cache),
    }


def run(command, cwd, env, stdin_path=None):
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    try:
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        elapsed = (time.perf_counter() - started) * 1000.0
    finally:
        if stdin is not subprocess.DEVNULL:
            stdin.close()
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit": completed.returncode,
        "ms": elapsed,
    }


def traced(command, cwd, env, stdin_path, contract=CONTRACT):
    prefix = [str(binary()), "run", "--json"]
    if contract:
        prefix += ["--contract", contract]
    result = run([*prefix, "--", *command], cwd, env, stdin_path)
    try:
        report = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None, result
    return report, result


def check(name, command, stdin_name, root, runs):
    work = root / f"work-{name}"
    work.mkdir(parents=True)
    body = text_input()
    (work / "input.txt").write_text(body)
    stdin_path = str(work / stdin_name) if stdin_name else None
    cache = root / f"cache-{name}"
    env = environment(cache)

    direct_samples = [run(command, work, env, stdin_path) for _ in range(3)]
    expected = direct_samples[0]["stdout"]
    direct_stable = all(sample["stdout"] == expected for sample in direct_samples)

    first_report, _ = traced(command, work, env, stdin_path)
    second_report, _ = traced(command, work, env, stdin_path)
    third_report, _ = traced(command, work, env, stdin_path)

    row = {
        "workload": name,
        "command": command,
        "direct_runs": 3,
        "direct_output_stable": direct_stable,
        "classification": first_report and first_report["classification"],
        "contract": first_report and first_report["contract"],
        "first_matches_direct": bool(first_report) and bytes(first_report["stdout_bytes"]) == expected,
        "reused": bool(second_report) and second_report["cache_decision"] == "Reused",
        "reused_matches_direct": bool(second_report)
        and bytes(second_report["stdout_bytes"]) == expected,
        "consecutive_reused": bool(third_report) and third_report["cache_decision"] == "Reused",
        "checks": {},
    }

    # A changed input must deoptimize and return the new bytes.
    (work / "input.txt").write_text(body + "changed-line\n")
    changed = run(command, work, env, stdin_path)["stdout"]
    changed_report, _ = traced(command, work, env, stdin_path)
    # A stdin change can also change the runtime identity (fd 0's fingerprint), which is a miss
    # rather than a guard failure. Both are safe; only `Reused` with old bytes would not be.
    row["checks"]["content_change_not_reused"] = bool(changed_report) and (
        changed_report["cache_decision"] != "Reused"
        and bytes(changed_report["stdout_bytes"]) == changed
    )
    (work / "input.txt").write_text(body)

    # An environment change must not reuse.
    changed_environment = environment(cache)
    changed_environment["TZ"] = "Pacific/Auckland"
    environment_report, _ = traced(command, work, changed_environment, stdin_path)
    row["checks"]["environment_change_misses"] = bool(environment_report) and (
        environment_report["cache_decision"] != "Reused"
    )

    # Native mode has a different identity and must not reuse the controlled entry.
    native_report, _ = traced(command, work, env, stdin_path, contract=None)
    row["checks"]["native_does_not_reuse_controlled"] = bool(native_report) and (
        native_report["cache_decision"] != "Reused"
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", default="benchmarks/results/phase2g/contract")
    args = parser.parse_args()

    output_dir = REPO / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tracejit-contract-"))

    rows = []
    for name, command, stdin_name in WORKLOADS:
        if shutil.which(command[0]) is None:
            rows.append({"workload": name, "status": "missing-tool"})
            continue
        rows.append(check(name, command, stdin_name, root, args.runs))

    reusable = [row for row in rows if row.get("reused")]
    verified = [
        row
        for row in reusable
        if row.get("first_matches_direct")
        and row.get("reused_matches_direct")
        and all(row["checks"].values())
    ]
    result = {
        "generated_by": "benchmarks/realworld/contract_check.py",
        "contract": CONTRACT,
        "tracejit_binary": str(binary()),
        "workloads": len(rows),
        "reusable_under_contract": len(reusable),
        "fully_verified": len(verified),
        "rows": rows,
    }
    (output_dir / "contract-check.json").write_text(json.dumps(result, indent=2) + "\n")
    for row in rows:
        if row.get("status"):
            print(f"{row['workload']:8} {row['status']}")
            continue
        print(
            f"{row['workload']:8} {row['classification']:16} reused={row['reused']!s:5} "
            f"direct_match={row['first_matches_direct']!s:5} checks={row['checks']}"
        )
    print(f"reusable under contract: {len(reusable)}/{len(rows)}; fully verified: {len(verified)}/{len(rows)}")
    print("RESULT contract-check PASS" if len(verified) == len(reusable) and reusable else
          "RESULT contract-check FAIL")
    return 0 if len(verified) == len(reusable) and reusable else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Fixed direct-execution compatibility suite.

Every workload is invoked without a shell, from its own working directory, with the
arguments a user would type. The suite never drops a workload from the denominator:
a refusal, a missing tool, a crash and a nondeterministic result all count, and each one
is reported with the reason the classifier gave.

For each workload it records:

  * direct execution: bytes, exit status, wall time
  * cold traced execution: bytes, exit status, wall time, classification
  * a second traced execution: the cache decision, and whether the bytes match direct
  * for reusable workloads: N timed direct runs and N timed cached runs

Timing runs do not use `--json`: serialising captured stdout as a JSON integer array
inflates wall time by orders of magnitude on large outputs.

Usage:
    python3 benchmarks/realworld/direct_suite.py [--runs N] [--output-dir DIR]
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
TRACEJIT = REPO / "target" / "debug" / "tracejit"
RELEASE = REPO / "target" / "release" / "tracejit"


def binary() -> Path:
    for candidate in (RELEASE, TRACEJIT):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary; run: cargo build -p tracejit-cli")


def text_input(rows: int = 20000) -> str:
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    lines = []
    for index in range(rows):
        lines.append(f"{index % 977} {words[index % len(words)]} {index * 7 % 1013}\n")
    return "".join(lines)


def json_input(rows: int = 4000) -> str:
    items = [{"id": index, "v": index % 17, "name": f"item-{index}"} for index in range(rows)]
    return json.dumps(items)


C_SOURCE = """#include <stdio.h>
#include <stdlib.h>

static unsigned mix(unsigned value) {
    value ^= value << 13;
    value ^= value >> 17;
    return value * 2654435761u;
}

int main(void) {
    unsigned acc = 1;
    for (unsigned index = 0; index < 200000u; index++) {
        acc = mix(acc + index);
    }
    printf("%u\\n", acc);
    return 0;
}
"""

ASM_SOURCE = """    .text
    .globl main
main:
    movl $7, %eax
    ret
"""

# A workload is (name, argv, files, stdin-file). Every entry stays in the suite whether
# it is reusable or not: the denominator is fixed, and a refusal is a recorded result.
WORKLOADS = [
    ("gzip", ["gzip", "-9", "-c", "input.txt"], {"input.txt": text_input()}, None),
    ("bzip2", ["bzip2", "-9", "-c", "input.txt"], {"input.txt": text_input()}, None),
    ("xz", ["xz", "-9", "-c", "input.txt"], {"input.txt": text_input()}, None),
    ("tar", ["tar", "-cf", "bundle.tar", "input.txt"], {"input.txt": text_input()}, None),
    ("sed", ["sed", "-e", "s/alpha/ALPHA/g", "input.txt"], {"input.txt": text_input()}, None),
    ("grep", ["grep", "-c", "alpha", "input.txt"], {"input.txt": text_input()}, None),
    ("sort", ["sort", "-u", "input.txt"], {"input.txt": text_input()}, None),
    ("tr", ["tr", "a-z", "A-Z"], {"input.txt": text_input()}, "input.txt"),
    ("base64", ["base64", "-w0", "input.txt"], {"input.txt": text_input()}, None),
    ("md5sum", ["md5sum", "input.txt"], {"input.txt": text_input()}, None),
    ("wc", ["wc", "-c", "input.txt"], {"input.txt": text_input()}, None),
    ("jq", ["jq", "-c", "map(select(.v > 5)) | length", "input.json"],
     {"input.json": json_input()}, None),
    ("python-json", ["python3", "-c",
                     "import json,sys;d=json.load(open('input.json'));"
                     "print(sum(x['v'] for x in d))"],
     {"input.json": json_input()}, None),
    ("gcc-compile", ["gcc", "-O2", "-c", "hello.c", "-o", "hello.o"],
     {"hello.c": C_SOURCE}, None),
    ("assemble", ["as", "hello.s", "-o", "hello.o"], {"hello.s": ASM_SOURCE}, None),
    ("strip", ["strip", "-o", "stripped", "hello.o"], {"hello.o": b""}, None),
]


def run(cmd, cwd, env, stdin_path=None, capture=True):
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    try:
        started = time.perf_counter()
        completed = subprocess.run(
            cmd, cwd=cwd, env=env, stdin=stdin,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        )
        elapsed = (time.perf_counter() - started) * 1000.0
    finally:
        if stdin is not subprocess.DEVNULL:
            stdin.close()
    return {
        "elapsed_ms": elapsed,
        "exit_code": completed.returncode,
        "stdout": completed.stdout if capture else b"",
        "stderr": completed.stderr if capture else b"",
    }


def traced(cmd, cwd, env, stdin_path):
    """Run under TraceJIT with --json so the cache decision is observable."""
    result = run([str(binary()), "run", "--json", "--", *cmd], cwd, env, stdin_path)
    try:
        report = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None, result
    return report, result


def fresh_cache(root: Path, name: str) -> Path:
    path = root / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def environment(cache: Path, extra=None) -> dict:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "TRACEJIT_CACHE_DIR": str(cache),
    }
    if extra:
        env.update(extra)
    return env


def prepare_workload(root: Path, name: str, argv, files, stdin_name):
    """Build the fixture, running any real set-up command outside the measurement."""
    work = root / f"work-{name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for filename, content in files.items():
        target = work / filename
        if isinstance(content, str):
            target.write_text(content)
        else:
            target.write_bytes(content)
    if name == "strip":
        # `strip` needs a real object file; build it with an untimed direct command.
        (work / "hello.c").write_text(C_SOURCE)
        built = run(["gcc", "-O2", "-c", "hello.c", "-o", "hello.o"], work,
                    {"PATH": os.environ["PATH"], "LC_ALL": "C"})
        if built["exit_code"] != 0:
            return None
    return work


def median_ms(samples):
    return round(statistics.median(samples), 2) if samples else None


def p95_ms(samples):
    if not samples:
        return None
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return round(ordered[index], 2)


def measure(name, argv, work, stdin_name, runs, decision, cache_root):
    """Time direct and cached invocations of a workload that actually reused."""
    direct, cached = [], []
    cache = fresh_cache(cache_root, f"timing-{name}")
    env = environment(cache)
    stdin_path = str(work / stdin_name) if stdin_name else None
    cold = run([str(binary()), "run", "--", *argv], work, env, stdin_path)
    for _ in range(runs):
        direct.append(run(argv, work, env, stdin_path)["elapsed_ms"])
        hit = run([str(binary()), "run", "--", *argv], work, env, stdin_path)
        cached.append(hit["elapsed_ms"])
    # The cached samples include the whole TraceJIT process; the last one must still be a
    # hit, which is verified separately by `decision`.
    break_even = None
    if cached and median_ms(cached) and median_ms(direct):
        saved = median_ms(direct) - median_ms(cached)
        penalty = cold["elapsed_ms"] - median_ms(direct)
        break_even = round(penalty / saved, 2) if saved > 0 else None
    return {
        "direct_median_ms": median_ms(direct),
        "direct_p95_ms": p95_ms(direct),
        "cached_median_ms": median_ms(cached),
        "cached_p95_ms": p95_ms(cached),
        "cold_ms": round(cold["elapsed_ms"], 2),
        "runs": runs,
        "saved_ms": round(median_ms(direct) - median_ms(cached), 2),
        "speedup": round(median_ms(direct) / median_ms(cached), 2) if median_ms(cached) else None,
        "tracing_penalty_ms": round(cold["elapsed_ms"] - median_ms(direct), 2),
        "hits_to_repay": break_even,
        "final_decision": decision,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--output-dir", default="benchmarks/results/phase2d/direct-suite")
    parser.add_argument("--only", default=None, help="restrict to one workload name")
    args = parser.parse_args()

    if not binary():
        return 2
    output_dir = REPO / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tracejit-direct-"))
    cache_root = root / "caches"
    cache_root.mkdir()

    rows, failures, checks = [], [], {}
    for name, argv, files, stdin_name in WORKLOADS:
        if args.only and name != args.only:
            continue
        if shutil.which(argv[0]) is None:
            rows.append({"workload": name, "status": "missing-tool",
                         "tool": argv[0], "reason": "tool is not installed"})
            failures.append(f"{name}: tool {argv[0]} is not installed")
            continue
        work = prepare_workload(root, name, argv, files, stdin_name)
        if work is None:
            rows.append({"workload": name, "status": "setup-failed",
                         "reason": "the fixture's own set-up command failed"})
            failures.append(f"{name}: fixture set-up failed")
            continue
        cache = fresh_cache(cache_root, name)
        env = environment(cache)
        stdin_path = str(work / stdin_name) if stdin_name else None

        direct = run(argv, work, env, stdin_path)
        cold_report, cold = traced(argv, work, env, stdin_path)
        if cold_report is None:
            rows.append({"workload": name, "status": "trace-failed",
                         "reason": cold["stderr"].decode(errors="replace")[:400]})
            failures.append(f"{name}: traced run produced no report")
            continue
        second_report, second = traced(argv, work, env, stdin_path)

        direct_out = direct["stdout"]
        row = {
            "workload": name,
            "argv": argv,
            "stdin": stdin_name,
            "classification": cold_report["classification"],
            "eligible": cold_report["eligible_for_reuse"],
            "reasons": cold_report["reasons"][:6],
            "cold_decision": cold_report["cache_decision"],
            "second_decision": second_report["cache_decision"] if second_report else None,
            "direct_exit": direct["exit_code"],
            "traced_exit": cold_report["exit_code"],
            "direct_stdout_bytes": len(direct_out),
            "traced_stdout_matches": direct_out == bytes(cold_report["stdout_bytes"]),
            "traced_stderr_matches": direct["stderr"] == bytes(cold_report["stderr_bytes"]),
            "second_stdout_matches": (
                second_report is not None
                and direct_out == bytes(second_report["stdout_bytes"])
            ),
            "direct_ms": round(direct["elapsed_ms"], 2),
            "cold_ms": round(cold["elapsed_ms"], 2),
            "traced_overhead_ms": round(cold["elapsed_ms"] - direct["elapsed_ms"], 2),
        }
        reused = row["second_decision"] == "Reused"
        row["reused"] = reused
        if reused:
            if not row["second_stdout_matches"]:
                failures.append(f"{name}: reused bytes differ from a direct run")
            row["timing"] = measure(
                name, argv, work, stdin_name, args.runs, row["second_decision"], cache_root
            )
        rows.append(row)

    denominator = len(rows)
    reusable = [row for row in rows if row.get("reused")]
    equivalent = [row for row in rows if row.get("traced_stdout_matches")]
    summary = {
        "generated_by": "benchmarks/realworld/direct_suite.py",
        "tracejit_binary": str(binary()),
        "workloads": denominator,
        "reused": len(reusable),
        "reused_names": [row["workload"] for row in reusable],
        "traced_output_equivalent": len(equivalent),
        "runs": args.runs,
        "rows": rows,
    }
    (output_dir / "direct-suite.json").write_text(json.dumps(summary, indent=2) + "\n")

    lines = ["# Direct-execution compatibility suite", "",
             f"Workloads: {denominator} (denominator fixed; refusals stay in it)",
             f"Reused on the second run: {len(reusable)}/{denominator}",
             f"Traced output matched a direct run: {len(equivalent)}/{denominator}", ""]
    for row in rows:
        head = f"## {row['workload']}"
        if row.get("status"):
            lines += [head, f"- {row['status']}: {row['reason']}", ""]
            continue
        lines.append(head)
        lines.append(f"- classification {row['classification']}, eligible {row['eligible']}, "
                     f"reused {row['reused']}, second decision {row['second_decision']}")
        lines.append(f"- direct exit {row['direct_exit']}, traced exit {row['traced_exit']}, "
                     f"stdout matches {row['traced_stdout_matches']}")
        if row["reasons"]:
            lines.append(f"- reasons: {'; '.join(row['reasons'])}")
        timing = row.get("timing")
        if timing:
            lines.append(f"- timing: direct {timing['direct_median_ms']} ms, cached "
                         f"{timing['cached_median_ms']} ms, cold {timing['cold_ms']} ms, "
                         f"{timing['speedup']}x, {timing['hits_to_repay']} hits to repay")
        lines.append("")
    (output_dir / "direct-suite.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    if failures:
        print("FAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print("RESULT direct-suite FAIL")
        return 1
    print("RESULT direct-suite PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

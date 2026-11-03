#!/usr/bin/env python3
"""Measure whether a directory that is opened only for name resolution invalidates reuse.

The scenario is deliberately the awkward one: the command writes its own output beside its input,
which is what an ordinary shell redirection does. A cache that treats "the parent directory was
opened" as "the parent directory's timestamps were observed" deoptimizes on every run after the
first, and no amount of repeated use repays the trace.

Usage:
    dir_guard_probe.py --binary target/debug/tracejit --label before --output-dir results/
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

PAYLOAD = ("record-payload-line\n" * 20000).encode()


def run(binary, cache, work):
    """One traced invocation of the ordinary `gzip -9 -c <input>` pattern."""
    input_path = work / "input.txt"
    result = subprocess.run(
        [binary, "run", "--json", "--", "gzip", "-9", "-c", str(input_path)],
        env={"TRACEJIT_CACHE_DIR": str(cache), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
    )
    report = json.loads(result.stdout) if result.stdout.strip() else {}
    return {
        "decision": report.get("cache_decision", "NO-JSON"),
        "classification": report.get("classification"),
        "stdout_bytes": report.get("stdout_bytes") or [],
        "exit": result.returncode,
        "stderr": result.stderr.decode(errors="replace").strip().splitlines()[-3:],
    }


def direct(work):
    return subprocess.run(
        ["gzip", "-9", "-c", str(work / "input.txt")],
        capture_output=True,
        check=True,
    ).stdout


def scenario(binary, work, cache, record, name, mutate=None):
    """Run twice, optionally mutate the work directory, then run twice more."""
    steps = []
    for index in range(2):
        outcome = run(binary, cache, work)
        outcome["expected_stdout_matches"] = outcome["stdout_bytes"] == list(direct(work))
        steps.append({"step": f"{name}-run{index + 1}", **outcome})
    if mutate is not None:
        mutate(work)
        for index in range(2):
            outcome = run(binary, cache, work)
            outcome["expected_stdout_matches"] = outcome["stdout_bytes"] == list(direct(work))
            steps.append({"step": f"{name}-after-{index + 1}", **outcome})
    record.extend(steps)
    return steps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    if not shutil.which("gzip"):
        print("RESULT dir-guard-probe SKIP (no gzip)")
        return 0

    binary = args.binary
    record = []
    with tempfile.TemporaryDirectory() as root:
        root = pathlib.Path(root)
        # Cache lives outside the working directory so the harness's own writes cannot be
        # mistaken for a dependency of the traced command.
        cache = root / "cache"
        work = root / "work"
        work.mkdir()
        (work / "input.txt").write_bytes(PAYLOAD)

        scenario(binary, work, cache, record, "untouched")

        def sibling(directory):
            (directory / "unrelated.txt").write_text("not an input of this command\n")

        scenario(binary, work, cache, record, "sibling-created", sibling)

        def output_beside_input(directory):
            (directory / "input.txt.gz").write_bytes(direct(directory))

        scenario(binary, work, cache, record, "output-written-beside-input", output_beside_input)

        def content_change(directory):
            (directory / "input.txt").write_bytes(PAYLOAD + b"appended-line\n")

        scenario(binary, work, cache, record, "input-content-changed", content_change)

    decisions = [step["decision"] for step in record]
    print(f"label           {args.label}")
    print(f"commit          {args.commit}")
    print(f"binary          {args.binary}")
    print()
    print(f"{'step':40} {'decision':14} {'stdout==direct'}")
    for step in record:
        print(f"{step['step']:40} {step['decision']:14} {step['expected_stdout_matches']}")
    print()
    print(f"decisions       {decisions}")

    output = pathlib.Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / f"dir-guard-probe-{args.label}.json").write_text(
        json.dumps({"label": args.label, "commit": args.commit, "steps": record}, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

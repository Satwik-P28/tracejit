#!/usr/bin/env python3
"""Direct-invocation real-world suite: does TraceJIT skip a useful command, correctly?

The nine-workload census in `census.py` invokes most workloads through `sh -c`, so it measures the
shell as well as the workload. This suite invokes each program directly, records what TraceJIT
classifies, and then exercises the full reuse contract on the first workload that is eligible.

Every assertion is on observable behaviour: the cached bytes must equal a direct run's bytes, an
input change must not replay the old bytes, and a hit must be positively reported as `Reused`.

Run: python3 benchmarks/realworld/direct_suite.py [--output-dir DIR]
Exit status is non-zero when any assertion fails or when the expected eligible workload is not
eligible, so the suite cannot report success by silently doing nothing.
"""

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

ROOT = Path(__file__).resolve().parents[2]

CANDIDATES = [
    ("gzip", ["gzip", "-9", "-c", "{input}"]),
    ("sort", ["sort", "-n", "{input}"]),
    ("base64", ["base64", "{input}"]),
    ("md5sum", ["md5sum", "{input}"]),
    ("tr", ["tr", "0-9", "x", "{input}"]),
    ("wc", ["wc", "-l", "{input}"]),
]


def run_json(tracejit: Path, argv: list[str], cwd: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(
        [str(tracejit), "run", "--json", "--", *argv],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
    )
    if not completed.stdout:
        raise RuntimeError(
            f"tracejit emitted no JSON for {' '.join(argv)}: {completed.stderr.decode()}"
        )
    return json.loads(completed.stdout)


def direct(argv: list[str], cwd: Path, env: dict[str, str]) -> bytes:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False).stdout


def cached_bytes(report: dict) -> bytes:
    return bytes(report.get("stdout_bytes") or [])


def timed(argv: list[str], cwd: Path, env: dict[str, str], runs: int) -> tuple[float, float]:
    samples = []
    for _ in range(runs):
        started = time.perf_counter_ns()
        subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.DEVNULL, check=False)
        samples.append((time.perf_counter_ns() - started) / 1e6)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(ROOT / "target" / "release" / "tracejit"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()

    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")

    scratch = Path(tempfile.mkdtemp(prefix="tracejit-direct-"))
    cache = scratch / "cache"
    source = scratch / "data.txt"
    with source.open("w", encoding="utf-8") as handle:
        for index in range(400_000):
            handle.write(f"record-{index:08d}-payload-{'y' * 20}\n")

    base_env = dict(os.environ)
    base_env.update({"TRACEJIT_CACHE_DIR": str(cache), "LC_ALL": "C"})
    failures: list[str] = []
    records: list[dict] = []

    print("# Direct-invocation compatibility\n")
    for name, template in CANDIDATES:
        if shutil.which(template[0]) is None:
            print(f"- `{name}`: SKIP (tool missing)")
            records.append({"name": name, "status": "tool-missing"})
            continue
        argv = [part.format(input=source) for part in template]
        completed = subprocess.run(
            [str(tracejit), "analyze", "--json", "--", *argv],
            cwd=scratch,
            env=base_env,
            capture_output=True,
            check=False,
        )
        report = json.loads(completed.stdout)
        eligible = bool(report.get("eligible_for_reuse"))
        print(
            f"- `{name}`: {report['classification']}, eligible={eligible}, "
            f"dependencies={report['dependency_count']}"
        )
        for reason in report.get("reasons", [])[:3]:
            print(f"  - {reason}")
        records.append(
            {
                "name": name,
                "classification": report["classification"],
                "eligible": eligible,
                "dependency_count": report["dependency_count"],
                "reasons": report.get("reasons", []),
            }
        )

    print("\n# Reuse contract for `gzip -9 -c`\n")
    shutil.rmtree(cache, ignore_errors=True)
    command = ["gzip", "-9", "-c", str(source)]
    expected = direct(command, scratch, base_env)
    first = run_json(tracejit, command, scratch, base_env)
    second = run_json(tracejit, command, scratch, base_env)

    checks = [
        ("classification is Guarded", first["classification"] == "Guarded"),
        ("recorded run matches direct", cached_bytes(first) == expected),
        ("second run reports Reused", second.get("cache_decision") == "Reused"),
        ("reused bytes match direct", cached_bytes(second) == expected),
    ]

    with source.open("a", encoding="utf-8") as handle:
        handle.write("appended-line\n")
    changed = direct(command, scratch, base_env)
    third = run_json(tracejit, command, scratch, base_env)
    checks.append(("content change alters output", changed != expected))
    checks.append(("content change deoptimizes", third.get("cache_decision") == "Deoptimized"))
    checks.append(("deoptimized run matches direct", cached_bytes(third) == changed))

    fourth = run_json(tracejit, command, scratch, base_env)
    checks.append(("entry reusable again", fourth.get("cache_decision") == "Reused"))
    checks.append(("reusable bytes match direct", cached_bytes(fourth) == changed))

    for label, ok in checks:
        print(f"- {'PASS' if ok else 'FAIL'}: {label}")
        if not ok:
            failures.append(label)

    print(f"\n# Timing ({args.runs} runs each)\n")
    shutil.rmtree(cache, ignore_errors=True)
    cold_started = time.perf_counter_ns()
    run_json(tracejit, command, scratch, base_env)
    cold_ms = (time.perf_counter_ns() - cold_started) / 1e6
    direct_median, direct_p95 = timed(command, scratch, base_env, args.runs)
    hit_median, hit_p95 = timed(
        [str(tracejit), "run", "--", *command], scratch, base_env, args.runs
    )
    speedup = direct_median / hit_median if hit_median else float("inf")
    saved = direct_median - hit_median
    repay = (cold_ms - hit_median) / saved if saved > 0 else float("inf")

    print(f"- direct: {direct_median:.2f} ms median, {direct_p95:.2f} ms p95")
    print(f"- cached: {hit_median:.2f} ms median, {hit_p95:.2f} ms p95")
    print(f"- cold: {cold_ms:.2f} ms (one sample)")
    print(f"- speedup: {speedup:.2f}x, saved {saved:.2f} ms, hits to repay {repay:.2f}")
    if speedup < 1.0:
        failures.append("cached reuse is slower than direct execution")

    summary = {
        "tracejit": str(tracejit),
        "input_bytes": source.stat().st_size,
        "candidates": records,
        "checks": {label: ok for label, ok in checks},
        "timing": {
            "direct_median_ms": direct_median,
            "direct_p95_ms": direct_p95,
            "cached_median_ms": hit_median,
            "cached_p95_ms": hit_p95,
            "cold_ms": cold_ms,
            "speedup": speedup,
            "saved_ms": saved,
            "hits_to_repay": repay,
            "runs": args.runs,
        },
        "failures": failures,
    }

    if args.output_dir:
        destination = Path(args.output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "direct-suite.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {destination / 'direct-suite.json'}")

    print("\nRESULT direct-suite " + ("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Timing for the two directory layouts that matter for ordinary use.

`isolated` keeps the command's output away from its input's directory. `same-dir` writes the output
beside the input after every run, exactly as `gzip -9 -c input.txt > input.txt.gz` does, and adds a
new unrelated sibling each run as well. Both layouts must report the same decisions; only the second
one used to pay a retrace on every output write.

Timing runs `tracejit run` without `--json`: serialising the captured stdout into the JSON report is
part of the measured wall time in that mode, which would attribute report formatting to the hit path.
"""

import argparse
import functools
import json
import pathlib
import random
import statistics
import subprocess
import tempfile
import time

SIZES = {
    "small": 480_000,
    "large": 6_000_000,
}


@functools.lru_cache(maxsize=None)
def payload(size):
    """Deterministic varied text, so compression cost reflects content and not repetition."""
    words = [
        b"alpha", b"beta", b"gamma", b"delta", b"epsilon", b"zeta", b"eta", b"theta",
        b"iota", b"kappa", b"lambda", b"mu", b"nu", b"xi", b"omicron", b"pi",
    ]
    rng = random.Random(20261103)
    count = size // 82 + 1
    flat = rng.choices(words, k=count * 12)
    lines = [b" ".join(flat[index : index + 12]) for index in range(0, len(flat), 12)]
    return b"\n".join(lines)[:size]


def direct(binary_input):
    start = time.perf_counter()
    result = subprocess.run(
        ["gzip", "-9", "-c", str(binary_input)], capture_output=True, check=True
    )
    return (time.perf_counter() - start) * 1000.0, result.stdout


def traced(binary, cache, input_path):
    start = time.perf_counter()
    result = subprocess.run(
        [binary, "run", "--", "gzip", "-9", "-c", str(input_path)],
        env={"TRACEJIT_CACHE_DIR": str(cache), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
    )
    elapsed = (time.perf_counter() - start) * 1000.0
    stderr = result.stderr.decode(errors="replace")
    return {
        "ms": elapsed,
        "stdout": result.stdout,
        "hit": "cache          HIT" in stderr,
        "exit": result.returncode,
    }


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def session(binary, label, runs, session_dir):
    results = []
    for size_name, size in SIZES.items():
        for layout in ("isolated", "same-dir"):
            with tempfile.TemporaryDirectory() as root:
                root = pathlib.Path(root)
                work = root / "work"
                work.mkdir()
                input_path = work / "input.txt"
                input_path.write_bytes(payload(size))
                cache = root / "cache"

                direct_ms, expected = [], None
                for _ in range(runs):
                    elapsed, stdout = direct(input_path)
                    direct_ms.append(elapsed)
                    expected = stdout

                cold = traced(binary, cache, input_path)
                warm = []
                for index in range(runs):
                    outcome = traced(binary, cache, input_path)
                    outcome["matches"] = outcome["stdout"] == expected
                    warm.append(outcome)
                    if layout == "same-dir":
                        # The command's own output, then an unrelated entry, both beside the input.
                        (work / "input.txt.gz").write_bytes(expected)
                        (work / f"unrelated-{index}.txt").write_bytes(b"not an input\n")

                direct_median = statistics.median(direct_ms)
                warm_ms = [entry["ms"] for entry in warm]
                warm_median = statistics.median(warm_ms)
                cold_penalty = cold["ms"] - direct_median
                saving = direct_median - warm_median
                results.append(
                    {
                        "size": size_name,
                        "bytes": size,
                        "layout": layout,
                        "runs": runs,
                        "direct_median_ms": round(direct_median, 2),
                        "direct_p95_ms": round(percentile(direct_ms, 0.95), 2),
                        "cold_ms": round(cold["ms"], 2),
                        "cold_output_matches": cold["stdout"] == expected,
                        "warm_median_ms": round(warm_median, 2),
                        "warm_p95_ms": round(percentile(warm_ms, 0.95), 2),
                        "warm_hits": sum(1 for entry in warm if entry["hit"]),
                        "warm_output_matches": sum(1 for entry in warm if entry["matches"]),
                        "speedup": round(direct_median / warm_median, 2) if warm_median else None,
                        "saved_per_run_ms": round(saving, 2),
                        "tracing_penalty_ms": round(cold_penalty, 2),
                        "hits_to_repay": round(cold_penalty / saving, 2) if saving > 0 else None,
                        "cumulative_saved_ms": round(saving * sum(1 for e in warm if e["hit"]), 2),
                        "invalidation_rate": round(
                            1.0 - sum(1 for entry in warm if entry["hit"]) / len(warm), 3
                        ),
                        "exit_codes": sorted({entry["exit"] for entry in warm}),
                    }
                )
                print(
                    f"{label:7} {size_name:5} {layout:9} direct {direct_median:8.2f} "
                    f"warm {warm_median:7.2f} ms  hits {results[-1]['warm_hits']}/{runs} "
                    f"speedup {results[-1]['speedup']}x  repay {results[-1]['hits_to_repay']}"
                )
                assert results[-1]["warm_output_matches"] == runs, results[-1]
                assert results[-1]["exit_codes"] == [0], results[-1]

    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "dir-layout.json").write_text(json.dumps(results, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()
    results = session(args.binary, args.label, args.runs, pathlib.Path(args.output_dir) / args.label)
    failures = [row for row in results if row["invalidation_rate"] != 0.0]
    print(f"commit {args.commit}")
    print(f"RESULT dir-layout {'PASS' if not failures else 'FAIL'} ({len(results)} cells)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase R: native candidate-order benchmark.

Compares production newest-first against the experimental orders on the same host,
workload and cache, using the release binary and a guarded C fixture.

    research/phase_r/bench_candidates.py [--runs N]

Writes research/phase_r/results/candidates.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BINARY = REPO / "target/release/tracejit"
FIXTURE = REPO / "tests/fixtures/fixture_driver.c"
RESULTS = HERE / "results"

MODES = ["newest", "last-success", "hit-count"]


def compile_fixture(directory: Path) -> Path:
    out = directory / "fixture-driver"
    subprocess.run(
        ["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread", str(FIXTURE), "-o", str(out)],
        check=True,
    )
    return out


def base_env(cache: Path) -> dict:
    env = os.environ.copy()
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    # glibc seeds tcache with getrandom on first allocation; disable so the fixture stays
    # classifiable as Guarded, matching the integration fixtures.
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    return env


def invoke(cache: Path, work: Path, binary: Path, mode: str | None) -> tuple[float, dict]:
    env = base_env(cache)
    if mode is not None:
        env["TRACEJIT_CANDIDATE_ORDER"] = mode
    started = time.perf_counter()
    proc = subprocess.run(
        [str(BINARY), "run", "--json", "--", str(binary), "plain_file_read", str(work)],
        capture_output=True,
        env=env,
        cwd=work,
        close_fds=True,
    )
    elapsed_ms = (time.perf_counter() - started) * 1e3
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    return elapsed_ms, json.loads(proc.stdout)


def state_bytes(index: int, size: int) -> bytes:
    seed = f"state-{index}\n".encode()
    filler = bytes(((i * 31 + index * 17) % 251 for i in range(size)))
    return seed + filler


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = (len(ordered) - 1) * q
    low, high = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def scenario_sequence(name: str, states: int, runs: int) -> list[int]:
    if name == "alternate2":
        return [i % 2 for i in range(runs)]
    if name == "cycle4":
        return [i % min(4, states) for i in range(runs)]
    if name == "cycle8":
        return [i % min(8, states) for i in range(runs)]
    if name == "skew2":
        # 80/20 deterministic schedule: four A then one B, repeated
        pattern = [0, 0, 0, 0, 1]
        return [pattern[i % len(pattern)] for i in range(runs)]
    if name == "single":
        return [0] * runs
    raise ValueError(name)


def bootstrap_ci_median(values: list[float], iterations: int = 2000, seed: int = 7):
    """Percentile bootstrap 95% CI for the median of paired run differences."""
    rng = random.Random(seed)
    n = len(values)
    medians = []
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        medians.append(statistics.median(sample))
    medians.sort()
    return medians[int(0.025 * iterations)], medians[int(0.975 * iterations) - 1]


def measure(name: str, states: int, mode: str, runs: int, size: int, root: Path) -> dict:
    work = root / f"work-{name}-{mode}"
    cache = root / f"cache-{name}-{mode}"
    work.mkdir(parents=True)
    cache.mkdir()
    binary = compile_fixture(root)
    payloads = [state_bytes(i, size) for i in range(states)]

    def write_state(index: int) -> None:
        (work / "input.txt").write_bytes(payloads[index])

    def check(index: int) -> None:
        restored = (work / "output.txt").read_bytes()
        if restored != payloads[index]:
            raise AssertionError(f"{name}/{mode}: restored output differs for state {index}")

    # Establish one record and one success per state, in a fixed order for every mode.
    for index in range(states):
        write_state(index)
        for _ in range(2):
            _, report = invoke(cache, work, binary, mode)
        check(index)

    sequence = scenario_sequence(name, states, runs)
    warmups = 10
    for index in sequence[:warmups]:
        write_state(index)
        invoke(cache, work, binary, mode)
        check(index)

    samples: list[float] = []
    examined: list[int] = []
    kinds: dict[str, int] = {}
    for index in sequence[warmups:]:
        write_state(index)
        elapsed, report = invoke(cache, work, binary, mode)
        check(index)
        samples.append(elapsed)
        examined.append(int(report.get("candidates_examined", 0)))
        kinds[report["kind"]] = kinds.get(report["kind"], 0) + 1

    return {
        "scenario": name,
        "mode": mode,
        "states": states,
        "runs": len(samples),
        "median_ms": statistics.median(samples),
        "p95_ms": percentile(samples, 0.95),
        "mean_ms": statistics.fmean(samples),
        "mean_candidates_examined": statistics.fmean(examined),
        "kinds": kinds,
        "all_reused": kinds.get("Reused", 0) == len(samples),
        "samples": samples,
    }


def direct_baseline(root: Path, runs: int, size: int) -> dict:
    work = root / "work-direct"
    work.mkdir(parents=True)
    binary = compile_fixture(root)
    payload = state_bytes(0, size)
    (work / "input.txt").write_bytes(payload)
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        subprocess.run([str(binary), "plain_file_read", str(work)], cwd=work, check=True)
        samples.append((time.perf_counter() - started) * 1e3)
    return {
        "scenario": "direct",
        "mode": "direct",
        "median_ms": statistics.median(samples),
        "p95_ms": percentile(samples, 0.95),
        "mean_ms": statistics.fmean(samples),
        "runs": len(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=140)
    parser.add_argument("--size", type=int, default=4 * 1024 * 1024)
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="tracejit-phase-r-"))
    try:
        rows = []
        for name, states in (
            ("single", 1),
            ("alternate2", 2),
            ("cycle8", 8),
            ("skew2", 2),
        ):
            per_mode = {}
            for mode in MODES:
                row = measure(name, states, mode, args.runs, args.size, root)
                per_mode[mode] = row
                rows.append(row)
                print(
                    f"{name:10s} {mode:12s} median={row['median_ms']:8.3f} ms "
                    f"p95={row['p95_ms']:8.3f} examined={row['mean_candidates_examined']:.3f} "
                    f"reused={row['kinds'].get('Reused', 0)}/{row['runs']}"
                )
            base = per_mode["newest"]["samples"]
            for mode in MODES[1:]:
                other = per_mode[mode]["samples"]
                diffs = [a - b for a, b in zip(other, base)]
                low, high = bootstrap_ci_median(diffs)
                per_mode[mode]["median_diff_vs_newest_ms"] = statistics.median(diffs)
                per_mode[mode]["diff_ci95_ms"] = [low, high]
                print(
                    f"{'':10s} {mode:12s} paired median diff vs newest = "
                    f"{statistics.median(diffs):+7.3f} ms [{low:+.3f}, {high:+.3f}]"
                )
        for row in rows:
            row.pop("samples", None)
        direct = direct_baseline(root, max(30, args.runs // 4), args.size)
        print(f"{'direct':10s} {'-':12s} median={direct['median_ms']:8.3f} ms")
        payload = {
            "binary": str(BINARY),
            "input_bytes": args.size,
            "runs_per_cell": args.runs,
            "host": {
                "kernel": os.uname().release,
                "machine": os.uname().machine,
            },
            "rows": rows,
            "direct": direct,
        }
        (RESULTS / "candidates.json").write_text(json.dumps(payload, indent=2))
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

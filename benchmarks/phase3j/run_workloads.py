#!/usr/bin/env python3
"""Measure when controlled reuse amortizes on CPU-heavy Python workloads.

This is not a native-equivalence claim. Each controlled output is compared
byte-for-byte with a native run of the same input, and every reuse is required
to report `Reused`. The workloads are pure standard-library Python so the
audited interpreter does not need third-party extensions.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACEJIT = ROOT / "target/release/tracejit"
PYTHON = Path("/usr/bin/python3.12")
WORKLOADS = ROOT / "benchmarks/phase3j/workloads"
RESULTS = ROOT / "benchmarks/results/phase3j"
ENV = {
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "MALLOC_ARENA_MAX": "1",
}
CONTRACTS = ("python-runtime-v1", "python-runtime-v2")
DIRECT_RUNS = 5
COLD_RUNS = 2
WARM_RUNS = 8


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], env: dict[str, str], timeout: int = 120):
    started = time.perf_counter_ns()
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=timeout,
        close_fds=True,
    )
    result.wall_ns = time.perf_counter_ns() - started
    return result


def report(result) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def make_dataset(work: Path) -> dict[str, Path]:
    heavy = work / "transactions.csv"
    with heavy.open("w", encoding="utf-8") as handle:
        handle.write("transaction_id,account,amount_cents,score\n")
        for index in range(120_000):
            handle.write(
                f"t{index:07d},a{index % 64:03d},"
                f"{(index * 37) % 100_000},{index % 1000}\n"
            )
    image = work / "input.ppm"
    width, height = 320, 240
    body = bytes(
        (x * 7 + y * 11 + channel * 3) % 256
        for y in range(height)
        for x in range(width)
        for channel in range(3)
    )
    image.write_bytes(b"P6\n%d %d\n255\n" % (width, height) + body)
    return {"heavy": heavy, "image": image}


def specs(work: Path) -> dict[str, dict]:
    return {
        "heavy_transform": {
            "script": WORKLOADS / "heavy_transform.py",
            "input": work / "transactions.csv",
            "output": work / "heavy.json",
            "invalidate": "append",
        },
        "image_convolution": {
            "script": WORKLOADS / "image_convolution.py",
            "input": work / "input.ppm",
            "output": work / "image.ppm",
            "invalidate": "pixel",
        },
    }


def direct_command(spec: dict) -> list[str]:
    return [str(PYTHON), str(spec["script"]), str(spec["input"]), str(spec["output"])]


def target_command(spec: dict, contract: str) -> list[str]:
    return [
        str(TRACEJIT),
        "run",
        "--json",
        "--contract",
        contract,
        "--",
        *direct_command(spec),
    ]


def invalidate(spec: dict) -> None:
    path = spec["input"]
    data = bytearray(path.read_bytes())
    if spec["invalidate"] == "append":
        data.extend(b"t9999999,a999,1,1\n")
    else:
        # Change one byte in the pixel payload, after the PPM header.
        offset = data.index(b"\n", data.index(b"\n", data.index(b"\n") + 1) + 1) + 1
        data[offset] ^= 0x01
    path.write_bytes(data)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tracejit-phase3j-workloads-"))
    make_dataset(work)
    original = {
        "heavy": (work / "transactions.csv").read_bytes(),
        "image": (work / "input.ppm").read_bytes(),
    }
    output: dict = {
        "phase": "3J",
        "python": str(PYTHON),
        "contracts": CONTRACTS,
        "workloads": {},
        "notes": [
            "direct and target wall times include CPython/TraceJIT process startup",
            "cold is a fresh cache; warm is a steady hit after one decision-persist hit",
            "outputs are compared byte-for-byte with native execution for the same input",
            "break_even is derived from wall medians and is an estimate, not a guarantee",
        ],
    }
    try:
        for workload, spec in specs(work).items():
            output["workloads"][workload] = {}
            direct_values = []
            direct_hash = ""
            for _ in range(DIRECT_RUNS):
                if spec["output"].exists():
                    spec["output"].unlink()
                result = run(
                    direct_command(spec),
                    ENV,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"{workload} direct failed: {result.stderr}")
                direct_values.append(result.wall_ns)
                direct_hash = digest(spec["output"])
            output["workloads"][workload]["direct"] = {
                "runs_ns": direct_values,
                "median_ns": int(statistics.median(direct_values)),
                "output_sha256": direct_hash,
            }

            for contract in CONTRACTS:
                spec["input"].write_bytes(original["heavy" if workload == "heavy_transform" else "image"])
                cache_root = work / f"cache-{workload}-{contract}"
                shutil.rmtree(cache_root, ignore_errors=True)
                cold_runs = []
                for cold_index in range(COLD_RUNS):
                    cold_cache = cache_root / f"cold-{cold_index}"
                    if spec["output"].exists():
                        spec["output"].unlink()
                    result = run(
                        target_command(spec, contract),
                        {**ENV, "TRACEJIT_CACHE_DIR": str(cold_cache)},
                    )
                    parsed = report(result)
                    cold_runs.append(
                        {
                            "kind": parsed.get("kind"),
                            "runtime_ns": parsed.get("runtime_ns"),
                            "wall_ns": result.wall_ns,
                            "exit_code": parsed.get("exit_code"),
                            "output_sha256": digest(spec["output"])
                            if spec["output"].exists()
                            else None,
                        }
                    )
                warm_cache = cache_root / f"cold-{COLD_RUNS - 1}"
                first_hit = run(
                    target_command(spec, contract),
                    {**ENV, "TRACEJIT_CACHE_DIR": str(warm_cache)},
                )
                first_parsed = report(first_hit)
                warm_runs = []
                for _ in range(WARM_RUNS):
                    result = run(
                        target_command(spec, contract),
                        {**ENV, "TRACEJIT_CACHE_DIR": str(warm_cache)},
                    )
                    parsed = report(result)
                    warm_runs.append(
                        {
                            "kind": parsed.get("kind"),
                            "runtime_ns": parsed.get("runtime_ns"),
                            "wall_ns": result.wall_ns,
                            "output_sha256": digest(spec["output"]),
                        }
                    )

                # Invalidate a byte of the real input and require both a new
                # native-equivalent output and a re-establishable reusable record.
                invalidate(spec)
                direct_changed = run(direct_command(spec), ENV)
                if direct_changed.returncode != 0:
                    raise RuntimeError(
                        f"{workload} changed-input direct failed: {direct_changed.stderr}"
                    )
                changed_hash = digest(spec["output"])
                invalidated = run(
                    target_command(spec, contract),
                    {**ENV, "TRACEJIT_CACHE_DIR": str(warm_cache)},
                )
                invalidated_parsed = report(invalidated)
                invalidated_hash = digest(spec["output"])
                recovered = run(
                    target_command(spec, contract),
                    {**ENV, "TRACEJIT_CACHE_DIR": str(warm_cache)},
                )
                recovered_parsed = report(recovered)

                direct_median = int(statistics.median(direct_values))
                warm_median = int(
                    statistics.median(item["wall_ns"] for item in warm_runs)
                )
                cold_median = int(statistics.median(item["wall_ns"] for item in cold_runs))
                delta = direct_median - warm_median
                break_even_runs = (
                    None
                    if delta <= 0
                    else int((cold_median + delta - 1) // delta)
                )
                output["workloads"][workload][contract] = {
                    "cold": cold_runs,
                    "first_hit": {
                        "kind": first_parsed.get("kind"),
                        "runtime_ns": first_parsed.get("runtime_ns"),
                        "wall_ns": first_hit.wall_ns,
                    },
                    "warm": {
                        "runs": warm_runs,
                        "wall_ns": int(
                            statistics.median(item["wall_ns"] for item in warm_runs)
                        ),
                        "runtime_ns": int(
                            statistics.median(
                                item["runtime_ns"] for item in warm_runs
                            )
                        ),
                        "all_reused": all(
                            item["kind"] == "Reused" for item in warm_runs
                        ),
                    },
                    "invalidation": {
                        "kind": invalidated_parsed.get("kind"),
                        "runtime_ns": invalidated_parsed.get("runtime_ns"),
                        "wall_ns": invalidated.wall_ns,
                        "output_matches_direct": invalidated_hash == changed_hash,
                        "output_sha256": invalidated_hash,
                        "direct_output_sha256": changed_hash,
                        "recovered_kind": recovered_parsed.get("kind"),
                        "recovered_runtime_ns": recovered_parsed.get("runtime_ns"),
                    },
                    "equivalence": {
                        "warm_output_matches_direct": all(
                            item["output_sha256"] == direct_hash
                            for item in warm_runs
                        )
                        and cold_runs[-1]["output_sha256"] == direct_hash,
                        "direct_output_sha256": direct_hash,
                    },
                    "break_even": {
                        "additional_runs_after_cold": break_even_runs,
                        "complete_runs_including_cold": (
                            None if break_even_runs is None else 1 + break_even_runs
                        ),
                        "cold_wall_ns": cold_median,
                        "warm_wall_ns": warm_median,
                        "direct_wall_ns": direct_median,
                    },
                }
    finally:
        shutil.rmtree(work, ignore_errors=True)

    destination = RESULTS / "cpu-workloads.json"
    destination.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(destination)
    for workload, values in output["workloads"].items():
        print(workload, "direct", values["direct"]["median_ns"])
        for contract in CONTRACTS:
            item = values[contract]
            print(
                " ",
                contract,
                "cold",
                item["break_even"]["cold_wall_ns"],
                "warm",
                item["warm"]["wall_ns"],
                "reused",
                item["warm"]["all_reused"],
                "equal",
                item["equivalence"]["warm_output_matches_direct"],
                "break-even runs",
                item["break_even"]["complete_runs_including_cold"],
                "invalidation",
                item["invalidation"]["kind"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

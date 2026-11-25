#!/usr/bin/env python3
"""Phase AE: economics of the measured matrix — no hand-written numbers.

Reads ``benchmarks/results/phaseae/matrix.json`` and emits, to stdout and to
``benchmarks/results/phaseae/economics.json``:

* per (workload, arm) cold-inclusive totals and steady-state totals per session size,
* per-invocation median costs and a bootstrap 95 % interval over invocations,
* the *measured* break-even (smallest session where the cold-inclusive total is no larger
  than native execution of the same session), and the *model* break-even from the measured
  cold/hit/direct costs (integer ceil, see ``competitive_matrix.break_even``),
* the reuse classification at a reference size: both engines reused / only TraceJIT /
  only Firebuild / neither.

Everything printed here is regenerated from raw samples; the documents quote this output.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

import competitive_matrix as matrix  # noqa: E402

# Arm ids for the competitor are ``<label>-<configuration>`` where the label starts with the
# ``fb`` prefix and the version (``fb082``, ``fb862``, ``fb0861``, ...).  Matching a fixed list
# of versions silently miscounted a new arm as a TraceJIT arm, which inverted the reuse
# classification for that row; the prefix test is version-agnostic and is pinned by a test.
FIREBUILD_ARM = re.compile(r"^fb\d")


def is_firebuild(arm: str) -> bool:
    return FIREBUILD_ARM.match(arm) is not None


def cells(payload: dict) -> dict:
    table: dict = {}
    for row in payload["rows"]:
        key = (row["workload"], row["arm"], row["mode"], row["size"])
        table.setdefault(key, []).append(row)
    return table


def medians(rows: list[dict], field: str = "wall_ns") -> list[int]:
    values = []
    for row in rows:
        values.extend(record[field] for record in row["invocations"])
    return values


def bootstrap_ci(values: list[int], rounds: int = 2000, seed: int = 7) -> tuple[int, int]:
    if len(values) < 2:
        return (values[0], values[0]) if values else (0, 0)
    rng = random.Random(seed)
    medians_ = []
    for _ in range(rounds):
        sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
        medians_.append(statistics.median(sample))
    medians_.sort()
    return int(medians_[int(0.025 * rounds)]), int(medians_[int(0.975 * rounds) - 1])


def session_total(rows: list[dict]) -> int:
    return int(statistics.median(row["session"]["command_ns"] for row in rows))


def analyze(payload: dict, reference_size: int) -> dict:
    table = cells(payload)
    workloads = sorted({key[0] for key in table})
    arms = sorted({key[1] for key in table})
    sizes = sorted({key[3] for key in table})

    out = {"reference_size": reference_size, "workloads": {}, "classification": []}
    for workload in workloads:
        entry: dict = {"arms": {}, "classification": {}}
        for arm in arms:
            per_mode = {}
            for mode in ("cold", "steady"):
                series = []
                for size in sizes:
                    rows = table.get((workload, arm, mode, size))
                    if not rows:
                        continue
                    invocations = medians(rows)
                    hit_only = [record["wall_ns"] for row in rows for record in row["invocations"]
                                if record["decision"] == "hit"]
                    miss_only = [record["wall_ns"] for row in rows for record in row["invocations"]
                                 if record["decision"] != "hit"]
                    hits = len(hit_only)
                    series.append({
                        "size": size,
                        "session_ns": session_total(rows),
                        "per_invocation_median_ns": int(statistics.median(invocations)),
                        "per_invocation_ci95_ns": list(bootstrap_ci(invocations)),
                        "hit_median_ns": int(statistics.median(hit_only)) if hit_only else None,
                        "hit_ci95_ns": list(bootstrap_ci(hit_only)) if hit_only else None,
                        "miss_median_ns": int(statistics.median(miss_only)) if miss_only else None,
                        "hits": hits,
                        "invocations": sum(len(row["invocations"]) for row in rows),
                        "repeats": len(rows),
                        "cache_bytes": max(row["cache_bytes_final"] for row in rows),
                    })
                per_mode[mode] = series
            entry["arms"][arm] = per_mode

            # Break-even, both measured and modelled, using the reference size's samples.
            # Native has no cache, so a break-even against itself is meaningless.
            if arm == "native":
                continue
            cold = table.get((workload, arm, "cold", reference_size))
            native_cold = table.get((workload, "native", "cold", reference_size))
            # Aggregate over every repeat.  Using one arbitrary row made the published
            # break-even depend on which repeat happened to sort first: an arm whose reuse
            # first appeared in a later repeat silently lost its break-even block.
            if cold and native_cold and any(
                record["decision"] == "hit"
                for row in cold for record in row["invocations"]
            ):
                cold_cost = int(statistics.median(row["invocations"][0]["wall_ns"] for row in cold))
                hit_samples = [record["wall_ns"] for row in cold
                               for record in row["invocations"] if record["decision"] == "hit"]
                hit_cost = int(statistics.median(hit_samples)) if hit_samples else cold_cost
                direct = int(statistics.median(record["wall_ns"] for row in native_cold
                                               for record in row["invocations"]))
                entry["arms"][arm]["break_even"] = {
                    "reference_size": reference_size,
                    "cold_ns": cold_cost,
                    "hit_ns": hit_cost,
                    "direct_ns": direct,
                    "model": matrix.break_even(cold_cost, hit_cost, direct),
                    "measured": measured_break_even(table, workload, arm, sizes),
                }
        # Reuse classification at the reference size, per *configuration*: an engine that
        # reuses only when its skip list is cleared is not the same claim as one that reuses
        # out of the box, so the arm names are recorded and reported.
        def reusing(predicate) -> list[str]:
            found = []
            for arm in arms:
                if not predicate(arm):
                    continue
                if any(record["decision"] == "hit"
                       for row in table.get((workload, arm, "cold", reference_size), [])
                       for record in row["invocations"]):
                    found.append(arm)
            return found

        # ``native`` is the baseline, not a TraceJIT arm: counting it would classify every
        # row that contains a native HIT as "both".
        tracejit_arms = reusing(lambda arm: not is_firebuild(arm) and arm != "native")
        firebuild_arms = reusing(is_firebuild)
        category = ("both" if tracejit_arms and firebuild_arms else
                    "tracejit-only" if tracejit_arms else
                    "firebuild-only" if firebuild_arms else "neither")
        entry["classification"] = {
            "tracejit_reused_by": tracejit_arms,
            "firebuild_reused_by": firebuild_arms,
            "category": category,
        }
        out["workloads"][workload] = entry
        out["classification"].append({"workload": workload, "category": category})
    return out


def measured_break_even(table: dict, workload: str, arm: str, sizes: list[int]) -> dict:
    """Smallest session length whose cold-inclusive total is not worse than native."""

    per_size = {}
    for size in sizes:
        cold = table.get((workload, arm, "cold", size))
        native = table.get((workload, "native", "cold", size))
        if not cold or not native:
            continue
        arm_ns = session_total(cold)
        native_ns = session_total(native)
        per_size[size] = {
            "arm_ns": arm_ns,
            "native_ns": native_ns,
            "ratio": arm_ns / native_ns,
        }
    first = next((size for size in sorted(per_size) if per_size[size]["ratio"] <= 1.0), None)
    return {"first_profitable_size": first, "per_size": per_size}


def markdown(analysis: dict) -> str:
    lines = []
    for workload, entry in analysis["workloads"].items():
        lines.append(f"### {workload}")
        lines.append("")
        lines.append("| arm | mode | n | session ms | per-invocation ms (95 % CI) | hits | cache MB |")
        lines.append("| --- | --- | ---: | ---: | --- | ---: | ---: |")
        for arm, modes in entry["arms"].items():
            for mode, series in modes.items():
                if mode not in ("cold", "steady"):
                    continue
                for point in series:
                    low, high = point["per_invocation_ci95_ns"]
                    lines.append(
                        f"| {arm} | {mode} | {point['size']} | {point['session_ns']/1e6:.1f} | "
                        f"{point['per_invocation_median_ns']/1e6:.1f} "
                        f"({low/1e6:.1f}–{high/1e6:.1f}) | {point['hits']} | "
                        f"{point['cache_bytes']/1e6:.2f} |"
                    )
        lines.append("")
        back = entry["arms"]
        for arm, data in back.items():
            break_even = data.get("break_even")
            if not break_even:
                continue
            model = break_even["model"]["integer_invocations"]
            measured = break_even["measured"]["first_profitable_size"]
            lines.append(
                f"- {arm}: cold {break_even['cold_ns']/1e6:.1f} ms, hit "
                f"{break_even['hit_ns']/1e6:.1f} ms, direct {break_even['direct_ns']/1e6:.1f} ms; "
                f"model n* = {model}, measured first profitable session = {measured}"
            )
        lines.append(f"- reuse at n={analysis['reference_size']}: {entry['classification']['category']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=REPO / "benchmarks/results/phaseae/matrix.json")
    parser.add_argument("--output", type=Path, default=REPO / "benchmarks/results/phaseae/economics.json")
    parser.add_argument("--reference-size", type=int, default=25)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)

    payload = json.loads(args.results.read_text())
    analysis = analyze(payload, args.reference_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n")
    print(markdown(analysis) if args.markdown else json.dumps(
        {w: e["classification"] for w, e in analysis["workloads"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))

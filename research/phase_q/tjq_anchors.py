"""Measured anchors for Phase Q, extracted from committed benchmark results.

No number in this module is invented: every value is read from a JSON artifact in
this repository, or fitted from those values (the fit is reported with its residual).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

LATENCY = REPO / "benchmarks/results/phase3c/latency.json"
CANDIDATES = REPO / "benchmarks/results/phase3c/candidate-scaling.json"
WARM_HIT = REPO / "benchmarks/results/final_stab_pr4/warm_hit_phase_breakdown.json"
CENSUS = REPO / "benchmarks/results/phase3c/census-native/census.json"
ADMISSION = REPO / "benchmarks/results/phase_k9/admission-eval.json"


@dataclass
class Anchors:
    # Guard-set shape of the measured bzip2 asset workload (Phase 3C, native run).
    guard_counts: list[int]
    guard_validation_ms_median: float
    hit_wall_ms_median: float
    deopt_wall_ms_median: float
    cold_wall_ms_median: float
    baseline_runtime_ms: float
    dependency_count: int
    # Measured deopt: which guard index failed out of how many were checked.
    transition_failed_at: int
    transition_checked: int
    # Candidate scaling: bound -> retained candidates and wall medians.
    candidate_bounds: list[int]
    candidate_target_ms: list[float]
    candidate_newest_ms: list[float]
    candidate_miss_ms: list[float]
    # Linear fit wall_ms = base_ms + per_candidate_ms * depth over target medians.
    candidate_base_ms: float
    candidate_per_validation_ms: float
    candidate_fit_r2: float
    # Admission matrix recorded by the product harness (Phase K9).
    admission_policies: list[dict]
    admission_oracle_ns: int
    warm_hit_phases_ms: dict[str, float]


def _median(values):
    return float(statistics.median(values))


def _guard_counts(row) -> dict:
    """Stable rows carry a JSON object; transition rows carry a Rust Debug string."""
    guards = row["report"]["guards"]
    if isinstance(guards, dict):
        return guards
    import re

    checked = re.search(r"checked: (\d+)", guards or "")
    passed = re.search(r"passed: (\d+)", guards or "")
    return {
        "checked": int(checked.group(1)) if checked else 0,
        "passed": int(passed.group(1)) if passed else 0,
    }


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 1.0
    return intercept, slope, r2


def load_anchors() -> Anchors:
    lat = json.loads(LATENCY.read_text())
    cand = json.loads(CANDIDATES.read_text())
    warm = json.loads(WARM_HIT.read_text())
    adm = json.loads(ADMISSION.read_text())

    stable_rows = [row for group in lat["stable"] for row in group["rows"]]
    guard_counts = sorted({_guard_counts(row)["checked"] for row in stable_rows})
    guard_ms = _median(
        [row["phases_ns"]["guard_validation_ns"] for row in stable_rows]
    ) / 1e6

    transition_rows = lat["transition"]["rows"]
    checked = [_guard_counts(row)["checked"] for row in transition_rows]
    # A first-failure guard report counts the guard that failed, so checked is the
    # failing position and passed = checked - 1 on the transition rows.
    failed_at = checked[0]

    bounds = [b["bound"] for b in cand["bounds"]]
    target_ms = [b["target_ms_median"] for b in cand["bounds"]]
    newest_ms = [b["newest_ms_median"] for b in cand["bounds"]]
    miss_ms = [b["miss_ms_median"] for b in cand["bounds"]]
    base, per, r2 = _fit([float(b) for b in bounds], target_ms)

    warm_phases = {
        k: round(float(v), 4) for k, v in warm["phases_ms_median"].items()
    }

    return Anchors(
        guard_counts=guard_counts,
        guard_validation_ms_median=round(guard_ms, 4),
        hit_wall_ms_median=round(float(lat["summary"]["stable_independent"]["wall_ms_median"]), 4),
        deopt_wall_ms_median=round(float(lat["summary"]["transition"]["wall_ms_median"]), 4),
        cold_wall_ms_median=round(float(lat["summary"]["cold"]["wall_ms_median"]), 4),
        baseline_runtime_ms=round(float(stable_rows[0]["report"]["baseline_runtime_ns"]) / 1e6, 4),
        dependency_count=int(stable_rows[0]["report"]["dependency_count"]),
        transition_failed_at=int(failed_at),
        transition_checked=int(checked[0]),
        candidate_bounds=bounds,
        candidate_target_ms=target_ms,
        candidate_newest_ms=newest_ms,
        candidate_miss_ms=miss_ms,
        candidate_base_ms=round(base, 4),
        candidate_per_validation_ms=round(per, 4),
        candidate_fit_r2=round(r2, 5),
        admission_policies=adm["policies"],
        admission_oracle_ns=int(adm["policies"][0]["oracle_ns"]),
        warm_hit_phases_ms=warm_phases,
    )


def census_guard_shape() -> list[dict]:
    """Per-workload dependency/effect counts, used only for problem-size context."""
    census = json.loads(CENSUS.read_text())
    rows = []
    for w in census["workloads"]:
        rows.append(
            {
                "name": w["name"],
                "dependency_count": w.get("dependency_count"),
                "reads": w.get("effect_counts", {}).get("reads"),
                "eligible": w.get("eligible_for_reuse"),
            }
        )
    return rows


if __name__ == "__main__":
    anchors = load_anchors()
    print(json.dumps(asdict(anchors), indent=2))

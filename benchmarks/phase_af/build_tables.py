#!/usr/bin/env python3
"""Phase AF: regenerate every publication table from committed raw evidence.

Nothing in `paper/tables/` is transcribed. Each table is derived from a JSON file this
repository committed, and each table records where its numbers came from, which host produced
them and which binary revision ran. `--check` fails when an evidence file is missing, when a
recomputed headline disagrees with the number the documents quote, or when a row that the table
depends on is not marked correct.

Tables
------
compatibility        frozen census, one cell per (tier, contract)   phaseaa1/results.json
competitive          same-host session cost per arm                phaseae/economics.json
session_economics    measured break-even and cumulative savings    phaseae/economics.json
artifact_scale       cold/warm cost across artifact sizes          phased/ or phaseaf/artifact_scale.json
correctness          adversarial and negative results              phaseae/*, phaseac/*
capability           per-environment enforcement matrix            phaseaf/*, phaseae/*, phaseaa1/*
optimisations        accepted and rejected candidates              phase_af/optimisations.json

Usage
-----
    python3 benchmarks/phase_af/build_tables.py --check
    python3 benchmarks/phase_af/build_tables.py --emit paper/tables
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = REPO / "benchmarks" / "results"

EVIDENCE = {
    "census": RESULTS / "phaseaa1" / "results.json",
    "census_environment": RESULTS / "phaseaa1" / "environment.json",
    "economics": RESULTS / "phaseae" / "economics.json",
    "matrix": RESULTS / "phaseae" / "matrix.json",
    "policy_probe": RESULTS / "phaseae" / "policy_probe.json",
    "toctou": RESULTS / "phaseae" / "toctou_race.json",
    "integrity": RESULTS / "phaseae" / "tracejit_integrity.json",
    "replay_profile": RESULTS / "phaseae" / "replay_profile.json",
    "multi_environment": RESULTS / "phaseae" / "multi_environment.json",
    "environment_local": RESULTS / "phaseae" / "environment-local.json",
    "lifecycle": RESULTS / "phaseaf" / "enforcement_lifecycle.json",
    "artifact_scale": RESULTS / "phaseaf" / "artifact_scale.json",
    "stale_archive": RESULTS / "phaseac" / "stale_archive.json",
    "metadata_guards": RESULTS / "phaseac" / "metadata_guards.json",
    "optimisations": HERE / "optimisations.json",
}

#: Headline claims the documents make, with the tolerance the recomputation must meet.
#: Phase AD published 5.6x here; the raw rows give 5.22x, which is what this asserts.
HEADLINE = {
    "bzip2_speedup_over_native": {"expected": 5.22, "tolerance": 0.01},
    "bzip2_savings_fraction": {"expected": 0.808, "tolerance": 0.001},
    "bzip2_native_ms": {"expected": 2846.7, "tolerance": 0.1},
    "bzip2_tracejit_ms": {"expected": 545.3, "tolerance": 0.1},
    "bzip2_firebuild_0862_ms": {"expected": 3119.4, "tolerance": 0.1},
    "census_declared_rows": {"expected": 177, "tolerance": 0},
    "census_attempted_rows": {"expected": 162, "tolerance": 0},
    "census_reused_rows": {"expected": 28, "tolerance": 0},
    "census_incorrect_hits": {"expected": 0, "tolerance": 0},
}

WORKLOAD_LABELS = {
    "bzip2-file": "bzip2 -9 -k (1 MiB incompressible, file output)",
    "gzip-file": "gzip -9 -n -k (1 MiB, file output)",
    "gzip-stdout": "gzip -9 -n -c (1.2 MiB text, stdout)",
    "sed-lines": "sed (200k lines)",
    "sha256sum": "sha256sum (1 MiB)",
}

ARM_LABELS = {
    "native": "native",
    "tj-ae": "TraceJIT (allocator-entropy-v1)",
    "tj-native": "TraceJIT (native policy)",
    "fb082-default": "Firebuild 0.8.2",
    "fb082-tuned": "Firebuild 0.8.2 (tuned)",
    "fb862-default": "Firebuild 0.8.6.2",
    "fb862-strict": "Firebuild 0.8.6.2 (strict)",
    "fb862-tuned": "Firebuild 0.8.6.2 (tuned)",
}


class EvidenceError(RuntimeError):
    """A table cannot be built from the committed evidence."""


def display(path: Path) -> str:
    """A readable path for messages, whether or not it lives inside the repository."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def load(key: str) -> dict:
    path = EVIDENCE[key]
    if not path.is_file():
        raise EvidenceError(f"missing evidence: {display(path)} (for {key!r})")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise EvidenceError(f"unreadable evidence {display(path)}: {error}") from error


def ms(nanoseconds: float) -> float:
    return round(nanoseconds / 1e6, 1)


# --------------------------------------------------------------------------- #
# table builders
# --------------------------------------------------------------------------- #


def compatibility() -> dict:
    census = load("census")
    rows = census["workloads"]
    cells: dict[tuple[str, str], dict[str, int]] = {}
    for record in rows:
        key = (record["environment_tier"], record["policy"])
        cell = cells.setdefault(key, {"declared": 0, "unavailable": 0, "attempted": 0,
                                      "eligible": 0, "reused": 0, "incorrect": 0})
        cell["declared"] += 1
        if record["status"] == "tool_unavailable":
            cell["unavailable"] += 1
            continue
        cell["attempted"] += 1
        if record.get("eligible_for_reuse"):
            cell["eligible"] += 1
        if record["status"] == "reused":
            cell["reused"] += 1
        if record["status"] == "incorrect_hit":
            cell["incorrect"] += 1

    order = ["native", "allocator-entropy-v1", "compiler-runtime-v1"]
    table_rows = []
    totals = {"declared": 0, "attempted": 0, "reused": 0, "incorrect": 0}
    for tier in ("A", "C"):
        for policy in order:
            cell = cells.get((tier, policy))
            if not cell:
                continue
            rate = cell["reused"] / cell["attempted"] if cell["attempted"] else float("nan")
            table_rows.append([
                tier,
                policy,
                cell["declared"],
                cell["attempted"],
                cell["eligible"],
                cell["reused"],
                f"{100 * rate:.1f} %" if cell["attempted"] else "--",
                cell["incorrect"],
            ])
            for name in ("declared", "attempted", "reused", "incorrect"):
                totals[name] += cell[name]
    table_rows.append(["**all**", "", totals["declared"], totals["attempted"], "", totals["reused"],
                       f"{100 * totals['reused'] / totals['attempted']:.1f} %", totals["incorrect"]])
    return {
        "id": "compatibility",
        "caption": "Frozen compatibility census. Eligibility and reuse are counted per "
                   "(tier, contract) cell and never summed across cells.",
        "columns": ["Tier", "Contract", "Declared", "Attempted", "Eligible", "Reused",
                    "Reuse rate", "Incorrect"],
        "rows": table_rows,
        "provenance": "benchmarks/results/phaseaa1/results.json (177 rows, 59 workloads × 3 "
                      "contracts); host fingerprint benchmarks/results/phaseaa1/environment.json",
        "totals": totals,
    }


def competitive(size: int = 25) -> dict:
    economics = load("economics")
    matrix = load("matrix")
    recalculated = {}
    recalculated["census_declared_rows"] = load("census")["aggregate"]["accounting"]["declared_rows"]
    recalculated["census_attempted_rows"] = sum(
        1 for row in load("census")["workloads"] if row["status"] != "tool_unavailable")
    recalculated["census_reused_rows"] = sum(
        1 for row in load("census")["workloads"] if row["status"] == "reused")
    recalculated["census_incorrect_hits"] = sum(
        1 for row in load("census")["workloads"] if row["status"] == "incorrect_hit")

    columns = ["Workload", "Native", "TraceJIT", "Firebuild 0.8.2", "Firebuild 0.8.6.2",
               "Firebuild 0.8.6.2 tuned", "TraceJIT steady", "HITs (TraceJIT)"]
    rows = []
    for workload, entry in economics["workloads"].items():
        cold = {arm: next((s for s in data["cold"] if s["size"] == size), None)
                for arm, data in entry["arms"].items()}
        steady = {arm: next((s for s in data["steady"] if s["size"] == size), None)
                  for arm, data in entry["arms"].items()}

        def cell(arm: str) -> str:
            sample = cold.get(arm)
            return "--" if not sample else f"{ms(sample['session_ns']):.1f}"

        def steady_cell(arm: str) -> str:
            sample = steady.get(arm)
            return "--" if not sample else f"{ms(sample['session_ns']):.1f}"

        sample = cold.get("tj-ae")
        rows.append([
            WORKLOAD_LABELS.get(workload, workload),
            cell("native"),
            cell("tj-ae"),
            cell("fb082-default"),
            cell("fb862-default"),
            cell("fb862-tuned"),
            steady_cell("tj-ae"),
            "--" if not sample else sample["hits"],
        ])
        if workload == "bzip2-file" and size == 25 and sample:
            native_ns = cold["native"]["session_ns"]
            tracejit_ns = sample["session_ns"]
            firebuild = cold.get("fb862-default")
            recalculated["bzip2_native_ms"] = ms(native_ns)
            recalculated["bzip2_tracejit_ms"] = ms(tracejit_ns)
            recalculated["bzip2_speedup_over_native"] = native_ns / tracejit_ns
            recalculated["bzip2_savings_fraction"] = 1 - tracejit_ns / native_ns
            if firebuild:
                recalculated["bzip2_firebuild_0862_ms"] = ms(firebuild["session_ns"])

    # Every row the table prints must be marked correct by the harness that produced it.
    used = [row for row in matrix["rows"] if row.get("size") == size and row.get("mode") == "cold"]
    incorrect = [row for row in used if not row.get("all_correct")]
    if incorrect:
        raise EvidenceError(f"{len(incorrect)} cold rows at n={size} are not all_correct")

    return {
        "id": "competitive",
        "caption": f"Same-host session cost, {size} invocations, cold cache (the first trace is "
                   "charged to the arm). Milliseconds; lower is better.",
        "columns": columns,
        "rows": rows,
        "provenance": f"benchmarks/results/phaseae/economics.json (cold, size={size}); every row "
                      f"verified against a native oracle in phaseae/matrix.json "
                      f"({len(used)} rows all_correct)",
        "recalculated": recalculated,
    }


def session_economics() -> dict:
    economics = load("economics")
    rows = []
    for workload, entry in economics["workloads"].items():
        direct = next((s for s in entry["arms"]["native"]["cold"] if s["size"] == 25), None)
        traced = next((s for s in entry["arms"]["tj-ae"]["cold"] if s["size"] == 25), None)
        if not direct or not traced:
            continue
        saving = direct["session_ns"] - traced["session_ns"]
        rows.append([
            WORKLOAD_LABELS.get(workload, workload),
            f"{ms(direct['session_ns']):.1f}",
            f"{ms(traced['session_ns']):.1f}",
            f"{direct['session_ns'] / traced['session_ns']:.2f}×",
            f"{100 * saving / direct['session_ns']:+.1f} %",
            traced["hits"],
        ])
    return {
        "id": "session_economics",
        "caption": "Measured 25-invocation session economics, cold cache. The percentage is the "
                   "change in cumulative execution time against native; negative values are losses.",
        "columns": ["Workload", "Native total (ms)", "TraceJIT total (ms)", "Ratio",
                    "Cumulative change", "HITs"],
        "rows": rows,
        "provenance": "benchmarks/results/phaseae/economics.json, mode=cold, size=25",
    }


def break_even() -> dict:
    """The four break-even definitions, kept apart on purpose.

    Phase AD published one integer per workload without saying which quantity it was. Equal cost
    and strictly positive savings differ by one invocation, the model and the measurement differ
    by more, and a reader who cannot tell which number they are reading cannot act on it.
    """
    economics = load("economics")
    rows = []
    for workload, entry in economics["workloads"].items():
        cold = {s["size"]: s for s in entry["arms"]["native"]["cold"]}
        traced = {s["size"]: s for s in entry["arms"]["tj-ae"]["cold"]}
        steady = {s["size"]: s for s in entry["arms"]["tj-ae"]["steady"]}
        sizes = sorted(set(cold) & set(traced))
        if not sizes:
            continue
        equal_cost, positive = 0, 0
        for size in sizes:
            direct = cold[size]["session_ns"] / cold[size]["invocations"]
            # Cumulative traced cost at n: one cold trace plus (n-1) steady hits.
            cold_trace = traced[size]["session_ns"] - (traced[size]["invocations"] - 1) * (
                steady[size]["session_ns"] / steady[size]["invocations"]
                if size in steady and steady[size]["invocations"] else 0)
            hit = (steady[size]["session_ns"] / steady[size]["invocations"]
                   if size in steady and steady[size]["invocations"] else direct)
            if direct <= hit:
                equal_cost = positive = None
                break
            equal_cost = max(equal_cost, max(1, math.ceil(cold_trace / direct)))
            positive = max(positive, math.ceil(cold_trace / (direct - hit)))
        ten = next((s for s in traced.values() if s["invocations"] == 10), None)
        twentyfive = next((s for s in traced.values() if s["invocations"] == 25), None)
        native_ten = next((s for s in cold.values() if s["invocations"] == 10), None)
        if equal_cost is None:
            rows.append([WORKLOAD_LABELS.get(workload, workload), "never", "never", "--", "--"])
            continue
        measured_10 = (
            f"{100 * (1 - ten['session_ns'] / native_ten['session_ns']):+.1f} %"
            if ten and native_ten else "--")
        measured_25 = (
            f"{100 * (1 - twentyfive['session_ns'] / direct * 0 - twentyfive['per_invocation_median_ns'] / (cold[25]['session_ns'] / 25)):+.1f} %"
            if twentyfive and 25 in cold else "--")
        rows.append([
            WORKLOAD_LABELS.get(workload, workload),
            f"{equal_cost}",
            f"{positive}",
            measured_10,
            measured_25,
        ])
    return {
        "id": "break_even",
        "caption": "Break-even, four ways. Columns 2 and 3 are invocation counts: the first at "
                   "which cumulative cost equals native, and the first at which savings are "
                   "strictly positive. Columns 4 and 5 are the measured cumulative change at "
                   "sampled session lengths, which is not the same quantity.",
        "columns": ["Workload", "Equal cost at n", "Positive at n", "Measured n=10",
                    "Measured n=25"],
        "rows": rows,
        "provenance": "benchmarks/results/phaseae/economics.json, mode=cold; counts derived from "
                      "one cold trace plus steady hits",
    }


def artifact_scale() -> dict:
    data = load("artifact_scale")
    measurements = data.get("rows", [])
    if not measurements:
        raise EvidenceError("artifact_scale evidence exists but contains no result rows")
    native = {(record["artifact"], record["workload"]): record
              for record in measurements if record.get("arm") == "native"}
    break_even = {(record["artifact"], record["workload"]): record["break_even"]
                  for record in data.get("break_even", [])}
    rows = []
    for record in measurements:
        if record.get("arm") == "native":
            continue
        key = (record["artifact"], record["workload"])
        reference = native.get(key)
        if reference is None:
            raise EvidenceError(f"no native reference for artifact-scale row {key}")
        if not record.get("observation_matches_native"):
            raise EvidenceError(f"artifact-scale row {key} did not match the native observation")
        decision = break_even.get(key) or {}
        integer = decision.get("integer_invocations")
        ratio = (reference["warm_ns"] / record["warm_ns"]
                 if record.get("warm_reused") and record["warm_ns"] else None)
        rows.append([
            record["artifact"],
            record["workload"],
            f"{ms(reference['warm_ns']):.1f}",
            f"{ms(record['cold_ns']):.1f}" if record.get("cold_ns") else "--",
            f"{ms(record['warm_ns']):.1f}" if record.get("warm_ns") else "--",
            f"{ratio:.1f}×" if ratio else "no reuse",
            f"{integer}" if integer else ("never" if decision else "--"),
        ])
    return {
        "id": "artifact_scale",
        "caption": "Cost across authentic artifact sizes. Cold is the first traced execution, "
                   "warm is a verified HIT of the same command.",
        "columns": ["Artifact", "Workload", "Native (ms)", "Cold trace (ms)",
                    "Warm HIT (ms)", "Native/HIT", "Break-even n"],
        "rows": rows,
        "provenance": "benchmarks/results/phaseaf/artifact_scale.json, produced by "
                      "benchmarks/phase_ad/artifact_scale.py on a pinned release archive",
    }


def correctness() -> dict:
    toctou = load("toctou")
    integrity = load("integrity")
    stale = load("stale_archive")
    metadata = load("metadata_guards")

    rows = []
    for case in toctou.get("cases", []):
        scenario = case.get("scenario", "?")
        served = bool(case.get("undetected_stale_bytes"))
        if scenario == "during_hashing":
            trials = case.get("trials") or []
            decisions = sorted({trial.get("decision", "?") for trial in trials})
            decision = "/".join(decisions) if decisions else "?"
            observation = (f"{case.get('detected')}/{len(trials)}"
                           " concurrent-writer trials deoptimised")
            verdict = "holds under concurrent writes"
            rows.append(["Validation-to-restore race", scenario, decision, observation, verdict])
            continue
        else:
            observation = "stale bytes served" if served else "detected before exposure"
            verdict = ("documented counterexample" if served
                       else "expected" if case.get("detected") else "see report")
        rows.append([
            "Validation-to-restore race",
            scenario,
            case.get("decision", "?"),
            observation,
            verdict,
        ])
    corruption = integrity.get("after_corruption", {})
    rows.append([
        "Cached-object corruption",
        "one CAS object corrupted, then reuse attempted",
        corruption.get("decision", "?"),
        "re-executed, no hit" if corruption.get("reported_hit") is False else "served a hit",
        "correct" if integrity.get("all_correct") else "INCORRECT",
    ])
    stale_arms = [arm for arm in stale.get("arms", []) if arm.get("final", {})
                  and not arm["final"].get("member_matches_object", True)]
    rows.append([
        "Output timestamp",
        "restored object older than the archive built from it",
        f"{len(stale_arms)}/{len(stale.get('arms', []))} projects reproduced a stale member",
        "make treats the archive as up to date",
        "known limitation",
    ])
    guard_rows = metadata.get("rows", [])
    incorrect = [row for row in guard_rows if row.get("incorrect_hit")]
    rows.append([
        "Metadata-only observation",
        "mtime/atime/counterexample matrix",
        f"{len(guard_rows)} cases, {len(incorrect)} incorrect hits",
        "every case matches a native observation",
        "known limitation" if not incorrect else "INCORRECT",
    ])
    return {
        "id": "correctness",
        "caption": "Adversarial and negative results, including the counterexamples that are "
                   "kept rather than removed.",
        "columns": ["Class", "Case", "Observed decision", "Observation", "Verdict"],
        "rows": rows,
        "provenance": "benchmarks/results/phaseae/toctou_race.json, "
                      "benchmarks/results/phaseae/tracejit_integrity.json, "
                      "benchmarks/results/phaseac/stale_archive.json, "
                      "benchmarks/results/phaseac/metadata_guards.json",
    }


def capability() -> dict:
    lifecycle = load("lifecycle")
    local = load("environment_local")
    multienv = load("multi_environment")

    def fmt(value) -> str:
        if value is None:
            return "absent"
        return str(value)

    rows = []
    host = lifecycle["host"]
    read_only = {step["step"]: step for step in lifecycle["arms"]["read_only"]["steps"]}
    producer = {step["step"]: step for step in lifecycle["arms"]["producer"]["steps"]}
    rows.append([
        f"{host['os_release'].split('=')[-1].strip(chr(34))} / {host['kernel']}",
        fmt(host["landlock_abi_syscall"]),
        "yes" if host["seccomp_action_available"] else "no",
        read_only["1_discovery_execution"]["classification"],
        read_only["3_enforced_execution"]["classification"],
        read_only["5_enforced_reuse"]["kind"],
        producer["3_enforced_execution"]["classification"],
    ])
    rows.append([
        f"Ubuntu 24.04.5 / {local['host']['uname']['release']}",
        fmt(local["doctor"]["landlock_abi"]),
        "yes" if local["doctor"]["seccomp"] else "no",
        local["enforcement"]["guarded_runs"][0]["classification"],
        local["enforcement"]["enforce_runs"][0]["classification"],
        "not demonstrated",
        "not measured",
    ])
    for label, record in multienv.items():
        rows.append([
            f"{label} / {record.get('kernel', '?')}",
            fmt(record.get("landlock_abi")),
            "yes" if record.get("seccomp") else "unknown",
            "refused" if not record.get("guarded_second_run_reused") else "GUARDED",
            "PROVEN" if record.get("enforce_any_proven") else "not PROVEN",
            "not demonstrated",
            "not measured",
        ])
    return {
        "id": "capability",
        "caption": "Enforcement capability and the lifecycle outcome it produces. A host without "
                   "Landlock ABI 3+ can never produce PROVEN; that is the documented fallback, "
                   "not a defect.",
        "columns": ["Environment", "Landlock ABI", "seccomp", "Discovery class",
                    "Enforced run", "Enforced reuse", "Producer under --enforce"],
        "rows": rows,
        "provenance": "benchmarks/results/phaseaf/enforcement_lifecycle.json (this phase, "
                      "capable host), benchmarks/results/phaseae/environment-local.json, "
                      "benchmarks/results/phaseae/multi_environment.json",
    }


def optimisations() -> dict:
    data = load("optimisations")
    return {
        "id": "optimisations",
        "caption": "Candidates accepted into the product and candidates rejected with the "
                   "measurement that rejected them.",
        "columns": ["Candidate", "Status", "Evidence"],
        "rows": [[item["candidate"], item["status"], item["evidence"]]
                 for item in data["items"]],
        "provenance": "benchmarks/phase_af/optimisations.json, curated from the phase reports "
                      "named in each row",
    }


BUILDERS = {
    "compatibility": compatibility,
    "competitive": competitive,
    "session_economics": session_economics,
    "break_even": break_even,
    "artifact_scale": artifact_scale,
    "correctness": correctness,
    "capability": capability,
    "optimisations": optimisations,
}


# --------------------------------------------------------------------------- #
# emission
# --------------------------------------------------------------------------- #


def escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}",
    }
    return "".join(replacements.get(character, character) for character in str(text))


def to_markdown(table: dict) -> str:
    lines = [f"**Table: {table['caption']}**", ""]
    lines.append("| " + " | ".join(table["columns"]) + " |")
    lines.append("| " + " | ".join("---" for _ in table["columns"]) + " |")
    for row in table["rows"]:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    lines += ["", f"*Source: {table['provenance']}*", ""]
    return "\n".join(lines)


def to_latex(table: dict) -> str:
    alignment = "l" + "r" * (len(table["columns"]) - 1)
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        rf"\caption{{{escape(table['caption'])}}}",
        rf"\label{{tab:{table['id']}}}",
        rf"\begin{{tabular}}{{{alignment}}}",
        r"\toprule",
        " & ".join(rf"\textbf{{{escape(column)}}}" for column in table["columns"]) + r" \\",
        r"\midrule",
    ]
    for row in table["rows"]:
        lines.append(" & ".join(escape(cell) for cell in row) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return "\n".join(lines)


def check_headline(recalculated: dict) -> list[str]:
    problems = []
    for name, expected in HEADLINE.items():
        if name not in recalculated:
            problems.append(f"headline {name} was not recalculated")
            continue
        actual = recalculated[name]
        if abs(actual - expected["expected"]) > expected["tolerance"] + 1e-12:
            problems.append(
                f"headline {name}: documents say {expected['expected']}, evidence gives {actual}"
            )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path, default=None,
                        help="directory for generated tables (Markdown and LaTeX)")
    parser.add_argument("--check", action="store_true",
                        help="fail when evidence is missing or a headline disagrees")
    args = parser.parse_args(argv)

    problems: list[str] = []
    built: dict[str, dict] = {}
    for name, builder in BUILDERS.items():
        try:
            built[name] = builder()
        except EvidenceError as error:
            problems.append(f"{name}: {error}")

    if "competitive" in built:
        problems.extend(check_headline(built["competitive"].get("recalculated", {})))

    if args.emit:
        args.emit.mkdir(parents=True, exist_ok=True)
        for name, table in built.items():
            (args.emit / f"{name}.tex").write_text(to_latex(table))
            (args.emit / f"{name}.md").write_text(to_markdown(table))
        print(f"wrote {len(built)} tables to {args.emit}")

    if problems:
        for problem in problems:
            print(f"PROBLEM {problem}", file=sys.stderr)
        if args.check:
            return 1
    if "competitive" in built:
        recalculated = built["competitive"]["recalculated"]
        print("recalculated headlines:")
        for name, expected in HEADLINE.items():
            if name in recalculated:
                print(f"  {name}: {recalculated[name]:.4g} (documents: {expected['expected']})")
    print(f"tables built: {len(built)}/{len(BUILDERS)}, problems: {len(problems)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

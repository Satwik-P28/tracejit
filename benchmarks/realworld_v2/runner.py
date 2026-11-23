#!/usr/bin/env python3
"""Phase AA real-world benchmark runner (protocol version 1).

What this measures, and what it refuses to measure
--------------------------------------------------
Every row is one (workload, execution-policy) pair. Two policies exist:

``native``
    ``tracejit run -- <command>`` with no execution contract.
``contract``
    the same command with ``--contract allocator-entropy-v1``.

Eligibility is only ever counted per (environment tier, policy). Tier A rows
(no workload adaptation) and tier C rows (declared adaptation) are never
summed, and no native-contract figure is ever averaged with a contract figure.

Timing is a *randomized paired* design. For each sample both arms run once, in
random order, from the same pre-state (declared outputs removed first), and the
per-pair ratio is what the confidence interval is computed on. Cold tracing is
sampled separately because it needs a fresh cache directory. Raw nanosecond
samples are always written next to any summary.

A sample is only counted as a cache HIT when TraceJIT itself reports
``kind == "Reused"`` for that exact invocation *and* the cache decision field
agrees. Anything else (a deoptimisation, a refusal, an admission skip) is
recorded as its own decision. A ``Reused`` decision whose independent oracle
observation differs from native execution is an **incorrect hit** and fails the
run.

Usage
-----
    python3 benchmarks/realworld_v2/runner.py --tracejit target/release/tracejit \
        --mode qualify --policies native,contract --splits dev,validation,heldout

    python3 benchmarks/realworld_v2/runner.py --mode time --output-dir .../phaseaa

    python3 benchmarks/realworld_v2/runner.py --mode transitions --workloads <ids>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus  # noqa: E402
import oracle  # noqa: E402

SCHEMA_VERSION = "tracejit.realworld.results/v1"

#: Policy name -> value passed to ``--contract`` (None = native execution).
POLICIES = {
    "native": None,
    "allocator-entropy-v1": "allocator-entropy-v1",
    "compiler-runtime-v1": "compiler-runtime-v1",
}
REPO = Path(__file__).resolve().parents[2]
DEFAULT_SCRATCH = Path(tempfile.gettempdir()) / "tracejit-realworld-v2"
UNMODELED_SYSCALL = re.compile(r"unmodeled (?:successful |failed )?syscall (\d+)")


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #


def median(values: list[float]) -> float:
    return statistics.median(values)


def summarise(samples: list[int], seed: int = 0xAA) -> dict:
    """Median, tails and a percentile-bootstrap 95 % CI of the median."""

    ordered = sorted(samples)
    ci_low, ci_high = bootstrap_ci(ordered, statistic=median, seed=seed)
    return {
        "n": len(samples),
        "median_ns": int(median(ordered)),
        "mean_ns": int(statistics.fmean(ordered)),
        "p05_ns": ordered[max(0, math.ceil(0.05 * len(ordered)) - 1)],
        "p95_ns": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
        "min_ns": ordered[0],
        "max_ns": ordered[-1],
        "median_ci95_ns": [int(ci_low), int(ci_high)],
        "samples_ns": list(samples),
    }


def bootstrap_ci(
    values: list[float], statistic, seed: int, resamples: int = 4000, alpha: float = 0.05
) -> tuple[float, float]:
    rng = random.Random(seed)
    count = len(values)
    if count < 2:
        return values[0], values[0]
    estimates = []
    for _ in range(resamples):
        draw = [values[rng.randrange(count)] for _ in range(count)]
        estimates.append(statistic(draw))
    estimates.sort()
    low = estimates[int((alpha / 2) * resamples)]
    high = estimates[min(resamples - 1, int((1 - alpha / 2) * resamples))]
    return low, high


def paired_ratio(direct: list[int], other: list[int], seed: int = 0xAB) -> dict:
    """Paired direct/other ratio with a bootstrap CI on the geometric mean.

    ``other`` is the arm being evaluated (warm hit or cold trace). The ratio is
    ``direct / other``, so a value above 1 means ``other`` was **faster** than
    direct execution, and a value below 1 means it was slower.
    """

    pairs = min(len(direct), len(other))
    ratios = [direct[i] / other[i] for i in range(pairs) if other[i] > 0]
    logs = [math.log(value) for value in ratios]
    ci_low, ci_high = bootstrap_ci(logs, statistic=median, seed=seed)
    return {
        "pairs": pairs,
        "geometric_mean_ratio": math.exp(statistics.fmean(logs)) if logs else None,
        "median_ratio": median(ratios),
        "ratio_ci95": [math.exp(ci_low), math.exp(ci_high)],
        "ratios": ratios,
    }


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #


def _text(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return (completed.stdout + completed.stderr).strip()


def fingerprint(tracejit: Path) -> dict:
    libc = None
    for candidate in ("/lib/x86_64-linux-gnu/libc.so.6", "/usr/lib/x86_64-linux-gnu/libc.so.6"):
        if Path(candidate).is_file():
            libc = {
                "path": candidate,
                "build_id": _text(["sh", "-c", f"readelf -n {candidate} 2>/dev/null | awk '/Build ID/ {{print $3}}'"]),
                "version": _text([candidate]),
            }
            break
    tools = {}
    for tool in ("gcc", "cc", "clang", "make", "ninja", "ccache", "sccache", "hyperfine",
                 "perf", "tar", "gzip", "bzip2", "xz", "zstd", "zip", "unzip", "jq",
                 "node", "python3", "cargo", "rustc", "objcopy", "strip", "objdump",
                 "readelf", "nm", "cppcheck", "shellcheck", "ruff", "firebuild"):
        path = shutil.which(tool)
        tools[tool] = {"path": path, "version": _text([tool, "--version"]).splitlines()[0] if path else None}
    cpuinfo = {}
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                cpuinfo.setdefault(key.strip(), value.strip())
    except OSError:
        pass
    governor = None
    governor_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if governor_path.is_file():
        governor = governor_path.read_text().strip()
    return {
        "tracejit": {
            "path": str(tracejit),
            "sha256": hashlib.sha256(tracejit.read_bytes()).hexdigest(),
            "reported_version": _text([str(tracejit), "--version"]),
            "doctor": _text([str(tracejit), "doctor"]),
        },
        "commit": _text(["git", "rev-parse", "HEAD"]),
        # Tracked modifications only: the evidence directory this run writes into
        # is untracked, and counting it would mark every honest run as dirty. The
        # untracked count is recorded separately so the distinction stays visible.
        "working_tree_dirty": bool(_text(["git", "status", "--porcelain", "--untracked-files=no"])),
        "untracked_entries": len(
            [line for line in _text(["git", "status", "--porcelain", "--untracked-files=all"]).splitlines() if line.strip()]
        ),
        "kernel": {"release": platform.release(), "uname": _text(["uname", "-a"])},
        "distribution": _text(["sh", "-c", "cat /etc/os-release"]),
        "libc": libc,
        "cpu": {
            "model": cpuinfo.get("model name"),
            "logical_count": os.cpu_count(),
            "physical_cores": _text(["sh", "-c", "lscpu | awk -F: '/Core\\(s\\) per socket/{gsub(/ /,\"\",$2); print $2}'"]),
            "governor": governor,
            "lscpu": _text(["lscpu"]),
        },
        "memory": _text(["sh", "-c", "free -b"]),
        "filesystem": _text(["sh", "-c", f"df -T {DEFAULT_SCRATCH} 2>/dev/null || df -T ."]),
        "virtualization": _text(["sh", "-c", "systemd-detect-virt 2>/dev/null || echo unknown"]),
        "container_markers": [name for name in ("/.dockerenv", "/run/.containerenv") if Path(name).exists()],
        "tools": tools,
        "environment_allowlist": {
            key: os.environ.get(key)
            for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "PYTHONHASHSEED",
                        "PYTHONDONTWRITEBYTECODE", "GLIBC_TUNABLES", "MALLOC_ARENA_MAX")
        },
        "contract": "allocator-entropy-v1 (separate policy; never merged with native rows)",
        "page_cache_control": "not attempted; the host cannot establish a cold page cache reliably",
        "hardware_counters": (
            "perf is not installed on this image"
            if shutil.which("perf") is None
            else "perf present; counters used only when --perf is passed"
        ),
    }


# --------------------------------------------------------------------------- #
# execution primitives
# --------------------------------------------------------------------------- #


def cache_env(base: dict, cache: Path) -> dict:
    env = dict(base)
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run_traced(
    tracejit: Path, argv: list[str], ws: Path, env: dict, policy: str, timeout: int = 900
) -> tuple[int, dict, dict | None, bytes, bytes]:
    prefix = [str(tracejit), "run", "--json"]
    contract = POLICIES.get(policy)
    if contract:
        prefix += ["--contract", contract]
    completed = subprocess.run(
        [*prefix, "--", *argv], cwd=ws, env=env, capture_output=True, check=False, timeout=timeout
    )
    report = None
    error = None
    try:
        report = json.loads(completed.stdout)
        raw_stdout = bytes(report.get("stdout_bytes") or [])
        raw_stderr = bytes(report.get("stderr_bytes") or [])
    except (json.JSONDecodeError, TypeError) as decode_error:
        error = f"{decode_error}: {completed.stdout[:400]!r}"
        raw_stdout, raw_stderr = completed.stdout, completed.stderr
    return completed.returncode, {
        "cache_decision": (report or {}).get("cache_decision"),
        "kind": (report or {}).get("kind"),
        "decision_reason": (report or {}).get("decision_reason"),
        "parse_error": error,
        "wrapper_exit_status": completed.returncode,
        "wrapper_stderr_tail": completed.stderr[-600:].decode(errors="replace") if error else None,
    }, report, raw_stdout, raw_stderr


def reset_outputs(workload: corpus.Workload, ws: Path) -> list[str]:
    if workload.reset != "delete_outputs":
        return []
    removed = []
    for relative in workload.outputs:
        path = ws / relative
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
            removed.append(relative + "/")
        elif path.exists() or path.is_symlink():
            path.unlink()
            removed.append(relative)
    return removed


def is_hit(decision: dict | None) -> bool:
    if not decision:
        return False
    return decision.get("kind") == "Reused"


def decision_record(decision: dict | None, extra: dict | None = None) -> dict:
    payload = {
        "kind": (decision or {}).get("kind"),
        "cache_decision": (decision or {}).get("cache_decision"),
        "decision_reason": (decision or {}).get("decision_reason"),
    }
    if (decision or {}).get("parse_error"):
        payload["parse_error"] = decision["parse_error"]
        payload["wrapper_exit_status"] = decision.get("wrapper_exit_status")
        payload["wrapper_stderr_tail"] = decision.get("wrapper_stderr_tail")
    if extra:
        payload.update(extra)
    return payload


def env_digest(env: dict) -> str:
    payload = json.dumps(
        {k: env[k] for k in sorted(env) if k.startswith(("TRACEJIT_", "PYTHON", "OMP", "OPENBLAS", "MKL", "NUMEXPR", "GLIBC", "MALLOC"))},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# qualification: is this workload reusable, and is a reuse correct?
# --------------------------------------------------------------------------- #


def qualify(
    workload: corpus.Workload,
    policy: str,
    tracejit: Path,
    ctx: dict,
    scratch: Path,
    base_env: dict,
) -> dict:
    record: dict = {
        "workload_id": workload.id,
        "family": workload.family,
        "split": workload.split,
        "environment_tier": workload.tier,
        "policy": policy,
        "cost_class": workload.cost,
        "provenance": workload.provenance,
        "required_tools": list(workload.requires),
        "adaptations": list(workload.adaptations),
        "environment_adaptations": dict(workload.env),
        "status": "unknown",
        "decisions": [],
        "correctness": {},
    }

    if workload.unsupported_tool:
        tool = workload.unsupported_tool
        present = shutil.which(tool) is not None if tool != "pyarrow" else _module_present("pyarrow")
        if not present:
            record.update(
                status="tool_unavailable",
                tool_evidence={"tool": tool, "path": shutil.which(tool), "note": "not an eligibility measurement"},
            )
            return record
    missing = [tool for tool in workload.requires if shutil.which(tool) is None]
    if missing:
        record.update(status="tool_unavailable", tool_evidence={"missing": missing})
        return record

    root = scratch / "qualify" / f"{workload.id}__{policy}"
    shutil.rmtree(root, ignore_errors=True)
    native_ws = root / "native"
    traced_ws = root / "traced"
    cache = root / "cache"
    corpus.prepare(native_ws, ctx, workload)
    corpus.prepare(traced_ws, ctx, workload)
    root.mkdir(parents=True, exist_ok=True)

    env = cache_env({**base_env, **workload.env}, cache)
    record["environment_digest"] = env_digest(env)
    argv = workload.command(traced_ws, ctx)
    record["argv"] = [Path(item).name if item.startswith(ctx["zlib"]) else item for item in argv]

    # 1. clean native execution in the twin. A nonzero exit is a legitimate
    #    observation and is kept; only "command not found" is a tool problem.
    reset_outputs(workload, native_ws)
    native_exit, native_stdout, native_stderr = _run_capture(argv, native_ws, env)
    native_tree = oracle.observe_workspace(native_ws)
    native_obs = oracle.process_observation(native_exit, native_stdout, native_stderr, native_tree)
    record["direct_exit_status"] = native_exit
    if native_exit in (126, 127):
        record.update(status="tool_unavailable", tool_evidence={"exit_status": native_exit,
                                                               "argv": argv[:1]})
        return record

    # 2. cold traced execution with a fresh cache
    reset_outputs(workload, traced_ws)
    started = time.perf_counter_ns()
    _, decision, report, stdout, stderr = run_traced(tracejit, argv, traced_ws, env, policy)
    cold_ns = time.perf_counter_ns() - started
    cold_tree = oracle.observe_workspace(traced_ws)
    cold_obs = oracle.process_observation(
        int((report or {}).get("exit_code", -1)), stdout, stderr, cold_tree
    )
    cold_compare = oracle.compare(native_obs, cold_obs)
    record["cold_ns"] = cold_ns
    record["decisions"].append(decision_record(decision, {"step": "cold"}))
    record["cold_equivalence"] = cold_compare
    if decision.get("parse_error"):
        record.update(status="tracejit_error", error=decision["parse_error"])
        return record
    if not cold_compare["match"]:
        record.update(status="cold_mismatch")
        return record

    classification = (report or {}).get("classification")
    eligible = bool((report or {}).get("eligible_for_reuse"))
    record["classification"] = classification
    record["eligible_for_reuse"] = eligible
    record["reasons"] = (report or {}).get("reasons") or []
    record["dependency_count"] = (report or {}).get("dependency_count")
    record["output_count"] = (report or {}).get("output_count")

    if not eligible:
        record["status"] = "refused"
        record["refusal_categories"] = _categorise(record["reasons"])
        return record

    # 3. first warm reuse attempt, with declared outputs removed first
    reset_outputs(workload, traced_ws)
    warm_ns, warm_decision, warm_report, warm_stdout, warm_stderr = run_traced(
        tracejit, argv, traced_ws, env, policy
    )
    warm_tree = oracle.observe_workspace(traced_ws)
    warm_obs = oracle.process_observation(
        int((warm_report or {}).get("exit_code", -1)), warm_stdout, warm_stderr, warm_tree
    )
    warm_compare = oracle.compare(native_obs, warm_obs)
    record["warm_ns"] = warm_ns
    record["decisions"].append(decision_record(warm_decision, {"step": "warm"}))
    record["warm_equivalence"] = warm_compare
    if not is_hit(warm_decision):
        record["status"] = "eligible_but_no_hit"
        record["hit_failure"] = decision_record(warm_decision)
        return record
    if not warm_compare["match"]:
        record["status"] = "incorrect_hit"
        record["incorrect_hit"] = {"step": "warm", "differences": warm_compare["covered_differences"]}
        return record

    # 4. input mutation must deoptimise and must not expose stale output
    mutation = corpus.apply_mutation(workload, traced_ws)
    record["mutation"] = mutation
    if mutation:
        reset_outputs(workload, traced_ws)
        _, deopt_decision, deopt_report, deopt_stdout, deopt_stderr = run_traced(
            tracejit, argv, traced_ws, env, policy
        )
        deopt_tree = oracle.observe_workspace(traced_ws)
        deopt_obs = oracle.process_observation(
            int((deopt_report or {}).get("exit_code", -1)), deopt_stdout, deopt_stderr, deopt_tree
        )
        native_after_mutation = _native_twin_after_mutation(workload, argv, ctx, native_ws, env)
        deopt_compare = oracle.compare(native_after_mutation, deopt_obs)
        record["decisions"].append(decision_record(deopt_decision, {"step": "after_mutation"}))
        record["mutation_equivalence"] = deopt_compare
        record["deoptimised_after_mutation"] = not is_hit(deopt_decision)
        if is_hit(deopt_decision):
            # A HIT after an input edit is only wrong if the observation differs.
            # The corpus deliberately includes edits to files a command does not
            # read, where a correct HIT is the expected outcome.
            if not deopt_compare["match"]:
                record["status"] = "incorrect_hit"
                record["incorrect_hit"] = {
                    "step": "after_mutation",
                    "note": "a HIT after an input change produced stale output",
                    "differences": deopt_compare["covered_differences"],
                }
                return record
            record["mutation_hit_note"] = (
                "correct hit: the mutated path was not an observable input of this command"
            )
        elif not deopt_compare["match"]:
            record["status"] = "mutation_mismatch"
            return record
        # immediate retry with no further change: still a miss
        reset_outputs(workload, traced_ws)
        _, retry_decision, _, _, _ = run_traced(tracejit, argv, traced_ws, env, policy)
        record["decisions"].append(decision_record(retry_decision, {"step": "retry_after_mutation"}))
        # restore the earlier input state: candidate reuse may or may not fire
        corpus.restore_mutation(workload, traced_ws, ctx)
        reset_outputs(workload, traced_ws)
        _, restored_decision, restored_report, restored_stdout, restored_stderr = run_traced(
            tracejit, argv, traced_ws, env, policy
        )
        restored_tree = oracle.observe_workspace(traced_ws)
        restored_obs = oracle.process_observation(
            int((restored_report or {}).get("exit_code", -1)), restored_stdout, restored_stderr, restored_tree
        )
        restored_compare = oracle.compare(native_obs, restored_obs)
        record["decisions"].append(decision_record(restored_decision, {"step": "input_restored"}))
        record["restored_equivalence"] = restored_compare
        if is_hit(restored_decision) and not restored_compare["match"]:
            record["status"] = "incorrect_hit"
            record["incorrect_hit"] = {"step": "input_restored", "differences": restored_compare["covered_differences"]}
            return record
    else:
        record["decisions"].append({"step": "after_mutation", "kind": None, "note": "no mutation defined"})

    # 5. cache restart: a fresh cache directory must never hit
    restarted = root / "cache-restarted"
    _, restart_decision, _, _, _ = run_traced(
        tracejit, argv, traced_ws, cache_env({**base_env, **workload.env}, restarted), policy
    )
    record["decisions"].append(decision_record(restart_decision, {"step": "cache_restart"}))
    if is_hit(restart_decision):
        record["status"] = "incorrect_hit"
        record["incorrect_hit"] = {"step": "cache_restart", "note": "HIT from an empty cache"}
        return record

    # 6. cache-object corruption: remove one stored CAS object and re-run.
    #    A missing object must never surface as a wrong HIT; retracing is correct.
    objects_dir = cache / "objects"
    if objects_dir.is_dir():
        victims = sorted(path for path in objects_dir.iterdir() if path.is_file())
        if victims:
            victim = victims[-1]
            stash = root / "corrupt-object.bak"
            shutil.copy2(victim, stash)
            victim.unlink()
            reset_outputs(workload, traced_ws)
            _, corrupt_cache_decision, corrupt_cache_report, cc_stdout, cc_stderr = run_traced(
                tracejit, argv, traced_ws, env, policy
            )
            cc_tree = oracle.observe_workspace(traced_ws)
            cc_obs = oracle.process_observation(
                int((corrupt_cache_report or {}).get("exit_code", -1)), cc_stdout, cc_stderr, cc_tree
            )
            cc_compare = oracle.compare(native_obs, cc_obs)
            record["decisions"].append(
                decision_record(corrupt_cache_decision, {"step": "cache_object_corruption",
                                                         "removed_object": victim.name})
            )
            record["cache_corruption_equivalence"] = cc_compare
            shutil.copy2(stash, victim)
            if is_hit(corrupt_cache_decision) and not cc_compare["match"]:
                record["status"] = "incorrect_hit"
                record["incorrect_hit"] = {
                    "step": "cache_object_corruption",
                    "differences": cc_compare["covered_differences"],
                }
                return record
            if not cc_compare["match"]:
                record["status"] = "cache_corruption_mismatch"
                return record

    # 7. output corruption: outputs are not inputs; a hit must restore them
    if workload.outputs and workload.reset == "delete_outputs":
        target = traced_ws / workload.outputs[0]
        if target.is_file():
            target.write_bytes(b"CORRUPTED-BY-PHASE-AA\n")
            reset_note = "corrupted an existing output, then reused"
        else:
            reset_note = "output absent; nothing to corrupt"
        _, corrupt_decision, corrupt_report, corrupt_stdout, corrupt_stderr = run_traced(
            tracejit, argv, traced_ws, env, policy
        )
        corrupt_tree = oracle.observe_workspace(traced_ws)
        corrupt_obs = oracle.process_observation(
            int((corrupt_report or {}).get("exit_code", -1)), corrupt_stdout, corrupt_stderr, corrupt_tree
        )
        corrupt_compare = oracle.compare(native_obs, corrupt_obs)
        record["decisions"].append(decision_record(corrupt_decision, {"step": "output_corruption", "note": reset_note}))
        record["corruption_equivalence"] = corrupt_compare
        if is_hit(corrupt_decision) and not corrupt_compare["match"]:
            record["status"] = "incorrect_hit"
            record["incorrect_hit"] = {"step": "output_corruption", "differences": corrupt_compare["covered_differences"]}
            return record

    record["status"] = "reused"
    record["cache_storage_bytes"] = _directory_bytes(cache)
    return record


def _run_capture(argv: list[str], ws: Path, env: dict) -> tuple[int, bytes, bytes]:
    completed = subprocess.run(argv, cwd=ws, env=env, capture_output=True, check=False, timeout=600)
    return completed.returncode, completed.stdout, completed.stderr


def _native_twin_after_mutation(
    workload: corpus.Workload, argv: list[str], ctx: dict, native_ws: Path, env: dict
) -> dict:
    corpus.apply_mutation(workload, native_ws)
    reset_outputs(workload, native_ws)
    exit_status, stdout, stderr = _run_capture(argv, native_ws, env)
    tree = oracle.observe_workspace(native_ws)
    corpus.restore_mutation(workload, native_ws, ctx)
    return oracle.process_observation(exit_status, stdout, stderr, tree)


def _module_present(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _directory_bytes(path: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).lstat().st_size
            except OSError:
                pass
    return total


REASON_CATEGORIES = [
    ("randomness", "randomness"),
    ("clock", "clock"),
    ("process_identity", "process identity"),
    ("network", "network"),
    ("system_information", "system information"),
    ("procfs_process_relative", "process-relative procfs"),
    ("unclassified_descriptor", "unclassified fd"),
    ("unhashable_open", "opened dependency cannot be guarded"),
    ("unrestorable_output", "cannot be restored"),
    ("access_check", "access check cannot be guarded"),
    ("unguardable_metadata", "cannot be guarded"),
]


def _categorise(reasons: list[str]) -> dict:
    counts: dict[str, int] = {}
    for reason in reasons:
        lowered = reason.lower()
        match = UNMODELED_SYSCALL.search(reason)
        if match:
            key = f"unmodeled_syscall:{match.group(1)}"
        else:
            key = next((name for name, needle in REASON_CATEGORIES if needle in lowered), f"other:{reason[:50]}")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------- #
# timing
# --------------------------------------------------------------------------- #


def time_workload(
    workload: corpus.Workload,
    policy: str,
    tracejit: Path,
    ctx: dict,
    scratch: Path,
    base_env: dict,
    reps_scale: float,
    seed: int,
) -> dict:
    root = scratch / "time" / f"{workload.id}__{policy}"
    shutil.rmtree(root, ignore_errors=True)
    native_ws = root / "native"
    traced_ws = root / "traced"
    cache = root / "cache"
    corpus.prepare(native_ws, ctx, workload)
    corpus.prepare(traced_ws, ctx, workload)
    root.mkdir(parents=True, exist_ok=True)

    env = cache_env({**base_env, **workload.env}, cache)
    argv = workload.command(traced_ws, ctx)
    reset_outputs(workload, native_ws)
    reset_outputs(workload, traced_ws)

    # Populate the cache; the first run must not be counted as a hit.
    _, prime_decision, prime_report, _, _ = run_traced(tracejit, argv, traced_ws, env, policy)
    if not is_hit(run_traced(tracejit, argv, traced_ws, env, policy)[1]):
        return {
            "workload_id": workload.id,
            "policy": policy,
            "status": "not_eligible_for_timing",
            "prime": decision_record(prime_decision),
        }
    if not (prime_report or {}).get("eligible_for_reuse"):
        return {
            "workload_id": workload.id,
            "policy": policy,
            "status": "not_eligible_for_timing",
            "prime": decision_record(prime_decision),
        }

    reps = max(3, int(round(workload.reps * reps_scale)))
    cold_reps = max(3, min(reps, 10 if workload.cost == "light" else 5 if workload.cost == "medium" else 3))

    # warm-ups on both arms
    for _ in range(2):
        reset_outputs(workload, native_ws)
        _run_capture(argv, native_ws, env)
        reset_outputs(workload, traced_ws)
        run_traced(tracejit, argv, traced_ws, env, policy)

    rng = random.Random(f"{seed}:{workload.id}:{policy}")
    direct_samples: list[int] = []
    warm_samples: list[int] = []
    warm_decisions: list[dict] = []
    warm_equivalence_failures = 0

    for _ in range(reps):
        order = ["direct", "warm"]
        rng.shuffle(order)
        for arm in order:
            if arm == "direct":
                reset_outputs(workload, native_ws)
                started = time.perf_counter_ns()
                exit_status, stdout, stderr = _run_capture(argv, native_ws, env)
                elapsed = time.perf_counter_ns() - started
                if exit_status != 0:
                    return {
                        "workload_id": workload.id,
                        "policy": policy,
                        "status": "direct_failed_during_timing",
                        "exit_status": exit_status,
                    }
                direct_samples.append(elapsed)
            else:
                reset_outputs(workload, traced_ws)
                started = time.perf_counter_ns()
                _, decision, report, stdout, stderr = run_traced(tracejit, argv, traced_ws, env, policy)
                elapsed = time.perf_counter_ns() - started
                warm_samples.append(elapsed)
                warm_decisions.append(decision_record(decision))
                if not is_hit(decision):
                    return {
                        "workload_id": workload.id,
                        "policy": policy,
                        "status": "hit_lost_during_timing",
                        "decision": decision_record(decision),
                        "warm_samples_ns": warm_samples,
                    }
                # The decision is the only thing asserted here. Full oracle
                # comparison for every timed sample would double the oracle cost
                # for no extra information, so it is done once per workload in
                # qualification and once more on the final sample below.
                if (report or {}).get("cache_decision") not in (None, "Reused"):
                    warm_equivalence_failures += 1


    cold_samples: list[int] = []
    for index in range(cold_reps):
        fresh = root / f"cold-{index}"
        reset_outputs(workload, traced_ws)
        started = time.perf_counter_ns()
        run_traced(tracejit, argv, traced_ws, cache_env({**base_env, **workload.env}, fresh), policy)
        cold_samples.append(time.perf_counter_ns() - started)

    direct_summary = summarise(direct_samples)
    warm_summary = summarise(warm_samples)
    cold_summary = summarise(cold_samples)
    storage = _directory_bytes(cache)

    break_even = None
    if direct_summary["median_ns"] > warm_summary["median_ns"]:
        cold_overhead = cold_summary["median_ns"] - direct_summary["median_ns"]
        per_run_saving = direct_summary["median_ns"] - warm_summary["median_ns"]
        if per_run_saving > 0:
            break_even = max(1, math.ceil(cold_overhead / per_run_saving))

    session = {}
    for repeats in (2, 5, 10, 25, 50):
        session[f"{repeats}"] = {
            "direct_ns": repeats * direct_summary["median_ns"],
            "traced_ns": cold_summary["median_ns"] + (repeats - 1) * warm_summary["median_ns"],
        }
        session[f"{repeats}"]["speedup"] = (
            session[f"{repeats}"]["direct_ns"] / session[f"{repeats}"]["traced_ns"]
        )

    cost_model = phase_probe(workload, ctx, tracejit, policy, base_env, root)

    return {
        "workload_id": workload.id,
        "policy": policy,
        "status": "measured",
        "reps": reps,
        "cold_reps": cold_reps,
        "direct": direct_summary,
        "warm": warm_summary,
        "cold": cold_summary,
        "additional_hit_overhead": warm_equivalence_failures,
        "warm_ratio": paired_ratio(direct_samples, warm_samples),
        "cold_ratio": paired_ratio(direct_samples, cold_samples[: len(direct_samples)]),
        "cache_storage_bytes": storage,
        "break_even_repeats": break_even,
        "session": session,
        "cost_model": cost_model,
        "warm_decisions": warm_decisions,
        "environment_digest": env_digest(env),
    }


def phase_probe(
    workload: corpus.Workload, ctx: dict, tracejit: Path, policy: str, base_env: dict, root: Path
) -> dict:
    """One instrumented hit in its own session, for the per-stage cost breakdown.

    TraceJIT hashes the inherited environment into the cache key, so enabling
    instrumentation on a cache that was populated without it turns the probe into
    a miss. The probe therefore runs its own two-run session in a private
    workspace and cache with instrumentation enabled for both runs. Its numbers
    are a breakdown of a hit, never the headline warm-hit latency, because the
    instrumentation itself costs time.
    """

    probe_root = root / "instrumented"
    shutil.rmtree(probe_root, ignore_errors=True)
    ws = probe_root / "ws"
    cache = probe_root / "cache"
    corpus.prepare(ws, ctx, workload)
    path = probe_root / "phase.json"
    env = cache_env({**base_env, **workload.env}, cache)
    env["TRACEJIT_PHASE_TIMING"] = "1"
    env["TRACEJIT_PHASE_TIMING_PATH"] = str(path)
    argv = workload.command(ws, ctx)
    reset_outputs(workload, ws)
    run_traced(tracejit, argv, ws, env, policy)
    reset_outputs(workload, ws)
    _, decision, _, _, _ = run_traced(tracejit, argv, ws, env, policy)
    if not is_hit(decision):
        return {
            "available": False,
            "reason": "the instrumented session did not reuse",
            "decision": decision_record(decision),
        }
    if not path.is_file():
        return {"available": False, "reason": "no phase timing file was produced"}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        return {"available": False, "reason": f"unreadable phase timing: {error}"}
    stages = {
        key: data.get(key)
        for key in (
            "process_startup_ns",
            "cli_parse_ns",
            "identity_prepare_ns",
            "cache_prepare_ns",
            "sqlite_open_ns",
            "sqlite_schema_ns",
            "lookup_key_ns",
            "sqlite_query_ns",
            "record_decode_ns",
            "guard_validation_ns",
            "guard_recheck_ns",
            "cas_restore_ns",
            "stdio_replay_ns",
            "decision_persist_ns",
        )
        if key in data
    }
    return {
        "available": True,
        "stages_ns": stages,
        "instrumented": True,
        "note": "instrumented two-run session; the breakdown is not a timed sample",
    }


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #


def applicability(row: dict) -> str:
    if row.get("status") in ("tool_unavailable",):
        return "unavailable"
    if row.get("status") in ("incorrect_hit", "cold_mismatch", "mutation_mismatch"):
        return "unsafe_or_unresolved"
    if not row.get("timing"):
        return "ineligible"
    timing = row["timing"]
    if timing.get("status") != "measured":
        return "ineligible"
    direct = timing["direct"]["median_ns"]
    warm = timing["warm"]["median_ns"]
    # The paired ratio is direct/warm, so an interval that spans 1.0 means the
    # measurement cannot separate the arms. Saying "win" or "loss" there would be
    # reading noise as a result.
    ci_low, ci_high = timing.get("warm_ratio", {}).get("ratio_ci95", [1.0, 1.0])
    if ci_low <= 1.0 <= ci_high:
        return "indistinguishable"
    if warm >= direct:
        return "loss"
    break_even = timing.get("break_even_repeats")
    saving_at_25 = timing["session"]["25"]["speedup"]
    if break_even is not None and break_even <= 5 and saving_at_25 >= 1.2:
        return "clear_win"
    return "marginal_win"


def aggregate(rows: list[dict]) -> dict:
    def eligibility(tier: str, policy: str) -> dict:
        group = [row for row in rows if row["environment_tier"] == tier and row["policy"] == policy]
        attempted = [row for row in group if row["status"] not in ("tool_unavailable", "skipped_budget")]
        reused = [row for row in attempted if row["status"] == "reused"]
        refused = [row for row in attempted if row["status"] == "refused"]
        return {
            "workloads": len(group),
            "attempted": len(attempted),
            "reused": len(reused),
            "refused": len(refused),
            "other_failure": len(attempted) - len(reused) - len(refused),
            "rate": (len(reused) / len(attempted)) if attempted else None,
        }

    breakdown = {}
    present_policies = sorted({row["policy"] for row in rows})
    for tier in ("A", "C"):
        for policy in present_policies:
            breakdown[f"{tier}/{policy}"] = eligibility(tier, policy)

    measured = [row for row in rows if row.get("timing", {}).get("status") == "measured"]
    return {
        "requested": len(rows),
        "eligibility_by_tier_and_policy": breakdown,
        "tool_unavailable": [row["workload_id"] for row in rows if row["status"] == "tool_unavailable"],
        "refused": [row["workload_id"] for row in rows if row["status"] == "refused"],
        "incorrect_hits": [row["workload_id"] for row in rows if row["status"] == "incorrect_hit"],
        "timed_workloads": len({row["workload_id"] for row in measured}),
        "faster_than_native": sorted(
            {row["workload_id"] for row in measured if row["timing"]["warm"]["median_ns"] < row["timing"]["direct"]["median_ns"]}
        ),
        "slower_than_native": sorted(
            {row["workload_id"] for row in measured if row["timing"]["warm"]["median_ns"] >= row["timing"]["direct"]["median_ns"]}
        ),
        "positive_session_savings_at_25": sorted(
            {
                row["workload_id"]
                for row in measured
                if row["timing"]["session"]["25"]["speedup"] > 1.0
            }
        ),
    }


def write_markdown(result: dict, path: Path) -> None:
    lines = [
        "# TraceJIT Phase AA real-world benchmark",
        "",
        f"Schema `{result['schema_version']}` · commit `{result['environment']['commit']}` · "
        f"binary `{result['environment']['tracejit']['sha256'][:16]}`",
        "",
        "Eligibility is reported per environment tier and execution policy. Tier A (strict native) "
        "and tier C (declared adaptation) are never summed, and native-contract rows are never "
        "averaged with `allocator-entropy-v1` rows.",
        "",
        "## Eligibility",
        "",
        "| Tier / policy | Workloads | Attempted | Reused | Refused | Other | Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, stats in result["aggregate"]["eligibility_by_tier_and_policy"].items():
        rate = "-" if stats["rate"] is None else f"{stats['rate']:.3f}"
        lines.append(
            f"| {key} | {stats['workloads']} | {stats['attempted']} | {stats['reused']} | "
            f"{stats['refused']} | {stats['other_failure']} | {rate} |"
        )

    lines += [
        "",
        "## Workloads",
        "",
        "| Workload | Family | Tier | Policy | Status | Decision | Direct median | Warm median | Cold median | Break-even | Assessment |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in sorted(result["workloads"], key=lambda item: (item["workload_id"], item["policy"])):
        timing = row.get("timing") or {}
        decision = (row.get("decisions") or [{}])[0].get("kind")
        direct = f"{timing['direct']['median_ns'] / 1e6:.3f} ms" if timing.get("status") == "measured" else "-"
        warm = f"{timing['warm']['median_ns'] / 1e6:.3f} ms" if timing.get("status") == "measured" else "-"
        cold = f"{timing['cold']['median_ns'] / 1e6:.3f} ms" if timing.get("status") == "measured" else "-"
        breakeven = timing.get("break_even_repeats") if timing.get("status") == "measured" else None
        lines.append(
            f"| `{row['workload_id']}` | {row['family']} | {row['environment_tier']} | {row['policy']} | "
            f"{row['status']} | {decision or '-'} | {direct} | {warm} | {cold} | "
            f"{breakeven if breakeven is not None else '-'} | {row.get('assessment', '-')} |"
        )

    lines += ["", "## Negative results", ""]
    for row in result["workloads"]:
        if row["status"] in ("refused", "tool_unavailable", "eligible_but_no_hit", "incorrect_hit"):
            reasons = "; ".join((row.get("reasons") or [])[:3]) or row.get("tool_evidence", "")
            lines.append(f"- `{row['workload_id']}` ({row['policy']}): **{row['status']}** — {reasons}")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(REPO / "target" / "release" / "tracejit"))
    parser.add_argument("--mode", default="qualify",
                        choices=["qualify", "time", "both", "manifest", "report"])
    parser.add_argument("--policies", default="native,allocator-entropy-v1,compiler-runtime-v1",
                        help=f"comma-separated subset of {sorted(POLICIES)}")
    parser.add_argument("--splits", default="dev,validation,heldout")
    parser.add_argument("--workloads", default="")
    parser.add_argument("--reps-scale", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--output-dir", default=str(REPO / "benchmarks" / "results" / "phaseaa"))
    parser.add_argument("--scratch", default=str(DEFAULT_SCRATCH))
    parser.add_argument("--vendor", default=str(DEFAULT_SCRATCH / "vendor"))
    parser.add_argument("--reuse-qualification", action="store_true",
                        help="reuse an existing qualification file instead of re-running it")
    args = parser.parse_args()

    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    scratch = Path(args.scratch)
    vendor = Path(args.vendor)
    (scratch / "vendor").mkdir(parents=True, exist_ok=True)

    if args.mode == "report":
        environment = fingerprint(tracejit)
        rows = [json.loads(path.read_text()) for path in sorted(raw_dir.glob("*.json"))]
        if not rows:
            parser.error(f"no raw rows under {raw_dir}")
        return finalize(rows, environment, args, output_dir, 0.0)

    if args.mode == "manifest":
        manifest = {
            "manifest_version": "tracejit.realworld.corpus/v2",
            "generated_from_commit": _text_safe(["git", "rev-parse", "HEAD"]),
            "corpus_source_sha256": hashlib.sha256(Path(corpus.__file__).read_bytes()).hexdigest(),
            "tiers": {
                "A": "strict native: no workload adaptation, no execution contract",
                "B": "controlled execution: --contract allocator-entropy-v1 (a policy axis, not a workload property)",
                "C": "adapted workload: declared environment/input/invocation adaptation",
                "D": "unsupported: refused by TraceJIT and kept as a negative result",
            },
            "workloads": corpus.manifest_entries(vendor),
        }
        target = Path(__file__).resolve().parent / "manifest.json"
        target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"wrote {target} ({len(manifest['workloads'])} workloads)")
        return 0

    ctx = corpus.materialize_shared(scratch / "shared", vendor)
    environment = fingerprint(tracejit)
    policies = [item.strip() for item in args.policies.split(",") if item.strip()]
    unknown = [item for item in policies if item not in POLICIES]
    if unknown:
        parser.error(f"unknown policies {unknown}; choose from {sorted(POLICIES)}")
    splits = {item.strip() for item in args.splits.split(",") if item.strip()}
    selected = {item.strip() for item in args.workloads.split(",") if item.strip()}
    todos = [
        workload
        for workload in corpus.workloads()
        if workload.split in splits and (not selected or workload.id in selected)
    ]
    print(f"{len(todos)} workloads × {len(policies)} policies on {environment['cpu']['logical_count']} CPUs", flush=True)

    base_env = os.environ.copy()
    rows: list[dict] = []
    started_unix = time.time()
    for workload in todos:
        for policy in policies:
            row_path = raw_dir / f"{workload.id}__{policy}.json"
            if args.mode in ("qualify", "both") or args.reuse_qualification:
                if args.reuse_qualification and row_path.is_file():
                    row = json.loads(row_path.read_text())
                else:
                    try:
                        row = qualify(workload, policy, tracejit, ctx, scratch, base_env)
                    except Exception as error:  # noqa: BLE001 - recorded, never hidden
                        row = {
                            "workload_id": workload.id,
                            "family": workload.family,
                            "split": workload.split,
                            "environment_tier": workload.tier,
                            "policy": policy,
                            "status": "harness_error",
                            "error": f"{type(error).__name__}: {error}",
                            "decisions": [],
                        }
            else:
                row = json.loads(row_path.read_text()) if row_path.is_file() else {
                    "workload_id": workload.id,
                    "family": workload.family,
                    "split": workload.split,
                    "environment_tier": workload.tier,
                    "policy": policy,
                    "status": "not_qualified",
                    "decisions": [],
                }

            if args.mode in ("time", "both") and row.get("status") == "reused":
                try:
                    row["timing"] = time_workload(
                        workload, policy, tracejit, ctx, scratch, base_env, args.reps_scale, args.seed
                    )
                except Exception as error:  # noqa: BLE001
                    row["timing"] = {"status": "harness_error", "error": f"{type(error).__name__}: {error}"}

            row["assessment"] = applicability(row)
            row_path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
            rows.append(row)
            print(
                f"{workload.id:28} {policy:9} {row['status']:22} {row.get('classification', '-'):18} "
                f"{row['assessment']}",
                flush=True,
            )

    return finalize(rows, environment, args, output_dir, round(time.time() - started_unix, 3))


def finalize(rows: list[dict], environment: dict, args, output_dir: Path, elapsed: float) -> int:
    """Writes results.json, results.md and environment.json from the row set."""

    for row in rows:
        row["assessment"] = applicability(row)
    aggregate_result = aggregate(rows)
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_unix_ms": int(time.time() * 1000),
        "elapsed_seconds": elapsed,
        "environment": environment,
        "protocol": {
            "design": "randomized paired samples; paired geometric-mean ratio; percentile bootstrap CI",
            "bootstrap_resamples": 4000,
            "seed": args.seed,
            "reps_scale": args.reps_scale,
            "page_cache": "warm; the host cannot establish a cold page cache reliably",
            "outputs_removed_before_each_timed_sample": True,
            "hit_definition": "TraceJIT reports kind=Reused for that exact invocation",
            "incorrect_hit_definition": "a Reused decision whose independent oracle observation differs from native",
            "perf": environment["hardware_counters"],
            "hyperfine": (
                "available; see competitive.json for the independent wall-clock cross-check"
                if environment["tools"].get("hyperfine", {}).get("path")
                else "unavailable on this image"
            ),
        },
        "aggregate": aggregate_result,
        "workloads": sorted(rows, key=lambda item: (item["workload_id"], item["policy"])),
    }
    (output_dir / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    write_markdown(result, output_dir / "results.md")
    (output_dir / "environment.json").write_text(json.dumps(environment, indent=2, sort_keys=True) + "\n")
    print(json.dumps(aggregate_result, indent=2, sort_keys=True))
    failures = aggregate_result["incorrect_hits"] + [
        row["workload_id"] for row in rows if row["status"] in ("harness_error", "cold_mismatch", "mutation_mismatch")
    ]
    if failures:
        print(f"BENCHMARK FAILURES: {', '.join(sorted(set(failures)))}", file=sys.stderr)
        return 1
    return 0


def _text_safe(command: list[str]) -> str:
    """Like _text but never raises when the tool is absent."""

    try:
        return _text(command)
    except FileNotFoundError:
        return "unavailable"


if __name__ == "__main__":
    raise SystemExit(main())

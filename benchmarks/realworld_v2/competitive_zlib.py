#!/usr/bin/env python3
"""zlib compile head-to-head: native, ccache, TraceJIT.

All three arms run the same command in the same directory on the same CPU in
one interleaved randomised order, with the output object deleted before every
sample. Every sample's object is hashed against a native reference, so a fast
arm that produced the wrong bytes is caught rather than counted.

A cache sample is a hit only when that tool reports one: ccache from its own
``--print-stats`` counters, TraceJIT from the decision in its report. Wall time
is measured around the whole process; no arm's internal timers are used for the
comparison.

ccache and TraceJIT are not equivalent: ccache caches compiler invocations,
TraceJIT caches whole commands. A single compilation is ccache's best case and
the least favourable case for a whole-command cache, so this measures fixed hit
overhead per mechanism and supports no general productivity claim.

    python3 competitive_zlib.py --tracejit target/release/tracejit \\
        --ccache /tmp/tools/ccache --zlib-src /tmp/vendor/zlib-1.3.1 \\
        --reps 20 --output competitive_zlib.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402

ARMS = ("native", "ccache", "tracejit")
CCACHE_HITS = ("direct_cache_hit", "preprocessed_cache_hit")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_zlib(path: Path, root: Path) -> Path:
    """Accept an extracted tree or the pinned archive beside it.

    `fetch_inputs.py` downloads and verifies `zlib-1.3.1.tar.gz` but does not
    extract it; the corpus extracts it on first use. A standalone comparison may
    run before that, so extract here when only the archive exists.
    """

    if (path / "deflate.c").is_file():
        return path
    archive = path.parent / f"{path.name}.tar.gz"
    if archive.is_file():
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(root, filter="data")
            except TypeError:  # Python < 3.11.4 has no extraction filter
                tar.extractall(root)
        extracted = root / path.name
        if (extracted / "deflate.c").is_file():
            return extracted
    return path


def first_line(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, errors="replace", timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (completed.stdout or completed.stderr or "").strip().splitlines()
    return text[0] if text else None


def ccache_stats(ccache: Path, env: dict) -> dict[str, int]:
    completed = subprocess.run(
        [str(ccache), "--print-stats", "--format=json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return {key: int(value) for key, value in raw.items() if isinstance(value, (int, str))}


def stats_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: after.get(key, 0) - before.get(key, 0) for key in set(before) | set(after)}


def bootstrap_ratio(
    arm: list[int], reference: list[int], rng: random.Random, resamples: int = 10000
) -> list[float]:
    """Percentile bootstrap of median(reference) / median(arm)."""

    ratios = []
    for _ in range(resamples):
        left = statistics.median(rng.choices(reference, k=len(reference)))
        right = statistics.median(rng.choices(arm, k=len(arm)))
        if right:
            ratios.append(left / right)
    ratios.sort()
    if not ratios:
        return [float("nan"), float("nan")]
    return [ratios[int(0.025 * (len(ratios) - 1))], ratios[int(0.975 * (len(ratios) - 1))]]


def describe(samples: list[int]) -> dict:
    ordered = sorted(samples)
    return {
        "n": len(samples),
        "median_ns": int(statistics.median(samples)),
        "p10_ns": ordered[max(0, int(0.10 * (len(ordered) - 1)))],
        "p90_ns": ordered[int(0.90 * (len(ordered) - 1))],
        "min_ns": ordered[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", required=True)
    parser.add_argument("--ccache", default="")
    parser.add_argument("--zlib-src", required=True)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20261123)
    options = parser.parse_args()

    tracejit = Path(options.tracejit).resolve()
    ccache = Path(options.ccache).resolve() if options.ccache else None
    arms = [arm for arm in ARMS if arm != "ccache" or ccache is not None]

    root = Path(tempfile.mkdtemp(prefix="aa1-competitive-"))
    zlib = resolve_zlib(Path(options.zlib_src).resolve(), root)
    source = zlib / "deflate.c"
    if not source.is_file():
        print(f"missing {source}", file=sys.stderr)
        shutil.rmtree(root, ignore_errors=True)
        return 2
    work = root / "work"
    work.mkdir()
    command = ["gcc", "-O2", "-I", str(zlib), "-c", str(source), "-o", "deflate.o"]
    output = work / "deflate.o"

    base_env = {key: value for key, value in os.environ.items() if not key.startswith("CCACHE")}
    base_env["LC_ALL"] = "C"
    environments = {arm: dict(base_env) for arm in arms}
    environments["tracejit"]["TRACEJIT_CACHE_DIR"] = str(root / "tracejit-cache")
    if ccache is not None:
        environments["ccache"].update(
            {
                "CCACHE_DIR": str(root / "ccache-dir"),
                "CCACHE_MAXSIZE": "5G",
                # ccache >= 4.10 rejects CCACHE_COMPRESS=false; the negated
                # form is the documented spelling.
                "CCACHE_NOCOMPRESS": "1",
            }
        )

    def invoke(arm: str) -> subprocess.CompletedProcess:
        if arm == "native":
            argv = command
        elif arm == "ccache":
            argv = [str(ccache), *command]
        else:
            argv = [str(tracejit), "run", "--contract", "compiler-runtime-v1", "--", *command]
        return subprocess.run(
            argv, cwd=work, env=environments[arm], capture_output=True, timeout=600, check=False
        )

    output.unlink(missing_ok=True)
    reference = invoke("native")
    if reference.returncode != 0 or not output.is_file():
        print(f"native reference failed: {reference.stderr[:400]!r}", file=sys.stderr)
        return 2
    reference_hash = sha256(output)
    output.unlink()

    population: dict[str, int] = {}
    for arm in arms:
        output.unlink(missing_ok=True)
        started = time.perf_counter_ns()
        completed = invoke(arm)
        population[arm] = time.perf_counter_ns() - started
        if completed.returncode != 0:
            print(f"{arm} prime failed: {completed.stderr[:400]!r}", file=sys.stderr)
            return 2
        if sha256(output) != reference_hash:
            print(f"{arm} prime produced different bytes", file=sys.stderr)
            return 2
        # Two warm-up samples per arm, untimed, mirroring the protocol.
        for _ in range(2):
            output.unlink(missing_ok=True)
            invoke(arm)

    samples: dict[str, list[int]] = {arm: [] for arm in arms}
    hits: dict[str, int] = {arm: 0 for arm in arms}
    decisions: dict[str, dict[str, int]] = {arm: {} for arm in arms}
    mismatches = 0
    rng = random.Random(options.seed)

    for _ in range(options.reps):
        order = list(arms)
        rng.shuffle(order)
        for arm in order:
            output.unlink(missing_ok=True)
            before = ccache_stats(ccache, environments["ccache"]) if arm == "ccache" else {}
            started = time.perf_counter_ns()
            completed = invoke(arm)
            elapsed = time.perf_counter_ns() - started
            samples[arm].append(elapsed)
            if completed.returncode != 0 or not output.is_file() or sha256(output) != reference_hash:
                mismatches += 1
                continue
            if arm == "ccache":
                delta = stats_delta(before, ccache_stats(ccache, environments["ccache"]))
                if any(delta.get(key, 0) > 0 for key in CCACHE_HITS):
                    hits[arm] += 1
                    decisions[arm]["hit"] = decisions[arm].get("hit", 0) + 1
                else:
                    decisions[arm]["miss"] = decisions[arm].get("miss", 0) + 1
            elif arm == "tracejit":
                decision = runner.parse_plain_decision(completed.stderr)
                label = str(decision.get("cache_decision") or decision.get("kind") or "unknown")
                decisions[arm][label] = decisions[arm].get(label, 0) + 1
                if runner.is_hit(decision):
                    hits[arm] += 1

    native_median = statistics.median(samples["native"])
    result = {
        "schema": "tracejit.competitive-zlib/v1",
        "command": command,
        "repetitions": options.reps,
        "seed": options.seed,
        "mixed_order": True,
        "output_deleted_before_every_sample": True,
        "outputs_verified_against_native": mismatches == 0,
        "output_mismatches": mismatches,
        "environment": {
            "kernel": os.uname().release,
            "cpu_threads": os.cpu_count(),
            "gcc": first_line(["gcc", "--version"]),
            "tracejit_sha256": sha256(tracejit),
            "tracejit_commit": first_line(["git", "-C", str(Path(__file__).parents[2]), "rev-parse", "HEAD"]),
            "ccache": first_line([str(ccache), "--version"]) if ccache else None,
            "ccache_version_pin": "4.10.2",
            "zlib_sha256": hashlib.sha256((zlib / "deflate.c").read_bytes()).hexdigest(),
        },
        "arms": {},
        "comparison_note": (
            "ccache caches single compiler invocations; TraceJIT caches whole commands. "
            "One compilation is ccache's best case, so this measures hit overhead, not output."
        ),
    }
    for arm in arms:
        entry = {
            **describe(samples[arm]),
            "population_ns": population[arm],
            "observed_hits": hits[arm],
            "decisions": decisions[arm],
        }
        if arm != "native":
            entry["speedup_vs_native_median"] = native_median / statistics.median(samples[arm])
            entry["speedup_vs_native_ci95"] = bootstrap_ratio(samples[arm], samples["native"], rng)
        result["arms"][arm] = entry

    output_path = Path(options.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({arm: {k: v for k, v in entry.items() if k != "decisions"} for arm, entry in result["arms"].items()}, indent=1))
    print(f"outputs_verified={result['outputs_verified_against_native']} wrote {output_path}")
    shutil.rmtree(root, ignore_errors=True)
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

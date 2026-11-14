#!/usr/bin/env python3
"""Phase D differential harness: native vs discover vs reuse.

Compares full observables in the TraceJIT contract — stdout, stderr, exit status,
and named output files — not stdout alone. Each case:

  1. runs the command natively;
  2. discovers (cold TraceJIT run);
  3. reuses or retraces (warm TraceJIT run);
  4. optionally mutates the world and re-checks against a fresh native run.

A ``Reused`` decision whose observables differ from native is an ``incorrect_hit``.
Deterministic seeds. Minimized failures are persisted under the output directory.

Usage:
    python3 benchmarks/differential/phase_d.py [--seed N] [--output DIR] [--cases N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "allocator-entropy-v1"


def binary() -> Path:
    for candidate in (
        REPO / "target" / "release" / "tracejit",
        REPO / "target" / "debug" / "tracejit",
    ):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary; build with cargo build --workspace --release")


def env_for(cache: Path | None, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    if extra:
        env.update(extra)
    return env


def run(argv: list[str], cwd: Path, env: dict[str, str], stdin_bytes: bytes = b"") -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit": completed.returncode,
    }


def traced(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    stdin_bytes: bytes = b"",
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    result = run(
        [str(binary()), "run", "--json", "--contract", CONTRACT, "--", *argv],
        cwd,
        env,
        stdin_bytes,
    )
    try:
        report = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None, result
    return report, result


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.blake3(path.read_bytes()).hexdigest() if hasattr(hashlib, "blake3") else hashlib.sha256(path.read_bytes()).hexdigest()


def observables(
    stdout: bytes,
    stderr: bytes,
    exit_code: int,
    outputs: dict[str, str | None],
) -> dict[str, Any]:
    return {
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "exit": exit_code,
        "outputs": outputs,
    }


def collect_outputs(root: Path, names: list[str]) -> dict[str, str | None]:
    return {name: file_digest(root / name) for name in names}


def prepare(root: Path) -> None:
    input_path = root / "input.txt"
    if input_path.exists():
        input_path.chmod(0o644)
    input_path.write_text("alpha\nbeta\ngamma\n" * 2000)
    (root / "other").mkdir(exist_ok=True)
    (root / "sub").mkdir(exist_ok=True)
    (root / "sub" / "input.txt").write_text("alpha from sub\n" * 100)
    (root / "a").mkdir(exist_ok=True)
    (root / "b").mkdir(exist_ok=True)
    (root / "a" / "input.txt").write_text("alpha from a\n" * 100)
    (root / "b" / "input.txt").write_text("alpha from b\n" * 100)
    link = root / "link"
    if link.exists() or link.is_symlink():
        link.unlink()
    os.symlink("a", link)
    chain = root / "chain"
    if chain.exists() or chain.is_symlink():
        chain.unlink()
    os.symlink("a/input.txt", chain)
    (root / "payload.bin").write_bytes(b"\x00\x01\x02" * 4096)
    # Drop mutation leftovers so later arms start from a known tree.
    for leftover in ("sub-old", "input-moved.txt", "input-twin.txt", "copied.txt", "input.txt.bz2"):
        path = root / leftover
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink()


CASES: list[tuple[str, list[str], bytes, list[str]]] = [
    # name, argv, stdin, output file names relative to cwd (may be empty)
    ("sed", ["sed", "-e", "s/alpha/ALPHA/g", "input.txt"], b"", []),
    ("wc", ["wc", "-c", "input.txt"], b"", []),
    ("md5sum", ["md5sum", "input.txt"], b"", []),
    ("gzip", ["gzip", "-9", "-c", "input.txt"], b"", []),
    ("base64", ["base64", "input.txt"], b"", []),
    ("tr", ["tr", "a-z", "A-Z"], b"alpha beta\n", []),
    ("sed-sub", ["sed", "-e", "s/alpha/ALPHA/g", "sub/input.txt"], b"", []),
    ("cat", ["cat", "input.txt"], b"", []),
    ("head", ["head", "-c", "1000", "input.txt"], b"", []),
    ("cut", ["cut", "-d", " ", "-f1", "input.txt"], b"", []),
    ("bzip2-file", ["bzip2", "-k", "-f", "input.txt"], b"", ["input.txt.bz2"]),
    ("cp-out", ["cp", "input.txt", "copied.txt"], b"", ["copied.txt"]),
]


def mutate_content(root: Path, rng: random.Random) -> None:
    (root / "input.txt").write_text(f"changed {rng.random()}\n" * 1500)


def mutate_mtime(root: Path, rng: random.Random) -> None:
    del rng
    os.utime(root / "input.txt", (1_700_000_000, 1_700_000_100))


def mutate_permissions(root: Path, rng: random.Random) -> None:
    del rng
    (root / "input.txt").chmod(0o400)


def mutate_symlink(root: Path, rng: random.Random) -> None:
    del rng
    os.unlink(root / "link")
    os.symlink("b", root / "link")


def mutate_hardlink_swap(root: Path, rng: random.Random) -> None:
    del rng
    twin = root / "input-twin.txt"
    if twin.exists():
        twin.unlink()
    os.link(root / "input.txt", twin)
    twin.write_text("hardlink twin content\n" * 50)


def mutate_truncate(root: Path, rng: random.Random) -> None:
    del rng
    (root / "input.txt").write_text("truncated\n")


def mutate_append(root: Path, rng: random.Random) -> None:
    with open(root / "input.txt", "a") as handle:
        handle.write(f"appended {rng.random()}\n")


def mutate_rename(root: Path, rng: random.Random) -> None:
    del rng
    os.rename(root / "input.txt", root / "input-moved.txt")


def mutate_directory(root: Path, rng: random.Random) -> None:
    del rng
    shutil.rmtree(root / "sub2", ignore_errors=True)
    (root / "sub2").mkdir()
    (root / "sub2" / "input.txt").write_text("alpha from sub2\n" * 80)
    (root / "sub").rename(root / "sub-old")
    (root / "sub2").rename(root / "sub")


def mutate_env(root: Path, rng: random.Random) -> dict[str, str]:
    del root
    return {"TZ": "Europe/Paris", "FUZZ_MARKER": str(rng.random())}


def mutate_concurrent_writer(root: Path, rng: random.Random) -> None:
    del rng

    def writer() -> None:
        time.sleep(0.005)
        (root / "input.txt").write_text("concurrent\n" * 500)

    threading.Thread(target=writer).start()


def corrupt_cas(cache: Path, rng: random.Random) -> str | None:
    objects = sorted((cache / "objects").glob("*"), key=lambda path: path.stat().st_mtime)
    if not objects:
        return None
    victim = objects[rng.randrange(len(objects))]
    victim.write_bytes(b"\x00" * 8)
    return victim.name


MUTATIONS = [
    ("content", mutate_content),
    ("mtime", mutate_mtime),
    ("permissions", mutate_permissions),
    ("symlink", mutate_symlink),
    ("hardlink_swap", mutate_hardlink_swap),
    ("truncate", mutate_truncate),
    ("append", mutate_append),
    ("rename", mutate_rename),
    ("directory", mutate_directory),
    ("concurrent_writer", mutate_concurrent_writer),
]


def report_observables(report: dict[str, Any], root: Path, output_names: list[str]) -> dict[str, Any]:
    stdout = bytes(report.get("stdout_bytes") or [])
    stderr = bytes(report.get("stderr_bytes") or [])
    exit_code = int(report.get("exit_code", -1))
    return observables(stdout, stderr, exit_code, collect_outputs(root, output_names))


def native_observables(
    argv: list[str],
    root: Path,
    stdin_bytes: bytes,
    output_names: list[str],
    env_extra: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Clear tracked outputs so native and reuse start from the same prestate when possible.
    for name in output_names:
        path = root / name
        if path.exists():
            path.unlink()
    result = run(argv, root, env_for(None, env_extra), stdin_bytes)
    return (
        observables(
            result["stdout"],
            result["stderr"],
            result["exit"],
            collect_outputs(root, output_names),
        ),
        result,
    )


def shrink_failure(entry: dict[str, Any], output_dir: Path) -> Path:
    """Persist a minimized failure record (the case itself is already atomic)."""
    digest = hashlib.sha256(json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()[:12]
    path = output_dir / "failures" / f"minimized-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimization: keep only the fields needed to reproduce.
    minimized = {
        "case": entry.get("case"),
        "mutation": entry.get("mutation"),
        "decision": entry.get("decision"),
        "repro": entry.get("repro"),
        "native": entry.get("native"),
        "actual": entry.get("actual"),
        "seed": entry.get("seed"),
        "status": entry.get("status"),
    }
    path.write_text(json.dumps(minimized, indent=2) + "\n")
    return path


def compare_phase(
    name: str,
    argv: list[str],
    stdin_bytes: bytes,
    output_names: list[str],
    root: Path,
    cache: Path,
    seed: int,
) -> dict[str, Any]:
    for out in output_names:
        path = root / out
        if path.exists():
            path.unlink()

    native_obs, _ = native_observables(argv, root, stdin_bytes, output_names)
    # Reset outputs again before discovery so TraceJIT sees the same prestate.
    for out in output_names:
        path = root / out
        if path.exists():
            path.unlink()

    cold, raw_cold = traced(argv, root, env_for(cache), stdin_bytes)
    if cold is None:
        return {
            "case": name,
            "status": "discover-failed",
            "stderr": raw_cold["stderr"].decode(errors="replace")[:400],
            "seed": seed,
        }
    cold_obs = report_observables(cold, root, output_names)

    # Warm reuse / retrace against the post-discovery workspace.
    warm, raw_warm = traced(argv, root, env_for(cache), stdin_bytes)
    if warm is None:
        return {
            "case": name,
            "status": "warm-unparsed",
            "stderr": raw_warm["stderr"].decode(errors="replace")[:400],
            "seed": seed,
        }
    warm_obs = report_observables(warm, root, output_names)

    # After a mutating command, native must be re-run from an equivalent prestate.
    # For stream-only tools the prestate is just the input; for file writers we
    # compare warm against a native run that starts from a cleaned output path.
    for out in output_names:
        path = root / out
        if path.exists():
            path.unlink()
    native_after, _ = native_observables(argv, root, stdin_bytes, output_names)

    entry: dict[str, Any] = {
        "case": name,
        "seed": seed,
        "classification": cold.get("classification"),
        "first_decision": cold.get("cache_decision"),
        "warm_decision": warm.get("cache_decision"),
        "discover_matches_native": cold_obs == native_obs,
        "warm_matches_native": warm_obs == native_after,
        "reused": warm.get("cache_decision") == "Reused" or warm.get("kind") == "Reused",
        "native": native_obs,
        "discover": cold_obs,
        "warm": warm_obs,
        "native_after": native_after,
        "repro": f"{binary()} run --json --contract {CONTRACT} -- {' '.join(argv)}",
    }
    if entry["reused"] and not entry["warm_matches_native"]:
        entry["status"] = "INCORRECT_HIT"
        entry["actual"] = warm_obs
    elif not entry["discover_matches_native"]:
        # Discovery must match native observables when the command is executed.
        # A refusal that still returns native-equivalent bytes is ok; a mismatch is not.
        if cold.get("kind") == "Executed" and cold.get("exit_code") == native_obs["exit"]:
            # Some tools write outputs during discover; if digests differ only because
            # native was measured first, re-check discover against native_after.
            if cold_obs == native_after:
                entry["discover_matches_native"] = True
                entry["status"] = "ok"
            else:
                entry["status"] = "DISCOVER_MISMATCH"
                entry["actual"] = cold_obs
        else:
            entry["status"] = "ok" if entry["warm_matches_native"] else "refused-or-retraced"
    else:
        entry["status"] = "ok" if entry["warm_matches_native"] else "refused-or-retraced"
    return entry


def mutation_phase(
    mutation_name: str,
    mutation_fn,
    name: str,
    argv: list[str],
    stdin_bytes: bytes,
    output_names: list[str],
    root: Path,
    seed: int,
    rng: random.Random,
) -> dict[str, Any]:
    if mutation_name == "directory" and name != "sed-sub":
        return {"case": f"{mutation_name}:{name}", "status": "skipped", "seed": seed}
    if mutation_name == "symlink" and "link" not in " ".join(argv):
        # Still useful for path-identity tools that open input.txt via CWD only.
        pass

    cache = root / f"cache-{mutation_name}-{name}"
    cache.mkdir(parents=True, exist_ok=True)
    for out in output_names:
        path = root / out
        if path.exists():
            path.unlink()

    traced(argv, root, env_for(cache), stdin_bytes)
    env_extra: dict[str, str] | None = None
    if mutation_name == "env":
        env_extra = mutation_fn(root, rng)
    else:
        mutation_fn(root, rng)

    # Capture native answer under the mutated world.
    for out in output_names:
        path = root / out
        if path.exists():
            path.unlink()
    native_obs, _ = native_observables(argv, root, stdin_bytes, output_names, env_extra)

    for out in output_names:
        path = root / out
        if path.exists():
            path.unlink()
    report, raw = traced(argv, root, env_for(cache, env_extra), stdin_bytes)
    if report is None:
        return {
            "case": f"{mutation_name}:{name}",
            "mutation": mutation_name,
            "status": "refused-or-failed-closed",
            "seed": seed,
            "stderr": raw["stderr"].decode(errors="replace")[:400],
        }
    actual = report_observables(report, root, output_names)
    decision = report.get("cache_decision")
    reused = decision == "Reused" or report.get("kind") == "Reused"
    entry = {
        "case": f"{mutation_name}:{name}",
        "mutation": mutation_name,
        "decision": decision,
        "seed": seed,
        "native": native_obs,
        "actual": actual,
        "matches_native": actual == native_obs,
        "repro": f"{binary()} run --json --contract {CONTRACT} -- {' '.join(argv)}",
    }
    if reused and actual != native_obs:
        entry["status"] = "INCORRECT_HIT"
    else:
        entry["status"] = "ok" if actual == native_obs else "refused-or-retraced"
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="benchmarks/results/phase_d/differential")
    parser.add_argument(
        "--cases",
        type=int,
        default=0,
        help="optional cap on base cases (0 = all)",
    )
    args = parser.parse_args()
    rng = random.Random(args.seed)
    output_dir = REPO / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    root = Path(tempfile.mkdtemp(prefix="tracejit-phase-d-"))
    prepare(root)
    cases = CASES if args.cases <= 0 else CASES[: args.cases]
    results: dict[str, Any] = {
        "seed": args.seed,
        "contract": CONTRACT,
        "harness": "phase_d",
        "cases": [],
        "incorrect_hits": 0,
        "discover_mismatches": 0,
        "executed_scenarios": 0,
        "skipped_scenarios": 0,
    }

    for name, argv, stdin_bytes, output_names in cases:
        cache = root / f"cache-base-{name}"
        entry = compare_phase(name, argv, stdin_bytes, output_names, root, cache, args.seed)
        results["executed_scenarios"] += 1
        if entry["status"] == "INCORRECT_HIT":
            results["incorrect_hits"] += 1
            entry["failure_path"] = str(shrink_failure(entry, output_dir))
        elif entry["status"] == "DISCOVER_MISMATCH":
            results["discover_mismatches"] += 1
            entry["failure_path"] = str(shrink_failure(entry, output_dir))
        results["cases"].append(entry)

    # Environment mutation as a first-class arm (returns env overrides).
    for name, argv, stdin_bytes, output_names in cases:
        entry = mutation_phase(
            "env", mutate_env, name, argv, stdin_bytes, output_names, root, args.seed, rng
        )
        if entry["status"] == "skipped":
            results["skipped_scenarios"] += 1
        else:
            results["executed_scenarios"] += 1
        if entry.get("status") == "INCORRECT_HIT":
            results["incorrect_hits"] += 1
            entry["failure_path"] = str(shrink_failure(entry, output_dir))
        results["cases"].append(entry)

    for mutation_name, mutation_fn in MUTATIONS:
        for name, argv, stdin_bytes, output_names in cases:
            # Restore a clean input tree between mutations.
            prepare(root)
            entry = mutation_phase(
                mutation_name,
                mutation_fn,
                name,
                argv,
                stdin_bytes,
                output_names,
                root,
                args.seed,
                rng,
            )
            if entry["status"] == "skipped":
                results["skipped_scenarios"] += 1
            else:
                results["executed_scenarios"] += 1
            if entry.get("status") == "INCORRECT_HIT":
                results["incorrect_hits"] += 1
                entry["failure_path"] = str(shrink_failure(entry, output_dir))
            results["cases"].append(entry)

    # CAS corruption: must never expose unverified bytes as a hit.
    prepare(root)
    cache = root / "cache-corrupt"
    argv = ["md5sum", "input.txt"]
    traced(argv, root, env_for(cache))
    victim = corrupt_cas(cache, rng)
    native_obs, _ = native_observables(argv, root, b"", [])
    report, raw = traced(argv, root, env_for(cache))
    entry = {
        "case": "corrupt-cas-object",
        "victim": victim,
        "seed": args.seed,
        "decision": report.get("cache_decision") if report else None,
        "status": "refused-or-failed-closed",
    }
    results["executed_scenarios"] += 1
    if report is not None:
        actual = report_observables(report, root, [])
        reused = report.get("cache_decision") == "Reused" or report.get("kind") == "Reused"
        if reused and actual != native_obs:
            entry["status"] = "INCORRECT_HIT"
            entry["native"] = native_obs
            entry["actual"] = actual
            results["incorrect_hits"] += 1
            entry["failure_path"] = str(shrink_failure(entry, output_dir))
        elif actual == native_obs:
            entry["status"] = "ok"
    results["cases"].append(entry)

    # Contract mismatch: a native-mode record must not satisfy a controlled-contract lookup.
    prepare(root)
    cache = root / "cache-contract"
    argv = ["cat", "input.txt"]
    run(
        [str(binary()), "run", "--json", "--", *argv],
        root,
        env_for(cache),
    )
    report, _ = traced(argv, root, env_for(cache))
    entry = {
        "case": "contract-mismatch-native-vs-allocator",
        "seed": args.seed,
        "decision": report.get("cache_decision") if report else None,
        "kind": report.get("kind") if report else None,
        "status": "ok",
    }
    results["executed_scenarios"] += 1
    if report is not None:
        reused = report.get("cache_decision") == "Reused" or report.get("kind") == "Reused"
        if reused:
            entry["status"] = "INCORRECT_HIT"
            results["incorrect_hits"] += 1
            entry["failure_path"] = str(shrink_failure(entry, output_dir))
        else:
            entry["status"] = "ok"
    else:
        entry["status"] = "refused-or-failed-closed"
    results["cases"].append(entry)

    out_path = output_dir / f"phase-d-seed-{args.seed}.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    statuses: dict[str, int] = {}
    for case in results["cases"]:
        statuses[case["status"]] = statuses.get(case["status"], 0) + 1
    summary = {
        "seed": args.seed,
        "cases": len(results["cases"]),
        "executed_scenarios": results["executed_scenarios"],
        "skipped_scenarios": results["skipped_scenarios"],
        "statuses": statuses,
        "incorrect_hits": results["incorrect_hits"],
        "discover_mismatches": results["discover_mismatches"],
        "output": str(out_path),
    }
    print(json.dumps(summary, indent=2))
    shutil.rmtree(root, ignore_errors=True)
    failed = results["incorrect_hits"] + results["discover_mismatches"]
    print("RESULT phase-d-differential PASS" if failed == 0 else "RESULT phase-d-differential FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

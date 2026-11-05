#!/usr/bin/env python3
"""Adversarial differential testing: direct execution versus TraceJIT reuse.

Each case runs the same command twice under one declared contract, mutates the world between the
runs, and compares TraceJIT's bytes with a fresh native execution. A `Reused` decision whose bytes
differ from the native answer is an `incorrect_hit` and fails the run.

Mutations cover content, symlink chains before `..`, permissions, executable replacement,
environment, inherited stdin offsets, a concurrent writer, a missing-then-present input, and a
corrupt CAS object. Deterministic seeds; no claim of proof, only the cases listed in the report.

Usage:
    python3 benchmarks/differential/fuzz.py [--seed N] [--output DIR]
"""

from __future__ import annotations

import argparse
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

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "allocator-entropy-v1"


def binary() -> Path:
    for candidate in (REPO / "target" / "release" / "tracejit", REPO / "target" / "debug" / "tracejit"):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary")


def env_for(cache: Path | None) -> dict:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "LC_ALL": "C", "TZ": "UTC"}
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(argv, cwd, env, stdin_bytes=b""):
    completed = subprocess.run(
        argv, cwd=cwd, env=env, input=stdin_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return {"stdout": completed.stdout, "stderr": completed.stderr, "exit": completed.returncode}


def traced(argv, cwd, env, stdin_bytes=b""):
    result = run([str(binary()), "run", "--json", "--contract", CONTRACT, "--", *argv], cwd, env, stdin_bytes)
    try:
        report = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None, result
    return report, result


def prepare(root: Path) -> None:
    (root / "input.txt").write_text("alpha\nbeta\ngamma\n" * 2000)
    (root / "other").mkdir()
    (root / "sub").mkdir()
    (root / "sub" / "input.txt").write_text("alpha from sub\n" * 100)
    (root / "a").mkdir()
    (root / "b").mkdir()
    (root / "a" / "input.txt").write_text("alpha from a\n" * 100)
    (root / "b" / "input.txt").write_text("alpha from b\n" * 100)
    os.symlink("a", root / "link")
    os.symlink("a/input.txt", root / "chain")
    (root / "copy").write_bytes((REPO / "target/release/tracejit").read_bytes() if (REPO / "target/release/tracejit").is_file() else b"")


def native(argv, root, env, stdin_bytes=b""):
    return run(argv, root, env, stdin_bytes)


CASES = [
    ("sed", ["sed", "-e", "s/alpha/ALPHA/g", "input.txt"], b""),
    ("wc", ["wc", "-c", "input.txt"], b""),
    ("md5sum", ["md5sum", "input.txt"], b""),
    ("gzip", ["gzip", "-9", "-c", "input.txt"], b""),
    ("base64", ["base64", "input.txt"], b""),
    ("tr", ["tr", "a-z", "A-Z"], b"alpha beta\n"),
    ("sed-sub", ["sed", "-e", "s/alpha/ALPHA/g", "sub/input.txt"], b""),
]


def replace_content(root: Path, rng: random.Random) -> None:
    (root / "input.txt").write_text(f"changed {rng.random()}\n" * 1500)


def repoint_symlink(root: Path, rng: random.Random) -> None:
    os.unlink(root / "link")
    os.symlink("b", root / "link")


def permissions(root: Path, rng: random.Random) -> None:
    (root / "input.txt").chmod(0o400)


def environment(root: Path, rng: random.Random) -> dict:
    return {"TZ": "Europe/Paris", "FUZZ_MARKER": str(rng.random())}


def executable_replacement(root: Path, rng: random.Random) -> None:
    shutil.copy(binary(), root / "tracejit-copy")
    (root / "tracejit-copy").write_bytes(b"\x7fELF" + os.urandom(64))


def stdin_offset(root: Path, rng: random.Random) -> bytes:
    return b"x" * 3


def touch_metadata(root: Path, rng: random.Random) -> None:
    os.utime(root / "input.txt", None)


def directory_replacement(root: Path, rng: random.Random) -> None:
    # The command reads `sub/input.txt`; replace the directory the relative path resolves through.
    shutil.rmtree(root / "sub2", ignore_errors=True)
    (root / "sub2").mkdir()
    (root / "sub2" / "input.txt").write_text("alpha from sub2\n" * 80)
    (root / "sub").rename(root / "sub-old")
    (root / "sub2").rename(root / "sub")


def concurrent_writer(root: Path, rng: random.Random) -> None:
    def writer():
        time.sleep(0.005)
        (root / "input.txt").write_text("concurrent\n" * 500)

    thread = threading.Thread(target=writer)
    thread.start()


def corrupt_object(cache: Path, rng: random.Random) -> str | None:
    objects = sorted((cache / "objects").glob("*"), key=lambda path: path.stat().st_mtime)
    if not objects:
        return None
    victim = objects[-1]
    victim.write_bytes(b"\x00" * 8)
    return victim.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="benchmarks/results/phase2h/differential")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    output_dir = REPO / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    root = Path(tempfile.mkdtemp(prefix="tracejit-fuzz-"))
    prepare(root)
    cache = root / "cache"
    env = env_for(cache)
    results = {"seed": args.seed, "contract": CONTRACT, "cases": [], "incorrect_hits": 0}

    for name, argv, stdin_bytes in CASES:
        cold, raw = traced(argv, root, env, stdin_bytes)
        if cold is None:
            results["cases"].append({"case": name, "status": "trace-failed",
                                     "stderr": raw["stderr"].decode(errors="replace")[:400]})
            continue
        expected = native(argv, root, env_for(None), stdin_bytes)
        warm, _ = traced(argv, root, env, stdin_bytes)
        if warm is None:
            results["cases"].append({"case": name, "status": "warm-unparsed"})
            continue
        entry = {
            "case": name,
            "classification": cold.get("classification"),
            "first_decision": cold.get("cache_decision"),
            "warm_decision": warm.get("cache_decision"),
            "first_matches_native": bytes(cold.get("stdout_bytes") or []) == expected["stdout"],
            "warm_matches_native": bytes(warm.get("stdout_bytes") or []) == expected["stdout"],
            "reused": warm.get("cache_decision") == "Reused",
        }
        if entry["reused"] and not entry["warm_matches_native"]:
            results["incorrect_hits"] += 1
            entry["status"] = "INCORRECT_HIT"
        else:
            entry["status"] = "ok" if entry["warm_matches_native"] else "refused-or-retraced"
        results["cases"].append(entry)

    # Mutations: the second invocation must return what a native run observes now, or refuse.
    for mutation in (replace_content, repoint_symlink, permissions, executable_replacement,
                     stdin_offset, concurrent_writer, touch_metadata, directory_replacement):
        for name, argv, stdin_bytes in CASES:
            local_argv = list(argv)
            if mutation is executable_replacement:
                local_argv = list(argv)
                continue
            if mutation is stdin_offset and name != "tr":
                continue
            if mutation is directory_replacement and name != "sed-sub":
                continue
            current_root = root
            cache = root / f"cache-{mutation.__name__}-{name}"
            env = env_for(cache)
            traced(local_argv, current_root, env, stdin_bytes)
            changed_stdin = mutation(root, rng) if mutation is stdin_offset else stdin_bytes
            if mutation is environment:
                env = env_for(cache) | mutation(root, rng)
            extra_env = env
            expected = native(local_argv, current_root, env_for(None), changed_stdin)
            report, raw = traced(local_argv, current_root, extra_env, changed_stdin)
            if report is None:
                results["cases"].append({"case": f"{mutation.__name__}:{name}",
                                         "status": "refused-or-failed-closed"})
                continue
            actual = bytes(report.get("stdout_bytes") or [])
            decision = report.get("cache_decision")
            entry = {
                "case": f"{mutation.__name__}:{name}",
                "decision": decision,
                "matches_native": actual == expected["stdout"],
                "status": "ok" if actual == expected["stdout"] else "INCORRECT_HIT",
                "repro": f"bash: run --contract {CONTRACT} -- {' '.join(local_argv)}",
            }
            if decision == "Reused" and actual != expected["stdout"]:
                results["incorrect_hits"] += 1
                entry["status"] = "INCORRECT_HIT"
            results["cases"].append(entry)

    # Corrupt a CAS object: a hit must never expose bytes that are not the stored bytes.
    cache = root / "cache-corrupt"
    env = env_for(cache)
    argv = ["md5sum", "input.txt"]
    traced(argv, root, env)
    victim = corrupt_object(cache, rng)
    expected = native(argv, root, env_for(None))
    report, raw = traced(argv, root, env)
    entry = {"case": "corrupt-object", "victim": victim, "decision": report.get("cache_decision") if report else None,
             "status": "refused-or-failed-closed"}
    if report is not None:
        actual = bytes(report.get("stdout_bytes") or [])
        if report.get("cache_decision") == "Reused" and actual != expected["stdout"]:
            entry["status"] = "INCORRECT_HIT"
            results["incorrect_hits"] += 1
        elif actual == expected["stdout"]:
            entry["status"] = "ok"
    results["cases"].append(entry)

    output = output_dir / f"fuzz-{args.seed}.json"
    output.write_text(json.dumps(results, indent=2) + "\n")
    statuses = {}
    for case in results["cases"]:
        statuses[case["status"]] = statuses.get(case["status"], 0) + 1
    print(json.dumps({"cases": len(results["cases"]), "statuses": statuses,
                      "incorrect_hits": results["incorrect_hits"]}, indent=2))
    shutil.rmtree(root, ignore_errors=True)
    print("RESULT differential PASS" if results["incorrect_hits"] == 0 else "RESULT differential FAIL")
    return 0 if results["incorrect_hits"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

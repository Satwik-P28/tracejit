#!/usr/bin/env python3
"""Phase AE: deterministic and probabilistic tests of the validate→restore window.

Phase AD claimed a "second validation pass".  The implementation has **one** surviving
pass (Phase X removed the first).  This harness maps the window the passing code leaves
open, using the product's own test hooks, and records which mutations are detected:

``before_validation``   ``TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH`` writes the input
                        immediately before the surviving guard pass.  Must deoptimise.
``before_load``         ``TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH`` writes it before the cached
                        streams are loaded.  The surviving pass runs later, so a persistent
                        mutation must also deoptimise.
``reverted``            mutation + immediate restore in the same hook window: the surviving
                        pass sees the original bytes, so a HIT is correct and expected.
``after_validation``    ``TRACEJIT_TEST_RESTORE_PAUSE_PATH`` makes the hit path sleep
                        before applying the output; the harness mutates the input during
                        that sleep.  A HIT here serves bytes computed from the *old* input:
                        this is the residual race, and it is measured, not assumed.
``during_hashing``      a concurrent writer rewrites a 4 KiB block of a 128 MiB input while
                        a HIT hashes it.  Probabilistic: the outcome is recorded per trial.

Nothing in this harness modifies production behaviour; every hook is unset by default and
documented in the source as test-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "realworld_v2"))

import runner  # noqa: E402

CONTRACT = "allocator-entropy-v1"
ARGV = ["gzip", "-9", "-n", "-k", "-f", "input.bin"]
OUTPUT = "input.bin.gz"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def oracle(root: Path, payload: bytes) -> dict:
    """Native expectation for an exact input payload."""

    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    (root / "input.bin").write_bytes(payload)
    completed = subprocess.run(ARGV, cwd=root, env=dict(os.environ), capture_output=True, check=False)
    return {
        "exit": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "output_sha256": sha256_file(root / OUTPUT) if (root / OUTPUT).is_file() else None,
    }


def observed(ws: Path, completed: subprocess.CompletedProcess) -> dict:
    return {
        "exit": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "output_sha256": sha256_file(ws / OUTPUT) if (ws / OUTPUT).is_file() else None,
    }


def run(tracejit: Path, ws: Path, cache: Path, extra_env: dict | None = None):
    env = runner.cache_env(dict(os.environ), cache)
    env.pop("TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH", None)
    env.pop("TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH", None)
    # Never set a hook variable to an empty string: TraceJIT records TRACEJIT_TEST_*
    # environment values as dependencies, so a present-but-empty variable makes the next
    # run with the variable absent deoptimise for "environment value changed".
    env.pop("TRACEJIT_TEST_PRE_LOAD_RESTORE_HEX", None)
    env.pop("TRACEJIT_TEST_RESTORE_PAUSE_PATH", None)
    if extra_env:
        env.update(extra_env)
    completed, decision = runner.run_plain(tracejit, ARGV, ws, env, CONTRACT)
    return completed, decision


def prepare(ws: Path, cache: Path, payload: bytes) -> None:
    shutil.rmtree(ws, ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    ws.mkdir(parents=True)
    (ws / "input.bin").write_bytes(payload)


def populate(tracejit: Path, ws: Path, cache: Path, runs: int = 2) -> None:
    """Reach the steady state the experiments assume.

    One trace is not enough: the first lookup after a cold trace can deoptimise once (the
    recorded output state differs from the deleted-output pre-state).  Two population runs
    leave the cache in the state a repeated user actually sees, which the measured run then
    has to reuse.
    """

    for _ in range(runs):
        (ws / OUTPUT).unlink(missing_ok=True)
        run(tracejit, ws, cache)
    (ws / OUTPUT).unlink(missing_ok=True)


def hook_case(name: str, tracejit: Path, root: Path, payload: bytes, mutated: bytes) -> dict:
    ws, cache = root / "ws", root / "cache"
    prepare(ws, cache, payload)
    # The hook writes exactly these bytes, so this is the expectation the retrace must match.
    mutated = b"TOCTOU-MUTATED\n"
    old = oracle(root / "old", payload)
    new = oracle(root / "new", mutated)
    populate(tracejit, ws, cache)
    completed, decision = run(tracejit, ws, cache, {
        "TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH": str(ws / "input.bin"),
    })
    got = observed(ws, completed)
    return {
        "scenario": name,
        "decision": (decision or {}).get("kind"),
        "cache_decision": (decision or {}).get("cache_decision"),
        "correct_for_old_input": got == old,
        "correct_for_new_input": got == new,
        "detected": not runner.is_hit(decision),
        "exit": completed.returncode,
    }


def before_load_case(tracejit: Path, root: Path, payload: bytes, mutated: bytes) -> dict:
    ws, cache = root / "ws", root / "cache"
    prepare(ws, cache, payload)
    mutated = b"TOCTOU-MUTATED\n"
    old = oracle(root / "old", payload)
    new = oracle(root / "new", mutated)
    populate(tracejit, ws, cache)
    completed, decision = run(tracejit, ws, cache, {
        "TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH": str(ws / "input.bin"),
    })
    got = observed(ws, completed)
    return {
        "scenario": "before_load",
        "decision": (decision or {}).get("kind"),
        "cache_decision": (decision or {}).get("cache_decision"),
        "correct_for_old_input": got == old,
        "correct_for_new_input": got == new,
        "detected": not runner.is_hit(decision),
        "exit": completed.returncode,
    }


def reverted_case(tracejit: Path, root: Path, payload: bytes) -> dict:
    ws, cache = root / "ws", root / "cache"
    prepare(ws, cache, payload)
    old = oracle(root / "old", payload)
    populate(tracejit, ws, cache)
    # The hook writes TOCTOU-MUTATED, then writes the hex payload back in full, so the
    # surviving pass sees exactly the original bytes.  The caller supplies a payload small
    # enough for one hex argument (32 KiB).
    completed, decision = run(tracejit, ws, cache, {
        "TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH": str(ws / "input.bin"),
        "TRACEJIT_TEST_PRE_LOAD_RESTORE_HEX": payload.hex(),
    })
    got = observed(ws, completed)
    return {
        "scenario": "reverted_mutation",
        "decision": (decision or {}).get("kind"),
        "cache_decision": (decision or {}).get("cache_decision"),
        "correct_for_old_input": got == old,
        "hit": runner.is_hit(decision),
        "note": (
            "the hook restores the content but not the inode's mtime, so the metadata guard "
            "still deoptimises: a transient rewrite is detected, not invisible"
        ),
    }


def after_validation_case(tracejit: Path, root: Path, payload: bytes, mutated: bytes, trace: bool) -> dict:
    ws, cache = root / "ws", root / "cache"
    prepare(ws, cache, payload)
    old = oracle(root / "old", payload)
    new = oracle(root / "new", mutated)
    populate(tracejit, ws, cache)
    env = runner.cache_env(dict(os.environ), cache)
    env["TRACEJIT_TEST_RESTORE_PAUSE_PATH"] = str(ws / OUTPUT)
    started = time.time()
    process = subprocess.Popen(
        [str(tracejit), "run", "--contract", CONTRACT, "--", *ARGV],
        cwd=ws, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # The pause is 30 s; mutate 1 s in, well after the guard pass has finished and before
    # the staged output is applied.
    time.sleep(1.0)
    (ws / "input.bin").write_bytes(mutated)
    stdout, stderr = process.communicate(timeout=90)
    completed = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    decision = runner.parse_plain_decision(stderr)
    got = observed(ws, completed)
    return {
        "scenario": "after_validation_before_apply",
        "decision": (decision or {}).get("kind"),
        "cache_decision": (decision or {}).get("cache_decision"),
        "correct_for_old_input": got == old,
        "correct_for_new_input": got == new,
        "undetected_stale_bytes": runner.is_hit(decision) and got == old and got != new,
        "elapsed_s": round(time.time() - started, 2),
        "exit": process.returncode,
    }


def during_hashing_case(tracejit: Path, root: Path, trials: int, size: int) -> dict:
    rng = random.Random(11)
    base = (b"line of compressible text used for the hashing race\n" * (size // 50 + 1))[:size]
    outcomes = []
    for trial in range(trials):
        ws, cache = root / f"ws{trial}", root / f"cache{trial}"
        prepare(ws, cache, base)
        old = oracle(root / f"old{trial}", base)
        populate(tracejit, ws, cache)
        env = runner.cache_env(dict(os.environ), cache)
        process = subprocess.Popen(
            [str(tracejit), "run", "--contract", CONTRACT, "--", *ARGV],
            cwd=ws, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.time() + 5.0
        writes = 0
        while process.poll() is None and time.time() < deadline:
            offset = rng.randrange(0, size - 4096)
            with (ws / "input.bin").open("r+b") as handle:
                handle.seek(offset)
                handle.write(b"MUTATED-BLOCK" * 341)
            writes += 1
            time.sleep(0.002)
        stdout, stderr = process.communicate(timeout=120)
        completed = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        decision = runner.parse_plain_decision(stderr)
        got = observed(ws, completed)
        outcomes.append({
            "trial": trial,
            "decision": (decision or {}).get("kind"),
            "concurrent_writes": writes,
            "correct_for_old_input": got == old,
            "hit": runner.is_hit(decision),
        })
    return {
        "scenario": "during_hashing",
        "input_bytes": size,
        "trials": outcomes,
        "detected": sum(1 for outcome in outcomes if not outcome["hit"]),
        "undetected_stale": sum(1 for outcome in outcomes
                                if outcome["hit"] and outcome["correct_for_old_input"]),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseae-toctou")
    parser.add_argument("--output", type=Path,
                        default=REPO / "benchmarks/results/phaseae/toctou_race.json")
    parser.add_argument("--hashing-trials", type=int, default=8)
    parser.add_argument("--hashing-size", type=int, default=64 << 20)
    args = parser.parse_args(argv)

    tracejit = args.tracejit.resolve()
    payload = b"".join(f"row {i} key={(i * 7919) % 100003}\n".encode() for i in range(60_000))
    mutated = b"MUTATED-INPUT\n" + payload
    shutil.rmtree(args.scratch, ignore_errors=True)
    args.scratch.mkdir(parents=True)

    cases = [
        hook_case("before_validation", tracejit, args.scratch / "before-validation", payload, mutated),
        before_load_case(tracejit, args.scratch / "before-load", payload, mutated),
        reverted_case(tracejit, args.scratch / "reverted",
                      b"small payload for the reverted-mutation case\n" * 40),
        after_validation_case(tracejit, args.scratch / "after-validation", payload, mutated, False),
        during_hashing_case(tracejit, args.scratch / "during-hashing",
                            args.hashing_trials, args.hashing_size),
    ]
    payload_json = {"cases": cases, "argv": ARGV, "contract": CONTRACT,
                    "hooks": {
                        "before_validation": "TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH",
                        "before_load": "TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH",
                        "after_validation": "TRACEJIT_TEST_RESTORE_PAUSE_PATH + external writer",
                        "during_hashing": "concurrent writer, no hook",
                    }}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload_json, indent=2, sort_keys=True) + "\n")
    shutil.rmtree(args.scratch, ignore_errors=True)
    for case in cases:
        print({k: v for k, v in case.items() if k != "trials"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

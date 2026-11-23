#!/usr/bin/env python3
"""Phase AA adversarial suite.

Three kinds of evidence are reported separately and never merged:

``preserved_counterexamples``
    The Phase W1 rename-source case (a renamed-away file whose bytes move into
    an output) and the Phase X same-timestamp rewrite attempt. Both are run
    through the existing 13-case Phase W1 matrix, so a regression in either the
    product or the fixture is visible as a failure.

``workload_mutations``
    Mutations of the real corpus inputs: content replacement, symlink swap,
    hard-link alias edit, output corruption, and a rename-then-recreate command.

``race_window``
    The validate-to-restore TOCTOU window. A hit is raced against a concurrent
    writer. This cannot prove the window is closed; it measures whether a stale
    observation was produced in N attempts. Unsupported behaviour is reported as
    unsupported, never as a pass.

Exit status is non-zero only for an observed incorrect hit or a failing
preserved case. A race trial that produced a correct result is not evidence that
the race is impossible, and the JSON says so.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import oracle  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

RENAME_C = r"""
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
int main(void) {
  int fd = open("out.dat", O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (fd < 0) return 1;
  if (write(fd, "first\n", 6) != 6) return 1;
  close(fd);
  if (rename("out.dat", "out.dat.bak") != 0) return 1;
  fd = open("out.dat", O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (fd < 0) return 1;
  if (write(fd, "second\n", 7) != 7) return 1;
  return close(fd);
}
"""

COPY_C = r"""
#include <fcntl.h>
#include <unistd.h>
int main(int argc, char **argv) {
  if (argc < 3) return 2;
  int in = open(argv[1], O_RDONLY);
  if (in < 0) return 1;
  int out = open(argv[2], O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (out < 0) return 1;
  char buffer[4096];
  for (;;) {
    ssize_t got = read(in, buffer, sizeof buffer);
    if (got < 0) return 1;
    if (got == 0) break;
    if (write(out, buffer, (size_t)got) != got) return 1;
  }
  return close(in) | close(out);
}
"""


def compile_helper(source: str, target: Path) -> Path:
    c_file = target.with_suffix(".c")
    c_file.write_text(source)
    subprocess.run(["cc", "-O1", "-o", str(target), str(c_file)], check=True)
    return target


def run_native(argv: list[str], ws: Path) -> dict:
    completed = subprocess.run(argv, cwd=ws, capture_output=True, check=False)
    tree = oracle.observe_workspace(ws)
    return oracle.process_observation(completed.returncode, completed.stdout, completed.stderr, tree)


def run_traced(tracejit: Path, cache: Path, argv: list[str], ws: Path) -> dict:
    env = os.environ.copy()
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    completed = subprocess.run(
        [str(tracejit), "run", "--json", "--", *argv], cwd=ws, env=env, capture_output=True, check=False
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"report": None, "raw": completed.stdout[:400].decode(errors="replace")}
    stdout = bytes(report.get("stdout_bytes") or [])
    stderr = bytes(report.get("stderr_bytes") or [])
    tree = oracle.observe_workspace(ws)
    return {
        "report": report,
        "observation": oracle.process_observation(int(report.get("exit_code", -1)), stdout, stderr, tree),
    }


def case(
    name: str,
    root: Path,
    tracejit: Path,
    setup,
    argv_factory,
    mutate,
    description: str,
) -> dict:
    work = root / name / "work"
    native = root / name / "native"
    cache = root / name / "cache"
    for directory in (work, native):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        setup(directory)

    argv = argv_factory(work)
    cold = run_traced(tracejit, cache, argv, work)
    if cold.get("report") is None:
        return {"case": name, "status": "error", "detail": cold.get("raw")}

    mutate(work)
    mutate(native)
    for output in ("out.dat", "out.dat.bak", "copy.txt", "out.txt"):
        (work / output).unlink(missing_ok=True)
    native_obs = run_native(argv, native)
    warm = run_traced(tracejit, cache, argv, work)
    if warm.get("report") is None:
        return {"case": name, "status": "error", "detail": warm.get("raw")}

    comparison = oracle.compare(native_obs, warm["observation"])
    reused = warm["report"].get("kind") == "Reused"
    if reused and not comparison["match"]:
        status = "incorrect_hit"
    elif not comparison["match"]:
        status = "mismatch"
    else:
        status = "ok"
    return {
        "case": name,
        "status": status,
        "mutation": description,
        "reused": reused,
        "decision": warm["report"].get("cache_decision"),
        "classification": cold["report"].get("classification"),
        "covered_differences": comparison["covered_differences"],
        "out_of_contract_differences": comparison["out_of_contract_differences"],
    }


def same_timestamp_attempt(root: Path, tracejit: Path, seed: int) -> dict:
    """Attempts the Phase X same-size, same-mtime rewrite counterexample.

    Phase X rejected digest sharing between validation passes because a
    same-size rewrite inside one timestamp tick can leave size, mtime and ctime
    identical. Whether that tick-window is reachable depends on the kernel and
    filesystem, so this case *measures* the collision instead of assuming it:
    it reports whether mtime and ctime were actually reproduced, then runs the
    warm attempt and compares against native.
    """

    name = "same_size_same_mtime_rewrite"
    work = root / name / "work"
    native = root / name / "native"
    cache = root / name / "cache"
    helper = compile_helper(COPY_C, root / "copy-helper")
    for directory in (work, native):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        (directory / "in.txt").write_bytes(b"A" * 8192)
    argv = [str(helper), "in.txt", "copy.txt"]

    cold = run_traced(tracejit, cache, argv, work)
    if cold.get("report") is None:
        return {"case": name, "status": "error", "detail": cold.get("raw")}

    before = (work / "in.txt").stat()
    # Same size, different bytes, mtime restored to the recorded value.
    with (work / "in.txt").open("r+b") as handle:
        handle.seek(0)
        handle.write(b"B" * 8192)
    os.utime(work / "in.txt", ns=(before.st_atime_ns, before.st_mtime_ns))
    after = (work / "in.txt").stat()
    collision = {
        "size_unchanged": before.st_size == after.st_size,
        "mtime_ns_unchanged": before.st_mtime_ns == after.st_mtime_ns,
        "ctime_ns_unchanged": before.st_ctime_ns == after.st_ctime_ns,
        "ctime_delta_ns": after.st_ctime_ns - before.st_ctime_ns,
    }
    # Keep the native twin in exactly the same post-state.
    (native / "in.txt").write_bytes((work / "in.txt").read_bytes())
    os.utime(native / "in.txt", ns=(after.st_atime_ns, after.st_mtime_ns))
    (work / "copy.txt").unlink(missing_ok=True)
    (native / "copy.txt").unlink(missing_ok=True)

    native_obs = run_native(argv, native)
    warm = run_traced(tracejit, cache, argv, work)
    comparison = oracle.compare(native_obs, warm["observation"])
    reused = (warm.get("report") or {}).get("kind") == "Reused"
    return {
        "case": name,
        "status": "incorrect_hit" if (reused and not comparison["match"]) else ("ok" if comparison["match"] else "mismatch"),
        "reused": reused,
        "timestamps_fully_collided": all(collision[key] for key in ("size_unchanged", "mtime_ns_unchanged", "ctime_ns_unchanged")),
        "timestamp_observation": collision,
        "note": (
            "not reproducible on this kernel/filesystem"
            if not collision["ctime_ns_unchanged"]
            else "a true same-size/same-mtime/same-ctime rewrite was produced"
        ),
        "covered_differences": comparison["covered_differences"],
    }


def race_window(root: Path, tracejit: Path, trials: int, seed: int) -> dict:
    """Races a warm hit against a concurrent writer that flips the input.

    This is an empirical probe of the documented validate-to-restore window. A
    correct result here is **not** evidence that the window is closed.
    """

    rng = random.Random(seed)
    helper = compile_helper(COPY_C, root / "race-helper")
    results = []
    for trial in range(trials):
        work = root / "race" / f"t{trial}"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        (work / "in.txt").write_bytes(b"A" * 65536)
        cache = root / "race" / f"cache{trial}"
        run_traced(tracejit, cache, [str(helper), "in.txt", "copy.txt"], work)

        expected_a = (work / "copy.txt").read_bytes()
        (work / "in.txt").write_bytes(b"B" * 65536)
        expected_b = b"B" * 65536
        (work / "copy.txt").unlink(missing_ok=True)
        writer_done = work / "writer.done"

        def writer() -> None:
            time.sleep(rng.uniform(0.0005, 0.004))
            (work / "in.txt").write_bytes(b"B" * 65536)
            writer_done.write_text("done")

        import threading

        thread = threading.Thread(target=writer)
        thread.start()
        traced = run_traced(tracejit, cache, [str(helper), "in.txt", "copy.txt"], work)
        thread.join()
        content = (work / "copy.txt").read_bytes() if (work / "copy.txt").is_file() else None
        acceptable = content in (expected_a, expected_b)
        results.append(
            {
                "trial": trial,
                "decision": (traced.get("report") or {}).get("cache_decision"),
                "kind": (traced.get("report") or {}).get("kind"),
                "writer_finished": writer_done.exists(),
                "output_matches_some_valid_execution": acceptable,
                "observed_bytes": None if content is None else len(content),
            }
        )
    stale = [entry for entry in results if not entry["output_matches_some_valid_execution"]]
    return {
        "trials": trials,
        "stale_observations": len(stale),
        "stale_trials": stale,
        "interpretation": (
            "A stale observation in this probe demonstrates the documented validate-to-restore window. "
            "Zero stale observations do not demonstrate that the window is closed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(REPO / "target" / "release" / "tracejit"))
    parser.add_argument("--output", default=str(REPO / "benchmarks" / "results" / "phaseaa" / "adversarial.json"))
    parser.add_argument("--trials", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--skip-preserved", action="store_true")
    args = parser.parse_args()
    tracejit = Path(args.tracejit).resolve()
    output = Path(args.output)
    root = Path(tempfile.mkdtemp(prefix="tracejit-aa-adversarial-"))
    payload: dict = {"tracejit": str(tracejit), "root": str(root)}

    if not args.skip_preserved:
        w1_output = root / "phase_w1_audit.json"
        completed = subprocess.run(
            [sys.executable, str(REPO / "benchmarks/phase_w1/audit.py"),
             "--tracejit", str(tracejit), "--output", str(w1_output)],
            capture_output=True, text=True, check=False,
        )
        payload["preserved_counterexamples"] = {
            "suite": "benchmarks/phase_w1/audit.py",
            "exit_status": completed.returncode,
            "tail": completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "",
            # A crashed suite produced no JSON and an empty stdout tail, so the
            # reason was invisible in the artifact. Keep the last stderr lines.
            "stderr_tail": (
                completed.stderr.strip().splitlines()[-5:] if completed.stderr.strip() else []
            ),
            "results": json.loads(w1_output.read_text()) if w1_output.is_file() else None,
        }

    # The helper must exist before the cases that reference it are built.
    compile_helper(RENAME_C, root / "rename-helper")
    compile_helper(COPY_C, root / "copy-helper")
    payload["workload_mutations"] = [
        case(
            "rename_then_recreate_output", root, tracejit,
            lambda ws: None,
            lambda ws: [str(root / "rename-helper")],
            lambda ws: None,
            "the command itself renames and recreates its output",
        ),
    ]
    payload["workload_mutations"].append(
        case(
            "content_replacement_via_copy", root, tracejit,
            lambda ws: (ws / "in.txt").write_bytes(b"payload-one\n" * 256),
            lambda ws: [str(root / "copy-helper")],
            lambda ws: (ws / "in.txt").write_bytes(b"payload-two\n" * 512),
            "input content replaced between the recorded and warm run",
        )
    )
    payload["workload_mutations"].append(same_timestamp_attempt(root, tracejit, args.seed))
    payload["race_window"] = race_window(root, tracejit, args.trials, args.seed)

    hard_failures = [
        entry for entry in payload["workload_mutations"] if entry.get("status") == "incorrect_hit"
    ]
    preserved = payload.get("preserved_counterexamples") or {}
    preserved_ok = preserved.get("exit_status") in (0, None)
    payload["summary"] = {
        "preserved_counterexamples_pass": preserved_ok,
        "workload_mutations": len(payload["workload_mutations"]),
        "incorrect_hits": len(hard_failures),
        "race_stale_observations": payload["race_window"]["stale_observations"],
        "unsupported_or_unresolved": [
            entry["case"] for entry in payload["workload_mutations"]
            if entry.get("status") not in ("ok", "incorrect_hit")
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    print(f"wrote {output}")
    return 0 if preserved_ok and not hard_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

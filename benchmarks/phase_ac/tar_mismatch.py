#!/usr/bin/env python3
"""Phase AC: reproduce and root-cause the PR #44 ``tar-create`` cold mismatch.

The smoke job in ``.github/workflows/benchmark-v2.yml`` failed with
``cold_mismatch`` on ``tar-create``.  This script reproduces the exact harness
sequence for that workload and records *which* observation diverged, instead of
guessing:

    1. ``corpus.prepare`` into the native twin,
    2. ``corpus.prepare`` into the traced twin,
    3. ``tar -cf bundle.tar corpus.txt corpus.bin`` natively in the native twin,
    4. the same command cold under TraceJIT in the traced twin,
    5. ``oracle.compare`` over both observed states.

``--stagger`` inserts a delay between the two ``prepare`` calls.  A stagger that
crosses a whole-second boundary is the only difference between the two twins
that this experiment introduces, so it isolates wall-clock-derived fixture
metadata from TraceJIT behaviour.

Modes:

    --mode twins    both twins prepared by ``corpus.prepare`` (the shipped
                    sequence), with an optional stagger.  This is the defect.
    --mode clone    the native twin is prepared once and cloned with metadata
                    preserved, which is the fix under evaluation.

Both modes report, per trial, the archive digest and the tar header fields of
every member, so a divergence can be attributed to a field rather than to "the
bytes differ".
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
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "realworld_v2"))

import corpus  # noqa: E402
import oracle  # noqa: E402
import runner  # noqa: E402

WORKLOAD_ID = "tar-create"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tar_headers(archive: Path) -> list[dict]:
    """Parses the 512-byte ustar/GNU headers of an archive, without trusting tar."""

    raw = archive.read_bytes()
    members: list[dict] = []
    offset = 0
    while offset + 512 <= len(raw):
        block = raw[offset : offset + 512]
        if block == b"\x00" * 512:
            break
        name = block[0:100].split(b"\x00", 1)[0].decode("utf-8", "replace")
        if not name:
            break

        def octal(field: bytes) -> int:
            text = field.split(b"\x00", 1)[0].strip() or b"0"
            try:
                return int(text, 8)
            except ValueError:
                return -1

        size = octal(block[124:136])
        members.append(
            {
                "name": name,
                "mode": block[100:108].split(b"\x00", 1)[0].decode(),
                "uid": octal(block[108:116]),
                "gid": octal(block[116:124]),
                "size": size,
                "mtime": octal(block[136:148]),
                "typeflag": block[156:157].decode("utf-8", "replace"),
                "magic": block[257:265].split(b"\x00", 1)[0].decode("utf-8", "replace"),
                "uname": block[265:297].split(b"\x00", 1)[0].decode("utf-8", "replace"),
                "gname": block[297:329].split(b"\x00", 1)[0].decode("utf-8", "replace"),
                "block_sha256": hashlib.sha256(block).hexdigest(),
            }
        )
        offset += 512 + ((size + 511) // 512) * 512
    return members


def header_differences(left: list[dict], right: list[dict]) -> list[dict]:
    differences: list[dict] = []
    for index, (a, b) in enumerate(zip(left, right)):
        for key in a:
            if a[key] != b[key]:
                differences.append({"member": index, "field": key, "native": a[key], "traced": b[key]})
    if len(left) != len(right):
        differences.append({"member": None, "field": "member_count", "native": len(left), "traced": len(right)})
    return differences


def reconcile_mtimes(left: Path, right: Path) -> None:
    """Sets every path under ``right`` to the mtime/mode of its ``left`` twin."""

    for dirpath, dirnames, filenames in os.walk(left):
        for name in dirnames + filenames:
            source = Path(dirpath) / name
            target = right / source.relative_to(left)
            info = source.lstat()
            if target.is_symlink() or os.path.islink(target):
                continue
            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))


def prepare_pair(mode: str, root: Path, ctx: dict, workload: corpus.Workload, stagger: float) -> tuple[Path, Path]:
    native_ws = root / "native"
    traced_ws = root / "traced"
    if mode == "twins":
        corpus.prepare(native_ws, ctx, workload)
        if stagger:
            time.sleep(stagger)
        corpus.prepare(traced_ws, ctx, workload)
    elif mode == "clone":
        # The shipped fix: prepare once, clone with metadata preserved.
        runner.prepare_twins(native_ws, traced_ws, ctx, workload)
    elif mode == "reconcile":
        corpus.prepare(native_ws, ctx, workload)
        if stagger:
            time.sleep(stagger)
        corpus.prepare(traced_ws, ctx, workload)
        reconcile_mtimes(native_ws, traced_ws)
    else:  # pragma: no cover - argument validated by argparse
        raise SystemExit(f"unknown mode {mode}")
    return native_ws, traced_ws


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["twins", "clone", "reconcile"], default="twins")
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--stagger", choices=["none", "random"], default="random")
    parser.add_argument("--max-stagger", type=float, default=1.2)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--policies", default="native,compiler-runtime-v1")
    parser.add_argument("--tracejit-trials", type=int, default=0,
                        help="run TraceJIT cold on the first N trials (0 = all, -1 = none)")
    parser.add_argument("--scratch", type=Path, default=Path("/tmp/ac-tar-mismatch"))
    parser.add_argument("--vendor", type=Path, default=Path("/tmp/ac-vendor"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    policies = [item.strip() for item in args.policies.split(",") if item.strip()]
    args.scratch.mkdir(parents=True, exist_ok=True)
    ctx = corpus.materialize_shared(args.scratch / "shared", args.vendor)
    workload = corpus.by_id()[WORKLOAD_ID]
    argv_command = workload.command(args.scratch, ctx)
    rng = random.Random(20261124)
    base_env = dict(os.environ)

    rows: list[dict] = []
    for trial in range(args.trials):
        stagger = 0.0 if args.stagger == "none" else rng.uniform(0.0, args.max_stagger)
        row: dict = {"trial": trial, "mode": args.mode, "stagger_s": round(stagger, 3), "runs": []}

        for policy in policies:
            # One independent twin pair per (trial, policy): the native twin is
            # never reused after a run, so no stale archive can leak forward.
            root = args.scratch / f"{args.mode}-{trial:04d}-{policy}"
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True)
            native_ws, traced_ws = prepare_pair(args.mode, root, ctx, workload, stagger)

            pre_covered = oracle.compare_workspace_trees(
                oracle.observe_workspace(native_ws), oracle.observe_workspace(traced_ws)
            )
            input_mtimes = {
                name: [int((native_ws / name).stat().st_mtime), int((traced_ws / name).stat().st_mtime)]
                for name in ("corpus.txt", "corpus.bin")
            }
            equal = all(a == b for a, b in input_mtimes.values())
            row["prestate_covered_match"] = row.get("prestate_covered_match", True) and pre_covered["match"]
            row["input_mtime"] = input_mtimes
            row["input_mtime_equal"] = row.get("input_mtime_equal", True) and equal

            cache = root / f"cache-{policy}"
            env = runner.cache_env({**base_env, **workload.env}, cache)
            argv = workload.command(traced_ws, ctx)
            native = subprocess.run(argv_command, cwd=native_ws, env=env, capture_output=True, check=False)
            native_tree = oracle.observe_workspace(native_ws)
            native_obs = oracle.process_observation(native.returncode, native.stdout, native.stderr, native_tree)
            native_headers = tar_headers(native_ws / "bundle.tar")
            native_digest = sha256(native_ws / "bundle.tar")

            run = {"policy": policy, "native_exit": native.returncode,
                   "native_stdout": native.stdout.decode("utf-8", "replace"),
                   "native_stderr": native.stderr.decode("utf-8", "replace"),
                   "native_archive_sha256": native_digest, "native_headers": native_headers}
            if args.tracejit_trials != -1 and trial < (args.tracejit_trials or args.trials):
                _, decision, report, stdout, stderr = runner.run_traced(
                    args.tracejit, argv, traced_ws, env, policy
                )
                traced_tree = oracle.observe_workspace(traced_ws)
                traced_obs = oracle.process_observation(
                    int((report or {}).get("exit_code", -1)), stdout, stderr, traced_tree
                )
                compare = oracle.compare(native_obs, traced_obs)
                run.update(
                    tracejit_kind=(decision or {}).get("kind"),
                    tracejit_cold_match=compare["match"],
                    covered_differences=compare["covered_differences"],
                    out_of_contract_differences=compare["out_of_contract_differences"],
                    stdout_match=stdout == native.stdout,
                    stderr_match=stderr == native.stderr,
                )
                if (traced_ws / "bundle.tar").is_file():
                    run["traced_archive_sha256"] = sha256(traced_ws / "bundle.tar")
                    run["traced_headers"] = tar_headers(traced_ws / "bundle.tar")
                    run["header_differences"] = header_differences(
                        native_headers, run["traced_headers"]
                    )
            row["runs"].append(run)
            shutil.rmtree(root, ignore_errors=True)
        rows.append(row)

    def summarise(rows: list[dict]) -> dict:
        measured = [run for row in rows for run in row.get("runs", []) if "tracejit_cold_match" in run]
        mismatched = [run for run in measured if not run["tracejit_cold_match"]]
        fields: dict[str, int] = {}
        for run in mismatched:
            for difference in run["covered_differences"]:
                fields[difference["field"]] = fields.get(difference["field"], 0) + 1
        header_fields: dict[str, int] = {}
        for run in mismatched:
            for difference in run.get("header_differences", []):
                header_fields[difference["field"]] = header_fields.get(difference["field"], 0) + 1
        return {
            "trials": len(rows),
            "runs_compared": len(measured),
            "cold_mismatches": len(mismatched),
            "cold_mismatch_rate": (len(mismatched) / len(measured)) if measured else None,
            "covered_fields_in_mismatch": fields,
            "tar_header_fields_in_mismatch": header_fields,
            "input_mtime_unequal_trials": sum(1 for row in rows if not row["input_mtime_equal"]),
            "prestate_covered_mismatches": sum(1 for row in rows if not row["prestate_covered_match"]),
            "mismatch_when_mtimes_differ": sum(
                1 for row in rows if not row["input_mtime_equal"]
                and any(not run.get("tracejit_cold_match", True) for run in row.get("runs", []))
            ),
            "mismatch_when_mtimes_equal": sum(
                1 for row in rows if row["input_mtime_equal"]
                and any(not run.get("tracejit_cold_match", True) for run in row.get("runs", []))
            ),
        }

    payload = {
        "mode": args.mode,
        "workload": WORKLOAD_ID,
        "command": [Path(item).name if str(item).startswith(ctx["zlib"]) else str(item) for item in argv_command],
        "policies": policies,
        "summary": summarise(rows),
        "rows": rows,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
        print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

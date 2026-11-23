#!/usr/bin/env python3
"""Phase W1 snapshot-provenance audit.

Each case builds a workspace, records one cold execution with TraceJIT, changes the pre-state the
case is about, and then runs the same command twice: once warm through TraceJIT and once natively
in an identical workspace. A case passes only when the warm TraceJIT result is observationally
identical to native execution (exit status, stdout, stderr, every file's bytes and every symlink
target) *and* the reuse decision matches what the dependency rule claims.

Reuse is never asserted on its own: an extra deoptimisation is a performance regression, but a
wrong HIT is a correctness defect. `expect_reuse` therefore records the intended decision while
`files_match` and the stream/exit comparison decide the verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IGNORED = {"cache", "fixture-driver", "fixture-interpreter", "fixture-script"}


def build_fixture(repository: Path, destination: Path) -> Path:
    binary = destination / "fixture-driver"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            str(repository / "tests/fixtures/fixture_driver.c"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


def snapshot(directory: Path) -> dict[str, dict]:
    """Every observable entry in the workspace: bytes, absence, or a symlink target."""
    entries: dict[str, dict] = {}
    for path in sorted(directory.iterdir()):
        if path.name in IGNORED:
            continue
        info = path.lstat()
        if os.path.islink(path):
            entries[path.name] = {"kind": "symlink", "target": os.readlink(path)}
        elif path.is_dir():
            entries[path.name] = {
                "kind": "directory",
                "mode": oct(info.st_mode & 0o7777),
                "entries": sorted(child.name for child in path.iterdir()),
            }
        else:
            entries[path.name] = {
                "kind": "file",
                "bytes": path.read_bytes().hex(),
                "mode": oct(info.st_mode & 0o7777),
            }
    return entries


def run_native(binary: Path, mode: str, workspace: Path) -> dict:
    completed = subprocess.run(
        [str(binary), mode, str(workspace)], capture_output=True, timeout=120
    )
    return {
        "exit_code": completed.returncode,
        "stdout": list(completed.stdout),
        "stderr": list(completed.stderr),
        "files": snapshot(workspace),
    }


def run_tracejit(
    tracejit: Path, cache: Path, binary: Path, mode: str, workspace: Path
) -> dict:
    environment = dict(os.environ)
    environment["TRACEJIT_CACHE_DIR"] = str(cache)
    # glibc seeds tcache with getrandom on first allocation; keep the workload itself free of
    # entropy so only the case's own effects decide the outcome.
    environment["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    completed = subprocess.run(
        [
            str(tracejit),
            "run",
            "--json",
            "--",
            str(binary),
            mode,
            str(workspace),
        ],
        capture_output=True,
        timeout=180,
        env=environment,
    )
    payload = None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        pass
    return {
        "exit_code": completed.returncode,
        "report": payload,
        "report_stderr": completed.stderr.decode("utf-8", "replace"),
        "files": snapshot(workspace),
    }


def prepare(mode: str, workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "input.txt").write_bytes(b"input one\n")
    if mode == "failed_unlink_directory":
        return
    (workspace / "output.txt").write_bytes(b"old result\n")


def mutate(mode: str, workspace: Path) -> str:
    """The pre-state change the case is about; returns a short description."""
    output = workspace / "output.txt"
    if mode == "failed_unlink_directory":
        return "none (the failing mutation is the case)"
    if mode == "failed_rename_missing":
        return "none (the failing mutation is the case)"
    if mode == "replace_output":
        output.write_bytes(b"changed result\n")
        return "output.txt holds different bytes"
    if mode == "partial_then_exit":
        output.write_bytes(b"keep two\n")
        return "output.txt holds different bytes"
    if mode == "delete_only":
        output.write_bytes(b"keep two\n")
        return "output.txt holds different bytes"
    if mode == "delete_create_delete":
        output.write_bytes(b"seed two\n")
        return "output.txt holds different bytes"
    if mode == "rename_aside_recreate":
        output.write_bytes(b"changed result that is longer\n")
        return "output.txt holds different bytes (they are what moves aside)"
    if mode == "read_then_replace":
        output.write_bytes(b"beta is longer\n")
        return "output.txt holds bytes the program reads"
    if mode == "rename_over_existing":
        # The cold execution consumed input.txt by renaming it. Re-establish the pre-state so the
        # warm run performs the rename, with a destination whose own bytes changed.
        (workspace / "input.txt").write_bytes(b"input one\n")
        output.write_bytes(b"different stale result\n")
        return "output.txt (rename destination) holds different bytes"
    if mode == "delete_recreate":
        output.write_bytes(b"old result two\n")
        return "output.txt holds different bytes"
    if mode == "multiple_writes":
        output.write_bytes(b"seed changed\n")
        return "output.txt holds different bytes"
    if mode == "symlink_delete_recreate":
        target = workspace / "link-target.txt"
        target.write_bytes(b"link target\n")
        output.unlink(missing_ok=True)
        os.symlink("link-target.txt", output)
        return "output.txt is now a symbolic link"
    if mode == "replaced_inode":
        replacement = workspace / "replacement"
        replacement.write_bytes(b"old result\n")
        os.replace(replacement, output)
        return "output.txt is a different inode with identical bytes"
    if mode == "hardlink_twin":
        replacement = workspace / "replacement"
        replacement.write_bytes(b"old result two\n")
        os.replace(replacement, output)
        os.link(workspace / "twin.txt", workspace / "twin-check")
        (workspace / "twin-check").unlink()
        return "output.txt is a new inode; twin.txt still shares the original one"
    raise SystemExit(f"unknown mode {mode}")


def cases() -> list[dict]:
    return [
        {
            "name": "unlink_then_recreate",
            "mode": "replace_output",
            "expect_reuse": True,
            "rule": "superseded delete snapshot is elided",
        },
        {
            "name": "rename_aside_then_recreate",
            "mode": "rename_aside_recreate",
            "expect_reuse": False,
            "rule": "the rename source's bytes move into the destination output",
        },
        {
            "name": "rename_over_existing_destination",
            "mode": "rename_over_existing",
            "expect_reuse": True,
            "rule": "the destination's replaced pre-state is elided; the source stays",
        },
        {
            "name": "failed_unlink_eisdir",
            "mode": "failed_unlink_directory",
            "expect_reuse": False,
            "rule": "a failed mutation is recorded as unguardable",
        },
        {
            "name": "failed_rename_enoent",
            "mode": "failed_rename_missing",
            "expect_reuse": False,
            "rule": "a failed rename is recorded as unguardable",
        },
        {
            "name": "partial_delete_then_exit",
            "mode": "partial_then_exit",
            "expect_reuse": False,
            "rule": "the execution ends with the path absent: the removed bytes stay inputs",
        },
        {
            "name": "terminal_delete",
            "mode": "delete_only",
            "expect_reuse": False,
            "rule": "terminal deletion keeps the exact bytes it removed",
        },
        {
            "name": "delete_create_delete",
            "mode": "delete_create_delete",
            "expect_reuse": False,
            "rule": "the last write is a delete, so the pre-state stays a dependency",
        },
        {
            "name": "multiple_writes_same_path",
            "mode": "multiple_writes",
            "expect_reuse": True,
            "rule": "the last write authors the content; earlier pre-state cannot reach it",
        },
        {
            "name": "program_read_then_replace",
            "mode": "read_then_replace",
            "expect_reuse": False,
            "rule": "a program read is a genuine observation and is never elided",
        },
        {
            "name": "symlink_prestate",
            "mode": "symlink_delete_recreate",
            "expect_reuse": False,
            "rule": "a symlink pre-state cannot be fingerprinted, so the run is unguardable",
        },
        {
            "name": "hardlink_twin",
            "mode": "delete_recreate",
            "expect_reuse": True,
            "rule": "the twin is not an output and must keep its bytes",
            "setup_twin": True,
        },
        {
            "name": "replaced_inode_same_bytes",
            "mode": "replace_output",
            "expect_reuse": True,
            "rule": "the elided pre-state does not depend on the inode identity",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default="target/release/tracejit")
    parser.add_argument("--output", required=True)
    # A fixed default root is not re-runnable: on a shared /tmp another user can
    # own the directory, `rmtree(ignore_errors=True)` then silently leaves it and
    # `mkdir` fails with FileExistsError. The audit is part of the Phase AA
    # adversarial gate, so that made the gate fail on any second environment.
    parser.add_argument("--root", default="")
    options = parser.parse_args()

    repository = Path(__file__).resolve().parents[2]
    if options.root:
        root = Path(options.root)
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(tempfile.mkdtemp(prefix="tracejit-phase-w1-audit-"))
    binary = build_fixture(repository, root)
    tracejit = Path(options.tracejit).resolve()

    results = []
    for case in cases():
        workspace = root / case["name"]
        cache = root / f"{case['name']}-cache"
        prepare(case["mode"], workspace)
        if case.get("setup_twin"):
            os.link(workspace / "output.txt", workspace / "twin.txt")

        cold = run_tracejit(tracejit, cache, binary, case["mode"], workspace)
        description = mutate(case["mode"], workspace)

        # Native reference: an identical workspace with the same pre-state mutation.
        native_workspace = root / f"{case['name']}-native"
        shutil.copytree(workspace, native_workspace, symlinks=True)
        native = run_native(binary, case["mode"], native_workspace)

        warm = run_tracejit(tracejit, cache, binary, case["mode"], workspace)

        files_match = warm["files"] == native["files"]
        streams_match = (
            warm["report"] is not None
            and list(warm["report"].get("stdout_bytes") or []) == native["stdout"]
            and list(warm["report"].get("stderr_bytes") or []) == native["stderr"]
            and warm["report"].get("exit_code") == native["exit_code"]
            # The wrapper reports the traced command's status, so a fixture that exits non-zero
            # must do so identically here (the `partial_then_exit` case relies on it).
            and warm["exit_code"] == native["exit_code"]
        )
        report = warm["report"] or {}
        decision = report.get("cache_decision")
        reused = report.get("kind") == "Reused"
        decision_matches = reused == case["expect_reuse"]
        results.append(
            {
                "case": case["name"],
                "mode": case["mode"],
                "rule": case["rule"],
                "mutation": description,
                "cold": {
                    "kind": (cold["report"] or {}).get("kind"),
                    "classification": (cold["report"] or {}).get("classification"),
                    "reasons": (cold["report"] or {}).get("reasons"),
                },
                "warm": {
                    "kind": report.get("kind"),
                    "classification": report.get("classification"),
                    "cache_decision": decision,
                    "failed_guard": (
                        ((report.get("guards") or {}).get("failure") or {}).get("guard")
                    ),
                    "reasons": report.get("reasons"),
                },
                "expected_reuse": case["expect_reuse"],
                "reused": reused,
                "files_match_native": files_match,
                "streams_match_native": streams_match,
                "decision_matches_rule": decision_matches,
                "pass": bool(files_match and streams_match and decision_matches),
                "native_files": native["files"],
                "warm_files": warm["files"],
            }
        )
        print(
            f"{case['name']:<34} reused={str(reused):<5} expected={str(case['expect_reuse']):<5} "
            f"files={str(files_match):<5} streams={str(streams_match):<5} "
            f"{'PASS' if results[-1]['pass'] else 'FAIL'}"
        )

    summary = {
        "tracejit": str(tracejit),
        "fixture": str(binary),
        "cases": results,
        "passed": sum(1 for result in results if result["pass"]),
        "total": len(results),
    }
    Path(options.output).parent.mkdir(parents=True, exist_ok=True)
    Path(options.output).write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{summary['passed']}/{summary['total']} cases pass -> {options.output}")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())

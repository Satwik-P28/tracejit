#!/usr/bin/env python3
"""Write the release manifest: exact commit, toolchain, lockfile and artifact hashes."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(*command: str) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return (completed.stdout + completed.stderr).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifacts(stage: Path) -> list[dict[str, object]]:
    entries = []
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            entries.append(
                {
                    "path": path.relative_to(stage).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--dirty", required=True, choices=["true", "false"])
    parser.add_argument("--target", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    stage = Path(args.stage).resolve()
    binary = Path(args.binary).resolve()
    lockfile = root / "Cargo.lock"
    toolchain_file = root / "rust-toolchain.toml"

    cpu = ""
    for line in run("lscpu").splitlines():
        if line.startswith("Model name:"):
            cpu = line.split(":", 1)[1].strip()
            break

    locked = [
        line.strip()
        for line in lockfile.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("name =")
    ]

    manifest = {
        "schema_version": 1,
        "release": {
            "version": args.version,
            "tag": f"v{args.version}",
            "commit": args.commit,
            "commit_date": run("git", "log", "-1", "--format=%cI", args.commit),
            "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
            "working_tree_dirty": args.dirty == "true",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "toolchain": {
            "rustc": run("rustc", "--version"),
            "cargo": run("cargo", "--version"),
            "rust-toolchain.toml": toolchain_file.read_text(encoding="utf-8").strip(),
            "rust-toolchain.toml_sha256": sha256(toolchain_file),
        },
        "dependencies": {
            "lockfile": "Cargo.lock",
            "lockfile_sha256": sha256(lockfile),
            "locked_packages": len(locked),
        },
        "build": {
            "target": args.target,
            "profile": "release",
            "command": "cargo build --workspace --release",
            "binary_sha256": sha256(binary),
            "binary_bytes": binary.stat().st_size,
        },
        "artifacts": artifacts(stage),
        "environment": {
            "os": run("cat", "/etc/os-release"),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu": cpu or "unavailable",
            "cpus": os.cpu_count(),
        },
        "reproducibility": {
            "byte_for_byte_claimed": False,
            "note": (
                "Archive members are ordered and timestamped from the commit, and gzip "
                "stores no name or timestamp. Byte-for-byte rebuild equality has not been "
                "independently demonstrated, so it is not claimed."
            ),
        },
    }
    Path(args.output).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

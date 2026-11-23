#!/usr/bin/env python3
"""Independent observational oracle for the Phase AA real-world corpus.

This module imports nothing from TraceJIT. It observes a workspace with the
operating system only, and compares a traced execution against a native
execution performed in a byte-identical twin directory.

Two classes of observation are kept apart on purpose:

``covered``
    Observations TraceJIT's declared contract claims to reproduce: exit status,
    stdout, stderr, the set of paths, each path's type (file, directory,
    symlink), regular-file contents, permission bits, symlink targets and
    hard-link grouping.  A mismatch here on a ``Reused`` decision is an
    **incorrect hit**.

``advisory``
    Observations the contract does not claim: inode numbers, timestamps,
    ownership, extended attributes, device numbers of regular files.  They are
    recorded so a reader can see them, and a mismatch is reported as an
    ``out_of_contract`` difference, never folded into a pass or a failure.

Usage (programmatic)::

    obs = observe_workspace(root)
    diff = compare(native_obs, traced_obs)

It can also be run directly to fingerprint a directory, which is useful when
checking a claim by hand:

    python3 benchmarks/realworld_v2/oracle.py <directory>
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Iterable


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def observe_workspace(root: Path, exclude: Iterable[str] = ()) -> dict[str, Any]:
    """Fingerprints every entry under ``root`` without following symlinks.

    ``exclude`` is a set of workspace-relative paths (files or directory
    prefixes) that belong to the harness rather than to the workload, for
    example a cache directory placed inside the workspace.
    """

    root = Path(root)
    skip = tuple(str(item).strip("/") for item in exclude if str(item).strip("/"))
    entries: dict[str, dict[str, Any]] = {}
    inode_groups: dict[str, list[str]] = {}

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        for name in list(dirnames):
            relative = (current / name).relative_to(root).as_posix()
            if relative in skip or any(relative.startswith(prefix + "/") for prefix in skip):
                dirnames.remove(name)

        for name in dirnames + filenames:
            path = current / name
            relative = path.relative_to(root).as_posix()
            if relative in skip:
                continue
            info = path.lstat()
            mode = oct(stat.S_IMODE(info.st_mode))
            if stat.S_ISLNK(info.st_mode):
                entries[relative] = {
                    "kind": "symlink",
                    "target": os.readlink(path),
                    "link_count": info.st_nlink,
                    "advisory": {"inode": info.st_ino, "mtime_ns": info.st_mtime_ns},
                }
            elif stat.S_ISDIR(info.st_mode):
                entries[relative] = {
                    "kind": "directory",
                    "mode": mode,
                    "advisory": {"inode": info.st_ino, "mtime_ns": info.st_mtime_ns},
                }
            elif stat.S_ISREG(info.st_mode):
                entries[relative] = {
                    "kind": "file",
                    "mode": mode,
                    "size": info.st_size,
                    "sha256": _sha256_file(path),
                    "link_count": info.st_nlink,
                    "advisory": {
                        "inode": info.st_ino,
                        "mtime_ns": info.st_mtime_ns,
                        "atime_ns": info.st_atime_ns,
                        "ctime_ns": info.st_ctime_ns,
                        "uid": info.st_uid,
                        "gid": info.st_gid,
                    },
                }
                if info.st_nlink > 1:
                    inode_groups.setdefault(f"{info.st_dev}:{info.st_ino}", []).append(relative)
            else:
                entries[relative] = {
                    "kind": "other",
                    "mode": mode,
                    "advisory": {"inode": info.st_ino},
                }

    # Hard links are compared as *groups of paths*, never by inode number: two
    # twin directories legitimately use different inodes, and keying the group by
    # inode would report a false difference for every hard-link workload.
    hardlinks = sorted(
        sorted(paths) for paths in inode_groups.values() if len(paths) > 1
    )
    return {
        "paths": sorted(entries),
        "entries": entries,
        "hardlink_groups": hardlinks,
        "tree_digest": _digest(entries, hardlinks),
    }


def _digest(entries: dict[str, dict[str, Any]], hardlinks: list[list[str]]) -> str:
    canonical = {
        "entries": {
            path: {key: value for key, value in entry.items() if key != "advisory"}
            for path, entry in entries.items()
        },
        "hardlink_groups": hardlinks,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def process_observation(
    exit_status: int, stdout: bytes, stderr: bytes, workspace: dict[str, Any]
) -> dict[str, Any]:
    return {
        "exit_status": exit_status,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stdout_bytes": len(stdout),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stderr_bytes": len(stderr),
        "workspace": workspace,
    }


def compare(native: dict[str, Any], traced: dict[str, Any]) -> dict[str, Any]:
    """Compares two process observations and separates covered from advisory."""

    differences: list[dict[str, Any]] = []
    for field in ("exit_status", "stdout_sha256", "stderr_sha256", "stdout_bytes", "stderr_bytes"):
        if native[field] != traced[field]:
            differences.append({"field": field, "native": native[field], "traced": traced[field]})

    native_tree = native["workspace"]
    traced_tree = traced["workspace"]

    native_paths = set(native_tree["paths"])
    traced_paths = set(traced_tree["paths"])
    for path in sorted(native_paths - traced_paths):
        differences.append({"field": "missing_path", "path": path})
    for path in sorted(traced_paths - native_paths):
        differences.append({"field": "unexpected_path", "path": path})

    for path in sorted(native_paths & traced_paths):
        left = {k: v for k, v in native_tree["entries"][path].items() if k != "advisory"}
        right = {k: v for k, v in traced_tree["entries"][path].items() if k != "advisory"}
        if left != right:
            differences.append(
                {"field": "entry", "path": path, "native": left, "traced": right}
            )

    if native_tree["hardlink_groups"] != traced_tree["hardlink_groups"]:
        differences.append(
            {
                "field": "hardlink_groups",
                "native": native_tree["hardlink_groups"],
                "traced": traced_tree["hardlink_groups"],
            }
        )

    advisory: list[dict[str, Any]] = []
    for path in sorted(native_paths & traced_paths):
        left = native_tree["entries"][path].get("advisory", {})
        right = traced_tree["entries"][path].get("advisory", {})
        for key in sorted(set(left) | set(right)):
            # inode numbers legitimately differ between two directories; they are
            # recorded for completeness but never interesting on their own.
            if key == "inode":
                continue
            if left.get(key) != right.get(key):
                advisory.append({"path": path, "field": key})

    return {
        "match": not differences,
        "covered_differences": differences,
        "out_of_contract_differences": advisory,
        "tree_digest_native": native_tree["tree_digest"],
        "tree_digest_traced": traced_tree["tree_digest"],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    observation = observe_workspace(Path(argv[1]))
    print(json.dumps(observation, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

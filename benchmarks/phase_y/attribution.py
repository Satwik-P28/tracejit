#!/usr/bin/env python3
"""Phase Y: which files pay for content validation, and how much of it is repeated.

The Phase X1 profile says a compiler warm hit reads 107,160,458 bytes through 57 content guards for
43.4 MB of distinct content. This harness replaces the aggregate with the per-file ledger the
question actually needs:

  * every content guard in one recorded execution, in validation order;
  * the path, size and inode each guard names;
  * how many guards name the same path, and how many name the same inode;
  * the bytes each file contributes, and therefore the share of the measured content time.

Byte counts come from the record plus `stat`, and the cost column is bytes times the BLAKE3
throughput measured by TraceJIT's own guard profiler (bytes hashed / content nanoseconds), so it is
a linear model over a measured rate rather than a second stopwatch. The report states the rate it
used.

Usage:
  python3 benchmarks/phase_y/attribution.py \
      --binary target/release/tracejit \
      --output benchmarks/results/phase_y/attribution.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "benchmarks" / "phase_x"))

from ab import UNITS, compile_once, write_sources  # noqa: E402

# Every guard whose validation reads a file and compares a digest. `ControlledRuntime` and
# `ControlledEntropy` hash the runtime binary and the issuing library, which is why the compiler
# workload hashes `cc1` and `gcc-13` more than once per pass.
CONTENT_KINDS = {
    "FileHash": "path",
    "ExecutableHash": "path",
    "VerityContentIdentity": "path",
    "ControlledRuntime": "executable",
    "ControlledEntropy": "library",
}


def explain(binary: Path, cache: Path) -> dict:
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TRACEJIT_CACHE_DIR": str(cache),
    }
    completed = subprocess.run(
        [str(binary), "explain", "--json"],
        env=environment,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "explain failed: " + completed.stderr.decode(errors="replace")[:800]
        )
    return json.loads(completed.stdout)


def content_guards(record: dict) -> list[dict]:
    found = []
    for guard in record.get("guards", []):
        if not isinstance(guard, dict):
            continue
        for kind, path_field in CONTENT_KINDS.items():
            if kind in guard:
                body = guard[kind]
                found.append(
                    {
                        "kind": kind,
                        "path": body.get(path_field),
                        "expected": body.get("expected") or body.get("expected_hash"),
                        "verity": body.get("verity"),
                    }
                )
                break
    return found


def stat_path(path: str) -> dict:
    try:
        info = os.stat(path)
    except OSError as error:
        return {"state": "missing", "detail": str(error)}
    return {
        "state": "ok",
        "size": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "links": info.st_nlink,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "mode": oct(info.st_mode),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--functions", type=int, default=220)
    parser.add_argument("--root", default="/tmp/tracejit-phase-y-attribution")
    parser.add_argument(
        "--hash-rate-bytes-per-second",
        type=float,
        default=2_217_000_000.0,
        help="BLAKE3 throughput measured by the guard profiler on this host",
    )
    parser.add_argument("--hash-rate-source", default="phase_x1 guard profile")
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    root = Path(args.root)
    shutil.rmtree(root, ignore_errors=True)
    workspace = root / "work"
    cache = root / "cache"
    write_sources(workspace, args.functions)
    for unit in range(UNITS):
        compile_once(binary, workspace, cache, unit)
    for _ in range(2):
        for unit in range(UNITS):
            compile_once(binary, workspace, cache, unit)

    record = explain(binary, cache)
    guards = content_guards(record)

    rows = []
    for guard in guards:
        info = stat_path(guard["path"])
        rows.append(
            {
                "path": guard["path"],
                "kind": guard["kind"],
                "expected": guard["expected"],
                "verity_pin": guard["verity"],
                **info,
            }
        )

    total_bytes = sum(row.get("size", 0) for row in rows)
    by_path: dict[str, list[dict]] = {}
    for row in rows:
        by_path.setdefault(row["path"], []).append(row)
    by_inode: dict[tuple, list[dict]] = {}
    for row in rows:
        if row.get("state") == "ok":
            by_inode.setdefault((row["device"], row["inode"]), []).append(row)

    def distinct_bytes(groups: dict) -> int:
        return sum(group[0].get("size", 0) for group in groups.values())

    files = []
    for path, group in by_path.items():
        size = group[0].get("size", 0)
        files.append(
            {
                "path": path,
                "observations": len(group),
                "kinds": [row["kind"] for row in group],
                "bytes_each": size,
                "bytes_total": size * len(group),
                "share_of_all_content_bytes": (size * len(group) / total_bytes)
                if total_bytes
                else 0.0,
                "derived_cost_ms": (size * len(group) / args.hash_rate_bytes_per_second) * 1e3,
                "device": group[0].get("device"),
                "inode": group[0].get("inode"),
                "links": group[0].get("links"),
            }
        )
    files.sort(key=lambda entry: entry["bytes_total"], reverse=True)

    repeated_paths = [
        {
            "path": entry["path"],
            "observations": entry["observations"],
            "kinds": entry["kinds"],
            "wasted_bytes_if_shared": entry["bytes_each"] * (entry["observations"] - 1),
        }
        for entry in files
        if entry["observations"] > 1
    ]
    repeated_inodes = [
        {
            "device_inode": list(key),
            "observations": len(group),
            "paths": sorted({row["path"] for row in group}),
            "bytes_each": group[0].get("size", 0),
            "wasted_bytes_if_shared": group[0].get("size", 0) * (len(group) - 1),
        }
        for key, group in by_inode.items()
        if len(group) > 1
    ]

    report = {
        "harness": "phase_y/attribution.py",
        "binary": str(binary),
        "units": UNITS,
        "functions_per_unit": args.functions,
        "execution_id": record.get("id"),
        "classification": record.get("classification"),
        "guard_count": len(record.get("guards", [])),
        "content_guard_count": len(rows),
        "content_bytes_total": total_bytes,
        "content_bytes_distinct_by_path": distinct_bytes(by_path),
        "content_bytes_distinct_by_inode": distinct_bytes(by_inode),
        "redundancy_factor_by_path": (total_bytes / distinct_bytes(by_path))
        if distinct_bytes(by_path)
        else 0.0,
        "redundancy_factor_by_inode": (total_bytes / distinct_bytes(by_inode))
        if distinct_bytes(by_inode)
        else 0.0,
        "derived_content_cost_ms": (total_bytes / args.hash_rate_bytes_per_second) * 1e3,
        "hash_rate_bytes_per_second": args.hash_rate_bytes_per_second,
        "hash_rate_source": args.hash_rate_source,
        "files": files,
        "repeated_paths": repeated_paths,
        "repeated_inodes": repeated_inodes,
        "verity_pins_present": sum(1 for row in rows if row["verity_pin"]),
        "guards": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "content_guard_count",
                    "content_bytes_total",
                    "content_bytes_distinct_by_path",
                    "content_bytes_distinct_by_inode",
                    "redundancy_factor_by_path",
                    "verity_pins_present",
                    "derived_content_cost_ms",
                )
            },
            indent=2,
        )
    )
    print("top files:")
    for entry in files[:8]:
        print(
            f"  {entry['observations']}x {entry['bytes_each']:>10,} B "
            f"{entry['bytes_total']:>11,} B  {entry['path']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

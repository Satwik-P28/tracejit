#!/usr/bin/env python3
"""Phase X dependency-redundancy analysis.

Reads a stored record (`tracejit explain --json`) and reports what the guard list actually
requires: how many observations, how many distinct paths, how many bytes a strict pass hashes,
which guards are exactly duplicated, and which metadata observations share a path with a content
guard.

The analysis is descriptive. It never claims a duplicate is removable; the guard list is ordered
and a duplicate is only equivalent when the path, the expected value and the position relative to
the first write are all the same, which this script checks explicitly.

Usage:
  python3 benchmarks/phase_x/redundancy.py --record /tmp/tracejit-phase-x-profile/record.json
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

CONTENT = ("FileHash", "ExecutableHash")
METADATA = ("FileMetadata", "SymlinkMetadata")


def guard_kind(guard) -> str:
    # Unit variants (NoUnexpectedEffects) serialize as a bare string.
    return guard if isinstance(guard, str) else next(iter(guard))


def guard_body(guard) -> dict:
    return {} if isinstance(guard, str) else next(iter(guard.values()))


def canonical(guard: dict) -> str:
    return json.dumps(guard, sort_keys=True)


def analyse(record: dict) -> dict:
    guards = record["guards"]
    kinds = collections.Counter(guard_kind(guard) for guard in guards)

    paths = collections.defaultdict(set)
    for guard in guards:
        body = guard_body(guard)
        path = body.get("path") or body.get("library") or body.get("executable")
        if path:
            paths[guard_kind(guard)].add(path)

    # Content guards: which paths, how many bytes does a strict pass read.
    content_paths: dict[str, set[str]] = collections.defaultdict(set)
    bytes_by_path: dict[str, int] = {}
    for guard in guards:
        kind = guard_kind(guard)
        if kind not in CONTENT:
            continue
        body = guard_body(guard)
        content_paths[kind].add(body["path"])
    # Size comes from the paired metadata guard (the fingerprint the record expected).
    for guard in guards:
        if guard_kind(guard) != "FileMetadata":
            continue
        body = guard_body(guard)
        if body["expected"]["inode"] == 0 and body["expected"]["mode"] == 0:
            continue
        bytes_by_path[body["path"]] = max(
            bytes_by_path.get(body["path"], 0), int(body["expected"]["size"])
        )
    content_guard_bytes = sum(bytes_by_path.get(path, 0) for path in content_paths["FileHash"])
    executable_guard_bytes = sum(
        bytes_by_path.get(path, 0) for path in content_paths["ExecutableHash"]
    )

    # Exact duplicates: identical guard JSON repeated in the list.
    seen = collections.Counter(canonical(guard) for guard in guards)
    duplicates = {
        canonical(guard)[:160]: count for guard, count in seen.items() if count > 1
    }

    # Metadata guards whose path also carries a content guard, and whether the expected
    # fingerprint is identical (that is the only case where the two requirements coincide).
    metadata_by_path: dict[str, list[dict]] = collections.defaultdict(list)
    for index, guard in enumerate(guards):
        if guard_kind(guard) in METADATA:
            body = guard_body(guard)
            metadata_by_path[body["path"]].append(
                {"index": index, "expected": body["expected"], "kind": guard_kind(guard)}
            )
    content_path_set = set().union(*content_paths.values()) if content_paths else set()
    shared_metadata = {}
    for path in content_path_set:
        entries = metadata_by_path.get(path, [])
        if entries:
            fingerprints = {json.dumps(entry["expected"], sort_keys=True) for entry in entries}
            shared_metadata[path] = {
                "metadata_guards": len(entries),
                "distinct_expected_fingerprints": len(fingerprints),
                "kinds": sorted({entry["kind"] for entry in entries}),
            }

    # Adjacent metadata+content pairs, which the validator already collapses onto one open.
    adjacent_pairs = 0
    pair_positions = []
    for index, guard in enumerate(guards[:-1]):
        if guard_kind(guard) not in METADATA:
            continue
        following = guards[index + 1]
        if guard_kind(following) in CONTENT and (
            guard_body(following)["path"] == guard_body(guard)["path"]
        ):
            adjacent_pairs += 1
            pair_positions.append(index)

    sizes = sorted(bytes_by_path.values(), reverse=True)
    return {
        "guard_count": len(guards),
        "guards_by_kind": dict(kinds.most_common()),
        "distinct_paths_by_kind": {
            kind: len(values) for kind, values in sorted(paths.items())
        },
        "content_guards": {
            "FileHash": len(content_paths["FileHash"]),
            "ExecutableHash": len(content_paths["ExecutableHash"]),
            "bytes_hashed_file_hash": content_guard_bytes,
            "bytes_hashed_executable_hash": executable_guard_bytes,
            "bytes_hashed_total": content_guard_bytes + executable_guard_bytes,
        },
        "exactly_duplicated_guards": duplicates,
        "duplicate_guard_count": sum(count - 1 for count in seen.values() if count > 1),
        "adjacent_metadata_content_pairs": adjacent_pairs,
        "shared_metadata_and_content_paths": len(shared_metadata),
        "shared_metadata_detail": dict(
            sorted(shared_metadata.items(), key=lambda item: item[1]["metadata_guards"], reverse=True)[:20]
        ),
        "largest_paths_by_size": [
            {"path": path, "size": size}
            for path, size in sorted(bytes_by_path.items(), key=lambda item: -item[1])[:10]
        ],
        "total_distinct_bytes_referenced": sum(sizes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    record = json.loads(Path(args.record).read_text())
    result = analyse(record)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

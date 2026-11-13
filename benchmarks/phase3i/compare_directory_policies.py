#!/usr/bin/env python3
"""Compare byte-exact and typed directory-entry policies on the raw probe.

This is a benchmark-side prototype, not a production guard. It reads the
syscall-level `getdents64` probe with two different fill bytes and answers two
questions:

* byte-exact: are the returned buffers identical?
* typed: are d_ino, d_off, d_reclen, d_type, the name, and the call boundaries
  identical when alignment padding is excluded?

The CPython/glibc reader audit is what would make the typed projection sound
for one exact reader. A different program can read padding, so the typed result
is not a native-equivalence claim and is not wired into Guard::DirectoryEnumerated.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "benchmarks/results/phase3i/getdents-probe.txt"
OUTPUT = ROOT / "benchmarks/results/phase3i/policy-comparison.json"


def parse(path: Path) -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("[fill "):
            current = line.split()[1].rstrip("]")
            runs[current] = []
        elif line.startswith("record ") and current is not None:
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            runs[current].append(
                {
                    "ino": int(fields["ino"]),
                    "off": int(fields["off"]),
                    "reclen": int(fields["reclen"]),
                    "type": int(fields["type"]),
                    "name": fields["name"],
                    "padding": fields["padding"],
                }
            )
    if set(runs) != {"aa", "55"}:
        raise SystemExit(f"expected aa and 55 probe runs, got {sorted(runs)}")
    return runs


def semantic(records: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in record.items() if key != "padding"}
        for record in records
    ]


def main() -> int:
    runs = parse(PROBE)
    native_equal = runs["aa"] == runs["55"]
    typed_equal = semantic(runs["aa"]) == semantic(runs["55"])
    changed = [
        index
        for index, (left, right) in enumerate(zip(runs["aa"], runs["55"]))
        if left != right
    ]
    result = {
        "phase": "3I",
        "prototype": "benchmark-side typed directory projection",
        "native_byte_exact_equal": native_equal,
        "typed_fields_equal": typed_equal,
        "records": len(runs["aa"]),
        "changed_record_indices": changed,
        "padding_bytes_changed": sum(
            len(bytes.fromhex(runs["aa"][index]["padding"]))
            for index in changed
        ),
        "typed_fields": ["d_ino", "d_off", "d_reclen", "d_type", "d_name"],
        "note": (
            "The typed projection is sound only for the audited CPython/glibc "
            "reader. Native byte-exact guarding remains the default."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

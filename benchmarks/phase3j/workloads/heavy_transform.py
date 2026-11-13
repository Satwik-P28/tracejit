#!/usr/bin/env python3
"""CPU-heavy deterministic CSV transformation for Phase 3J.

usage: heavy_transform.py <transactions.csv> <summary.json>

The workload deliberately does enough parsing, grouping and hashing to make a
reuse hit meaningful. It does not read clocks, process identity, entropy, the
network or the environment, and it writes only the requested output.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    source, destination = (Path(argument) for argument in sys.argv[1:3])
    buckets: dict[str, list[int]] = {}
    digest = 0xCBF29CE484222325
    rows = 0
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or row[0] == "transaction_id":
                continue
            rows += 1
            account = row[1]
            amount = int(row[2])
            score = int(row[3])
            slot = buckets.setdefault(account, [0, 0, 0, 0])
            slot[0] += amount
            slot[1] += 1
            slot[2] = max(slot[2], score)
            slot[3] ^= amount * 2654435761 & 0xFFFFFFFF
            for value in (row[0], account, row[2], row[3]):
                for byte in value.encode():
                    digest ^= byte
                    digest = digest * 1099511628211 & 0xFFFFFFFFFFFFFFFF
    report = {
        "rows": rows,
        "accounts": {
            account: {
                "total": values[0],
                "count": values[1],
                "maximum_score": values[2],
                "xor": values[3],
            }
            for account, values in sorted(buckets.items())
        },
        "digest": f"{digest:016x}",
    }
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

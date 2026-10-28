#!/usr/bin/env python3
"""Deterministic CSV to JSON aggregation used by the real-world census.

usage: etl.py <sales.csv> <customers.csv> <report.json>

Written for the census so the Python workload is a real data-processing command
with file inputs and a file output, not a synthetic loop. It uses only the
standard library.
"""

import csv
import json
import sys
from pathlib import Path


def load_customers(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["region"] for row in csv.DictReader(handle)}


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    sales, customers_path, output_path = (Path(argument) for argument in sys.argv[1:4])
    customers = load_customers(customers_path)

    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    digest = 0
    with sales.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            region = customers[row["customer_id"]]
            amount = int(row["amount_cents"])
            totals[region] = totals.get(region, 0) + amount
            counts[region] = counts.get(region, 0) + 1
            for byte in f"{row['sale_id']}:{amount}".encode():
                digest = (digest * 1315423911 + byte) & 0xFFFFFFFFFFFFFFFF

    report = {
        "rows": sum(counts.values()),
        "totals_cents": dict(sorted(totals.items())),
        "counts": dict(sorted(counts.items())),
        "work_digest": f"{digest:016x}",
    }
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

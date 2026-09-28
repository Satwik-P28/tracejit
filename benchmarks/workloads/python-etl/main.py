#!/usr/bin/env python3
"""Deterministic local ETL workload used by the TraceJIT benchmark harness."""

import csv
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).parent
REGION = os.environ.get("TRACEJIT_REPORT_REGION", "all")


def load_customers() -> dict[str, str]:
    with (ROOT / "inputs" / "customers.csv").open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["region"] for row in csv.DictReader(handle)}


def build_report() -> dict[str, object]:
    customers = load_customers()
    totals: dict[str, int] = {}
    digest = hashlib.blake2b(digest_size=32)
    with (ROOT / "inputs" / "sales.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            region = customers[row["customer_id"]]
            if REGION != "all" and region != REGION:
                continue
            value = int(row["amount_cents"])
            totals[region] = totals.get(region, 0) + value
            for iteration in range(2_000):
                digest.update(f"{row['sale_id']}:{value}:{iteration}".encode())
    return {
        "cwd": str(Path.cwd()),
        "region": REGION,
        "totals_cents": dict(sorted(totals.items())),
        "work_digest": digest.hexdigest(),
    }


def main() -> None:
    output = ROOT / "output" / "report.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(build_report(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Summarize `benchmarks/results/phaseab/build_integrity.json` into the report's tables.

Every number printed here is read from the JSON the harness wrote; nothing is
reconstructed. The archive (`liblua.a`) is compared by *member content* rather
than by file bytes, because GNU `ar` stores members in the order it is given and
the direct arm compiles in sorted order while the Makefile uses its own order.
An archive whose members are byte-identical is reported as equal.

Usage::

    python3 benchmarks/phase_ab/summarize_build.py benchmarks/results/phaseab/build_integrity.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def archive_members(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    listing = subprocess.run(["ar", "t", str(path)], capture_output=True, text=True).stdout
    members = {}
    for name in listing.split():
        content = subprocess.run(["ar", "p", str(path), name], capture_output=True).stdout
        members[name] = hashlib.sha256(content).hexdigest()
    return members


def main(argv: list[str]) -> int:
    payload = json.loads(Path(argv[1]).read_text())
    scratch = Path(argv[2] if len(argv) > 2 else payload.get("scratch", ""))
    reference_archive = archive_members(scratch / "reference" / "src/liblua.a")
    print(f"project {payload['project']}  TUs {payload['translation_units']}  "
          f"reference build {payload['reference_build_ms']} ms")
    print(f"tracejit {payload['tracejit_sha256'][:16]}  ccache {payload['ccache_version']}")
    print()
    header = f"{'arm':10} {'scenario':34} {'label':24} {'ms':>9} {'comp':>5} {'hit':>4} {'miss':>5} {'ref':>4} {'bad':>4}"
    print(header)
    for row in payload["rows"]:
        for build in row["builds"]:
            bad = [name for name in build["mismatched_artifacts"] if name != "liblua.a"]
            archive = scratch / f"ws-{row['arm']}-{row['scenario']}" / "src/liblua.a"
            if archive.exists() and reference_archive:
                members = archive_members(archive)
                common = set(members) & set(reference_archive)
                if {name: members[name] for name in common} != {
                        name: reference_archive[name] for name in common}:
                    bad.append("liblua.a(members)")
                extra = sorted(set(members) - set(reference_archive))
                if extra:
                    bad.append(f"liblua.a(extra:{','.join(extra)})")
            decisions = build.get("decisions", {})
            print(f"{row['arm']:10} {row['scenario']:34} {build['label']:24} "
                  f"{build['wall_ms']:9.1f} {build.get('compiles_observed', 0):5} "
                  f"{decisions.get('hit', 0):4} {decisions.get('miss', 0):5} "
                  f"{decisions.get('nondeterministic', 0):4} {len(bad):4}"
                  + (f"  {bad}" if bad else ""))
        if "direct_recompile" in row:
            direct = row["direct_recompile"]
            print(f"{row['arm']:10} {row['scenario']:34} {'direct_recompile':24} "
                  f"{direct['wall_ms']:9.1f} {1:5} "
                  f"{direct['decisions'].get('hit', 0):4} {direct['decisions'].get('miss', 0):5} "
                  f"{direct['decisions'].get('nondeterministic', 0):4} "
                  f"{0 if direct['restored'] else 1:4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

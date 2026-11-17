#!/usr/bin/env python3
"""Write a minimal CycloneDX 1.5 software bill of materials from Cargo.lock.

This is a dependency inventory, not a vulnerability assessment. It lists the
exact locked crate versions so a consumer can rebuild or scan the same set.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    lock = tomllib.loads((root / "Cargo.lock").read_text(encoding="utf-8"))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()

    components = []
    for package in lock.get("package", []):
        name = package["name"]
        package_version = package["version"]
        component = {
            "type": "library",
            "name": name,
            "version": package_version,
            "purl": f"pkg:cargo/{name}@{package_version}",
        }
        source = package.get("source")
        if source:
            component["externalReferences"] = [{"type": "distribution", "url": source}]
        else:
            component["properties"] = [
                {"name": "tracejit:local_package", "value": "true"}
            ]
        components.append(component)

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "tracejit",
                "version": version,
                "licenses": [{"license": {"id": "Apache-2.0 OR MIT"}}],
            },
            "tools": [{"name": "scripts/release_sbom.py"}],
        },
        "components": sorted(components, key=lambda item: (item["name"], item["version"])),
    }
    Path(args.output).write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output} ({len(components)} components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

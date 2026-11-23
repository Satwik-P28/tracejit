#!/usr/bin/env python3
"""Downloads and verifies the pinned upstream inputs for the Phase AA corpus.

Only one archive is needed: zlib 1.3.1, whose SHA-256 is pinned in
``corpus.py``. Everything else is generated deterministically, so this script is
allowed to fail on a machine with no network as long as zlib workloads are
excluded (the runner reports them as ``tool_unavailable``-adjacent
``source_unavailable`` rather than silently skipping them).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import ZLIB_SHA256, ZLIB_URL  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", default="/tmp/tracejit-realworld-v2/vendor")
    parser.add_argument("--offline", action="store_true", help="verify an existing archive only")
    args = parser.parse_args()

    vendor = Path(args.vendor)
    vendor.mkdir(parents=True, exist_ok=True)
    archive = vendor / "zlib-1.3.1.tar.gz"

    if not archive.is_file():
        if args.offline:
            print(f"missing {archive} and --offline was given", file=sys.stderr)
            return 1
        print(f"fetching {ZLIB_URL}")
        urllib.request.urlretrieve(ZLIB_URL, archive)  # noqa: S310 - pinned https URL

    digest = sha256(archive)
    if digest != ZLIB_SHA256:
        print(f"digest mismatch: {digest} != {ZLIB_SHA256}", file=sys.stderr)
        return 1
    print(f"verified {archive} sha256={digest[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

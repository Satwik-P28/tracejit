#!/usr/bin/env python3
"""Deterministic image transformation used by the real-world census.

usage: image_transform.py <input.png> <output.png>

Converts to grayscale, posterizes to 4 levels, then halves both dimensions with
the deterministic nearest-neighbour filter. Pillow is required; the census
records a missing-tool entry when it is unavailable rather than treating it as a
TraceJIT refusal.
"""

import sys
from pathlib import Path


def posterize(value: int) -> int:
    return (value // 64) * 85


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    from PIL import Image

    source, destination = Path(sys.argv[1]), Path(sys.argv[2])
    with Image.open(source) as image:
        gray = image.convert("L")
        levels = gray.point(lambda value: posterize(int(value)))
        small = levels.resize((gray.width // 2, gray.height // 2), Image.NEAREST)
        small.save(destination, format="PNG", optimize=False)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

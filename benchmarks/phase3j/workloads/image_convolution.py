#!/usr/bin/env python3
"""Deterministic pure-Python image convolution for Phase 3J.

usage: image_convolution.py <input.ppm> <output.ppm>

P6 PPM is used so the result is a byte-exact image without encoder metadata.
The 5x5 Gaussian and Sobel passes are intentionally computed in Python; this
is image processing with no native extension, clock, identity or entropy
observation beyond CPython startup.
"""

from __future__ import annotations

import sys
from pathlib import Path

WIDTH = 320
HEIGHT = 240
GAUSSIAN = (
    1, 4, 6, 4, 1,
    4, 16, 24, 16, 4,
    6, 24, 36, 24, 6,
    4, 16, 24, 16, 4,
    1, 4, 6, 4, 1,
)


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(b"P6\n"):
        raise ValueError("expected a P6 PPM")
    magic, dimensions, maximum, body = data.split(b"\n", 3)
    if magic != b"P6" or maximum != b"255":
        raise ValueError("expected an 8-bit P6 PPM")
    width, height = (int(value) for value in dimensions.split())
    if len(body) != width * height * 3:
        raise ValueError("unexpected PPM body length")
    return width, height, body


def blur(pixels: bytes, width: int, height: int) -> bytes:
    output = bytearray(len(pixels))
    for y in range(height):
        for x in range(width):
            base = (y * width + x) * 3
            for channel in range(3):
                total = 0
                for ky in range(-2, 3):
                    yy = min(height - 1, max(0, y + ky))
                    for kx in range(-2, 3):
                        xx = min(width - 1, max(0, x + kx))
                        total += (
                            pixels[(yy * width + xx) * 3 + channel]
                            * GAUSSIAN[(ky + 2) * 5 + kx + 2]
                        )
                output[base + channel] = total // 256
    return bytes(output)


def edges(pixels: bytes, width: int, height: int) -> bytes:
    output = bytearray(len(pixels))
    for y in range(height):
        for x in range(width):
            base = (y * width + x) * 3
            left = pixels[(y * width + max(0, x - 1)) * 3]
            right = pixels[(y * width + min(width - 1, x + 1)) * 3]
            up = pixels[(max(0, y - 1) * width + x) * 3]
            down = pixels[(min(height - 1, y + 1) * width + x) * 3]
            magnitude = min(255, abs(right - left) + abs(down - up))
            output[base] = magnitude
            output[base + 1] = (pixels[base + 1] + magnitude) // 2
            output[base + 2] = (pixels[base + 2] * 3 + magnitude) // 4
    return bytes(output)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    source, destination = (Path(argument) for argument in sys.argv[1:3])
    width, height, pixels = read_ppm(source)
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError(f"expected {WIDTH}x{HEIGHT}, got {width}x{height}")
    result = edges(blur(pixels, width, height), width, height)
    destination.write_bytes(b"P6\n%d %d\n255\n" % (width, height) + result)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

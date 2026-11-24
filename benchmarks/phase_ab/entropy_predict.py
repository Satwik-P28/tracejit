#!/usr/bin/env python3
"""Static preflight prediction for the compiler temp-name entropy draw.

The observation is fully explained by one glibc code path: `mkstemps`/`mkstemp`
reach `__gen_tempname`, which derives a candidate name suffix from a monotonic
clock read and an uninitialised stack word, and calls
`getrandom(buf, 8, GRND_NONBLOCK)` when that draw lands above
`0xf49998db0aa753ff` — probability 4.45 % per call. The value seeds a temporary
*file name*, so it is application-visible and must stay ineligible.

That makes the refusal predictable without executing or substituting anything:
an executable whose dynamic symbol table imports a temp-name function can reach
the draw, and one that does not cannot reach it through this path. This tool
reads the ELF symbol table (no execution, no ptrace, no environment change) and
reports the import set plus the build-level probability for a given number of
invocations.

It is a *predictor*, not an admission rule. It cannot see a statically linked
libc, an `syscall(318, ...)` issued directly, a plugin, or a path through
another library, and it never changes eligibility.

Usage::

    python3 benchmarks/phase_ab/entropy_predict.py /usr/bin/x86_64-linux-gnu-gcc-13 \
        /usr/bin/readelf --invocations 32
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
from pathlib import Path

#: Measured probability of one temp-name generation reaching `getrandom`.
#: `1 - 0xf49998db0aa753ff / 2**64` (glibc 2.39 `__gen_tempname`).
DRAW_PROBABILITY = (2**64 - 0xF49998DB0AA753FF) / 2**64

TEMP_NAME_IMPORTS = {
    "mkstemp",
    "mkstemps",
    "mkostemp",
    "mkostemps",
    "mktemp",
    "tempnam",
    "tmpnam",
    "__gen_tempname",
}
ENTROPY_IMPORTS = {"getrandom", "getentropy"}


def dynamic_symbols(path: Path) -> list[str]:
    """Imported and exported dynamic symbol names, from the ELF section headers."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError(f"{path} is not a 64-bit little-endian ELF")
    section_offset = struct.unpack_from("<Q", data, 0x28)[0]
    section_size = struct.unpack_from("<H", data, 0x3A)[0]
    section_count = struct.unpack_from("<H", data, 0x3C)[0]
    names = []
    for index in range(section_count):
        header = section_offset + index * section_size
        name_offset, kind = struct.unpack_from("<II", data, header)
        offset, size = struct.unpack_from("<QQ", data, header + 0x18)
        link = struct.unpack_from("<I", data, header + 0x28)[0]
        if kind != 11 or link >= section_count:  # SHT_DYNSYM
            continue
        string_header = section_offset + link * section_size
        string_offset, string_size = struct.unpack_from("<QQ", data, string_header + 0x18)
        strings = data[string_offset:string_offset + string_size]
        for entry in range(size // 24):
            base = offset + entry * 24
            symbol_name = struct.unpack_from("<I", data, base)[0]
            if symbol_name >= len(strings):
                continue
            end = strings.find(b"\0", symbol_name)
            raw = strings[symbol_name:end if end != -1 else None]
            names.append(raw.decode(errors="replace"))
    return sorted(set(names))


def predict(path: Path, invocations: int) -> dict:
    try:
        imports = dynamic_symbols(path)
    except (OSError, ValueError) as error:
        return {"path": str(path), "error": str(error)}
    temp_names = sorted(set(imports) & TEMP_NAME_IMPORTS)
    entropy = sorted(set(imports) & ENTROPY_IMPORTS)
    direct = bool(temp_names) or bool(entropy)
    # Two different claims. A temp-name import gives a per-call probability, because the draw is
    # conditional inside glibc. A direct entropy import means the command *will* be refused if
    # that call executes; the predictor cannot know whether it does, so it reports certainty of
    # refusal on the path, not a rate.
    per_invocation = DRAW_PROBABILITY if temp_names else (1.0 if entropy else 0.0)
    return {
        "path": str(path),
        "imports_temp_name": temp_names,
        "imports_entropy": entropy,
        "temp_name_draw_probability": round(DRAW_PROBABILITY, 5) if temp_names else 0.0,
        "predicted_probability_any_refusal": (
            round(1 - (1 - per_invocation) ** invocations, 4) if temp_names
            else (1.0 if entropy else 0.0)
        ),
        "claim": (
            "each temp-name call draws entropy with probability 4.45%"
            if temp_names
            else ("refused whenever the imported entropy call executes" if entropy
                  else "no known entropy path through the dynamic symbol table")
        ),
        "limitations": [
            "static linking is invisible",
            "a direct syscall(318, ...) is invisible",
            "a plugin or dlopen'ed library is invisible",
            "the predictor never changes eligibility",
        ],
        "direct": direct,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executables", nargs="+")
    parser.add_argument("--invocations", type=int, default=1)
    parser.add_argument("--output")
    parser.add_argument("--binary", help="also report the dynamic imports of a TraceJIT binary")
    args = parser.parse_args(argv)

    payload = {
        "draw_probability": round(DRAW_PROBABILITY, 5),
        "invocations": args.invocations,
        "executables": [predict(Path(name), args.invocations) for name in args.executables],
        "measured": {
            "gcc-cc-small-tu": {"trials": 100, "refused": 8, "rate": 0.08,
                                "source": "benchmarks/results/phaseab/entropy_study_small.json"},
        },
    }
    if args.binary:
        binary = Path(args.binary)
        payload["binary"] = {
            "path": str(binary),
            "sha256": subprocess.run(["sha256sum", str(binary)], capture_output=True, text=True,
                                     check=False).stdout.split()[0],
            "dynamic_symbols": len(dynamic_symbols(binary)),
        }
    print(json.dumps(payload, indent=2))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

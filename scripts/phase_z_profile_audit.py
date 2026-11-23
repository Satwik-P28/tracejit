#!/usr/bin/env python3
"""Audit a runtime image against a TraceJIT allocator-entropy profile.

Two modes:

  compare   Explain how two glibc builds differ at the call sites that matter to the contract,
            and emit the profile fields the candidate build encodes.
  verify    Check one image against a profile dictionary (the fields a Rust profile asserts).

Everything here is read-only and works on copies of the libraries; nothing is installed, loaded
into a process of ours, or modified.

The audit answers four questions, in this order:

1. Which `getrandom` call sites exist, and how many? A build that adds a site is a build that can
   read entropy somewhere new, so the count is part of the evidence, not a footnote.
2. For the allocator site, what does the *instruction sequence* encode? The destination is
   computed from the buffer load's RIP-relative effective address, exactly as the tracer and the
   guard compute it, so a profile cannot claim a destination the library does not encode.
3. Are the two builds' audited functions the same instructions? Decoded instructions are compared
   with code addresses, raw bytes and RIP-relative displacements normalized away; the remaining
   differences are real semantic differences.
4. Where does the image stop being byte-identical, and by how much does everything after that
   shift? That is what turns "the offsets moved" into "these unrelated patches shrank one earlier
   function".

Usage:

  python3 scripts/phase_z_profile_audit.py compare \
      --reference /path/to/old/libc.so.6 --candidate /path/to/new/libc.so.6 \
      --json benchmarks/results/phase_z/glibc-diff.json \
      --markdown docs/PHASE_Z_GLIBC_DIFF.md

  python3 scripts/phase_z_profile_audit.py verify --image /lib/x86_64-linux-gnu/libc.so.6 \
      --site-offset 0xa9e69 --destination-offset 0x20b178 \
      --signature 0f05488d5dd04883f808
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

GETRANDOM_NUMBER = 318
SYS_GETRANDOM = b"\xb8" + struct.pack("<I", GETRANDOM_NUMBER) + b"\x0f\x05"
LEA_RDI_RIP = b"\x48\x8d\x3d"
MOV_ESI_LENGTH = b"\xbe\x08\x00\x00\x00"
MOV_EDX_NONBLOCK = b"\xba\x01\x00\x00\x00"
PT_LOAD = 1
PF_W = 2


# ---------------------------------------------------------------------------------------------
# ELF facts


def program_headers(image: bytes) -> list[dict]:
    if image[:4] != b"\x7fELF" or image[4] != 2 or image[5] != 1:
        raise SystemExit("not an ELF64 little-endian image")
    offset = struct.unpack_from("<Q", image, 0x20)[0]
    size = struct.unpack_from("<H", image, 0x36)[0]
    count = struct.unpack_from("<H", image, 0x38)[0]
    headers = []
    for index in range(count):
        at = offset + index * size
        kind, flags = struct.unpack_from("<II", image, at)
        virtual = struct.unpack_from("<Q", image, at + 16)[0]
        file_offset = struct.unpack_from("<Q", image, at + 8)[0]
        file_size = struct.unpack_from("<Q", image, at + 32)[0]
        memory_size = struct.unpack_from("<Q", image, at + 40)[0]
        headers.append(
            {
                "kind": kind,
                "flags": flags,
                "virtual": virtual,
                "file_offset": file_offset,
                "file_size": file_size,
                "memory_size": memory_size,
            }
        )
    return headers


def build_id(image: bytes) -> str:
    headers = program_headers(image)
    for header in headers:
        if header["kind"] != 4:
            continue
        note = image[header["file_offset"] : header["file_offset"] + header["file_size"]]
        cursor = 0
        while cursor + 12 <= len(note):
            namesz, descsz, kind = struct.unpack_from("<III", note, cursor)
            name = note[cursor + 12 : cursor + 12 + namesz]
            desc_at = cursor + 12 + ((namesz + 3) // 4) * 4
            desc = note[desc_at : desc_at + descsz]
            if kind == 3 and name.rstrip(b"\0") == b"GNU":
                return desc.hex()
            cursor = desc_at + ((descsz + 3) // 4) * 4
    raise SystemExit("no GNU build ID note")


def mapped_offsets(image: bytes) -> dict:
    """Virtual address -> file offset, from the PT_LOAD segments."""
    segments = [h for h in program_headers(image) if h["kind"] == PT_LOAD]
    return {"segments": segments}


def file_offset_of(address: int, segments: list[dict]) -> int | None:
    for segment in segments:
        start = segment["virtual"]
        if start <= address < start + segment["file_size"]:
            return segment["file_offset"] + (address - start)
    return None


def writable_data_contains(offset: int, segments: list[dict]) -> bool:
    for segment in segments:
        if segment["kind"] != PT_LOAD or not segment["flags"] & PF_W:
            continue
        if segment["virtual"] <= offset < segment["virtual"] + segment["memory_size"]:
            return True
    return False


def find(pattern: bytes, image: bytes) -> list[int]:
    hits, at = [], image.find(pattern)
    while at >= 0:
        hits.append(at)
        at = image.find(pattern, at + 1)
    return hits


def dynamic_symbols(path: Path) -> list[tuple[int, str]]:
    output = subprocess.run(
        ["nm", "-D", "--defined-only", str(path)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    symbols = []
    for line in output.splitlines():
        match = re.match(r"^([0-9a-fA-F]+)\s+\S\s+(\S+)$", line)
        if match:
            symbols.append((int(match.group(1), 16), match.group(2)))
    symbols.sort()
    return symbols


def nearest_symbol(symbols: list[tuple[int, str]], address: int) -> str:
    name = None
    for value, symbol in symbols:
        if value > address:
            break
        name = symbol
    if name is None:
        return "?"
    for value, symbol in symbols:
        if value == address:
            return symbol
    return f"{name}+{address - [v for v, s in symbols if s == name][0]:#x}"


# ---------------------------------------------------------------------------------------------
# Instruction normalisation


INSTRUCTION = re.compile(r"^\s*([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*(\S.*)?$")


def instructions(path: Path, start: int, end: int) -> list[str]:
    """Decoded instructions with addresses, raw bytes and displacements normalized away."""
    output = subprocess.run(
        [
            "objdump",
            "-d",
            "--no-show-raw-insn",
            f"--start-address={start:#x}",
            f"--stop-address={end:#x}",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    normalized = []
    for line in output.splitlines():
        match = re.match(r"^\s*([0-9a-f]+):\t(\S.*)$", line)
        if not match:
            continue
        normalized.append(normalize_instruction(match.group(2)))
    return normalized


def normalize_instruction(text: str) -> str:
    """Keep the operation and its resolved target; drop everything relocation rewrites.

    Three things change between two builds of the same function: the code address, the encoded
    RIP-relative displacement, and the numeric target of a call or jump. None of them is a
    behaviour change, so all three are removed. The comment objdump prints names the target
    symbolically, and that survives a re-link.
    """
    operation, _, comment = text.partition("#")
    operation = re.sub(r"0x[0-9a-f]+\(%rip\)", "(%rip)", operation)
    operation = re.sub(r"^(call|j\w+)\s+[0-9a-f]+\s*$", r"\1", operation.strip())
    operation = re.sub(r"^(call|j\w+)\s+[0-9a-f]+\s+(?=<)", r"\1 ", operation)
    operation = re.sub(r"\s+", " ", operation).strip()
    comment = comment.strip()
    target = None
    if comment:
        symbol = re.search(r"<([^>]*)>", comment)
        address = re.match(r"([0-9a-f]+)", comment)
        target = symbol.group(1) if symbol else (address.group(1) if address else comment)
    return f"{operation} -> {target}" if target else operation


def audited_region(path: Path, site_offset: int, window_back: int = 0x40, window_forward: int = 0x80):
    start = max(0, site_offset - 2 - window_back)
    end = site_offset - 2 + window_forward
    return instructions(path, start, end)


def normalized_diff(left: list[str], right: list[str]) -> dict:
    """Line-by-line comparison; identical modulo relocation means empty `only_*` lists."""
    import difflib

    only_left = [line for line in left if line not in right]
    only_right = [line for line in right if line not in left]
    matcher = difflib.SequenceMatcher(a=left, b=right)
    return {
        "identical": left == right,
        "ratio": round(matcher.ratio(), 4),
        "only_reference": only_left,
        "only_candidate": only_right,
    }


# ---------------------------------------------------------------------------------------------
# Site analysis


def analyse_sites(image: bytes, path: Path) -> dict:
    segments = mapped_offsets(image)["segments"]
    symbols = dynamic_symbols(path)
    sites = []
    for at in find(SYS_GETRANDOM, image):
        syscall = at + 5
        resume = syscall + 2
        lea_at = None
        for candidate in range(max(0, at - 0x40), at):
            if image[candidate : candidate + 3] == LEA_RDI_RIP:
                lea_at = candidate
        destination = None
        if lea_at is not None:
            displacement = struct.unpack_from("<i", image, lea_at + 3)[0]
            destination = lea_at + 7 + displacement
        sanctioned = (
            lea_at is not None
            and destination is not None
            and writable_data_contains(destination, segments)
            and image[lea_at - 5 : lea_at] == MOV_ESI_LENGTH
            and image[lea_at - 10 : lea_at - 5] == MOV_EDX_NONBLOCK
        )
        sites.append(
            {
                "syscall_file_offset": hex(syscall),
                "resume_offset": hex(resume),
                "buffer_load_offset": hex(lea_at) if lea_at is not None else None,
                "destination_offset": hex(destination) if destination is not None else None,
                "destination_in_writable_segment": (
                    writable_data_contains(destination, segments)
                    if destination is not None
                    else None
                ),
                "audited_probe_shape": sanctioned,
                "nearest_dynamic_symbol": nearest_symbol(symbols, syscall),
                "following_bytes": image[syscall : syscall + 16].hex(),
            }
        )
    return {"sites": sites}


def symbol_shift(reference: Path, candidate: Path) -> dict:
    old = dict((name, value) for value, name in dynamic_symbols(reference))
    new = dict((name, value) for value, name in dynamic_symbols(candidate))
    shared = sorted(set(old) & set(new), key=lambda name: old[name])
    deltas: dict[int, int] = {}
    first_shift = None
    last_unchanged = None
    for name in shared:
        delta = new[name] - old[name]
        deltas[delta] = deltas.get(delta, 0) + 1
        if delta != 0 and first_shift is None:
            first_shift = {
                "symbol": name,
                "reference_address": hex(old[name]),
                "candidate_address": hex(new[name]),
                "delta": delta,
            }
        if delta == 0 and first_shift is None:
            last_unchanged = {"symbol": name, "reference_address": hex(old[name])}
    return {
        "shared_symbols": len(shared),
        "delta_histogram": {str(k): v for k, v in sorted(deltas.items())},
        "last_unchanged_symbol": last_unchanged,
        "first_shifted_symbol": first_shift,
    }


def byte_prefix(reference: bytes, candidate: bytes) -> dict:
    limit = min(len(reference), len(candidate))
    at = 0
    while at < limit and reference[at] == candidate[at]:
        at += 1
    return {"common_prefix_bytes": hex(at)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--json", type=Path)
    compare.add_argument("--markdown", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--image", type=Path, required=True)
    verify.add_argument("--site-offset", required=True, help="resume offset, hex")
    verify.add_argument("--destination-offset", required=True, help="buffer offset, hex")
    verify.add_argument("--signature", required=True, help="hex bytes at site_offset-2")

    args = parser.parse_args()
    if args.mode == "verify":
        image = args.image.read_bytes()
        offset = int(args.site_offset, 16)
        destination = int(args.destination_offset, 16)
        signature = bytes.fromhex(args.signature)
        sites = analyse_sites(image, args.image)["sites"]
        match = [
            site
            for site in sites
            if int(site["resume_offset"], 16) == offset
            and site["destination_offset"] == hex(destination)
            and image[offset - 2 : offset - 2 + len(signature)] == signature
        ]
        print(
            json.dumps(
                {
                    "image": str(args.image),
                    "build_id": build_id(image),
                    "sites": sites,
                    "profile_matches": bool(match),
                },
                indent=2,
            )
        )
        return 0 if match else 1

    reference_image = args.reference.read_bytes()
    candidate_image = args.candidate.read_bytes()
    report = {
        "reference": {
            "path": str(args.reference),
            "build_id": build_id(reference_image),
            "size": len(reference_image),
            "entropy_sites": analyse_sites(reference_image, args.reference)["sites"],
        },
        "candidate": {
            "path": str(args.candidate),
            "build_id": build_id(candidate_image),
            "size": len(candidate_image),
            "entropy_sites": analyse_sites(candidate_image, args.candidate)["sites"],
        },
        "symbol_shift": symbol_shift(args.reference, args.candidate),
        "byte_identity": byte_prefix(reference_image, candidate_image),
    }

    sanctioned_reference = [
        site for site in report["reference"]["entropy_sites"] if site["audited_probe_shape"]
    ]
    sanctioned_candidate = [
        site for site in report["candidate"]["entropy_sites"] if site["audited_probe_shape"]
    ]
    report["audited_probe"] = {
        "reference_sites": len(sanctioned_reference),
        "candidate_sites": len(sanctioned_candidate),
        "same_shape": [
            (a["destination_offset"] == b["destination_offset"])
            for a, b in zip(sanctioned_reference, sanctioned_candidate)
        ],
    }
    if sanctioned_reference and sanctioned_candidate:
        left = audited_region(args.reference, int(sanctioned_reference[0]["resume_offset"], 16))
        right = audited_region(args.candidate, int(sanctioned_candidate[0]["resume_offset"], 16))
        report["audited_function"] = normalized_diff(left, right)

    print(json.dumps(report, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(report) + "\n")
    return 0


def markdown(report: dict) -> str:
    reference = report["reference"]
    candidate = report["candidate"]
    lines = [
        "# glibc build-to-build audit for the allocator-entropy contract",
        "",
        "Generated by `scripts/phase_z_profile_audit.py compare`. Read-only: both images were",
        "opened for reading only and neither was installed, loaded into a process, or modified.",
        "",
        "| | reference | candidate |",
        "|---|---|---|",
        f"| image | `{reference['path']}` | `{candidate['path']}` |",
        f"| build ID | `{reference['build_id']}` | `{candidate['build_id']}` |",
        f"| size | {reference['size']} | {candidate['size']} |",
        f"| `getrandom` sites | {len(reference['entropy_sites'])} | {len(candidate['entropy_sites'])} |",
        "",
        "## Entropy call sites",
        "",
        "| build | syscall offset | buffer load | destination | audited probe shape |",
        "|---|---|---|---|---|",
    ]
    for label, entry in (("reference", reference), ("candidate", candidate)):
        for site in entry["entropy_sites"]:
            lines.append(
                f"| {label} | `{site['syscall_file_offset']}` | `{site['buffer_load_offset']}` | "
                f"`{site['destination_offset']}` | {site['audited_probe_shape']} |"
            )
    difference = report["audited_function"]
    lines += [
        "",
        "## Audited function comparison",
        "",
        "Instructions are decoded and compared with code addresses, raw bytes and RIP-relative",
        "displacements normalized to their resolved targets, so relocation-only differences do not",
        "count as behaviour changes.",
        "",
        f"- identical instruction streams: **{difference['identical']}** "
        f"(sequence ratio {difference['ratio']})",
        f"- present only in the reference: {len(difference['only_reference'])}",
        f"- present only in the candidate: {len(difference['only_candidate'])}",
        "",
        "## Layout shift",
        "",
        f"- first byte where the images differ: `{report['byte_identity']['common_prefix_bytes']}`",
        f"- shared dynamic symbols compared: {report['symbol_shift']['shared_symbols']}",
        f"- address delta histogram: `{json.dumps(report['symbol_shift']['delta_histogram'])}`",
    ]
    unchanged = report["symbol_shift"]["last_unchanged_symbol"]
    if unchanged:
        lines.append(
            f"- last symbol whose address is unchanged: `{unchanged['symbol']}` "
            f"at `{unchanged['reference_address']}`"
        )
    first = report["symbol_shift"]["first_shifted_symbol"]
    if first:
        lines.append(
            f"- first shifted symbol: `{first['symbol']}` "
            f"`{first['reference_address']}` -> `{first['candidate_address']}` "
            f"({first['delta']:+#x})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())

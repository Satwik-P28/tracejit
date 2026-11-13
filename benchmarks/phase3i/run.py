#!/usr/bin/env python3
"""Phase 3I acceptance harness for the controlled Python directory replay.

The target is the original python-csv-json workload, not a smoke script. It
records independent cold runs, warm reuse, invalidation, direct timing, complete
filesystem effects for the output, an entropy refusal, and syscall-level
directory-entry observations. The controlled padding policy is explicit; it is
not a claim that the bytes are native for a reader that inspects padding.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = ROOT / "benchmarks/realworld/workloads/etl.py"
PROBE_SOURCE = ROOT / "benchmarks/phase3i/getdents_probe.c"
RESULTS = ROOT / "benchmarks/results/phase3i"
TRACEJIT = ROOT / "target/release/tracejit"
PYTHON = Path("/usr/bin/python3.12")
LIBC = Path("/lib/x86_64-linux-gnu/libc.so.6")
TARGET_ENV = {
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "MALLOC_ARENA_MAX": "1",
}


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def build_id(path: Path) -> str:
    output = subprocess.run(
        ["readelf", "-n", str(path)], capture_output=True, text=True, check=True
    ).stdout
    for line in output.splitlines():
        if "Build ID:" in line:
            return line.split("Build ID:", 1)[1].strip()
    return ""


def identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": digest_file(path),
        "build_id": build_id(path),
    }


def run(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    started = time.perf_counter_ns()
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        close_fds=True,
    )
    result.wall_ns = time.perf_counter_ns() - started
    return result


def report(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


def make_data(directory: Path) -> tuple[Path, Path]:
    sales = directory / "sales.csv"
    customers = directory / "customers.csv"
    sales.write_text(
        "sale_id,customer_id,amount_cents\n"
        + "".join(
            f"s{index:04d},c{index % 12:03d},{(index * 37) % 5000}\n"
            for index in range(1, 401)
        ),
        encoding="utf-8",
    )
    customers.write_text(
        "customer_id,region\n"
        + "".join(
            f"c{index:03d},{['north', 'south', 'east', 'west'][index % 4]}\n"
            for index in range(12)
        ),
        encoding="utf-8",
    )
    return sales, customers


def target_command(output: Path, sales: Path, customers: Path, contract: str | None) -> list[str]:
    command = [str(TRACEJIT), "run", "--json"]
    if contract:
        command += ["--contract", contract]
    return command + [
        "--",
        str(PYTHON),
        str(WORKLOAD),
        str(sales),
        str(customers),
        str(output),
    ]


def direct_command(output: Path, sales: Path, customers: Path) -> list[str]:
    return [str(PYTHON), str(WORKLOAD), str(sales), str(customers), str(output)]


def target_run(
    cache: Path, output: Path, sales: Path, customers: Path, contract: str | None
) -> subprocess.CompletedProcess:
    return run(
        target_command(output, sales, customers, contract),
        {**TARGET_ENV, "TRACEJIT_CACHE_DIR": str(cache)},
    )


def explain(cache: Path) -> dict:
    result = run(
        [str(TRACEJIT), "explain", "--json"],
        {"TRACEJIT_CACHE_DIR": str(cache), **TARGET_ENV},
    )
    return report(result.stdout)


def parse_records(blob: list[int]) -> list[dict]:
    raw = bytes(blob)
    records = []
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < 19:
            raise ValueError(f"truncated header at {offset}")
        record = raw[offset : offset + 19]
        ino = int.from_bytes(record[0:8], "little")
        off = int.from_bytes(record[8:16], "little", signed=True)
        reclen = int.from_bytes(record[16:18], "little")
        if reclen < 20 or offset + reclen > len(raw):
            raise ValueError(f"invalid reclen {reclen} at {offset}")
        body = raw[offset : offset + reclen]
        name = body[19:]
        terminator = name.find(b"\0")
        if terminator < 0:
            raise ValueError(f"unterminated name at {offset}")
        name = name[:terminator]
        padding = body[19 + terminator + 1 :]
        records.append(
            {
                "ino": ino,
                "off": off,
                "reclen": reclen,
                "type": body[18],
                "name_hex": name.hex(),
                "padding_hex": padding.hex(),
            }
        )
        offset += reclen
    return records


def directory_summary(record: dict) -> dict:
    guards = record.get("guards") or []
    entries = []
    for guard in guards:
        if not isinstance(guard, dict):
            continue
        data = guard.get("DirectoryEnumerated")
        if not data:
            continue
        calls = []
        for request in data.get("requests", []):
            parsed = parse_records(request.get("returned", []))
            calls.append(
                {
                    "requested": request.get("requested"),
                    "returned_len": len(request.get("returned", [])),
                    "padding": request.get("padding", "Native"),
                    "records": parsed,
                }
            )
        semantic = [
            [
                {
                    key: value
                    for key, value in item.items()
                    if key != "padding_hex"
                }
                for item in call["records"]
            ]
            for call in calls
        ]
        entries.append(
            {
                "path": data.get("path"),
                "calls": calls,
                "semantic_sha256": digest_bytes(
                    json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
                ),
                "padding_bytes": sum(
                    len(bytes.fromhex(item["padding_hex"]))
                    for call in calls
                    for item in call["records"]
                ),
                "non_zero_padding": sum(
                    any(byte != 0 for byte in bytes.fromhex(item["padding_hex"]))
                    for call in calls
                    for item in call["records"]
                ),
            }
        )
    return {"directories": entries}


def output_effect(path: Path) -> dict:
    metadata = path.stat()
    return {
        "exists": True,
        "sha256": digest_file(path),
        "size": metadata.st_size,
        "mode": f"{metadata.st_mode & 0o7777:04o}",
        "nlink": metadata.st_nlink,
    }


def direct_effect(command: list[str], output: Path) -> tuple[dict, int]:
    if output.exists():
        output.unlink()
    result = run(command, TARGET_ENV)
    return output_effect(output), result.returncode


def target_effect(result: subprocess.CompletedProcess, output: Path) -> dict:
    parsed = report(result.stdout)
    return {
        "kind": parsed.get("kind"),
        "classification": parsed.get("classification"),
        "cache_decision": parsed.get("cache_decision"),
        "decision_reason": parsed.get("decision_reason"),
        "exit_code": parsed.get("exit_code"),
        "output": output_effect(output),
    }


def compile_probe(directory: Path) -> Path:
    binary = directory / "getdents-probe"
    result = run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", str(PROBE_SOURCE), "-o", str(binary)])
    if result.returncode != 0:
        raise RuntimeError(f"probe compilation failed: {result.stderr}")
    return binary


def parse_probe(text: str) -> list[dict]:
    records = []
    for line in text.splitlines():
        if not line.startswith("record "):
            continue
        fields = dict(part.split("=", 1) for part in line.split()[1:])
        records.append(
            {
                "ino": int(fields["ino"]),
                "off": int(fields["off"]),
                "reclen": int(fields["reclen"]),
                "type": int(fields["type"]),
                "name_hex": fields["name"],
                "padding_hex": fields["padding"],
            }
        )
    return records


def adversarial_suite(work: Path) -> dict:
    # Use `-c` rather than a script file: CPython opens and enumerates a script's
    # parent directory, whose atime is itself a guarded metadata input. The
    # probe is about time/PID/entropy values, not that unrelated directory.
    sources = {
        "time": "import time; print(time.time_ns())",
        "identity": (
            "import os, threading; "
            "print(os.getpid(), os.getppid(), threading.get_native_id())"
        ),
        "entropy": "import os; print(os.urandom(8).hex())",
    }
    results = {}
    for name, source in sources.items():
        cache = work / "caches" / f"adversarial-{name}"
        direct = run([str(PYTHON), "-S", "-c", source], TARGET_ENV)
        target = [
            str(TRACEJIT),
            "run",
            "--json",
            "--contract",
            "python-runtime-v1",
            "--",
            str(PYTHON),
            "-S",
            "-c",
            source,
        ]
        first = run(
            target,
            {**TARGET_ENV, "TRACEJIT_CACHE_DIR": str(cache)},
        )
        second = run(
            target,
            {**TARGET_ENV, "TRACEJIT_CACHE_DIR": str(cache)},
        )
        results[name] = {
            "direct_stdout": direct.stdout,
            "direct_stderr": direct.stderr,
            "first": report(first.stdout),
            "second": report(second.stdout),
        }
    return results


def main() -> int:
    if not TRACEJIT.exists():
        raise SystemExit(f"missing release binary: {TRACEJIT}; run cargo build --release")
    if not PYTHON.exists():
        raise SystemExit(f"missing pinned interpreter: {PYTHON}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tracejit-phase3i-"))
    data = work / "data"
    out = work / "out"
    caches = work / "caches"
    data.mkdir()
    out.mkdir()
    caches.mkdir()
    sales, customers = make_data(data)
    output = out / "report.json"

    identities = {
        "python": identity(PYTHON),
        "libc": identity(LIBC),
        "version": run([str(PYTHON), "-V"]).stdout.strip(),
        "kernel": run(["uname", "-srmo"]).stdout.strip(),
    }

    direct_fx, direct_status = direct_effect(
        direct_command(output, sales, customers), output
    )

    cold = []
    cold_summaries = []
    for index in range(3):
        cache = caches / f"cold-{index}"
        if output.exists():
            output.unlink()
        result = target_run(cache, output, sales, customers, "python-runtime-v1")
        cold.append(
            {
                "report": report(result.stdout),
                "wall_ns": result.wall_ns,
                "stderr": result.stderr,
                "effect": output_effect(output) if output.exists() else None,
            }
        )
        if index < 2:
            cold_summaries.append(directory_summary(explain(cache)))

    warm_cache = caches / "cold-0"
    warm = []
    for _ in range(10):
        result = target_run(warm_cache, output, sales, customers, "python-runtime-v1")
        warm.append(
            {
                "report": report(result.stdout),
                "wall_ns": result.wall_ns,
                "effect": output_effect(output),
            }
        )

    # Change the input after the warm campaign. The cached entry must deoptimize,
    # and the next execution must produce the new native output.
    sales.write_text(
        sales.read_text(encoding="utf-8") + "s0401,c001,1234\n", encoding="utf-8"
    )
    changed_direct_fx, changed_direct_status = direct_effect(
        direct_command(output, sales, customers), output
    )
    invalidated = target_run(warm_cache, output, sales, customers, "python-runtime-v1")
    invalidated_fx = output_effect(output) if output.exists() else None
    invalidated_report = report(invalidated.stdout)
    reusable_after = target_run(warm_cache, output, sales, customers, "python-runtime-v1")
    reusable_after_report = report(reusable_after.stdout)

    # Restore the original input for the timing comparison.
    sales, customers = make_data(data)
    if output.exists():
        output.unlink()
    direct_runs = []
    for _ in range(11):
        result = run(direct_command(output, sales, customers), TARGET_ENV)
        direct_runs.append(result.wall_ns)
    direct_output_fx = output_effect(output)

    # The raw syscall probe uses the same directory whose 48-byte record failed
    # in Phase 3H. It shows the fill byte surviving the kernel's padding write.
    probe = compile_probe(work)
    probe_dir = Path("/usr/local/lib/python3.12/dist-packages")
    if not probe_dir.is_dir():
        probe_dir = data
    probe_runs = {}
    for fill in ["aa", "55"]:
        result = run([str(probe), str(probe_dir), fill])
        probe_runs[fill] = {
            "status": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "records": parse_probe(result.stdout),
        }

    strace_dir = RESULTS / "strace"
    strace_dir.mkdir(exist_ok=True)
    strace_path = strace_dir / "target-getdents.strace"
    strace = run(
        [
            "strace",
            "-f",
            "-qq",
            "-e",
            "trace=getdents64",
            "-o",
            str(strace_path),
            *direct_command(output, sales, customers),
        ],
        TARGET_ENV,
    )

    adversarial = adversarial_suite(work)

    warm_fx = warm[-1]["effect"]
    effects_match = (
        warm_fx == direct_fx
        and warm_fx["sha256"] == cold[-1]["effect"]["sha256"]
        and invalidated_fx["sha256"] == changed_direct_fx["sha256"]
    )
    direct_median = statistics.median(direct_runs)
    cold_median = statistics.median(item["wall_ns"] for item in cold)
    warm_median = statistics.median(item["wall_ns"] for item in warm)
    document = {
        "phase": "3I",
        "target": "original python-csv-json",
        "identities": identities,
        "controlled_policy": "zero linux_dirent64 padding after getdents64 under python-runtime-v1",
        "direct": {
            "status": direct_status,
            "effect": direct_fx,
            "median_wall_ns": direct_median,
            "runs_ns": direct_runs,
        },
        "cold": [
            {
                "kind": item["report"].get("kind"),
                "classification": item["report"].get("classification"),
                "cache_decision": item["report"].get("cache_decision"),
                "wall_ns": item["wall_ns"],
                "effect": item["effect"],
                "stderr": item["stderr"],
            }
            for item in cold
        ],
        "warm": [
            {
                "kind": item["report"].get("kind"),
                "cache_decision": item["report"].get("cache_decision"),
                "wall_ns": item["wall_ns"],
                "effect": item["effect"],
            }
            for item in warm
        ],
        "invalidation": {
            "report": invalidated_report,
            "effect": invalidated_fx,
            "expected_direct": changed_direct_fx,
            "reusable_after": reusable_after_report,
        },
        "timing": {
            "direct_median_ns": direct_median,
            "cold_median_ns": cold_median,
            "warm_median_ns": warm_median,
            "complete_session_ns": sum(item["wall_ns"] for item in warm)
            + cold[-1]["wall_ns"],
            "direct_complete_session_ns": sum(direct_runs),
        },
        "filesystem_effects": {
            "direct": direct_fx,
            "warm": warm_fx,
            "invalidated": invalidated_fx,
            "changed_direct": changed_direct_fx,
            "match": effects_match,
        },
        "directory_observations": {
            "cold": cold_summaries,
            "semantic_stable": (
                len(cold_summaries) == 2
                and cold_summaries[0] == cold_summaries[1]
            ),
            "note": (
                "Semantic hashes exclude padding bytes but include d_ino, d_off, "
                "d_reclen, d_type and the name. The raw probe shows the fill byte "
                "surviving in native getdents64 padding."
            ),
        },
        "getdents_probe": probe_runs,
        "strace": {
            "status": strace.returncode,
            "path": str(strace_path.relative_to(ROOT)),
            "lines": strace_path.read_text(encoding="utf-8", errors="replace").splitlines(),
        },
        "adversarial": adversarial,
        "assertions": {
            "cold_executed": all(
                item["report"].get("kind") == "Executed"
                and item["report"].get("classification") == "Guarded"
                for item in cold
            ),
            "warm_reused": all(
                item["report"].get("kind") == "Reused" for item in warm
            ),
            "invalidated": invalidated_report.get("cache_decision") == "Deoptimized",
            "entropy_not_reused": (
                adversarial["entropy"]["second"].get("kind") != "Reused"
            ),
            "effects_match": effects_match,
        },
    }
    destination = RESULTS / "acceptance.json"
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RESULTS / "directory-records.json").write_text(
        json.dumps(cold_summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (RESULTS / "getdents-probe.txt").write_text(
        "\n".join(
            f"[fill {fill}] status {run['status']}\n{run['stdout']}"
            for fill, run in probe_runs.items()
        ),
        encoding="utf-8",
    )
    print(destination)
    print(json.dumps(document["assertions"], indent=2))
    print(
        "timing ms direct/cold/warm",
        round(direct_median / 1e6, 2),
        round(cold_median / 1e6, 2),
        round(warm_median / 1e6, 2),
    )
    print("output sha", direct_fx["sha256"], "match", effects_match)
    print("entropy second", adversarial["entropy"]["second"].get("kind"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

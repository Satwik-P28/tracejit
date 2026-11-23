#!/usr/bin/env python3
"""Phase Z benchmark harness: pin the environment, then measure.

Three subcommands:

  fingerprint   Emit the identity of the environment (runtime, toolchain, contract binary,
                corpus). Every result file carries one, and `session` refuses to compare against a
                stored result whose fingerprint differs in a pinned field.
  session       Cumulative compiler sessions: native, TraceJIT, make, ninja, over a schedule with
                edits, with byte-for-byte output checks and per-invocation cache decisions.
  workloads     Non-compiler candidates: measure compute against hashing-and-restore, and reject a
                workload whose cached execution is slower than running it.

Nothing here invents a number. Arms that cannot run in this environment are reported as
unavailable with the reason, not silently approximated.

Usage:

  python3 benchmarks/phase_z/harness.py fingerprint --json benchmarks/results/phase_z/env.json
  python3 benchmarks/phase_z/harness.py session --invocations 48 --json benchmarks/results/phase_z/session-48.json
  python3 benchmarks/phase_z/harness.py workloads --json benchmarks/results/phase_z/workloads.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACEJIT = ROOT / "target" / "release" / "tracejit"
CONTRACT = "compiler-runtime-v1"
UNITS = 3
PINNED_FIELDS = (
    "kernel_release",
    "cpu_model",
    "libc_build_id",
    "loader_build_id",
    "toolchain",
    "tracejit_sha256",
    "contract",
)


# ---------------------------------------------------------------------------------------------
# Environment identity


def sha256_of(path: Path) -> str | None:
    try:
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def elf_build_id(path: Path) -> str | None:
    try:
        image = path.read_bytes()
    except OSError:
        return None
    if image[:4] != b"\x7fELF" or image[4] != 2 or image[5] != 1:
        return None
    offset = int.from_bytes(image[0x20:0x28], "little")
    size = int.from_bytes(image[0x36:0x38], "little")
    count = int.from_bytes(image[0x38:0x3A], "little")
    for index in range(count):
        at = offset + index * size
        if int.from_bytes(image[at : at + 4], "little") != 4:
            continue
        start = int.from_bytes(image[at + 8 : at + 16], "little")
        length = int.from_bytes(image[at + 32 : at + 40], "little")
        note = image[start : start + length]
        cursor = 0
        while cursor + 12 <= len(note):
            namesz = int.from_bytes(note[cursor : cursor + 4], "little")
            descsz = int.from_bytes(note[cursor + 4 : cursor + 8], "little")
            kind = int.from_bytes(note[cursor + 8 : cursor + 12], "little")
            name = note[cursor + 12 : cursor + 12 + namesz]
            desc_at = cursor + 12 + ((namesz + 3) // 4) * 4
            if kind == 3 and name.rstrip(b"\0") == b"GNU":
                return note[desc_at : desc_at + descsz].hex()
            cursor = desc_at + ((descsz + 3) // 4) * 4
    return None


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


TOOLCHAIN_PATHS = {
    "cc": "/usr/bin/x86_64-linux-gnu-gcc-13",
    "cc1": "/usr/libexec/gcc/x86_64-linux-gnu/13/cc1",
    "as": "/usr/bin/x86_64-linux-gnu-as",
    "ld": "/usr/bin/x86_64-linux-gnu-ld",
    "collect2": "/usr/libexec/gcc/x86_64-linux-gnu/13/collect2",
}
PINNED_ENVIRONMENT = (
    "GLIBC_TUNABLES",
    "MALLOC_ARENA_MAX",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "SOURCE_DATE_EPOCH",
    "TZ",
    "LANG",
    "LC_ALL",
    "PYTHONHASHSEED",
    "TRACEJIT_GUARD_PROFILE",
)


def fingerprint(extra: dict | None = None) -> dict:
    import ctypes

    libc = ctypes.CDLL("libc.so.6")
    libc.gnu_get_libc_version.restype = ctypes.c_char_p
    version = libc.gnu_get_libc_version().decode()
    maps = Path("/proc/self/maps").read_text().splitlines()
    libc_path = next(
        (line.split()[-1] for line in maps if line.split()[-1].endswith("/libc.so.6")), None
    )
    loader = Path("/lib64/ld-linux-x86-64.so.2")
    doctor = None
    if TRACEJIT.exists():
        result = subprocess.run(
            [str(TRACEJIT), "doctor", "--json"], capture_output=True, text=True, check=False
        )
        try:
            doctor = json.loads(result.stdout)
        except json.JSONDecodeError:
            doctor = {"error": result.stdout[:200]}
    return {
        "captured_at_unix": int(time.time()),
        "os_release": Path("/etc/os-release").read_text().strip().splitlines()[:2],
        "kernel_release": platform.release(),
        "cpu_model": cpu_model(),
        "cpus": os.cpu_count(),
        "glibc_version": version,
        "libc_path": libc_path,
        "libc_build_id": elf_build_id(Path(libc_path)) if libc_path else None,
        "libc_sha256": sha256_of(Path(libc_path)) if libc_path else None,
        "loader_build_id": elf_build_id(loader),
        "toolchain": {
            name: {
                "path": path,
                "build_id": elf_build_id(Path(path)),
                "sha256": sha256_of(Path(path)),
            }
            for name, path in TOOLCHAIN_PATHS.items()
        },
        "tracejit": str(TRACEJIT),
        "tracejit_sha256": sha256_of(TRACEJIT),
        "contract": CONTRACT,
        "runtime_contract": (doctor or {}).get("runtime_contract"),
        "environment": {name: os.environ.get(name) for name in PINNED_ENVIRONMENT},
        "available_arms": {
            "ccache": bool(shutil.which("ccache")),
            "sccache": bool(shutil.which("sccache")),
            "make": bool(shutil.which("make")),
            "ninja": bool(shutil.which("ninja")),
        },
        **(extra or {}),
    }


def differences(left: dict, right: dict, fields=PINNED_FIELDS) -> list[str]:
    tail = "the comparison is refused"
    return [
        f"{field}: {left.get(field)!r} != {right.get(field)!r}; {tail}"
        for field in fields
        if left.get(field) != right.get(field)
    ]


# ---------------------------------------------------------------------------------------------
# Workloads


def write_sources(directory: Path, functions: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "common.h").write_text("#define SHARED_VALUE 1\n#define SCALE 3\n")
    for unit in range(UNITS):
        body = ['#include "common.h"', "#include <stdio.h>", "#include <string.h>", ""]
        for function in range(functions):
            body.append(
                f"long u{unit}_f{function}(long a) {{ char b[48]; snprintf(b, sizeof b, \"%ld\", a); "
                f"return (long)strlen(b) * {function + 1} + a; }}"
            )
        body.append("int main(void) { long t = 0;")
        for function in range(functions):
            body.append(f"  t += u{unit}_f{function}(SHARED_VALUE);")
        body.append('  printf("%ld\\n", t * SCALE);')
        body.append("  return 0;\n}\n")
        (directory / f"unit{unit}.c").write_text("\n".join(body))


def edit_header(directory: Path, state: int) -> None:
    (directory / "common.h").write_text(f"#define SHARED_VALUE {state}\n#define SCALE 3\n")


def run_command(
    command: list[str], cwd: Path, environment: dict | None = None
) -> tuple[float, dict | None]:
    env = dict(os.environ)
    env.pop("TRACEJIT_CACHE_DIR", None)
    if environment:
        env.update(environment)
    started = time.perf_counter()
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr}")
    decision = None
    if "--json" in command:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    decision = json.loads(line)
                except json.JSONDecodeError:
                    pass
    return elapsed, decision


def tracejit_compile(unit: int, cache: Path, environment: dict) -> list[str]:
    return [
        str(TRACEJIT),
        "run",
        "--json",
        "--contract",
        CONTRACT,
        "--",
        "gcc",
        "-O2",
        "-c",
        f"unit{unit}.c",
        "-o",
        f"unit{unit}.o",
    ]


def native_compile(unit: int) -> list[str]:
    return ["gcc", "-O2", "-c", f"unit{unit}.c", "-o", f"unit{unit}.o"]


def write_makefile(directory: Path, log: Path) -> None:
    wrapper = directory / "cc-logged"
    wrapper.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec gcc "$@"\n')
    wrapper.chmod(0o755)
    (directory / "Makefile").write_text(
        "\n".join(
            [
                f"CC := {wrapper}",
                "CFLAGS := -O2",
                "TARGETS := unit0.o unit1.o unit2.o",
                "all: $(TARGETS)",
                "unit0.o: unit0.c common.h\n\t$(CC) $(CFLAGS) -c unit0.c -o unit0.o",
                "unit1.o: unit1.c common.h\n\t$(CC) $(CFLAGS) -c unit1.c -o unit1.o",
                "unit2.o: unit2.c common.h\n\t$(CC) $(CFLAGS) -c unit2.c -o unit2.o",
                "clean:\n\trm -f $(TARGETS)",
                "",
            ]
        )
    )


def write_build_ninja(directory: Path, log: Path) -> None:
    wrapper = directory / "cc-logged"
    wrapper.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec gcc "$@"\n')
    wrapper.chmod(0o755)
    (directory / "build.ninja").write_text(
        "\n".join(
            [
                f"rule cc\n  command = {wrapper} -O2 -c $in -o $out",
                "build unit0.o: cc unit0.c | common.h",
                "build unit1.o: cc unit1.c | common.h",
                "build unit2.o: cc unit2.c | common.h",
                "build all: phony unit0.o unit1.o unit2.o",
                "default all",
                "",
            ]
        )
    )


def bootstrap_ci(values: list[float], rounds: int = 2000) -> tuple[float, float]:
    if len(values) < 2:
        return (float("nan"), float("nan"))
    generator = random.Random(20261123)
    means = [
        statistics.fmean(generator.choices(values, k=len(values))) for _ in range(rounds)
    ]
    means.sort()
    return (means[int(0.025 * rounds)], means[int(0.975 * rounds)])


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


# ---------------------------------------------------------------------------------------------
# Session


def session_with_decisions(
    invocations: int,
    scenario: str,
    workroot: Path,
    functions: int,
    edit_rounds: set[int],
) -> dict:
    """As `session`, but keeps the per-invocation cache decisions of the TraceJIT arm."""
    rounds = max(1, invocations // UNITS)
    arms = ["native", "tracejit"]
    if shutil.which("make"):
        arms.append("make")
    if shutil.which("ninja"):
        arms.append("ninja")
    unavailable = {
        name: "not installed; this sandbox has no root and no package-manager access"
        for name in ("ccache", "sccache")
        if not shutil.which(name)
    }

    arm_state = {}
    for arm in arms:
        directory = workroot / arm
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        write_sources(directory, functions)
        cache = workroot / f"{arm}-cache"
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir(parents=True)
        log = directory / "cc.log"
        log.write_text("")
        arm_state[arm] = {"directory": directory, "cache": cache, "log": log}
        if arm == "make":
            write_makefile(directory, log)
        if arm == "ninja":
            write_build_ninja(directory, log)

    records = []
    decisions = []
    edits_applied = 0
    for round_index in range(rounds):
        if scenario == "edits" and round_index in edit_rounds:
            edits_applied += 1
            for arm in arms:
                edit_header(arm_state[arm]["directory"], 1 + edits_applied % 2)
        for arm in arms:
            state = arm_state[arm]
            environment = {"TRACEJIT_CACHE_DIR": str(state["cache"])}
            elapsed = 0.0
            compiles = 0
            if arm in ("native", "tracejit"):
                for unit in range(UNITS):
                    command = (
                        native_compile(unit)
                        if arm == "native"
                        else tracejit_compile(unit, state["cache"], environment)
                    )
                    span, decision = run_command(
                        command,
                        state["directory"],
                        environment if arm == "tracejit" else None,
                    )
                    elapsed += span
                    compiles += 1
                    if decision and arm == "tracejit":
                        decisions.append(
                            {
                                "round": round_index,
                                "unit": unit,
                                "cache_decision": decision.get("cache_decision"),
                                "classification": decision.get("classification"),
                                "reasons": decision.get("reasons"),
                                # A deoptimisation's actual cause, not its classification note.
                                "guards": decision.get("guards"),
                                "decision_reason": decision.get("decision_reason"),
                            }
                        )
            else:
                command = ["make", "-s"] if arm == "make" else ["ninja", "-s"]
                before = len(state["log"].read_text().splitlines())
                elapsed, _ = run_command(command, state["directory"])
                # Only this round's compiles, never the cumulative log.
                compiles = len(state["log"].read_text().splitlines()) - before
            records.append(
                {"round": round_index, "arm": arm, "seconds": elapsed, "compiles": compiles}
            )

    final_native = workroot / "final-native"
    if final_native.exists():
        shutil.rmtree(final_native)
    final_native.mkdir(parents=True)
    write_sources(final_native, functions)
    final_edits = sum(1 for round_index in edit_rounds if round_index < rounds)
    if scenario == "edits" and final_edits:
        edit_header(final_native, 1 + final_edits % 2)
    for unit in range(UNITS):
        run_command(native_compile(unit), final_native)
    reference = {unit: (final_native / f"unit{unit}.o").read_bytes() for unit in range(UNITS)}
    identity = {
        arm: {
            unit: (arm_state[arm]["directory"] / f"unit{unit}.o").read_bytes()
            == reference[unit]
            for unit in range(UNITS)
        }
        for arm in arms
    }

    totals = {arm: sum(r["seconds"] for r in records if r["arm"] == arm) for arm in arms}
    summary = {}
    for arm in arms:
        spans = [r["seconds"] for r in records if r["arm"] == arm]
        low, high = bootstrap_ci(spans)
        summary[arm] = {
            "total_seconds": totals[arm],
            "median_round_ms": round(statistics.median(spans) * 1000, 2),
            "p95_round_ms": round(percentile(spans, 0.95) * 1000, 2),
            "mean_ci95_ms": [round(low * 1000, 2), round(high * 1000, 2)],
            "compiler_invocations": sum(r["compiles"] for r in records if r["arm"] == arm),
            "speedup_vs_native": round(totals["native"] / totals[arm], 3) if totals[arm] else None,
            "outputs_byte_identical_to_native": all(identity[arm].values()),
        }
    decision_counts = {}
    for decision in decisions:
        key = f"{decision['classification']}/{decision['cache_decision']}"
        decision_counts[key] = decision_counts.get(key, 0) + 1
    deopt_reasons = {}
    for decision in decisions:
        if decision["cache_decision"] not in ("Reused",):
            note = decision.get("decision_reason") or ""
            guards = decision.get("guards")
            if guards:
                note = f"{note} | guards {json.dumps(guards)[:200]}"
            if note:
                deopt_reasons[note] = deopt_reasons.get(note, 0) + 1

    return {
        "scenario": scenario,
        "invocations": rounds * UNITS,
        "rounds": rounds,
        "functions_per_unit": functions,
        "arms": arms,
        "unavailable_arms": unavailable,
        "fingerprint": fingerprint({"corpus_units": UNITS, "functions_per_unit": functions}),
        "summary": summary,
        "output_identity": {
            arm: {f"unit{unit}": ok for unit, ok in per_unit.items()}
            for arm, per_unit in identity.items()
        },
        "rounds_record": records,
        "tracejit_decision_counts": decision_counts,
        "tracejit_deopt_reasons": deopt_reasons,
        "tracejit_decisions": decisions,
    }


# ---------------------------------------------------------------------------------------------
# Non-compiler workloads


def build_corpus(directory: Path) -> dict:
    """Deterministic corpus: a fixed seed, so the fingerprint of the input is stable."""
    directory.mkdir(parents=True, exist_ok=True)
    generator = random.Random(20260101)
    words = directory / "words.txt"
    words.write_text(
        "\n".join(
            " ".join(
                generator.choice(
                    ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
                )
                for _ in range(8)
            )
            for _ in range(400_000)
        )
        + "\n"
    )
    numbers = directory / "numbers.txt"
    numbers.write_text("\n".join(str(generator.randrange(1_000_000)) for _ in range(300_000)) + "\n")
    blob = directory / "blob.bin"
    blob.write_bytes(bytes(generator.getrandbits(8) for _ in range(2_000_000)))
    document = directory / "document.json"
    document.write_text(
        json.dumps(
            {
                f"key{index}": {
                    "value": generator.randrange(1000),
                    "text": " ".join(
                        generator.choice(["red", "green", "blue"]) for _ in range(6)
                    ),
                }
                for index in range(20_000)
            }
        )
    )
    return {
        name: {"bytes": (directory / name).stat().st_size, "sha256": sha256_of(directory / name)}
        for name in ("words.txt", "numbers.txt", "blob.bin", "document.json")
    }


# Large outputs go to a file, never to stdout: TraceJIT captures a command's stdout into its JSON
# report, and a multi-megabyte capture would measure the report rather than the workload.
# Large outputs go to a file, never to stdout: `tracejit run --json` captures a command's stdout
# into the report, so a multi-megabyte capture would measure the report rather than the workload.
# `reset` is removed before every measured invocation, so each run starts from the same filesystem
# state and the first (cold) execution is a fair trace of the later ones.
WORKLOADS = [
    {
        "name": "sha256sum-blob",
        "kind": "compute",
        "command": ["sha256sum", "blob.bin"],
        "contract": "allocator-entropy-v1",
        "reset": [],
    },
    {
        "name": "gzip-blob",
        "kind": "compute",
        "command": ["gzip", "-9", "-n", "-k", "-f", "blob.bin"],
        "contract": "allocator-entropy-v1",
        "reset": ["blob.bin.gz"],
    },
    {
        "name": "sort-numbers",
        "kind": "compute",
        "command": ["sort", "-o", "sorted.txt", "numbers.txt"],
        "contract": "allocator-entropy-v1",
        "reset": ["sorted.txt"],
    },
    {
        "name": "sort-single-thread",
        "kind": "compute",
        "command": ["sort", "--parallel=1", "-S", "256M", "-o", "sorted1.txt", "numbers.txt"],
        "contract": "allocator-entropy-v1",
        "reset": ["sorted1.txt"],
    },
    {
        "name": "awk-sum",
        "kind": "compute",
        "command": ["awk", "{s+=$1} END {print s}", "numbers.txt"],
        "contract": "allocator-entropy-v1",
        "reset": [],
    },
    {
        "name": "sed-normalize",
        "kind": "transform",
        "command": ["sed", "-E", "-n", "s/[0-9]+/N/g;w normalized.txt", "numbers.txt"],
        "contract": "allocator-entropy-v1",
        "reset": ["normalized.txt"],
    },
    {
        "name": "wc-numbers",
        "kind": "cheap",
        "command": ["wc", "-l", "numbers.txt"],
        "contract": "allocator-entropy-v1",
        "reset": [],
    },
    {
        "name": "tar-words",
        "kind": "write-output",
        "command": ["tar", "-cf", "words.tar", "words.txt"],
        "contract": None,
        "reset": ["words.tar"],
    },
    {
        "name": "python-json-tool",
        "kind": "parse",
        "command": ["python3", "-m", "json.tool", "document.json", "formatted.json"],
        "contract": "allocator-entropy-v1",
        "reset": ["formatted.json"],
    },
]


def reset_outputs(directory: Path, workload: dict) -> None:
    for name in workload.get("reset") or []:
        (directory / name).unlink(missing_ok=True)


def measure(binary: Path, workload: dict, directory: Path, cache: Path, rounds: int) -> dict:
    contract = workload["contract"]
    prefix = [str(binary), "run", "--json"]
    if contract:
        prefix += ["--contract", contract]
    command = prefix + ["--"] + workload["command"]
    native_spans = []
    for _ in range(rounds):
        reset_outputs(directory, workload)
        span, _ = run_command(workload["command"], directory)
        native_spans.append(span)
    reset_outputs(directory, workload)
    first, cold = run_command(command, directory, {"TRACEJIT_CACHE_DIR": str(cache)})
    hit_spans = []
    decisions = []
    for _ in range(rounds):
        reset_outputs(directory, workload)
        span, decision = run_command(command, directory, {"TRACEJIT_CACHE_DIR": str(cache)})
        hit_spans.append(span)
        decisions.append(decision or {})
    profiled_cache = cache.parent / (cache.name + "-profile")
    if profiled_cache.exists():
        shutil.rmtree(profiled_cache)
    profiled_cache.mkdir(parents=True)
    phase_path = directory / f"phases-{workload['name']}.json"
    profiled_environment = {
        "TRACEJIT_CACHE_DIR": str(profiled_cache),
        "TRACEJIT_GUARD_PROFILE": "1",
        "TRACEJIT_PHASE_TIMING": "1",
        "TRACEJIT_PHASE_TIMING_PATH": str(phase_path),
    }
    reset_outputs(directory, workload)
    run_command(command, directory, profiled_environment)
    reset_outputs(directory, workload)
    _, profile_hit = run_command(command, directory, profiled_environment)
    phases = {}
    if phase_path.exists():
        try:
            phases = json.loads(phase_path.read_text())
        except json.JSONDecodeError:
            phases = {}
    guards = phases.get("guard_profile") or {}
    guard_pass = (guards.get("passes") or [{}])[-1] if guards else {}
    classification = (decisions[-1] or {}).get("classification")
    reusable = all((decision or {}).get("cache_decision") == "Reused" for decision in decisions)
    native_median = statistics.median(native_spans)
    hit_median = statistics.median(hit_spans)
    return {
        "name": workload["name"],
        "kind": workload["kind"],
        "command": workload["command"],
        "contract": contract,
        "classification": classification,
        "cache_decisions": sorted(
            {(decision or {}).get("cache_decision") for decision in decisions}
        ),
        "reused_every_round": reusable,
        "native_median_ms": round(native_median * 1000, 2),
        "cold_trace_ms": round(first * 1000, 2),
        "hit_median_ms": round(hit_median * 1000, 2),
        "speedup": round(native_median / hit_median, 3) if hit_median else None,
        "hit_slower_than_native": hit_median > native_median,
        "guard_bytes_hashed": guard_pass.get("bytes_hashed"),
        "guard_count": guard_pass.get("guards"),
        "guard_content_ns": guard_pass.get("content_ns"),
        "guard_total_ns": guard_pass.get("total_ns"),
        "restore_ns": phases.get("cas_restore_ns"),
        "stdio_replay_ns": phases.get("stdio_replay_ns"),
        "decision_persist_ns": phases.get("decision_persist_ns"),
        "reasons": (decisions[-1] or {}).get("reasons"),
    }


# ---------------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("fingerprint", "session", "workloads"), help="what to do"
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument("--compare-to", type=Path, help="refuse a comparison across environments")
    parser.add_argument("--invocations", type=int, default=48)
    parser.add_argument("--scenario", default="edits", choices=("edits", "repeat"))
    parser.add_argument("--functions", type=int, default=220)
    parser.add_argument(
        "--edit-rounds", default="3,6", help="rounds that edit the shared header"
    )
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--workroot", type=Path, default=Path("/tmp/tracejit-phase-z"))
    args = parser.parse_args()

    if not TRACEJIT.exists():
        raise SystemExit(f"build the release binary first: {TRACEJIT}")

    if args.mode == "fingerprint":
        report = fingerprint()
    elif args.mode == "session":
        report = session_with_decisions(
            args.invocations,
            args.scenario,
            args.workroot / f"session-{args.invocations}",
            args.functions,
            {int(part) for part in args.edit_rounds.split(",") if part.strip()},
        )
        report["edit_rounds"] = args.edit_rounds
    else:
        corpus = args.workroot / "corpus"
        if corpus.exists():
            shutil.rmtree(corpus)
        manifest = build_corpus(corpus)
        results = []
        for index, workload in enumerate(WORKLOADS):
            cache = args.workroot / "workload-cache" / f"{index}-{workload['name']}"
            if cache.exists():
                shutil.rmtree(cache)
            cache.mkdir(parents=True)
            results.append(measure(TRACEJIT, workload, corpus, cache, args.rounds))
        report = {
            "corpus": manifest,
            "rounds": args.rounds,
            "fingerprint": fingerprint({"corpus": manifest}),
            "workloads": results,
            "shortlist": [
                entry["name"]
                for entry in results
                if entry["reused_every_round"] and not entry["hit_slower_than_native"]
            ],
        }

    if args.compare_to and args.compare_to.exists():
        stored = json.loads(args.compare_to.read_text())
        mismatch = differences(stored.get("fingerprint") or {}, report["fingerprint"])
        if mismatch:
            print(json.dumps({"refused": mismatch}, indent=2))
            return 2
        report["compared_against"] = str(args.compare_to)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

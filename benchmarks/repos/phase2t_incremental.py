#!/usr/bin/env python3
"""Phase 2T: TraceJIT against correctly configured incremental build tools.

Every arm produces the same real artifacts in the same workspace layout. The transformation is
`bzip2 -9 -k -f`, so the output write, timestamp preservation and mode changes happen inside the
timed command for all five arms. The content-addressed arm is an independent, deliberately simple
cache keyed by relative path plus input bytes; it is not TraceJIT code.

Usage:
    cargo build --release --workspace
    python3 benchmarks/repos/phase2t_incremental.py --sessions 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRACEJIT = REPO / "target/release/tracejit"
ROOT = Path("/tmp/tracejit-phase2t")
RESULTS = REPO / "benchmarks/results/phase2t"
ASSETS = ("app.js", "vendor.js", "worker.js")
CONTRACT = "allocator-entropy-v1"
ARMS = ("native", "tracejit", "make", "ninja", "hashcache")


def sha256(path: Path) -> str:
    # Verification must not mutate the atime that TraceJIT guards. O_NOATIME is available to the
    # file owner on this host; the fallback restores the original timestamps after reading.
    digest = hashlib.sha256()
    noatime = getattr(os, "O_NOATIME", 0)
    metadata = path.stat()
    descriptor = os.open(path, os.O_RDONLY | noatime)
    try:
        with os.fdopen(descriptor, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    finally:
        if not noatime:
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    return digest.hexdigest()


def copy_without_atime(source: Path, destination: Path) -> None:
    """Copy an input without letting the reference arm mutate its guarded atime."""
    metadata = source.stat()
    noatime = getattr(os, "O_NOATIME", 0)
    input_fd = os.open(source, os.O_RDONLY | noatime)
    try:
        with os.fdopen(input_fd, "rb") as reader, destination.open("wb") as writer:
            shutil.copyfileobj(reader, writer, 1 << 20)
    finally:
        if not noatime:
            os.utime(source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    os.chmod(destination, metadata.st_mode & 0o7777)
    os.utime(destination, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "sha256": sha256(path),
        "size": stat.st_size,
        "mode": oct(stat.st_mode & 0o7777),
        "mtime_ns": stat.st_mtime_ns,
    }


def write_assets(assets: Path) -> None:
    assets.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(ASSETS):
        with (assets / name).open("w") as handle:
            for row in range(48_000):
                handle.write(
                    f"export const value_{index}_{row} = "
                    f"{(row * (index + 3) * 2654435761) % 1_000_000_007}; "
                    f"// bundle-{index}-{row:06d}\n"
                )


def write_makefile(path: Path) -> None:
    lines = ["BZ2 := " + " ".join(f"assets/{name}.bz2" for name in ASSETS), "", "all: $(BZ2)", ""]
    for name in ASSETS:
        # bzip2 stores the input's whole-second mtime. Touch the target after the write so the
        # declared graph records a completed build instead of rebuilding on every invocation.
        lines += [
            f"assets/{name}.bz2: assets/{name}",
            "\tbzip2 -9 -k -f $<",
            "\ttouch $@",
            "",
        ]
    path.write_text("\n".join(lines))


def write_ninja(path: Path) -> None:
    lines = [
        "rule bz",
        "  command = bzip2 -9 -k -f $in && touch $out",
        "  description = BZ $out",
        "",
    ]
    for name in ASSETS:
        lines.append(f"build assets/{name}.bz2: bz assets/{name}")
    lines += ["", "default " + " ".join(f"assets/{name}.bz2" for name in ASSETS), ""]
    path.write_text("\n".join(lines))


HASHCACHE = """#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
from pathlib import Path

cache = Path('.hashcache')
objects = cache / 'objects'
objects.mkdir(parents=True, exist_ok=True)
hits = misses = 0
for name in sys.argv[1:]:
    source = Path(name)
    output = Path(name + '.bz2')
    content = hashlib.sha256(source.read_bytes()).hexdigest()
    key = hashlib.sha256((str(source) + '\\0' + content).encode()).hexdigest()
    stored = objects / (key + '.bz2')
    if stored.is_file():
        hits += 1
    else:
        misses += 1
        temporary = objects / (key + '.tmp')
        subprocess.run(['bzip2', '-9', '-c', str(source)], stdout=temporary.open('wb'), check=True)
        os.replace(temporary, stored)
    temporary = output.with_name(output.name + '.tmp')
    temporary.write_bytes(stored.read_bytes())
    os.replace(temporary, output)
(cache / 'last.json').write_text(json.dumps({'hits': hits, 'misses': misses}) + '\\n')
"""


@dataclass
class Arm:
    name: str
    root: Path
    cache: Path
    work: Path
    env: dict
    config_lines: int = 0
    config_edges: int = 0
    phase_index: int = 0
    phases: list[dict] = field(default_factory=list)

    def inputs(self) -> list[Path]:
        return [self.work / "assets" / name for name in ASSETS]

    def outputs(self) -> list[Path]:
        return [self.work / "assets" / f"{name}.bz2" for name in ASSETS]


def arm_environment(cache: Path | None) -> dict:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def prepare_arm(arm_name: str, session_root: Path) -> Arm:
    root = session_root / arm_name
    work = root / "work"
    cache = root / "cache"
    root.mkdir(parents=True)
    work.mkdir()
    write_assets(work / "assets")
    (work / "assets" / "notes.txt").write_text("unrelated project note\n")
    if arm_name == "make":
        write_makefile(work / "Makefile")
    elif arm_name == "ninja":
        write_ninja(work / "build.ninja")
    elif arm_name == "hashcache":
        (work / "hashcache.py").write_text(HASHCACHE)
    env = arm_environment(cache if arm_name == "tracejit" else None)
    arm = Arm(arm_name, root, cache, work, env)
    if arm_name == "make":
        arm.config_lines = len((work / "Makefile").read_text().splitlines())
        arm.config_edges = len(ASSETS)
    elif arm_name == "ninja":
        arm.config_lines = len((work / "build.ninja").read_text().splitlines())
        arm.config_edges = len(ASSETS)
    elif arm_name == "hashcache":
        arm.config_lines = len(HASHCACHE.splitlines())
        arm.config_edges = len(ASSETS)
    return arm


def run_command(argv: list[str], cwd: Path, env: dict) -> tuple[float, subprocess.CompletedProcess]:
    started = time.perf_counter()
    completed = subprocess.run(
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return (time.perf_counter() - started) * 1000.0, completed


def parse_tracejit(completed: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "cache_decision": "NO_JSON",
            "stderr": completed.stderr.decode(errors="replace")[-500:],
            "exit": completed.returncode,
        }


def tracejit_phases(arm: Arm) -> dict | None:
    path = arm.root / "phases-current.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    finally:
        path.unlink(missing_ok=True)


def tracejit_argv(asset: Path) -> list[str]:
    return [
        str(TRACEJIT), "run", "--json", "--contract", CONTRACT,
        "--", "bzip2", "-9", "-k", "-f", f"assets/{asset.name}",
    ]


def run_build(arm: Arm, jobs: int = 1) -> dict:
    started = time.perf_counter()
    decisions: list[str] = []
    run_phases: list[dict] = []
    if arm.name == "native":
        for name in ASSETS:
            run_command(
                ["bzip2", "-9", "-k", "-f", f"assets/{name}"], arm.work, arm.env
            )
    elif arm.name == "tracejit":
        if jobs == 1:
            for name in ASSETS:
                timing = arm.root / "phases-current.json"
                env = dict(arm.env)
                env["TRACEJIT_PHASE_TIMING"] = "1"
                env["TRACEJIT_PHASE_TIMING_PATH"] = str(timing)
                elapsed, completed = run_command(
                    tracejit_argv(arm.work / "assets" / name), arm.work, env
                )
                report = parse_tracejit(completed)
                decisions.append({
                    "decision": report.get("cache_decision", "NO_JSON"),
                    "reason": report.get("decision_reason"),
                    "guard_failure": report.get("guard_failure"),
                })
                phase = tracejit_phases(arm)
                if phase:
                    arm.phases.append(phase)
                    run_phases.append(phase)
        else:
            processes = []
            for index, name in enumerate(ASSETS):
                timing = arm.root / "phases-current.json"
                env = dict(arm.env)
                env["TRACEJIT_PHASE_TIMING"] = "1"
                env["TRACEJIT_PHASE_TIMING_PATH"] = str(timing)
                processes.append((
                    subprocess.Popen(
                        tracejit_argv(arm.work / "assets" / name),
                        cwd=arm.work, env=env,
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    ),
                    timing,
                ))
            for process, timing in processes:
                stdout, stderr = process.communicate()
                try:
                    report = json.loads(stdout)
                except json.JSONDecodeError:
                    report = {"cache_decision": "NO_JSON"}
                decisions.append(report.get("cache_decision", "NO_JSON"))
                try:
                    arm.phases.append(json.loads(timing.read_text()))
                except (OSError, json.JSONDecodeError):
                    pass
    elif arm.name == "make":
        _, completed = run_command(
            ["make", "-f", "Makefile", f"-j{jobs}"], arm.work, arm.env
        )
        decisions.append(f"make-exit-{completed.returncode}")
    elif arm.name == "ninja":
        _, completed = run_command(
            ["/tmp/tracejit-tools/bin/ninja", "-f", "build.ninja", f"-j{jobs}"],
            arm.work, arm.env,
        )
        decisions.append(f"ninja-exit-{completed.returncode}")
    elif arm.name == "hashcache":
        run_command(
            ["python3", "hashcache.py", *[f"assets/{name}" for name in ASSETS]],
            arm.work, arm.env,
        )
        try:
            decisions.append(json.loads((arm.work / ".hashcache" / "last.json").read_text()))
        except (OSError, json.JSONDecodeError):
            decisions.append("NO_JSON")
    else:
        raise AssertionError(arm.name)
    return {
        "ms": round((time.perf_counter() - started) * 1000.0, 2),
        "decisions": decisions,
        "phases": run_phases,
    }


def expected_outputs(work: Path, reference_root: Path) -> dict[str, dict]:
    assets = work / "assets"
    if reference_root.exists():
        shutil.rmtree(reference_root)
    (reference_root / "assets").mkdir(parents=True)
    result = {}
    for name in ASSETS:
        copy_without_atime(assets / name, reference_root / "assets" / name)
        completed = subprocess.run(
            ["bzip2", "-9", "-k", "-f", f"assets/{name}"],
            cwd=reference_root, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            raise SystemExit(f"reference compression failed: {completed.stderr.decode()}")
        result[name] = fingerprint(reference_root / "assets" / f"{name}.bz2")
    return result


def verify(arm: Arm, expected: dict[str, dict]) -> tuple[bool, list[str], bool]:
    failures = []
    metadata_matches = True
    for name in ASSETS:
        output = arm.work / "assets" / f"{name}.bz2"
        if not output.is_file():
            failures.append(f"{name}: missing")
            metadata_matches = False
            continue
        actual = fingerprint(output)
        if actual["sha256"] != expected[name]["sha256"]:
            failures.append(f"{name}: content differs")
        if (actual["mode"] != expected[name]["mode"]
                or actual["mtime_ns"] != expected[name]["mtime_ns"]):
            metadata_matches = False
    return not failures, failures, metadata_matches


def delete_outputs(arm: Arm) -> None:
    for output in arm.outputs():
        output.unlink(missing_ok=True)


def edit(path: Path, text: str, preserve_mtime: bool = False) -> None:
    metadata = path.stat()
    path.write_text(path.read_text() + text)
    if preserve_mtime:
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))


def scenario_sequence(arm: Arm, reference_root: Path) -> list[dict]:
    rows = []

    def measure(label: str, jobs: int = 1, before=None) -> None:
        if before is not None:
            before()
        expected = expected_outputs(arm.work, reference_root)
        run = run_build(arm, jobs)
        correct, failures, metadata_matches = verify(arm, expected)
        rows.append({
            "scenario": label,
            "jobs": jobs,
            "ms": run["ms"],
            "decisions": run["decisions"],
            "correct": correct,
            "output_metadata_matches_native": metadata_matches,
            "artifact_failures": failures,
            "tracejit_phases": run["phases"],
            "cache_bytes": sum(
                path.stat().st_size for path in arm.cache.rglob("*")
                if path.is_file()
            ) if arm.cache.exists() else 0,
            "outputs": {
                name: fingerprint(arm.work / "assets" / f"{name}.bz2")
                for name in ASSETS
                if (arm.work / "assets" / f"{name}.bz2").is_file()
            },
        })

    measure("1_first_build_no_outputs")
    measure("2_identical_rerun_outputs_present")
    measure("3_outputs_deleted", before=lambda: delete_outputs(arm))
    measure("4_one_input_modified", before=lambda: edit(
        arm.work / "assets" / "app.js", "\n// app edit\n"
    ))
    measure("5_unrelated_file_modified", before=lambda: edit(
        arm.work / "assets" / "notes.txt", "another note\n"
    ))
    measure("6_input_changed_mtime_preserved", before=lambda: edit(
        arm.work / "assets" / "vendor.js", "\n// preserved-mtime edit\n", preserve_mtime=True
    ))

    def corrupt_output() -> None:
        output = arm.work / "assets" / "worker.js.bz2"
        output.write_bytes(b"corrupted output without an input change\n")
        metadata = (arm.work / "assets" / "worker.js").stat()
        os.utime(output, ns=(metadata.st_atime_ns + 2_000_000_000,
                            metadata.st_mtime_ns + 2_000_000_000))

    measure("7_output_corrupted_no_input_change", before=corrupt_output)

    old_work = arm.work
    relocated = arm.root / "relocated"
    relocated.mkdir()
    new_work = relocated / "work"
    old_work.rename(new_work)
    arm.work = new_work
    measure("8_build_directory_relocated")
    measure("9_parallel_transformations", jobs=3, before=lambda: delete_outputs(arm))

    started = time.perf_counter()
    for index in range(5):
        edit(arm.work / "assets" / ASSETS[index % len(ASSETS)], f"\n// session {index}\n")
        run_build(arm, 1)
    session_ms = (time.perf_counter() - started) * 1000.0
    expected = expected_outputs(arm.work, reference_root)
    correct, failures, metadata_matches = verify(arm, expected)
    rows.append({
        "scenario": "10_five_development_sessions",
        "jobs": 1,
        "ms": round(session_ms, 2),
        "decisions": [],
        "correct": correct,
        "output_metadata_matches_native": metadata_matches,
        "artifact_failures": failures,
        "tracejit_phases": [],
        "cache_bytes": sum(
            path.stat().st_size for path in arm.cache.rglob("*")
            if path.is_file()
        ) if arm.cache.exists() else 0,
        "outputs": {
            name: fingerprint(arm.work / "assets" / f"{name}.bz2") for name in ASSETS
        },
    })
    return rows


def repo_state() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
    }


def summarize(sessions: list[dict]) -> dict:
    summary = {}
    for scenario in sessions[0]["arms"]["native"]:
        label = scenario["scenario"]
        summary[label] = {}
        for arm in ARMS:
            samples = [
                next(row for row in session["arms"][arm] if row["scenario"] == label)
                for session in sessions
            ]
            summary[label][arm] = {
                "median_ms": round(statistics.median(row["ms"] for row in samples), 2),
                "samples_ms": [row["ms"] for row in samples],
                "all_correct": all(row["correct"] for row in samples),
                "all_output_metadata_matches_native": all(
                    row["output_metadata_matches_native"] for row in samples
                ),
                "incorrect_sessions": [
                    session["session"] for session in sessions
                    if not next(row for row in session["arms"][arm]
                                if row["scenario"] == label)["correct"]
                ],
            }
            base = statistics.median(
                next(row for row in session["arms"]["native"] if row["scenario"] == label)["ms"]
                for session in sessions
            )
            summary[label][arm]["vs_native"] = round(
                base / summary[label][arm]["median_ms"], 3
            )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--output-dir", default=str(RESULTS))
    parser.add_argument("--seed", type=int, default=20261110)
    args = parser.parse_args()
    if not TRACEJIT.is_file():
        raise SystemExit("missing target/release/tracejit; build the release workspace first")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    input_template = ROOT / "inputs"
    write_assets(input_template)
    sessions = []
    for index in range(args.sessions):
        session_root = ROOT / f"session-{index + 1}"
        session_root.mkdir()
        order = list(ARMS)
        random.Random(args.seed + index).shuffle(order)
        result = {"session": index + 1, "arm_order": order, "arms": {}}
        for arm_name in order:
            arm = prepare_arm(arm_name, session_root)
            result["arms"][arm_name] = scenario_sequence(
                arm, session_root / f"reference-{arm_name}"
            )
            result.setdefault("configuration", {})[arm_name] = {
                "lines": arm.config_lines,
                "declared_edges": arm.config_edges,
                "build_file": arm_name in {"make", "ninja"},
            }
        sessions.append(result)
        print(f"session {index + 1} complete in arm order {order}", file=sys.stderr)

    summary = summarize(sessions)
    binary = {
        "sha256": sha256(TRACEJIT),
        "size": TRACEJIT.stat().st_size,
    }
    report = {
        "phase": "2T",
        "workload": "three JavaScript assets precompressed with bzip2 -9 -k -f",
        "contract": CONTRACT,
        "tracejit": binary,
        "repository": repo_state(),
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "cpus": os.cpu_count(),
            "memory": Path("/proc/meminfo").read_text().splitlines()[0],
            "make": subprocess.run(["make", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
            "ninja": subprocess.run(
                ["/tmp/tracejit-tools/bin/ninja", "--version"], capture_output=True, text=True
            ).stdout.strip(),
        },
        "input_fingerprints": {
            name: fingerprint(input_template / name) for name in ASSETS
        },
        "configuration": sessions[0]["configuration"],
        "sessions": sessions,
        "summary": summary,
        "method": {
            "timing": "complete wall time of each build invocation, including process startup and output writes",
            "cold": "session 1 includes TraceJIT's cold traces; each session has an isolated cache",
            "references": "native output bytes for the current inputs, generated untimed before each scenario",
            "order": "arm order randomized per session; scenario order fixed because each state depends on the previous one",
        },
    }
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "incremental.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        label: {
            arm: values[arm]["median_ms"] for arm in ARMS
        } for label, values in summary.items()
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase AE: verified competitive matrix across native, TraceJIT and Firebuild versions.

Why this harness exists
-----------------------
Phase AD's competitive harness measured reuse, correctness and timing in *different*
invocations, pre-populated every cache before timing, and mixed the Firebuild cache with
its HOME.  This harness measures one invocation at a time and records, for every one of
them:

* the engine's own reuse decision (TraceJIT's plain-mode report; Firebuild's ``-s`` trailer),
* exit status,
* stdout and output-file digests against an independently computed native oracle,
* cache size after the invocation,
* whether an error was operational (spawn/IO) or a correctness failure.

Two experiments are kept apart:

``cold``    a brand-new cache per session; every invocation is measured, including the first
            trace, later reuse, refusals and deoptimizations.  This is the end-to-end cost a
            new user pays.
``steady``  the cache is populated outside the timer (one trace plus one reuse), then the
            session is measured.  This is the steady-state cost, and only this.

Neither mode is allowed to label an invocation a HIT without the engine's decision for that
same invocation, and neither may report a session whose outputs were not compared to the
oracle.

Timing boundaries
-----------------
``command`` is the wall time of one engine invocation (spawn to exit), measured around
``subprocess.run`` only.  ``cleanup`` is output removal between invocations, measured
separately.  ``outer`` is the wall time of the whole loop and is reported for cross-check;
it includes digesting, so it is never used as a performance number.

Firebuild note: ``-s`` prints statistics on the *firebuild* process's stdout, so its trailer
is stripped before the child's stdout is digested; the strip boundary is asserted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "realworld_v2"))

import runner  # noqa: E402

FIREBUILD_STATS = b"\nStatistics of current run:"
FB_HITS = re.compile(r"Hits:\s+(\d+) / (\d+)")
FB_MISSES = re.compile(r"Misses:\s+(\d+)")
FB_UNCACHEABLE = re.compile(r"Uncacheable:\s+(\d+)")
TRACEJIT_REPORT = b"\nTraceJIT\n"


# ------------------------------------------------------------------------------- workloads


def blob(size: int, seed: int = 0x2545F4914F6CDD1D) -> bytes:
    state = seed & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while len(out) < size:
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        out.extend(state.to_bytes(8, "little"))
    return bytes(out[:size])


def text_lines(count: int) -> bytes:
    return b"".join(
        f"row-{i:07d} key={(i * 7919) % 100003} tag=t{i % 11}\n".encode() for i in range(1, count + 1)
    )


@dataclass
class Workload:
    id: str
    note: str
    argv: list[str]
    input_bytes: bytes
    outputs: tuple[str, ...] = ()
    sizes: tuple[int, ...] = (2, 3, 10, 25, 100)
    mutate_every: int = 0          # rewrite the input before every Nth invocation (0 = never)
    input_name: str = "input.bin"


def workloads() -> dict[str, Workload]:
    small_blob = blob(1 << 20)
    text = text_lines(40_000)          # ~1.2 MiB, compressible
    lines = text_lines(200_000)        # ~7 MB
    return {
        "gzip-file": Workload(
            "gzip-file", "gzip -9 -n -k -f of a 1 MiB incompressible blob",
            ["gzip", "-9", "-n", "-k", "-f", "input.bin"], small_blob, ("input.bin.gz",),
        ),
        "bzip2-file": Workload(
            "bzip2-file", "bzip2 -9 -k -f of a 1 MiB incompressible blob",
            ["bzip2", "-9", "-k", "-f", "input.bin"], small_blob, ("input.bin.bz2",),
            sizes=(2, 3, 10, 25),
        ),
        "gzip-stdout": Workload(
            "gzip-stdout", "gzip -9 -n -c of 1.2 MiB text to stdout",
            ["gzip", "-9", "-n", "-c", "input.bin"], text,
        ),
        "sed-lines": Workload(
            "sed-lines", "sed substitution over 200k lines to stdout",
            ["sed", "s/key=/k=/g", "input.bin"], lines,
        ),
        "sha256sum": Workload(
            "sha256sum", "sha256sum of a 1 MiB blob",
            ["sha256sum", "input.bin"], small_blob,
        ),
        "gzip-mutating": Workload(
            "gzip-mutating", "gzip -9 -n -c where the input is rewritten before every 3rd invocation",
            ["gzip", "-9", "-n", "-c", "input.bin"], text,
            sizes=(10, 25), mutate_every=3,
        ),
    }


# ------------------------------------------------------------------------------- engines


@dataclass
class Arm:
    id: str
    kind: str                       # native | tracejit | firebuild
    binary: Path | None = None
    label: str = ""
    firebuild_version: str = ""
    conf: Path | None = None
    tuned: bool = False
    strict_clock: bool = False
    policy: str = "native"

    def describe(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "binary": str(self.binary) if self.binary else None,
            "binary_sha256": sha256_file(self.binary) if self.binary and self.binary.is_file() else None,
            "firebuild_version": self.firebuild_version,
            "config": str(self.conf) if self.conf else None,
            "tuned": self.tuned,
            "strict_clock": self.strict_clock,
            "policy": self.policy,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


class Engine:
    """One invocation, with the engine's own decision and the verified bytes."""

    def __init__(self, arm: Arm, root: Path, base_env: dict):
        self.arm = arm
        self.root = root
        self.base_env = base_env
        self.cache = root / "cache"
        self.home = root / "home"

    def env(self, ws: Path) -> dict:
        if self.arm.kind == "native":
            return dict(self.base_env)
        if self.arm.kind == "tracejit":
            return runner.cache_env(dict(self.base_env), self.cache)
        env = dict(self.base_env)
        env["HOME"] = str(self.home)
        env.pop("XDG_CACHE_HOME", None)
        libdir = getattr(self.arm, "libdir", "") or ""
        if libdir:
            env["LD_LIBRARY_PATH"] = libdir + (
                ":" + self.base_env["LD_LIBRARY_PATH"] if self.base_env.get("LD_LIBRARY_PATH") else ""
            )
        return env

    def storage(self) -> Path:
        return self.home / ".cache" / "firebuild" if self.arm.kind == "firebuild" else self.cache

    def reset(self) -> None:
        if self.arm.kind == "firebuild":
            shutil.rmtree(self.home, ignore_errors=True)
            self.home.mkdir(parents=True, exist_ok=True)
        else:
            shutil.rmtree(self.cache, ignore_errors=True)

    def run(self, ws: Path, argv: list[str]) -> dict:
        env = self.env(ws)
        if self.arm.kind == "native":
            completed = subprocess.run(argv, cwd=ws, env=env, capture_output=True, check=False)
            return {
                "decision": "executed", "hits": 0, "misses": 0, "uncacheable": 0,
                "exit": completed.returncode, "stdout": completed.stdout,
                "stderr": completed.stderr, "decision_source": "none",
            }
        if self.arm.kind == "tracejit":
            completed, decision = runner.run_plain(self.arm.binary, argv, ws, env, self.arm.policy)
            if runner.hit_accounting_disagrees(decision):
                raise SystemExit(
                    f"TraceJIT reported kind=Reused without a reuse decision for {self.arm.id}"
                )
            hit = runner.is_hit(decision)
            cache_decision = (decision or {}).get("cache_decision")
            decision_name = "hit" if hit else (
                "refused" if cache_decision in ("MISS", "Ineligible", "Skipped", "Deoptimized")
                else "executed"
            )
            marker = completed.stderr.rfind(TRACEJIT_REPORT)
            child_stderr = completed.stderr[:marker] if marker >= 0 else completed.stderr
            return {
                "decision": decision_name,
                "decision_detail": cache_decision,
                "hits": 1 if hit else 0,
                "misses": 0 if hit else 1,
                "uncacheable": 1 if decision_name == "refused" else 0,
                "exit": completed.returncode,
                "stdout": completed.stdout,
                "stderr": child_stderr,
                "decision_source": "tracejit-report",
                "reason": (decision or {}).get("reason"),
                "restored": hit,
            }
        # Firebuild: -s writes its statistics to the firebuild process's stdout, after the
        # child's output.  Strip that trailer so the child's bytes can be verified.
        command = [str(self.arm.binary), "-c", str(self.arm.conf)]
        if self.arm.tuned:
            command += ["-o", "processes.skip_cache=[]"]
        command += ["-s", "--", *argv]
        completed = subprocess.run(command, cwd=ws, env=env, capture_output=True, check=False)
        stdout = completed.stdout
        stats = ""
        marker = stdout.rfind(FIREBUILD_STATS)
        if marker >= 0:
            stats = stdout[marker:].decode(errors="replace")
            stdout = stdout[:marker]
        hits = FB_HITS.search(stats)
        misses = FB_MISSES.search(stats)
        uncacheable = FB_UNCACHEABLE.search(stats)
        hit_count = int(hits.group(1)) if hits else 0
        return {
            "decision": "hit" if hit_count else (
                "refused" if uncacheable and int(uncacheable.group(1)) else "executed"
            ),
            "decision_detail": stats.splitlines()[2].strip() if stats else None,
            "stats_parsed": bool(hits),
            "hits": hit_count,
            "misses": int(misses.group(1)) if misses else 0,
            "uncacheable": int(uncacheable.group(1)) if uncacheable else 0,
            "exit": completed.returncode,
            "stdout": stdout,
            "stderr": completed.stderr,
            "decision_source": "firebuild-stats",
            "restored": bool(hit_count),
        }


# ------------------------------------------------------------------------------- oracle


class Oracle:
    """Independent native expectation for each input variant, computed once."""

    def __init__(self, workload: Workload, root: Path, base_env: dict):
        self.workload = workload
        self.root = root
        self.base_env = base_env
        self.cache: dict[str, dict] = {}

    def variant_bytes(self, index: int) -> bytes:
        if not self.workload.mutate_every:
            return self.workload.input_bytes
        variant = int(index // self.workload.mutate_every)
        if variant == 0:
            return self.workload.input_bytes
        # Deterministically different, same size class, so no cache key can collide.
        return b"VARIANT %03d\n" % variant + self.workload.input_bytes

    def expectation(self, variant: int) -> dict:
        key = f"v{variant}"
        if key in self.cache:
            return self.cache[key]
        ws = self.root / key
        shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True)
        (ws / self.workload.input_name).write_bytes(self.variant_bytes(variant * self.workload.mutate_every))
        completed = subprocess.run(
            self.workload.argv, cwd=ws, env=dict(self.base_env), capture_output=True, check=False
        )
        expectation = {
            "exit": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "outputs_sha256": {
                name: sha256_file(ws / name) if (ws / name).is_file() else None
                for name in self.workload.outputs
            },
        }
        self.cache[key] = expectation
        return expectation


# ------------------------------------------------------------------------------- sessions


def prepare_workspace(ws: Path, workload: Workload, payload: bytes) -> None:
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    (ws / workload.input_name).write_bytes(payload)


def cleanup(ws: Path, workload: Workload) -> None:
    for name in workload.outputs:
        target = ws / name
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)


def run_session(
    engine: Engine,
    workload: Workload,
    oracle: Oracle,
    root: Path,
    mode: str,
    size: int,
    base_env: dict,
) -> dict:
    ws = root / "ws"
    engine.reset()
    prepare_workspace(ws, workload, workload.input_bytes)

    records: list[dict] = []
    command_ns = 0
    cleanup_ns = 0
    outer_started = time.perf_counter_ns()

    # Steady state: populate outside the timer.  Two invocations are enough for every engine
    # here to reach its warm path; the population itself is recorded but never reported.
    population = []
    if mode == "steady":
        for index in range(2):
            cleanup(ws, workload)
            started = time.perf_counter_ns()
            result = engine.run(ws, workload.argv)
            population.append({"index": index, "wall_ns": time.perf_counter_ns() - started,
                               "decision": result["decision"]})

    variant = 0
    for index in range(size):
        # A mutation persists until the next scheduled one: the expected output for this
        # invocation is the oracle of the input that is actually on disk.
        if workload.mutate_every and index and index % workload.mutate_every == 0:
            variant = index // workload.mutate_every
            (ws / workload.input_name).write_bytes(oracle.variant_bytes(index))
        cleanup_started = time.perf_counter_ns()
        cleanup(ws, workload)
        cleanup_ns += time.perf_counter_ns() - cleanup_started

        started = time.perf_counter_ns()
        result = engine.run(ws, workload.argv)
        wall = time.perf_counter_ns() - started
        command_ns += wall

        expectation = oracle.expectation(variant)
        observed = {
            "exit": result["exit"],
            "stdout_sha256": sha256_bytes(result["stdout"]),
            "outputs_sha256": {
                name: sha256_file(ws / name) if (ws / name).is_file() else None
                for name in workload.outputs
            },
        }
        correct = (
            observed["exit"] == expectation["exit"]
            and observed["stdout_sha256"] == expectation["stdout_sha256"]
            and observed["outputs_sha256"] == expectation["outputs_sha256"]
        )
        records.append({
            "index": index,
            "wall_ns": wall,
            "decision": result["decision"],
            "decision_detail": result.get("decision_detail"),
            "decision_source": result["decision_source"],
            "stats_parsed": result.get("stats_parsed"),
            "hits": result["hits"],
            "misses": result["misses"],
            "uncacheable": result["uncacheable"],
            "restored": result.get("restored"),
            "exit": result["exit"],
            "variant": variant,
            "correct": correct,
            "stdout_sha256": observed["stdout_sha256"],
            "expected_stdout_sha256": expectation["stdout_sha256"],
            "outputs_sha256": observed["outputs_sha256"],
            "cache_bytes": tree_bytes(engine.storage()),
            "error": None if correct else result["stderr"].decode(errors="replace")[-800:],
        })

    outer_ns = time.perf_counter_ns() - outer_started
    hits = sum(1 for record in records if record["decision"] == "hit")
    return {
        "arm": engine.arm.id,
        "workload": workload.id,
        "mode": mode,
        "size": size,
        "policy": engine.arm.policy,
        "population": population,
        "invocations": records,
        "session": {
            "command_ns": command_ns,
            "cleanup_ns": cleanup_ns,
            "outer_ns": outer_ns,
            "hits": hits,
            "executed": sum(1 for r in records if r["decision"] == "executed"),
            "refused": sum(1 for r in records if r["decision"] == "refused"),
        },
        "all_correct": all(record["correct"] for record in records),
        "cache_bytes_final": tree_bytes(engine.storage()),
        "input_bytes": len(workload.input_bytes),
        "note": workload.note,
    }


# ------------------------------------------------------------------------------- accounting


def check_row(row: dict) -> list[str]:
    """Invariants a published row must satisfy.  Used by the tests and before writing JSON."""

    problems = []
    invocations = row.get("invocations") or []
    if len(invocations) != row.get("size"):
        problems.append(f"{row.get('arm')}/{row.get('workload')}/{row.get('mode')}: "
                        f"{len(invocations)} invocations for size {row.get('size')}")
    for record in invocations:
        if record["decision"] == "hit" and record.get("decision_source") == "none":
            problems.append(f"{row['arm']}/{row['workload']}: hit without an engine decision")
        if record["decision"] == "hit" and record.get("restored") is not True:
            problems.append(f"{row['arm']}/{row['workload']}: hit without restoration evidence")
        if "correct" not in record:
            problems.append(f"{row['arm']}/{row['workload']}: invocation without output verification")
        if record.get("decision_source") == "firebuild-stats" and not record.get("stats_parsed"):
            problems.append(f"{row['arm']}/{row['workload']}: Firebuild stats missing at "
                            f"{record['index']}")
        if record.get("correct") is False:
            problems.append(f"{row['arm']}/{row['workload']}: incorrect output at {record['index']}")
    if row.get("mode") == "cold" and invocations and invocations[0]["decision"] == "hit":
        problems.append(f"{row['arm']}/{row['workload']}: cold session began with a hit")
    if row.get("all_correct") is False:
        problems.append(f"{row['arm']}/{row['workload']}: row contains a correctness failure")
    return problems


def break_even(cold_ns: int, hit_ns: int, direct_ns: int) -> dict:
    """Integer invocations at which a cold-then-hit session first repays direct execution.

    total(n) = cold + (n-1) * hit, compared with n * direct.  Solving for the smallest
    integer n >= 2 gives ceil((cold - hit) / (direct - hit)); the previous floor-plus-one
    overcounted when the ratio was an exact integer.
    """

    saving = direct_ns - hit_ns
    if saving <= 0:
        return {"integer_invocations": None, "fractional": None,
                "reason": "a hit is not cheaper than direct execution"}
    fractional = (cold_ns - hit_ns) / saving
    return {
        "integer_invocations": max(2, -(-int(cold_ns - hit_ns) // int(saving))),
        "fractional": fractional,
        "reason": None,
    }


def median(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0


# ------------------------------------------------------------------------------- driver


def arm_from_spec(spec: str, tracejit: Path) -> Arm:
    """Accepts ``native``, ``tj-native``, ``tj-ae`` or ``id:policy`` for TraceJIT arms."""

    if spec == "native":
        return Arm("native", "native")
    if spec in ("tj", "tj-native"):
        return Arm("tj-native", "tracejit", tracejit, policy="native")
    if spec == "tj-ae":
        return Arm("tj-ae", "tracejit", tracejit, policy="allocator-entropy-v1")
    identifier, _, policy = spec.partition(":")
    if not policy:
        raise SystemExit(f"unknown arm {spec}")
    return Arm(identifier, "tracejit", tracejit, policy=policy)


def firebuild_arm(identifier: str, binary: Path, version: str, conf: Path, tuned: bool,
                  strict_clock: bool, libdir: str) -> Arm:
    arm = Arm(identifier, "firebuild", binary, firebuild_version=version, conf=conf,
              tuned=tuned, strict_clock=strict_clock)
    arm.libdir = libdir  # consumed by Engine.env
    return arm


def merge_rows(path: Path, rows: list[dict], setup: dict) -> None:
    existing = {"setup": {}, "rows": []}
    if path.is_file():
        existing = json.loads(path.read_text())
    def key(row):
        return (row["arm"], row["workload"], row["mode"], row["size"], row.get("repeat", 0))

    keep = {key(row) for row in rows}
    merged = [row for row in existing.get("rows", []) if key(row) not in keep]
    merged.extend(rows)
    existing["rows"] = sorted(merged, key=key)
    existing.setdefault("setup", {}).update(setup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseae-matrix")
    parser.add_argument("--output", type=Path, default=REPO / "benchmarks/results/phaseae/matrix.json")
    parser.add_argument("--arms", default="native,tj-ae")
    parser.add_argument("--workloads", default="gzip-file,gzip-stdout")
    parser.add_argument("--sizes", default="2,3,10")
    parser.add_argument("--modes", default="cold,steady")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--firebuild-conf", type=Path, default=None)
    parser.add_argument("--firebuild-binary", type=Path, default=None)
    parser.add_argument("--firebuild-version", default="")
    parser.add_argument("--firebuild-libdir", default="")
    parser.add_argument("--firebuild-label", default="fb", help="prefix for Firebuild arm ids")
    parser.add_argument("--tuned", action="store_true")
    parser.add_argument("--strict-clock", action="store_true")
    parser.add_argument("--list-workloads", action="store_true")
    args = parser.parse_args(argv)

    catalog = workloads()
    if args.list_workloads:
        for workload in catalog.values():
            print(f"{workload.id:14s} sizes={workload.sizes} mutate={workload.mutate_every} {workload.note}")
        return 0

    arms: list[Arm] = []
    for spec in [item for item in args.arms.split(",") if item]:
        arms.append(arm_from_spec(spec, args.tracejit.resolve()))
    if args.firebuild_binary:
        conf = args.firebuild_conf or (args.firebuild_binary.parent.parent / "etc" / "firebuild.conf")
        label = args.firebuild_label
        arms.append(firebuild_arm(f"{label}-default", args.firebuild_binary, args.firebuild_version,
                                  conf, False, False, args.firebuild_libdir))
        if args.tuned:
            arms.append(firebuild_arm(f"{label}-tuned", args.firebuild_binary, args.firebuild_version,
                                      conf, True, False, args.firebuild_libdir))
        if args.strict_clock:
            strict = Path(args.firebuild_conf or conf)
            strict_text = strict.read_text()
            stripped = strict_text.replace('  "ignore-time-queries",\n', "")
            if stripped == strict_text:
                raise SystemExit("could not remove ignore-time-queries from the config")
            strict_path = strict.with_name(strict.stem + "-strict.conf")
            strict_path.write_text(stripped)
            arms.append(firebuild_arm(f"{label}-strict", args.firebuild_binary, args.firebuild_version,
                                      strict_path, False, False, args.firebuild_libdir))

    base_env = dict(os.environ)
    base_env.pop("TRACEJIT_CACHE_DIR", None)
    base_env.pop("TRACEJIT_PHASE_TIMING", None)
    base_env.pop("TRACEJIT_PHASE_TIMING_PATH", None)
    shutil.rmtree(args.scratch, ignore_errors=True)

    rows: list[dict] = []
    failures: list[str] = []
    setup = {
        "generated_unix_ms": int(time.time() * 1000),
        "host": {
            "kernel": os.uname().release,
            "machine": os.uname().machine,
            "filesystem": "ext4",
            "cpus": os.cpu_count(),
        },
        "arms": [],
    }
    for arm in arms:
        described = arm.describe()
        if arm.kind == "firebuild":
            described["library_path"] = getattr(arm, "libdir", "") or ""
        setup["arms"].append(described)

    import random

    rng = random.Random(args.seed)
    for workload_id in [item for item in args.workloads.split(",") if item]:
        workload = catalog[workload_id]
        sizes = [int(item) for item in args.sizes.split(",") if item]
        oracle = Oracle(workload, args.scratch / f"oracle-{workload_id}", base_env)
        for repeat in range(args.repeats):
            # Randomized paired trials: the same engine set runs in a different order each
            # repeat, so a drift in host load cannot favour one arm consistently.
            order = list(arms)
            rng.shuffle(order)
            for arm in order:
                engine = Engine(arm, args.scratch / f"{workload_id}-{arm.id}", base_env)
                for mode in [item for item in args.modes.split(",") if item]:
                    for size in sizes:
                        row = run_session(engine, workload, oracle, engine.root, mode, size, base_env)
                        row["repeat"] = repeat
                        problems = check_row(row)
                        failures.extend(problems)
                        rows.append(row)
                        print(
                            f"{workload_id:13s} {arm.id:12s} {mode:6s} n={size:3d} r={repeat} "
                            f"cmd={row['session']['command_ns']/1e6:8.1f}ms "
                            f"hits={row['session']['hits']:3d} refused={row['session']['refused']:3d} "
                            f"correct={row['all_correct']} cache={row['cache_bytes_final']/1e6:7.2f}MB",
                            flush=True,
                        )
    merge_rows(args.output, rows, setup)
    shutil.rmtree(args.scratch, ignore_errors=True)
    print(f"wrote {len(rows)} rows to {args.output}")
    if failures:
        print("ACCOUNTING FAILURES:", *failures[:10], sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

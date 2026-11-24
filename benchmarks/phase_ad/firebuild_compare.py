#!/usr/bin/env python3
"""Phase AD: same-host comparison of native, TraceJIT and Firebuild.

Four arms over the same pre-state and the same command line:

    native      direct execution
    tracejit    ``tracejit run`` (native policy, no contract)
    tracejit-ae ``tracejit run --contract allocator-entropy-v1``
    firebuild   ``firebuild -- <command>`` (pinned 0.8.2 from the Ubuntu debs)

The point is not to win.  It is to answer, with numbers from one machine, whether
TraceJIT's non-compiler niche survives contact with the closest competing system,
and to record where each system's *contract* differs.

Metrics per arm: cold invocation, warm invocation (median of several, outputs
deleted before each), repeated-invocation sessions, cache storage, and an
independent correctness check (stdout bytes plus output-file digests against the
native run).

Firebuild is invoked with an explicit config file and cache directory because it
was installed into a user prefix (no root).  Its own ``-s`` statistics are read in
a separate, untimed run so the timed numbers do not include statistics
formatting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIREBUILD_HITS = re.compile(r"Hits:\s+(\d+) / (\d+)")
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "realworld_v2"))

import oracle  # noqa: E402
import runner  # noqa: E402

FB_PREFIX = Path("/tmp/fb/prefix")
FB_BIN = FB_PREFIX / "usr/bin/firebuild"
FB_CONF = FB_PREFIX / "etc/firebuild.conf"
FB_LIB = FB_PREFIX / "usr/lib/x86_64-linux-gnu"


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
    return b"".join(f"row-{i:07d} key={(i * 7919) % 100003} tag=t{i % 11}\n".encode() for i in range(1, count + 1))


class Workload:
    def __init__(self, identifier, note, argv, inputs, outputs, max_session):
        self.id = identifier
        self.note = note
        self.argv = argv            # callable(ws) -> list[str]
        self.inputs = inputs        # callable(ws) -> None
        self.outputs = outputs      # tuple[str, ...]
        self.max_session = max_session


def workloads() -> list[Workload]:
    shared_text = text_lines(4000)
    shared_blob = blob(2 << 20)
    big_lines = text_lines(200_000)
    return [
        Workload(
            "bzip2-9-2MiB", "bzip2 -9 -k -f of a 2 MiB incompressible blob",
            lambda ws: ["bzip2", "-9", "-k", "-f", "blob.bin"],
            lambda ws: (ws / "blob.bin").write_bytes(shared_blob),
            ("blob.bin.bz2",), 25,
        ),
        Workload(
            "gzip-9-2MiB", "gzip -9 -n -k -f of a 2 MiB incompressible blob",
            lambda ws: ["gzip", "-9", "-n", "-k", "-f", "blob.bin"],
            lambda ws: (ws / "blob.bin").write_bytes(shared_blob),
            ("blob.bin.gz",), 25,
        ),
        Workload(
            "gzip-n-c-text", "gzip -9 -n -c of 256 KiB text to stdout",
            lambda ws: ["gzip", "-9", "-n", "-c", "corpus.txt"],
            lambda ws: (ws / "corpus.txt").write_bytes(shared_text),
            (), 100,
        ),
        Workload(
            "sed-200k", "sed substitution over 200k lines to stdout",
            lambda ws: ["sed", "s/key=/k=/g", "lines.txt"],
            lambda ws: (ws / "lines.txt").write_bytes(big_lines),
            (), 100,
        ),
    ]


def fresh_workspace(root: Path, workload: Workload) -> Path:
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    workload.inputs(root)
    return root


def clean(ws: Path, workload: Workload) -> None:
    for name in workload.outputs:
        target = ws / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def observation(ws: Path, workload: Workload, exit_status: int, stdout: bytes, stderr: bytes) -> dict:
    tree = oracle.observe_workspace(ws)
    return {
        "exit": exit_status,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "outputs": {name: digest(ws / name) for name in workload.outputs},
        "tree_digest": tree["tree_digest"],
    }


def run_native(ws: Path, workload: Workload, env: dict) -> tuple[int, bytes, bytes]:
    completed = subprocess.run(workload.argv(ws), cwd=ws, env=env, capture_output=True, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def strip_tracejit_report(stderr: bytes) -> bytes:
    """Removes TraceJIT's own report block from plain-mode stderr.

    Plain mode writes its report after the child's stderr, so the child's bytes are everything
    before the last banner.  The report is the only way to read the decision without ``--json``,
    whose byte-array encoding of a multi-megabyte stdout would be measured as product cost.
    """

    marker = stderr.rfind(b"\nTraceJIT\n")
    return stderr[:marker] if marker >= 0 else stderr


def firebuild_env(base: dict, home: Path) -> dict:
    env = dict(base)
    env["LD_LIBRARY_PATH"] = str(FB_LIB) + (":" + base["LD_LIBRARY_PATH"] if base.get("LD_LIBRARY_PATH") else "")
    # Firebuild's cache lives at $HOME/.cache/firebuild.  A per-arm HOME gives each arm an
    # isolated cache without relying on an undocumented config key, and keeps the
    # fingerprint's environment identical within an arm.
    env["HOME"] = str(home)
    env.pop("XDG_CACHE_HOME", None)
    return env


def run_firebuild(
    ws: Path, workload: Workload, env: dict, stats: bool = False, tuned: bool = False
) -> tuple[int, bytes, bytes, str]:
    argv = [str(FB_BIN), "-c", str(FB_CONF)]
    if tuned:
        # Firebuild's shipped default ``skip_cache`` list names cp, sed, head, tail, grep, tr,
        # cut, dd, ... -- utilities it declines to cache because they are "fast enough".  The
        # tuned arm clears that list so the comparison also measures what the engine can do when
        # a user asks for those commands, not only its default policy.
        argv += ["-o", "processes.skip_cache=[]"]
    if stats:
        argv.append("-s")
    argv += ["--", *workload.argv(ws)]
    completed = subprocess.run(argv, cwd=ws, env=env, capture_output=True, check=False)
    # Firebuild 0.8.2 prints its statistics on **stdout**, so a timed run must not
    # request them; they would corrupt a filter's stdout.  The evidence run reads
    # them from stdout and its child stdout is discarded.
    return completed.returncode, completed.stdout, completed.stderr, completed.stdout.decode(errors="replace")


def tracejit_env(base: dict, cache: Path) -> dict:
    return runner.cache_env(dict(base), cache)


def measure_arm(
    arm: str,
    workload: Workload,
    root: Path,
    tracejit: Path,
    base_env: dict,
    reps: int,
    sessions: list[int],
    native_obs: dict,
) -> dict:
    ws = fresh_workspace(root / "ws", workload)
    cache = root / "cache"
    shutil.rmtree(cache, ignore_errors=True)
    policy = "allocator-entropy-v1" if arm == "tracejit-ae" else "native"

    if arm == "native":
        env = dict(base_env)
        run = lambda: run_native(ws, workload, env)
        hit_check = None
        warm_run = None
    elif arm.startswith("firebuild"):
        tuned = arm == "firebuild-tuned"
        home = root / "home"
        home.mkdir(parents=True, exist_ok=True)
        env = firebuild_env(base_env, home)
        run = lambda: run_firebuild(ws, workload, env, tuned=tuned)[:3]
        hit_check = lambda: run_firebuild(ws, workload, env, stats=True, tuned=tuned)[3]
    else:
        env = tracejit_env(base_env, cache)
        def run():
            completed, _ = runner.run_plain(tracejit, workload.argv(ws), ws, env, policy)
            return (
                completed.returncode,
                completed.stdout,
                strip_tracejit_report(completed.stderr),
            )
        hit_check = None

    clean(ws, workload)
    started = time.perf_counter_ns()
    cold = run()
    cold_ns = time.perf_counter_ns() - started
    cold_obs = observation(ws, workload, *cold)

    samples = []
    for _ in range(reps):
        clean(ws, workload)
        started = time.perf_counter_ns()
        run()
        samples.append(time.perf_counter_ns() - started)
    warm_ns = int(statistics.median(samples))

    # Whether the warm path actually reused, measured once per arm.
    stats_text = ""
    if arm.startswith("firebuild"):
        clean(ws, workload)
        stats_text = hit_check() or ""
        hits = FIREBUILD_HITS.search(stats_text)
        warm_reused = bool(hits) and int(hits.group(1)) > 0
        hits_line = next((line.strip() for line in stats_text.splitlines() if "Hits:" in line), "")
    elif arm in ("tracejit", "tracejit-ae"):
        clean(ws, workload)
        _, decision = runner.run_plain(tracejit, workload.argv(ws), ws, env, policy)
        warm_reused = runner.is_hit(decision)
        hits_line = f"kind={((decision or {}).get('kind'))} cache={((decision or {}).get('cache_decision'))}"
    else:
        warm_reused = False
        hits_line = "direct execution"

    # Correctness: warm result against the cold native observation.
    clean(ws, workload)
    warm = run()
    warm_obs = observation(ws, workload, *warm)
    correct = warm_obs == native_obs

    measured_sessions = []
    for count in [n for n in sessions if n <= workload.max_session]:
        clean(ws, workload)
        started = time.perf_counter_ns()
        for index in range(count):
            if index:
                clean(ws, workload)
            run()
        total = time.perf_counter_ns() - started
        measured_sessions.append({"invocations": count, "total_ns": total})

    native_reference = None
    if arm != "native":
        # Same session length on the native arm, measured in this process for a fair ratio.
        clean(ws, workload)
        started = time.perf_counter_ns()
        for index in range(min(workload.max_session, max(sessions))):
            if index:
                clean(ws, workload)
            run_native(ws, workload, dict(base_env))
        native_reference = time.perf_counter_ns() - started

    return {
        "arm": arm,
        "workload": workload.id,
        "note": workload.note,
        "policy": policy if arm.startswith("tracejit") else arm,
        "cold_ns": cold_ns,
        "warm_ns": warm_ns,
        "warm_samples_ns": samples,
        "warm_reused": warm_reused,
        "reuse_evidence": hits_line,
        "observation_matches_native": correct,
        "observation": warm_obs,
        "sessions": measured_sessions,
        "native_session_ns": native_reference,
        "cache_bytes": sum(
            p.stat().st_size
            for p in ((root / "home") if arm == "firebuild" else cache).rglob("*")
            if p.is_file()
        ) if ((root / "home").exists() or cache.exists()) else 0,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=HERE.parents[1] / ".phasead-scratch")
    parser.add_argument("--output", type=Path, default=HERE.parent / "results/phasead/firebuild_compare.json")
    parser.add_argument("--arms", default="native,tracejit,tracejit-ae,firebuild")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--sessions", default="3,10,25,100")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)

    if not FB_BIN.is_file():
        raise SystemExit(f"firebuild is not installed at {FB_BIN}")
    arms = [item.strip() for item in args.arms.split(",") if item.strip()]
    sessions = [int(item) for item in args.sessions.split(",")]
    only = {item.strip() for item in args.only.split(",") if item.strip()} or None
    base_env = dict(os.environ)
    base_env.pop("TRACEJIT_CACHE_DIR", None)
    shutil.rmtree(args.scratch, ignore_errors=True)

    version_env = dict(base_env)
    version_env["LD_LIBRARY_PATH"] = str(FB_LIB)
    payload = {"setup": {
        "firebuild_version": subprocess.run([str(FB_BIN), "-c", str(FB_CONF), "--version"], capture_output=True, text=True, env=version_env).stdout.splitlines()[0],
        "firebuild_binary_sha256": hashlib.sha256(FB_BIN.read_bytes()).hexdigest(),
        "host_kernel": os.uname().release,
        "tracejit_sha256": hashlib.sha256(Path(args.tracejit).read_bytes()).hexdigest(),
    }, "rows": []}

    try:
      for workload in workloads():
        if only and workload.id not in only:
            continue
        reference = fresh_workspace(args.scratch / f"{workload.id}-reference", workload)
        reference_result = run_native(reference, workload, dict(base_env))
        native_obs = observation(reference, workload, *reference_result)
        payload.setdefault("native_observations", {})[workload.id] = native_obs
        for arm in arms:
            row = measure_arm(arm, workload, args.scratch / f"{workload.id}-{arm}", args.tracejit, base_env, args.reps, sessions, native_obs)
            payload["rows"].append(row)
            s = {item["invocations"]: item["total_ns"] for item in row["sessions"]}
            print(f"{workload.id:14s} {arm:12s} cold={row['cold_ns']/1e6:8.1f}ms warm={row['warm_ns']/1e6:8.1f}ms "
                  f"reused={row['warm_reused']} correct={row['observation_matches_native']} "
                  f"cache={row['cache_bytes']/1e6:.2f}MB "
                  f"sessions={ {k: round(v/1e6) for k,v in s.items()} }")

    finally:
        shutil.rmtree(args.scratch, ignore_errors=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

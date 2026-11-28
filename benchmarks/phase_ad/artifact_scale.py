#!/usr/bin/env python3
"""Phase AD: authentic artifact workloads across scale.

Phase AC measured 2 MiB synthetic blobs.  This harness asks whether the non-compiler
advantage survives authentic inputs at 1, 10 and 100 MiB, where input hashing, output
materialisation and cache storage all grow with the artifact.

Inputs are derived deterministically from one pinned, independently acquired release
archive (Linux 6.6.50 from cdn.kernel.org, whose sha256 the project pins below):

* ``text-<size>.bin``  -- the first ``size`` bytes of the uncompressed kernel release
  tarball, which is dominated by C sources and documentation: a realistic,
  highly compressible software artifact.
* ``xz-<size>.bin``    -- the first ``size`` bytes of the release's ``.tar.xz``:
  authentic, effectively incompressible data.

Only the first 100 MiB of the archive is used, so the whole study needs one 130 MiB
download and about 1.2 GiB of scratch space outside the repository.

For every (artifact, size, workload, arm) it records cold cost, warm cost, repeated
sessions, cache footprint, peak RSS and the *integer* number of invocations at which the
cache first repays its tracing cost.  The integer break-even is the quantity a user can
act on; a fractional ``C/(D-H)`` ratio is not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "realworld_v2"))

import firebuild_compare as fbc  # noqa: E402
import runner  # noqa: E402

KERNEL_URL = "https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.50.tar.xz"
SIZES = {"1MiB": 1 << 20, "10MiB": 10 << 20, "100MiB": 100 << 20}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire(archive: Path) -> dict:
    """Downloads the pinned release once and derives the sized inputs."""

    artifact_dir = archive.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not archive.is_file() or archive.stat().st_size < 100 << 20:
        subprocess.run(["curl", "-fsSL", "-o", str(archive), KERNEL_URL], check=True)
    archive_digest = sha256_file(archive)

    # The uncompressed tar stream is the compressible artifact.  Streaming it through xz
    # avoids a 1.3 GiB file: only the first 100 MiB are kept.
    plain = artifact_dir / "text-100MiB.bin"
    if not plain.is_file() or plain.stat().st_size < 100 << 20:
        with plain.open("wb") as out:
            decompressor = subprocess.Popen(["xz", "-dc", str(archive)], stdout=subprocess.PIPE)
            remaining = 100 << 20
            while remaining:
                chunk = decompressor.stdout.read(min(1 << 20, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
            decompressor.kill()

    inputs = {}
    for label, size in SIZES.items():
        text = artifact_dir / f"text-{label}.bin"
        if not text.is_file() or text.stat().st_size != size:
            text.write_bytes(plain.read_bytes()[:size])
        incompressible = artifact_dir / f"xz-{label}.bin"
        if not incompressible.is_file() or incompressible.stat().st_size != size:
            with archive.open("rb") as source, incompressible.open("wb") as out:
                out.write(source.read(size))
        inputs[label] = {
            "text": {"path": str(text), "sha256": sha256_file(text), "bytes": size},
            "xz": {"path": str(incompressible), "sha256": sha256_file(incompressible), "bytes": size},
        }
    # The digest of the downloaded release is recorded next to the derived inputs; it is what a
    # rerun on another host must match, rather than a value copied from a web page.
    return {
        "archive": {"url": KERNEL_URL, "path": str(archive), "sha256": archive_digest,
                    "bytes": archive.stat().st_size},
        "inputs": inputs,
    }


def workloads(size_label: str):
    """(identifier, argv, input file, output paths) triples sized for the artifact."""

    rows = [
        ("gzip-stdout", ["gzip", "-9", "-n", "-c", "input.bin"], "text", ()),
        ("gzip-stdout-incompressible", ["gzip", "-9", "-n", "-c", "input.bin"], "xz", ()),
        ("sha256sum", ["sha256sum", "input.bin"], "text", ()),
    ]
    if size_label != "100MiB":
        rows.append(("bzip2-stdout", ["bzip2", "-9", "-c", "input.bin"], "text", ()))
        rows.append(("gzip-file", ["gzip", "-9", "-n", "-k", "-f", "input.bin"], "text", ("input.bin.gz",)))
    return rows


def break_even(direct_ns: int, cold_ns: int, hit_ns: int) -> dict:
    """Integer invocation count at which tracing first beats running directly."""

    saving = direct_ns - hit_ns
    if saving <= 0:
        return {"integer_invocations": None, "fractional": None,
                "reason": "a HIT is not cheaper than direct execution"}
    fractional = (cold_ns - hit_ns) / saving
    return {
        "integer_invocations": max(2, math.floor(fractional) + 1),
        "fractional": fractional,
        "reason": None,
    }


MEASURE = r'''
import resource, subprocess, sys, time
started = time.perf_counter_ns()
subprocess.run(sys.argv[1:], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
      time.perf_counter_ns() - started)
'''


def peak_kib(argv: list[str], cwd: Path, env: dict) -> tuple[int, int]:
    """Peak RSS (KiB) and wall time of one invocation.

    ``/usr/bin/time`` is not installed here, and ``getrusage(RUSAGE_CHILDREN)`` in this process
    would report the maximum over every child it has ever waited for.  A fresh interpreter
    therefore measures and reports the one child it spawns.
    """

    completed = subprocess.run(
        [sys.executable, "-c", MEASURE, *argv], cwd=cwd, env=env, capture_output=True, check=False
    )
    parts = completed.stdout.decode(errors="replace").split()
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1])
    return 0, 0


def measure(arm: str, artifact: dict, size_label: str, workload, sessions, reps, scratch: Path, tracejit: Path, base_env: dict) -> dict:
    identifier, argv, flavour, outputs = workload
    inputs = artifact["inputs"][size_label]
    source = Path(inputs[flavour]["path"])
    size = inputs[flavour]["bytes"]

    root = scratch / f"{size_label}-{identifier}-{arm}"
    ws = root / "ws"
    shutil.rmtree(root, ignore_errors=True)
    ws.mkdir(parents=True)
    shutil.copyfile(source, ws / "input.bin")

    cache = root / "cache"
    policy = "allocator-entropy-v1"
    peak_command = argv
    if arm == "native":
        env = dict(base_env)
        run = lambda: fbc.run_native(ws, _wrapper(argv, outputs), env)
    elif arm.startswith("firebuild"):
        home = root / "home"
        home.mkdir(parents=True)
        env = fbc.firebuild_env(base_env, home)
        tuned = arm == "firebuild-tuned"
        run = lambda: fbc.run_firebuild(ws, _wrapper(argv, outputs), env, tuned=tuned)[:3]
        peak_command = [str(fbc.FB_BIN), "-c", str(fbc.FB_CONF), "--", *argv]
    else:
        env = runner.cache_env(dict(base_env), cache)
        def run():
            completed, _ = runner.run_plain(tracejit, argv, ws, env, policy)
            return completed.returncode, completed.stdout, fbc.strip_tracejit_report(completed.stderr)
        peak_command = [str(tracejit), "run", "--", *argv]

    clean = lambda: [ (ws / name).unlink(missing_ok=True) for name in outputs ]
    clean()
    started = time.perf_counter_ns()
    cold_result = run()
    cold_ns = time.perf_counter_ns() - started
    cold_obs = fbc.observation(ws, _wrapper(argv, outputs), *cold_result)

    samples = []
    for _ in range(reps):
        clean()
        started = time.perf_counter_ns()
        run()
        samples.append(time.perf_counter_ns() - started)
    warm_ns = int(statistics.median(samples))

    clean()
    warm_result = run()
    warm_obs = fbc.observation(ws, _wrapper(argv, outputs), *warm_result)
    if arm.startswith("tracejit"):
        clean()
        _, decision = runner.run_plain(tracejit, argv, ws, env, policy)
        reused = runner.is_hit(decision)
        evidence = f"{decision.get('kind')}/{decision.get('cache_decision')}"
    elif arm.startswith("firebuild"):
        clean()
        stats = fbc.run_firebuild(ws, _wrapper(argv, outputs), env, stats=True)[3]
        match = fbc.FIREBUILD_HITS.search(stats)
        reused = bool(match) and int(match.group(1)) > 0
        evidence = next((line.strip() for line in stats.splitlines() if "Hits:" in line), "")
    else:
        reused, evidence = False, "direct"

    # Peak RSS is measured last: the helper executes the command, and running it before the
    # cold sample would turn the cold measurement into a cache HIT.
    peak = peak_kib(peak_command, ws, env)

    measured_sessions = []
    for count in [n for n in sessions if n <= (3 if size_label == "100MiB" else 25)]:
        clean()
        started = time.perf_counter_ns()
        for index in range(count):
            if index:
                clean()
            run()
        measured_sessions.append({"invocations": count, "total_ns": time.perf_counter_ns() - started})

    return {
        "arm": arm,
        "artifact": size_label,
        "workload": identifier,
        "input_bytes": size,
        "input_sha256": inputs[flavour]["sha256"],
        "cold_ns": cold_ns,
        "warm_ns": warm_ns,
        "warm_samples_ns": samples,
        "warm_reused": reused,
        "reuse_evidence": evidence,
        "observation_matches_native": warm_obs == cold_obs,
        "sessions": measured_sessions,
        "cache_bytes": sum(
            p.stat().st_size
            for p in ((root / "home") if arm.startswith("firebuild") else cache).rglob("*")
            if p.is_file()
        ),
        "peak_rss_kib": peak[0],
        "peak_wall_ns": peak[1],
    }


class _wrapper:
    """Lets the shared observation helper see the workload's argv and outputs."""

    def __init__(self, argv, outputs):
        self._argv = argv
        self.outputs = outputs
        self.id = "artifact"
        self.note = ""

    def argv(self, _ws):
        return list(self._argv)

    def __call__(self, _ws):
        return list(self._argv)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--archive", type=Path, default=Path("/tmp/artifacts/linux-6.6.50.tar.xz"))
    parser.add_argument("--scratch", type=Path, default=runner.REPO / ".phasead-artifacts")
    parser.add_argument("--output", type=Path, default=HERE.parent / "results/phasead/artifact_scale.json")
    parser.add_argument("--arms", default="native,tracejit-ae,firebuild")
    parser.add_argument("--sizes", default="1MiB,10MiB,100MiB")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--sessions", default="3,10,25")
    args = parser.parse_args(argv)

    artifact = acquire(args.archive)
    arms = [item for item in args.arms.split(",") if item]
    sizes = [item for item in args.sizes.split(",") if item]
    sessions = [int(item) for item in args.sessions.split(",")]
    base_env = dict(os.environ)
    base_env.pop("TRACEJIT_CACHE_DIR", None)
    payload = {"artifact": artifact, "rows": []}
    shutil.rmtree(args.scratch, ignore_errors=True)

    try:
        for size_label in sizes:
            for workload in workloads(size_label):
                for arm in arms:
                    row = measure(arm, artifact, size_label, workload, sessions, args.reps,
                                  args.scratch, args.tracejit, base_env)
                    payload["rows"].append(row)
                    print(f"{size_label:7s} {row['workload']:24s} {arm:12s} "
                          f"cold={row['cold_ns']/1e6:9.1f}ms warm={row['warm_ns']/1e6:9.1f}ms "
                          f"reused={row['warm_reused']} correct={row['observation_matches_native']} "
                          f"rss={row['peak_rss_kib']}KiB cache={row['cache_bytes']/1e6:.1f}MB", flush=True)
    finally:
        shutil.rmtree(args.scratch, ignore_errors=True)

    # Integer break-even per (artifact, workload): measured direct vs measured cold/hit.
    table = []
    by_key = {}
    for row in payload["rows"]:
        by_key[(row["artifact"], row["workload"], row["arm"])] = row
    for (size_label, workload, arm), row in by_key.items():
        if arm == "native":
            continue
        direct = by_key.get((size_label, workload, "native"))
        if not direct:
            continue
        table.append({
            "artifact": size_label,
            "workload": workload,
            "arm": arm,
            "direct_ns": direct["warm_ns"],
            "cold_ns": row["cold_ns"],
            "hit_ns": row["warm_ns"],
            "reused": row["warm_reused"],
            "break_even": break_even(direct["warm_ns"], row["cold_ns"], row["warm_ns"]),
        })
    payload["break_even"] = table

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

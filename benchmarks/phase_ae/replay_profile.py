#!/usr/bin/env python3
"""Phase AE: where a large-artifact HIT spends its time, and how close that is to the floor.

TraceJIT already has opt-in phase instrumentation (`TRACEJIT_PHASE_TIMING=1` plus
`TRACEJIT_PHASE_TIMING_PATH`), so this harness reads the product's own disjoint spans
instead of inferring costs from end-to-end totals:

    guard_validation   hashing every recorded input (BLAKE3 over the bytes)
    stdio_replay       loading and verifying cached stdout/stderr objects
    cas_restore        staging, verifying, renaming and syncing output files
    present            writing the cached stdout to the caller's descriptor
    lookup/decode/sqlite  record discovery
    decision_persist   rewriting the record's decision row

It then measures the practical floor for the same host — sequential read, write+fsync,
memory copy and BLAKE3 throughput — so the report can say whether 85 ms for a 100 MiB
text compression hit is close to what verified replay must cost, rather than attributing
the whole hit to "hashing" by assumption.

Peak RSS is defined as the maximum resident set size reported by `getrusage(RUSAGE_CHILDREN)`
in a *fresh* wrapper process that spawns exactly one TraceJIT run, i.e. the maximum over that
run and its descendants, not over the harness.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "realworld_v2"))

import runner  # noqa: E402

CONTRACT = "allocator-entropy-v1"
PHASES = (
    "process_startup_ns", "cli_parse_ns", "identity_prepare_ns", "cache_prepare_ns",
    "sqlite_open_ns", "sqlite_schema_ns", "lookup_key_ns", "sqlite_query_ns",
    "record_decode_ns", "guard_validation_ns", "guard_recheck_ns", "cas_restore_ns",
    "stdio_replay_ns", "decision_persist_ns", "present_ns",
)

MEASURE_RSS = r'''
import resource, subprocess, sys, time
started = time.perf_counter_ns()
subprocess.run(sys.argv[1:], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, time.perf_counter_ns() - started)
'''


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_with_phases(tracejit: Path, argv: list[str], ws: Path, cache: Path, phase_file: Path) -> dict:
    env = runner.cache_env(dict(os.environ), cache)
    env["TRACEJIT_PHASE_TIMING"] = "1"
    env["TRACEJIT_PHASE_TIMING_PATH"] = str(phase_file)
    phase_file.unlink(missing_ok=True)
    started = time.perf_counter_ns()
    completed, decision = runner.run_plain(tracejit, argv, ws, env, CONTRACT)
    wall = time.perf_counter_ns() - started
    phases = json.loads(phase_file.read_text()) if phase_file.is_file() else {}
    return {
        "decision": (decision or {}).get("kind"),
        "wall_ns": wall,
        "exit": completed.returncode,
        "phases": {name: phases.get(name, 0) for name in PHASES},
    }


def peak_rss_kib(tracejit: Path, argv: list[str], ws: Path, cache: Path) -> tuple[int, int]:
    env = runner.cache_env(dict(os.environ), cache)
    completed = subprocess.run(
        [sys.executable, "-c", MEASURE_RSS, str(tracejit), "run", "--contract", CONTRACT, "--", *argv],
        cwd=ws, env=env, capture_output=True, check=False,
    )
    parts = completed.stdout.decode(errors="replace").split()
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1])
    return 0, 0


def workload_measure(artifact: Path, flavor: str, size: int, argv: list[str], outputs: tuple[str, ...],
                     arms: list[str], reps: int, scratch: Path, tracejit: Path,
                     firebuild: Path | None, firebuild_conf: Path | None, libdir: str) -> dict:
    ws = scratch / f"ws-{flavor}-{size}-{'-'.join(argv[:2])}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    shutil.copyfile(artifact, ws / "input.bin")
    cache = scratch / f"cache-{flavor}-{size}-{'-'.join(argv[:2])}"
    shutil.rmtree(cache, ignore_errors=True)
    phase_file = scratch / "phases.json"

    result = {
        "input": {"path": str(artifact), "bytes": size, "sha256": sha256_file(artifact)},
        "argv": argv,
        "outputs": list(outputs),
        "arms": {},
    }
    for arm in arms:
        if arm == "tracejit":
            clean = lambda: [ (ws / name).unlink(missing_ok=True) for name in outputs ]
            clean()
            cold = run_with_phases(tracejit, argv, ws, cache, phase_file)
            clean()
            run_with_phases(tracejit, argv, ws, cache, phase_file)  # warm the record
            hits = []
            for _ in range(reps):
                clean()
                hits.append(run_with_phases(tracejit, argv, ws, cache, phase_file))
            clean()
            rss, rss_wall = peak_rss_kib(tracejit, argv, ws, cache)
            result["arms"][arm] = {
                "cold": cold,
                "hits": hits,
                "median": {name: int(statistics.median(h["phases"][name] for h in hits)) for name in PHASES},
                "median_hit_ns": int(statistics.median(h["wall_ns"] for h in hits)),
                "peak_rss_kib": rss,
                "peak_rss_wall_ns": rss_wall,
            }
        elif arm == "firebuild" and firebuild and firebuild_conf:
            env = dict(os.environ)
            env["HOME"] = str(scratch / f"home-{flavor}-{size}")
            env["LD_LIBRARY_PATH"] = libdir
            shutil.rmtree(env["HOME"], ignore_errors=True)
            Path(env["HOME"]).mkdir(parents=True)
            command = [str(firebuild), "-c", str(firebuild_conf), "--", *argv]
            clean = lambda: [ (ws / name).unlink(missing_ok=True) for name in outputs ]
            clean()
            subprocess.run(command, cwd=ws, env=env, capture_output=True, check=False)
            hits = []
            for _ in range(reps):
                clean()
                started = time.perf_counter_ns()
                completed = subprocess.run(command, cwd=ws, env=env, capture_output=True, check=False)
                hits.append({"wall_ns": time.perf_counter_ns() - started,
                             "stdout_bytes": len(completed.stdout)})
            result["arms"][arm] = {
                "hits": hits,
                "median_hit_ns": int(statistics.median(h["wall_ns"] for h in hits)),
                "peak_rss_kib": None,
            }
    return result


def bounds(scratch: Path, file: Path, rounds: int) -> dict:
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    target = scratch / "out.bin"
    copy_src = scratch / "copy.c"
    copy_bin = scratch / "copy"
    copy_src.write_text(r'''
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdio.h>
int main(int argc, char **argv) {
  size_t size = (size_t)atol(argv[1]);
  char *src = malloc(size), *dst = malloc(size);
  memset(src, 1, size);
  struct timespec a, b;
  clock_gettime(CLOCK_MONOTONIC, &a);
  for (int i = 0; i < 5; i++) memcpy(dst, src, size);
  clock_gettime(CLOCK_MONOTONIC, &b);
  double ns = (b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec);
  printf("%.0f %d\n", ns / 5, dst[0] == 1);
  return 0;
}
''')
    subprocess.run(["gcc", "-O2", "-o", str(copy_bin), str(copy_src)], check=True)

    def timed(command: list[str]) -> int:
        started = time.perf_counter_ns()
        subprocess.run(command, check=False, capture_output=True)
        return time.perf_counter_ns() - started

    read_ns = statistics.median(timed(["dd", "if=" + str(file), "of=/dev/null", "bs=1M", "status=none"])
                                for _ in range(rounds))
    write_ns = statistics.median(
        timed(["dd", "if=/dev/zero", f"of={target}", "bs=1M", f"count={file.stat().st_size >> 20}",
               "conv=fsync", "status=none"]) for _ in range(rounds))
    memcpy_out = subprocess.run([str(copy_bin), str(file.stat().st_size)], capture_output=True, check=True)
    memcpy_ns = int(memcpy_out.stdout.split()[0])
    fsync_ns = []
    with target.open("r+b") as handle:
        for _ in range(rounds):
            handle.write(b"x" * 4096)
            handle.flush()
            started = time.perf_counter_ns()
            os.fsync(handle.fileno())
            fsync_ns.append(time.perf_counter_ns() - started)
    return {
        "input_bytes": file.stat().st_size,
        "sequential_read_ns": read_ns,
        "sequential_read_gib_s": round(file.stat().st_size / read_ns, 3) if read_ns else None,
        "sequential_write_fsync_ns": write_ns,
        "sequential_write_gib_s": round(file.stat().st_size / write_ns, 3) if write_ns else None,
        "memcpy_ns": memcpy_ns,
        "memcpy_gib_s": round(file.stat().st_size / memcpy_ns, 3) if memcpy_ns else None,
        "fsync_4k_median_ns": int(statistics.median(fsync_ns)),
        "note": "page cache warm for read and memcpy; write includes fdatasync via conv=fsync",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--artifacts", type=Path, default=Path("/tmp/artifacts"))
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseae-replay")
    parser.add_argument("--output", type=Path, default=REPO / "benchmarks/results/phaseae/replay_profile.json")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--firebuild", type=Path, default=None)
    parser.add_argument("--firebuild-conf", type=Path, default=None)
    parser.add_argument("--firebuild-libdir", default="")
    args = parser.parse_args(argv)

    tracejit = args.tracejit.resolve()
    scratch = args.scratch
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)

    cases = []
    text100 = args.artifacts / "text-100MiB.bin"
    xz100 = args.artifacts / "xz-100MiB.bin"
    text10 = args.artifacts / "text-10MiB.bin"
    cases.append(("gzip-stdout", text100, ["gzip", "-9", "-n", "-c", "input.bin"], ()))
    cases.append(("gzip-stdout-incompressible", xz100, ["gzip", "-9", "-n", "-c", "input.bin"], ()))
    cases.append(("gzip-file", text10, ["gzip", "-9", "-n", "-k", "-f", "input.bin"], ("input.bin.gz",)))
    cases.append(("sha256sum", text100, ["sha256sum", "input.bin"], ()))

    payload = {"cases": [], "bounds": {}, "environment": {
        "kernel": os.uname().release, "machine": os.uname().machine,
    }}
    for name, artifact, command, outputs in cases:
        if not artifact.is_file():
            print(f"skipping {name}: {artifact} missing")
            continue
        measured = workload_measure(artifact, name, artifact.stat().st_size, command, outputs,
                                    ["tracejit"] + (["firebuild"] if args.firebuild else []),
                                    args.reps, scratch, tracejit, args.firebuild,
                                    args.firebuild_conf, args.firebuild_libdir)
        measured["name"] = name
        payload["cases"].append(measured)
        arm = measured["arms"]["tracejit"]
        total = arm["median_hit_ns"]
        print(f"{name:28s} hit={total/1e6:8.1f}ms "
              f"guards={arm['median']['guard_validation_ns']/1e6:7.1f} "
              f"stdio={arm['median']['stdio_replay_ns']/1e6:7.1f} "
              f"restore={arm['median']['cas_restore_ns']/1e6:7.1f} "
              f"present={arm['median']['present_ns']/1e6:7.1f} "
              f"rss={arm['peak_rss_kib']}KiB", flush=True)
        if "firebuild" in measured["arms"]:
            print(f"{'':28s} firebuild hit={measured['arms']['firebuild']['median_hit_ns']/1e6:8.1f}ms")

    payload["bounds"]["read_write_memcpy_fsync"] = bounds(scratch / "bounds", text100, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    shutil.rmtree(scratch, ignore_errors=True)
    print("bounds:", payload["bounds"]["read_write_memcpy_fsync"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

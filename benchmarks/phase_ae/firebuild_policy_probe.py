#!/usr/bin/env python3
"""Phase AE: Firebuild's documented contract versus its measured reuse decisions.

Why this exists
---------------
Phase AD asserted two things about the competitor that its evidence did not support:

1. "no independent validation pass over the recorded inputs at reuse time: the fingerprint
   *is* the lookup key".  That is false: `ExecedProcessCacher::pio_matches_fs()` walks every
   recorded input and calls `HashCache::file_info_matches()`, which compares type, size,
   mode and (when the record carries one) the content hash before a shortcut is applied.
2. "replays clock-dependent commands by quirk" is true, but the same source shows the quirk
   is a named, disableable option (`ignore-time-queries`), and that disabling it makes
   Firebuild refuse to *cache* such a process.  A quirk that the configuration names is a
   different object from an unvalidated cache.

This harness measures the behaviour instead of arguing about it, for every Firebuild build
and configuration in the matrix:

``clock_date``            does ``date +%s`` get replayed, and does the strict config stop it?
``clock_time_ns``         the same for a Python clock read (interpreter + libc path)
``gzip_file``             gzip -9 -n -k (sets the output mtime)
``bzip2_file``            bzip2 -9 -k (also sets the output mtime)
``gzip_stdout``           gzip -9 -n -c
``sed_stdout``            sed over 200k lines (default ``skip_cache``)
``same_mtime_rewrite``    content replaced with the same size *and* the recorded mtime
                          restored; if this is reused, the cached bytes describe the old
                          input -- an incorrect HIT inside Firebuild's own stated contract
``mtime_only_change``     same content, new mtime (must not be reused if hashes are compared)
``output_restore``        remove the output, reuse, compare restored bytes with the oracle
``cache_corruption``      flip one byte in the cached stdout blob, then reuse: does the engine
expose bytes that were never verified?

Every invocation is recorded with the engine's own decision (``-s`` trailer), exit status,
stdout digest and output-file digests against an independently computed native oracle.  No
decision is inferred from another invocation.

Run one arm per invocation and merge into ``benchmarks/results/phaseae/policy_probe.json``:

    python3 benchmarks/phase_ae/firebuild_policy_probe.py \
        --firebuild /tmp/fb-build/src/firebuild/firebuild \
        --conf /tmp/fb-build/etc/firebuild.conf --label fb862
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

FIREBUILD_STATS = b"\nStatistics of current run:"
FB_HITS = re.compile(r"Hits:\s+(\d+) / (\d+)")
FB_MISSES = re.compile(r"Misses:\s+(\d+)")
FB_UNCACHEABLE = re.compile(r"Uncacheable:\s+(\d+)")
FB_NEWLY = re.compile(r"Newly cached:\s+([\d.]+) kB")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def blob(size: int, seed: int = 0x9E3779B97F4A7C15) -> bytes:
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


SMALL_BLOB = blob(1 << 20)
TEXT = text_lines(40_000)
LINES = text_lines(200_000)


class Engine:
    def __init__(self, binary: Path, conf: Path, libdir: str, tuned: bool):
        self.binary = binary
        self.conf = conf
        self.libdir = libdir
        self.tuned = tuned
        self.home = Path()

    def bind(self, root: Path) -> None:
        self.home = root / "home"
        shutil.rmtree(self.home, ignore_errors=True)
        self.home.mkdir(parents=True)

    def cache_dir(self) -> Path:
        return self.home / ".cache" / "firebuild"

    def command(self, argv: list[str]) -> list[str]:
        command = [str(self.binary), "-c", str(self.conf)]
        if self.tuned:
            command += ["-o", "processes.skip_cache=[]"]
        return command + ["-s", "--", *argv]

    def env(self) -> dict:
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("XDG_CACHE_HOME", None)
        if self.libdir:
            env["LD_LIBRARY_PATH"] = self.libdir
        return env

    def blobs(self) -> list[Path]:
        root = self.cache_dir() / "blobs"
        return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []

    def run(self, ws: Path, argv: list[str]) -> dict:
        started = time.perf_counter_ns()
        completed = subprocess.run(
            self.command(argv), cwd=ws, env=self.env(), capture_output=True, check=False
        )
        wall = time.perf_counter_ns() - started
        stdout = completed.stdout
        stats = ""
        marker = stdout.rfind(FIREBUILD_STATS)
        if marker >= 0:
            stats = stdout[marker:].decode(errors="replace")
            stdout = stdout[:marker]
        hits = FB_HITS.search(stats)
        misses = FB_MISSES.search(stats)
        uncacheable = FB_UNCACHEABLE.search(stats)
        newly = FB_NEWLY.search(stats)
        hit_count = int(hits.group(1)) if hits else 0
        return {
            "wall_ns": wall,
            "hits": hit_count,
            "misses": int(misses.group(1)) if misses else 0,
            "uncacheable": int(uncacheable.group(1)) if uncacheable else 0,
            "newly_cached_kb": float(newly.group(1)) if newly else None,
            "decision": "hit" if hit_count else (
                "refused" if uncacheable and int(uncacheable.group(1)) else "executed"
            ),
            "stats_parsed": bool(hits),
            "exit": completed.returncode,
            "stdout": stdout,
            "stderr": completed.stderr[-2000:].decode(errors="replace"),
            "cache_bytes": tree_bytes(self.cache_dir()),
        }


def oracle(argv: list[str], payload: bytes, outputs: tuple[str, ...], root: Path) -> dict:
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    (root / "input.bin").write_bytes(payload)
    completed = subprocess.run(argv, cwd=root, env=dict(os.environ), capture_output=True, check=False)
    return {
        "exit": completed.returncode,
        "stdout_sha256": sha256_bytes(completed.stdout),
        "outputs_sha256": {name: sha256_file(root / name) for name in outputs},
    }


def observe(ws: Path, result: dict, outputs: tuple[str, ...]) -> dict:
    return {
        "exit": result["exit"],
        "stdout_sha256": sha256_bytes(result["stdout"]),
        "outputs_sha256": {name: sha256_file(ws / name) for name in outputs},
    }


def matches(observed: dict, expectation: dict) -> bool:
    return (
        observed["exit"] == expectation["exit"]
        and observed["stdout_sha256"] == expectation["stdout_sha256"]
        and observed["outputs_sha256"] == expectation["outputs_sha256"]
    )


def base_case(name: str, engine: Engine, scratch: Path, argv: list[str], payload: bytes,
              outputs: tuple[str, ...] = (), runs: int = 2, gap_s: float = 0.0) -> dict:
    ws = scratch / f"ws-{name}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    (ws / "input.bin").write_bytes(payload)
    engine.bind(scratch / f"engine-{name}")
    expectation = oracle(argv, payload, outputs, scratch / f"oracle-{name}")
    records = []
    for index in range(runs):
        for output in outputs:
            (ws / output).unlink(missing_ok=True)
        if gap_s:
            time.sleep(gap_s)
        result = engine.run(ws, argv)
        seen = observe(ws, result, outputs)
        records.append({
            "index": index,
            **{key: result[key] for key in
               ("wall_ns", "hits", "misses", "uncacheable", "newly_cached_kb", "decision",
                "stats_parsed", "exit", "cache_bytes")},
            "stdout_sha256": seen["stdout_sha256"],
            "outputs_sha256": seen["outputs_sha256"],
            "correct": matches(seen, expectation),
            "stderr_tail": result["stderr"],
        })
    return {
        "case": name,
        "argv": argv,
        "input_bytes": len(payload),
        "outputs": list(outputs),
        "invocations": records,
        "all_correct": all(record["correct"] for record in records),
        "cache_bytes_final": records[-1]["cache_bytes"],
        "expectation": expectation,
    }


def clock_case(name: str, engine: Engine, scratch: Path, argv: list[str], gap_s: float) -> dict:
    """Two runs of a clock-reading command; the second must not claim freshness."""
    ws = scratch / f"ws-{name}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    engine.bind(scratch / f"engine-{name}")
    first = engine.run(ws, argv)
    time.sleep(gap_s)
    second = engine.run(ws, argv)
    replay = second["decision"] == "hit" and second["stdout"] == first["stdout"]
    return {
        "case": name,
        "argv": argv,
        "invocations": [
            {"index": i, **{key: result[key] for key in
                            ("wall_ns", "hits", "misses", "uncacheable", "newly_cached_kb",
                             "decision", "stats_parsed", "exit", "cache_bytes")},
             "stdout_sha256": sha256_bytes(result["stdout"]),
             "stdout_text": result["stdout"].decode(errors="replace").strip()[:200]}
            for i, result in enumerate((first, second))
        ],
        "replayed_stale_clock": replay,
        "all_correct": True,
        "note": "correctness of a clock-dependent workload is defined by the contract; see docs",
    }


def same_mtime_rewrite(engine: Engine, scratch: Path, argv: list[str], payload: bytes,
                       replacement: bytes) -> dict:
    """Populate the cache, then rewrite the input preserving size and recorded mtime."""
    assert len(replacement) <= len(payload)
    name = "same_mtime_rewrite"
    ws = scratch / f"ws-{name}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    target = ws / "input.bin"
    target.write_bytes(payload)
    engine.bind(scratch / f"engine-{name}")
    old_expectation = oracle(argv, payload, (), scratch / f"oracle-{name}-old")
    new_payload = replacement + payload[len(replacement):]
    new_expectation = oracle(argv, new_payload, (), scratch / f"oracle-{name}-new")

    records = []
    for index in range(2):
        result = engine.run(ws, argv)
        seen = observe(ws, result, ())
        records.append({"index": index, "decision": result["decision"], "hits": result["hits"],
                        "correct_for_old": matches(seen, old_expectation),
                        "correct_for_new": matches(seen, new_expectation),
                        "stdout_sha256": seen["stdout_sha256"]})

    recorded = target.stat()
    target.write_bytes(new_payload)
    os.utime(target, ns=(recorded.st_atime_ns, recorded.st_mtime_ns))
    after = target.stat()
    metadata_preserved = (
        after.st_size == recorded.st_size and after.st_mtime_ns == recorded.st_mtime_ns
    )
    result = engine.run(ws, argv)
    seen = observe(ws, result, ())
    records.append({
        "index": 2,
        "decision": result["decision"],
        "hits": result["hits"],
        "correct_for_old": matches(seen, old_expectation),
        "correct_for_new": matches(seen, new_expectation),
        "stdout_sha256": seen["stdout_sha256"],
        "metadata_preserved": metadata_preserved,
    })
    stale_hit = bool(
        records[-1]["decision"] == "hit"
        and records[-1]["correct_for_old"]
        and not records[-1]["correct_for_new"]
    )
    return {
        "case": name,
        "argv": argv,
        "metadata_preserved_on_rewrite": metadata_preserved,
        "invocations": records,
        "stale_hit_after_same_mtime_rewrite": stale_hit,
        "all_correct": all(record["correct_for_new"] for record in records[2:]),
        "note": "a stale hit here means the file-hash cache trusted (size, mtime, inode)",
    }


def mtime_only_change(engine: Engine, scratch: Path, argv: list[str], payload: bytes) -> dict:
    name = "mtime_only_change"
    ws = scratch / f"ws-{name}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    target = ws / "input.bin"
    target.write_bytes(payload)
    engine.bind(scratch / f"engine-{name}")
    expectation = oracle(argv, payload, (), scratch / f"oracle-{name}")
    records = []
    for index in range(2):
        result = engine.run(ws, argv)
        seen = observe(ws, result, ())
        records.append({"index": index, "decision": result["decision"], "hits": result["hits"],
                        "correct": matches(seen, expectation)})
    future = time.time_ns() + 1_000_000_000
    os.utime(target, ns=(future, future))
    result = engine.run(ws, argv)
    seen = observe(ws, result, ())
    records.append({"index": 2, "decision": result["decision"], "hits": result["hits"],
                    "correct": matches(seen, expectation)})
    return {
        "case": name,
        "argv": argv,
        "invocations": records,
        "reused_after_mtime_change": records[-1]["decision"] == "hit",
        "all_correct": all(record["correct"] for record in records),
    }


def cache_corruption(engine: Engine, scratch: Path) -> dict:
    """Corrupt the cached stdout object of a reuse-eligible command, then reuse it.

    ``-s`` writes Firebuild's statistics to the *firebuild* process's stdout, so every
    captured stream is stripped at the statistics trailer before it is compared.  The blob
    to corrupt is identified by content (size and digest of the native expectation), so the
    case cannot silently corrupt the wrong object.
    """
    name = "cache_corruption"
    argv = ["gzip", "-9", "-n", "-c", "input.bin"]
    ws = scratch / f"ws-{name}"
    shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True)
    (ws / "input.bin").write_bytes(TEXT)
    engine.bind(scratch / f"engine-{name}")
    expectation = oracle(argv, TEXT, (), scratch / f"oracle-{name}")

    def child_stdout(result: dict) -> bytes:
        return result["stdout"]

    population = []
    for index in range(2):
        result = engine.run(ws, argv)
        population.append({
            "index": index,
            "decision": result["decision"],
            "stdout_sha256": sha256_bytes(child_stdout(result)),
            "correct": sha256_bytes(child_stdout(result)) == expectation["stdout_sha256"],
        })

    target = None
    for blob in engine.blobs():
        try:
            data = blob.read_bytes()
        except OSError:
            continue
        if sha256_bytes(data) == expectation["stdout_sha256"]:
            target = blob
            break
    if target is None:
        return {
            "case": name,
            "argv": argv,
            "population": population,
            "blob_located": False,
            "note": "no cache object matched the expected stdout bytes",
            "all_correct": all(item["correct"] for item in population),
        }

    data = bytearray(target.read_bytes())
    offset = len(data) // 2
    data[offset] ^= 0xFF
    target.write_bytes(bytes(data))

    result = engine.run(ws, argv)
    served = child_stdout(result)
    return {
        "case": name,
        "argv": argv,
        "population": population,
        "blob_located": True,
        "blob": str(target),
        "corrupted_offset": offset,
        "blob_bytes": len(data),
        "invocations": [{
            "index": 2,
            "decision": result["decision"],
            "hits": result["hits"],
            "exit": result["exit"],
            "stdout_sha256": sha256_bytes(served),
            "expected_stdout_sha256": expectation["stdout_sha256"],
            "served_corrupted_bytes": sha256_bytes(served) != expectation["stdout_sha256"],
        }],
        "served_corrupted_bytes": sha256_bytes(served) != expectation["stdout_sha256"],
        "all_correct": (
            all(item["correct"] for item in population)
            and sha256_bytes(served) == expectation["stdout_sha256"]
        ),
        "note": "a corrupted-blob hit means cached bytes are exposed without verification",
    }


def cases(engine: Engine, scratch: Path) -> list[dict]:
    results = []
    results.append(clock_case("clock_date", engine, scratch, ["date", "+%s"], 1.1))
    results.append(clock_case(
        "clock_time_ns", engine, scratch,
        ["python3", "-c", "import time; print(time.time_ns())"], 0.05,
    ))
    results.append(base_case("gzip_file", engine, scratch,
                             ["gzip", "-9", "-n", "-k", "-f", "input.bin"], SMALL_BLOB,
                             ("input.bin.gz",)))
    results.append(base_case("bzip2_file", engine, scratch,
                             ["bzip2", "-9", "-k", "-f", "input.bin"], SMALL_BLOB,
                             ("input.bin.bz2",)))
    results.append(base_case("gzip_stdout", engine, scratch,
                             ["gzip", "-9", "-n", "-c", "input.bin"], TEXT))
    results.append(base_case("sed_stdout", engine, scratch,
                             ["sed", "s/key=/k=/g", "input.bin"], LINES))
    results.append(same_mtime_rewrite(engine, scratch, ["gzip", "-9", "-n", "-c", "input.bin"],
                                      TEXT, b"REWRITTEN-CONTENT\n"))
    results.append(mtime_only_change(engine, scratch, ["gzip", "-9", "-n", "-c", "input.bin"], TEXT))
    results.append(cache_corruption(engine, scratch))
    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firebuild", type=Path, required=True)
    parser.add_argument("--conf", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--libdir", default="")
    parser.add_argument("--tuned", action="store_true")
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseae-policy")
    parser.add_argument("--output", type=Path,
                        default=REPO / "benchmarks/results/phaseae/policy_probe.json")
    args = parser.parse_args(argv)

    binary, conf = args.firebuild.resolve(), args.conf.resolve()
    engine = Engine(binary, conf, args.libdir, args.tuned)
    shutil.rmtree(args.scratch, ignore_errors=True)
    args.scratch.mkdir(parents=True)

    payload = {
        "arm": args.label,
        "firebuild_version": args.version,
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
        "config": str(conf),
        "config_sha256": sha256_file(conf),
        "tuned": args.tuned,
        "host": {"kernel": os.uname().release, "machine": os.uname().machine},
        "cases": cases(engine, args.scratch),
    }
    for case in payload["cases"]:
        decision = [record["decision"] for record in case["invocations"]]
        print(f"{args.label:24s} {case['case']:22s} decisions={decision} "
              f"correct={case.get('all_correct')} "
              f"stale={case.get('stale_hit_after_same_mtime_rewrite', case.get('replayed_stale_clock'))}",
              flush=True)

    existing = {"arms": {}}
    if args.output.is_file():
        existing = json.loads(args.output.read_text())
    existing.setdefault("arms", {})[args.label] = payload
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    shutil.rmtree(args.scratch, ignore_errors=True)
    print(f"wrote {args.label} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

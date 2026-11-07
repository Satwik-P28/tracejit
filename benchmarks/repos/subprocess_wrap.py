#!/usr/bin/env python3
"""Bounded subprocess-reuse experiment: explicit wrapping versus whole-command caching.

The four repository sessions show that whole-command reuse cannot help a build: `make` and the
compiler are refused, and only the project's own tool is cached. This harness asks whether wrapping
an *eligible* child inside a real Makefile recipe is worth building infrastructure for, before any
transparent execve interception exists.

Arms:
    direct      native `make` with the system gzip
    wrapped     the same Makefile with the recipe's gzip replaced by
                `tracejit run --admission auto -- gzip`, one cache shared by all children
    top         ordinary whole-command caching of `tracejit run -- make`
    specialist  an existing specialist cache for gzip; none is installed, so recorded as N/A

Every arm compresses the same files with the same options. The workload is a standard per-file
static-asset compression rule applied to a pristine zlib 1.3.1 checkout. No repository in the
benchmark corpus gzips per file through its own Makefile, so the rule is the real-world pattern
rather than zlib's own build; that is recorded as a limitation, not hidden.

Usage:
    python3 benchmarks/repos/subprocess_wrap.py --session a
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = Path("/tmp/zlib")
SOURCE_COMMIT = "51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf"
WORKLOAD = "phase2m-subprocess-wrap-v1"
CONTRACT = "allocator-entropy-v1"
FILE_COUNT = 5
FILE_MEGABYTES = 4
MAKEFILE = """\
# Deliberately not named GZIP: make exports command-line variables into the recipe
# environment, and gzip parses $GZIP as default options, so a wrapper there would be
# read by gzip itself rather than by the shell.
COMPRESS ?= gzip
DATA := $(wildcard data/*.bin)
GZ := $(DATA:=.gz)
all: $(GZ)
data/%.bin.gz: data/%.bin
\t$(COMPRESS) -9 -c < $< > $@
"""


def binary() -> Path:
    candidate = REPO / "target" / "release" / "tracejit"
    if not candidate.is_file():
        raise SystemExit("no release tracejit binary; run cargo build --release")
    return candidate


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_environment() -> dict:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "TZ": "UTC",
    }


def run(argv, cwd: Path, env: dict, timeout: int = 600, stdin_path: Path | None = None):
    source = open(stdin_path, "rb") if stdin_path is not None else subprocess.DEVNULL
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    finally:
        if stdin_path is not None:
            source.close()
    return (time.perf_counter() - started) * 1000.0, completed


def prepare(work: Path) -> None:
    """Pristine project sources plus deterministic, untimed data files."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-C", str(SOURCE), "archive", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    subprocess.run(
        ["tar", "-x", "-C", str(work)],
        input=archive.stdout,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (work / "Makefile.precompress").write_text(MAKEFILE)
    data = work / "data"
    data.mkdir()
    for index in range(FILE_COUNT):
        with open(data / f"bundle-{index}.bin", "w") as handle:
            for line in range(FILE_MEGABYTES * 12000):
                handle.write(
                    f"{line * 2654435761 % 1000000007:010d} {line % 9973} "
                    f"{index:02d} alpha beta gamma delta epsilon\n"
                )


def inventory(work: Path) -> dict:
    files = {}
    total = 0
    for path in sorted((work / "data").glob("*.bin")):
        size = path.stat().st_size
        total += size
        files[path.name] = {"bytes": size, "sha256": sha256_file(path)}
    return {"files": files, "total_bytes": total}


def artifact_digest(work: Path) -> str:
    """Order-independent digest of every produced archive and its metadata."""
    digest = hashlib.sha256()
    for path in sorted((work / "data").glob("*.gz")):
        digest.update(path.name.encode())
        digest.update(sha256_file(path).encode())
    return digest.hexdigest()


def clear_outputs(work: Path) -> None:
    for path in (work / "data").glob("*.gz"):
        path.unlink()


def decision_counts(stderr: bytes) -> dict:
    text = stderr.decode(errors="replace")
    return {
        "hits": text.count("cache          HIT"),
        "misses": text.count("cache          MISS"),
        "deopts": text.count("cache          DEOPT"),
        "skips": text.count("cache          SKIP"),
        "database_locked": "database is locked" in text,
    }


def make_argv(parallel: int) -> list[str]:
    return ["make", f"-j{parallel}", "-f", "Makefile.precompress", "all"]


def build(work: Path, env: dict, command: list[str]):
    clear_outputs(work)
    elapsed, completed = run(command, work, env)
    return {
        "ms": round(elapsed, 2),
        "exit": completed.returncode,
        "stdout_bytes": len(completed.stdout),
        "stderr_bytes": len(completed.stderr),
        "decisions": decision_counts(completed.stderr),
        "artifact_digest": artifact_digest(work),
        "stderr": completed.stderr.decode(errors="replace")[-400:],
    }


def arm_direct(work: Path, parallel: int) -> dict:
    env = base_environment()
    return {
        "cold": build(work, env, make_argv(parallel)),
        "repeat": [build(work, env, make_argv(parallel)) for _ in range(2)],
    }


def arm_wrapped(work: Path, parallel: int, cache: Path) -> dict:
    env = base_environment()
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    wrapped = f"{binary()} run --admission auto --contract {CONTRACT} -- gzip"
    argv = [*make_argv(parallel), f"COMPRESS={wrapped}"]
    return {
        "cold": build(work, env, argv),
        "repeat": [build(work, env, argv) for _ in range(2)],
        "probes": probes(work, env),
    }


def arm_top(work: Path, parallel: int, cache: Path) -> dict:
    env = base_environment()
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    argv = [
        str(binary()),
        "run",
        "--admission",
        "auto",
        "--contract",
        CONTRACT,
        "--",
        *make_argv(parallel),
    ]
    return {
        "cold": build(work, env, argv),
        "repeat": [build(work, env, argv) for _ in range(2)],
    }


def probes(work: Path, env: dict) -> list[dict]:
    """Confirm, per input, that the wrapped invocation is actually reusable."""
    results = []
    for path in sorted((work / "data").glob("*.bin")):
        # Same argv and stdin shape as the recipe, otherwise the probe asks a different
        # question than the build did and could never hit.
        argv = [
            str(binary()),
            "run",
            "--json",
            "--admission",
            "auto",
            "--contract",
            CONTRACT,
            "--",
            "gzip",
            "-9",
            "-c",
        ]
        _, completed = run(argv, work, env, stdin_path=path)
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            report = None
        results.append(
            {
                "input": path.name,
                "exit": completed.returncode,
                "cache_decision": None if report is None else report.get("cache_decision"),
                "classification": None if report is None else report.get("classification"),
                "child_exit": None if report is None else report.get("exit_code"),
                "reasons": [] if report is None else (report.get("reasons") or [])[:2],
            }
        )
    return results


def invalidation(work: Path, wrapped: bool, cache: Path) -> dict:
    """Change one input's content and require exactly one re-execution."""
    env = base_environment()
    argv = make_argv(1)
    if wrapped:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
        argv = [*argv, f"COMPRESS={binary()} run --admission auto --contract {CONTRACT} -- gzip"]
    # Warm every record first so the invalidation is the only difference.
    build(work, env, argv)
    before = {path.name: sha256_file(path) for path in (work / "data").glob("*.gz")}
    target = work / "data" / "bundle-2.bin"
    with open(target, "a") as handle:
        handle.write("changed\n")
    os.utime(target)
    changed = build(work, env, argv)
    after = {path.name: sha256_file(path) for path in (work / "data").glob("*.gz")}
    rebuilt = build(work, env, argv)
    return {
        "changed_ms": changed["ms"],
        "decisions": changed["decisions"],
        "changed_archives": sorted(
            name for name in before if before[name] != after.get(name)
        ),
        "rebuild_exit": rebuilt["exit"],
        "rebuild_decisions": rebuilt["decisions"],
        "rebuilt_digest": rebuilt["artifact_digest"],
    }


def environment_change(work: Path, wrapped: bool, cache: Path) -> dict:
    """A different environment must not be served from the previous identity."""
    env = base_environment()
    env["TZ"] = "GMT"
    argv = make_argv(1)
    if wrapped:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
        argv = [*argv, f"COMPRESS={binary()} run --admission auto --contract {CONTRACT} -- gzip"]
    return build(work, env, argv)


def parallel_run(work: Path, wrapped: bool, cache: Path, workers: int) -> dict:
    env = base_environment()
    argv = make_argv(workers)
    if wrapped:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
        argv = [*argv, f"COMPRESS={binary()} run --admission auto --contract {CONTRACT} -- gzip"]
    cold = build(work, env, argv)
    warm = build(work, env, argv)
    return {"cold": cold, "warm": warm}


def failure_propagation() -> dict:
    """The wrapping must report the child's status and stderr, not its own success."""
    missing = ["gzip", "-9", "-c", "/nonexistent/input"]
    native_elapsed, native = run(missing, Path("/tmp"), base_environment())
    wrapped_elapsed, wrapped = run(
        [
            str(binary()),
            "run",
            "--admission",
            "auto",
            "--contract",
            CONTRACT,
            "--",
            *missing,
        ],
        Path("/tmp"),
        {**base_environment(), "TRACEJIT_CACHE_DIR": tempfile.mkdtemp(prefix="tracejit-fail-")},
    )
    return {
        "native_exit": native.returncode,
        "wrapped_exit": wrapped.returncode,
        "status_equal": native.returncode == wrapped.returncode,
        "native_stderr": native.stderr.decode(errors="replace")[-300:],
        "wrapped_stderr": wrapped.stderr.decode(errors="replace")[-600:],
        "ms": {"native": round(native_elapsed, 2), "wrapped": round(wrapped_elapsed, 2)},
    }


def repository_state() -> dict:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
        )
        return completed.stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD") or None,
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "binary_sha256": sha256_file(binary()),
    }


def tool_version(argv: list[str]) -> str | None:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return None
    return (completed.stdout or completed.stderr).strip().splitlines()[0]


def finalize(results: dict) -> None:
    direct = results["arms"]["direct"]
    baseline = direct["cold"]["artifact_digest"]
    direct_total = (
        direct["cold"]["ms"] + sum(pass_["ms"] for pass_ in direct["repeat"])
    )
    children = FILE_COUNT
    for name, arm in results["arms"].items():
        if not isinstance(arm, dict) or "cold" not in arm:
            continue
        total = arm["cold"]["ms"] + sum(pass_["ms"] for pass_ in arm["repeat"])
        arm["total_ms"] = round(total, 2)
        arm["speedup"] = round(direct_total / total, 3)
        arm["slowdown"] = round(total / direct_total, 3)
        arm["artifacts_match"] = all(
            entry["artifact_digest"] == baseline
            for entry in [arm["cold"], *arm["repeat"]]
        )
        arm["first_run_overhead_ms"] = round(arm["cold"]["ms"] - direct["cold"]["ms"], 2)
        repeat_native = sum(pass_["ms"] for pass_ in direct["repeat"]) / len(direct["repeat"])
        repeat_arm = sum(pass_["ms"] for pass_ in arm["repeat"]) / len(arm["repeat"])
        arm["per_child_overhead_ms"] = round((repeat_arm - repeat_native) / children, 2)
        arm["valid"] = arm["artifacts_match"] and all(
            entry["exit"] == 0 for entry in [arm["cold"], *arm["repeat"]]
        )
    results["direct_total_ms"] = round(direct_total, 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="a")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output-dir", default="benchmarks/results/phase2m/subprocess")
    args = parser.parse_args()
    if not SOURCE.is_dir():
        raise SystemExit(f"missing pristine checkout: {SOURCE}")
    root = Path(tempfile.mkdtemp(prefix="tracejit-wrap-"))
    inventory_reference = None
    inventories = {}
    results = {
        "session": args.session,
        "workload_version": WORKLOAD,
        "contract": CONTRACT,
        "tracejit": repository_state(),
        "source": {"project": "zlib v1.3.1", "commit": SOURCE_COMMIT},
        "host": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "cpus": os.cpu_count(),
        },
        "tools": {
            "gzip": tool_version(["gzip", "--version"]),
            "make": tool_version(["make", "--version"]),
            "specialist_cache": shutil.which("ccache") or shutil.which("sccache"),
        },
        "workload": {
            "recipe": "data/%.bin.gz: data/%.bin\n\t$(COMPRESS) -9 -c < $< > $@",
            "files": FILE_COUNT,
            "megabytes_each": FILE_MEGABYTES,
            "note": (
                "standard static-asset precompression rule over a pristine zlib 1.3.1 tree; "
                "no corpus project gzips per file through its own Makefile, so this is the "
                "real-world pattern rather than that project's build"
            ),
        },
        "arms": {},
        "invalidation": {},
        "environment": {},
        "parallel": {},
        "failure_propagation": failure_propagation(),
        "specialist": {
            "applicable": False,
            "reason": (
                "no installed cache serves gzip; ccache and sccache target compilers, which "
                "TraceJIT refuses, so a specialist arm cannot perform equivalent work"
            ),
        },
    }
    arms = [
        ("direct", lambda work, cache: arm_direct(work, args.workers)),
        ("wrapped", lambda work, cache: arm_wrapped(work, args.workers, cache)),
        ("top", lambda work, cache: arm_top(work, args.workers, cache)),
    ]
    for name, measure in arms:
        work = root / name
        cache = root / f"cache-{name}"
        prepare(work)
        inventories[name] = inventory(work)
        results["arms"][name] = measure(work, cache)
    inventory_reference = inventories["direct"]
    results["workload"]["inventory"] = inventory_reference
    results["workload"]["inventories_equal"] = all(
        entry == inventory_reference for entry in inventories.values()
    )
    for name in ("wrapped", "top"):
        work = root / name
        cache = root / f"cache-{name}"
        results["invalidation"][name] = invalidation(work, name == "wrapped", cache)
        results["environment"][name] = environment_change(work, name == "wrapped", cache)
        results["parallel"][name] = parallel_run(
            work, name == "wrapped", cache, args.workers
        )
    # Compare the pristine cold-pass artifacts. Invalidation deliberately mutates one input in
    # the wrapped and top arms, so comparing their post-experiment trees with the untouched
    # native tree would report a difference the experiment itself created.
    pristine = {name: results["arms"][name]["cold"]["artifact_digest"] for name in ("direct", "wrapped", "top")}
    results["artifacts"] = {
        "pristine": pristine,
        "all_equal": len(set(pristine.values())) == 1,
        "after_invalidation": {
            name: artifact_digest(root / name) for name in ("direct", "wrapped", "top")
        },
    }
    finalize(results)
    output = REPO / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"session-{args.session}.json"
    target.write_text(json.dumps(results, indent=2) + "\n")
    for name in ("direct", "wrapped", "top"):
        arm = results["arms"][name]
        print(
            f"{name} {args.session}: total={arm['total_ms']}ms speedup={arm['speedup']}x "
            f"valid={arm['valid']} hits={arm['cold']['decisions']['hits']}+"
            f"{sum(p['decisions']['hits'] for p in arm['repeat'])} "
            f"deopts={sum(p['decisions']['deopts'] for p in arm['repeat'])}"
        )
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

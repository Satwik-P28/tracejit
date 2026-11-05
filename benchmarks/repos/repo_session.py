#!/usr/bin/env python3
"""A real repository development session: zlib v1.3.1.

The session is a fixed sequence on a clean checkout: configure, clean build, identical rebuild,
an unrelated edit, a relevant source edit, the test target, and then repeated invocations of the
project's own `minigzip` tool over a 16 MB generated corpus (six compressions, four decompressions).

Both halves are kept deliberately. Build drivers (`make`) and the test target are typical developer
commands; the tool invocations are the deterministic repeated workload a developer or CI job runs
while checking compression behaviour. Timing the whole session prevents the second half from being
cherry-picked in isolation.

Usage:
    python3 benchmarks/repos/repo_session.py --repo /tmp/zlib --session a [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "allocator-entropy-v1"
CORPUS = "corpus.bin"
COMPRESSED = "corpus.gz"


def binary() -> Path:
    for candidate in (REPO / "target" / "release" / "tracejit", REPO / "target" / "debug" / "tracejit"):
        if candidate.is_file():
            return candidate
    raise SystemExit("no tracejit binary")


def environment(cache: Path | None) -> dict:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
           "LC_ALL": "C", "TZ": "UTC"}
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(argv, cwd, env, stdin_path: Path | None = None):
    source = open(stdin_path, "rb") if stdin_path is not None else subprocess.DEVNULL
    started = time.perf_counter()
    completed = subprocess.run(argv, cwd=cwd, env=env, stdin=source,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = (time.perf_counter() - started) * 1000.0
    if stdin_path is not None:
        source.close()
    return elapsed, completed


def phases() -> list[tuple[str, list[str], str | None]]:
    return [
        ("configure", ["./configure", "--static"], None),
        ("clean-build", ["make", "-j1", "clean"], None),
        ("build", ["make", "-j1"], None),
        ("rebuild", ["make", "-j1"], None),
        ("unrelated-edit", ["make", "-j1"], None),
        ("relevant-edit", ["make", "-j1"], None),
        ("test", ["make", "test"], None),
        ("generate-corpus", ["python3", "-c",
                             "import random\n"
                             "random.seed(3)\n"
                             "open('corpus.bin','w').write(''.join("
                             "f'{random.random():.12f} alpha beta gamma\\n' for _ in range(500000)))"],
         None),
        *[(f"compress-{index}", ["./minigzip"], CORPUS) for index in range(1, 7)],
        *[(f"decompress-{index}", ["./minigzip", "-d"], COMPRESSED) for index in range(1, 5)],
    ]


def reset(source: Path, work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(source, work)
    subprocess.run(["make", "-j1", "distclean"], cwd=work, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def session(source: Path, work: Path, policy: str, flags: list[str] | None) -> dict:
    reset(source, work)
    cache = work.parent / f"cache-{policy}"
    env = environment(cache if flags is not None else None)
    total = 0.0
    entries = []
    made_archive = False
    for name, argv, stdin_name in phases():
        if name == "unrelated-edit":
            path = work / "README"
            path.write_text(path.read_text() + "\nnote\n")
            os.utime(path)
        if name == "relevant-edit":
            path = work / "adler32.c"
            path.write_text(path.read_text() + "\n/* edit */\n")
        if name == "decompress-1" and not made_archive:
            # Untimed, native setup: build the archive the decompression runs consume.
            with open(work / CORPUS, "rb") as corpus, open(work / COMPRESSED, "wb") as archive:
                subprocess.run([str(work / "minigzip")], cwd=work, stdin=corpus,
                               stdout=archive, check=True)
            made_archive = True
        stdin_path = work / stdin_name if stdin_name is not None else None
        command = argv if flags is None else [str(binary()), "run", *flags, "--", *argv]
        elapsed, completed = run(command, work, env, stdin_path)
        total += elapsed
        entries.append({"phase": name, "ms": round(elapsed, 2), "exit": completed.returncode})
        if completed.returncode != 0 and name not in {"test"}:
            entries[-1]["stderr"] = completed.stderr.decode(errors="replace")[:300]
    decisions = []
    if flags is not None:
        for argv, stdin_name in ((["make", "-j1"], None), (["make", "test"], None),
                                 (["./minigzip"], CORPUS), (["./minigzip", "-d"], COMPRESSED)):
            stdin_path = work / stdin_name if stdin_name else None
            _, completed = run([str(binary()), "run", "--json", *flags, "--", *argv],
                               work, env, stdin_path)
            try:
                report = json.loads(completed.stdout)
            except json.JSONDecodeError:
                report = None
            decisions.append({
                "command": " ".join(argv),
                "decision": None if report is None else report.get("cache_decision"),
                "classification": None if report is None else report.get("classification"),
                "reasons": [] if report is None else (report.get("reasons") or [])[:3],
            })
    return {"total_ms": round(total, 2), "phases": entries, "decisions": decisions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/tmp/zlib")
    parser.add_argument("--session", default="a")
    parser.add_argument("--output-dir", default="benchmarks/results/phase2i/repo")
    args = parser.parse_args()
    source = Path(args.repo).resolve()
    if not (source / "configure").is_file():
        raise SystemExit(f"no zlib checkout at {source}")
    root = Path(tempfile.mkdtemp(prefix="tracejit-repo-"))
    results = {"repo": "zlib v1.3.1", "session": args.session, "policies": {}}
    for policy, flags in (
        ("direct", None),
        ("never", ["--contract", CONTRACT, "--admission", "never"]),
        ("always", ["--contract", CONTRACT]),
        ("auto", ["--contract", CONTRACT, "--admission", "auto"]),
    ):
        results["policies"][policy] = session(source, root / f"work-{policy}", policy, flags)
    direct = results["policies"]["direct"]["total_ms"]
    for entry in results["policies"].values():
        entry["total_ms"] = round(entry["total_ms"], 2)
        entry["speedup"] = round(direct / entry["total_ms"], 2)
        entry["slowdown"] = round(entry["total_ms"] / direct, 2)
    output_dir = REPO / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"repo-{args.session}.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({name: {"total_ms": entry["total_ms"], "speedup": entry["speedup"],
                             "slowdown": entry["slowdown"],
                             "decisions": entry["decisions"]}
                      for name, entry in results["policies"].items()}, indent=2))
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

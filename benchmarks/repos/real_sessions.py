#!/usr/bin/env python3
"""Complete developer-session measurements on real repositories.

Each policy gets a fresh copy of a pristine checkout, so a build product or cache from one policy
cannot change another policy's inputs. Phases are a realistic sequence: configure, build, immediate
rebuild, an unrelated edit, a relevant source edit, the project's test target, and repeated
invocations of the project's own tool over a generated corpus.

Usage:
    python3 benchmarks/repos/real_sessions.py --session a --repos zlib,libpng,lz4
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = "allocator-entropy-v1"
POLICIES = ("direct", "never", "auto-v1", "always", "auto")


def binary() -> Path:
    candidate = REPO / "target" / "release" / "tracejit"
    if not candidate.is_file():
        raise SystemExit("no release tracejit binary; run cargo build --release")
    return candidate


def environment(cache: Path | None) -> dict:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(argv, cwd: Path, env: dict, stdin_path: Path | None = None):
    source = open(stdin_path, "rb") if stdin_path is not None else subprocess.DEVNULL
    started = time.perf_counter()
    completed = subprocess.run(
        argv, cwd=cwd, env=env, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    if stdin_path is not None:
        source.close()
    return elapsed, completed


def edit(path: Path, line: str) -> None:
    path.write_text(path.read_text() + line)
    os.utime(path)


def corpus(root: Path, name: str, megabytes: int) -> Path:
    target = root / name
    if not target.exists():
        target.write_text(
            "".join(f"{index:08d} alpha beta gamma delta\n" for index in range(megabytes * 24000))
        )
    return target


def mixed_corpus(root: Path, name: str, megabytes: int) -> Path:
    # Repetitive text compresses in tens of milliseconds, which cannot repay a trace. These lines
    # vary in both fields, so compression costs hundreds of milliseconds like a real log or data
    # file. Generation is untimed and identical for every policy.
    target = root / name
    if not target.exists():
        with open(target, "w") as handle:
            for index in range(megabytes * 12000):
                handle.write(
                    f"{index * 2654435761 % 1000000007:010d} {index % 9973} "
                    "alpha beta gamma delta\n"
                )
    return target


def zlib_phases(root: Path) -> list[tuple[str, list[str], str | None]]:
    data = mixed_corpus(root, "corpus.bin", 16)
    return [
        ("configure", ["./configure", "--static"], None),
        ("build", ["make", "-j4"], None),
        ("rebuild", ["make", "-j4"], None),
        ("unrelated-edit", ["make", "-j4"], None),
        ("relevant-edit", ["make", "-j4"], None),
        ("test", ["make", "test"], None),
        *[(f"compress-{n}", ["./minigzip"], str(data)) for n in range(1, 7)],
        *[
            (f"decompress-{n}", ["./minigzip", "-d"], str(root / "corpus.gz"))
            for n in range(1, 5)
        ],
    ]


def libpng_phases(root: Path) -> list[tuple[str, list[str], str | None]]:
    return [
        ("configure", ["./configure", "--disable-shared"], None),
        ("build", ["make", "-j4"], None),
        ("rebuild", ["make", "-j4"], None),
        ("unrelated-edit", ["make", "-j4"], None),
        ("relevant-edit", ["make", "-j4"], None),
        *[(f"pngtest-{n}", ["./pngtest", "pngtest.png"], None) for n in range(1, 5)],
    ]


def lz4_phases(root: Path) -> list[tuple[str, list[str], str | None]]:
    data = corpus(root, "corpus.bin", 6)
    return [
        ("build", ["sh", "-c", "make -j4 && make -C programs -j4 lz4"], None),
        ("rebuild", ["sh", "-c", "make -j4 && make -C programs -j4 lz4"], None),
        ("unrelated-edit", ["sh", "-c", "make -j4 && make -C programs -j4 lz4"], None),
        ("relevant-edit", ["sh", "-c", "make -j4 && make -C programs -j4 lz4"], None),
        *[
            (f"compress-{n}", ["./programs/lz4", "-1", "-c"], str(data))
            for n in range(1, 7)
        ],
        *[
            (
                f"decompress-{n}",
                ["./programs/lz4", "-d", "-c"],
                str(root / "corpus.lz4"),
            )
            for n in range(1, 5)
        ],
    ]


SCENARIOS = {
    "zlib": {
        "source": "/tmp/zlib",
        "name": "zlib v1.3.1",
        "commit": "51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf",
        "clean": ["make", "distclean"],
        "phases": zlib_phases,
    },
    "libpng": {
        "source": "/tmp/libpng",
        "name": "libpng v1.6.43",
        "commit": "ed217e3e601d8e462f7fd1e04bed43ac42212429",
        "clean": ["make", "distclean"],
        "phases": libpng_phases,
    },
    "lz4": {
        "source": "/tmp/lz4",
        "name": "lz4 v1.9.4",
        "commit": "5ff839680134437dbf4678f3d0c7b371d84f4964",
        "clean": ["make", "clean"],
        "phases": lz4_phases,
    },
}


def flags(policy: str) -> list[str] | None:
    if policy == "direct":
        return None
    if policy == "never":
        return ["--contract", CONTRACT, "--admission", "never"]
    if policy == "always":
        return ["--contract", CONTRACT]
    return ["--contract", CONTRACT, "--admission", policy]


def prepare_work(source: Path, work: Path, clean: list[str]) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    # `git archive` gives every policy the same pristine sources. Copying the working tree instead
    # would carry build products and make `distclean` decide how much work a policy gets.
    archive = subprocess.run(
        ["git", "-C", str(source), "archive", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    subprocess.run(
        ["tar", "-x", "-C", str(work)], input=archive.stdout, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        clean, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )


def session(key: str, work: Path, policy: str) -> dict:
    scenario = SCENARIOS[key]
    prepare_work(Path(scenario["source"]).resolve(), work, scenario["clean"])
    cache = work.parent / f"cache-{policy}"
    if cache.exists():
        shutil.rmtree(cache)
    env = environment(cache if flags(policy) is not None else None)
    total = 0.0
    entries = []
    for name, argv, stdin_name in scenario["phases"](work):
        if name == "unrelated-edit":
            readme = work / "README"
            if not readme.exists():
                readme = work / "README.md"
            edit(readme, "\nnote\n")
        if name == "relevant-edit":
            target = {"zlib": "adler32.c", "libpng": "pngrutil.c", "lz4": "lib/lz4.c"}[key]
            edit(work / target, "\n/* edit */\n")
        if name == "decompress-1" and key == "zlib":
            # Corpus setup is untimed: it is the same archive for every policy.
            with open(work / "corpus.bin", "rb") as source, open(
                work / "corpus.gz", "wb"
            ) as archive:
                subprocess.run(["./minigzip"], cwd=work, stdin=source, stdout=archive,
                               stderr=subprocess.DEVNULL, check=False)
        if name == "decompress-1" and key == "lz4":
            with open(work / "corpus.bin", "rb") as source, open(
                work / "corpus.lz4", "wb"
            ) as archive:
                subprocess.run(
                    ["./programs/lz4", "-1", "-c"], cwd=work, stdin=source, stdout=archive,
                    stderr=subprocess.DEVNULL, check=False,
                )
        stdin_path = Path(stdin_name) if stdin_name else None
        command = argv if flags(policy) is None else [str(binary()), "run", *flags(policy), "--", *argv]
        elapsed, completed = run(command, work, env, stdin_path)
        total += elapsed
        entry = {"phase": name, "ms": round(elapsed, 2), "exit": completed.returncode}
        if completed.returncode != 0:
            entry["stderr"] = completed.stderr.decode(errors="replace")[:200]
        entries.append(entry)
    repeated = [
        entry["ms"]
        for entry in entries
        if entry["phase"].startswith(("compress-", "decompress-", "pngtest-"))
    ]
    decisions = []
    if flags(policy) is not None:
        probes = {
            "zlib": [
                (["make", "-j1"], None),
                (["./minigzip"], work / "corpus.bin"),
                (["./minigzip", "-d"], work / "corpus.gz"),
            ],
            "libpng": [(["./pngtest", "pngtest.png"], None)],
            "lz4": [
                (["./programs/lz4", "-1", "-c"], work / "corpus.bin"),
                (["./programs/lz4", "-d", "-c"], work / "corpus.lz4"),
            ],
        }[key]
        for argv, stdin_path in probes:
            _, completed = run(
                [str(binary()), "run", "--json", *flags(policy), "--", *argv],
                work, env, stdin_path,
            )
            try:
                report = json.loads(completed.stdout)
            except json.JSONDecodeError:
                report = None
            decisions.append(
                {
                    "command": " ".join(argv),
                    "decision": None if report is None else report.get("cache_decision"),
                    "classification": None if report is None else report.get("classification"),
                    "reasons": [] if report is None else (report.get("reasons") or [])[:2],
                }
            )
    footprint = 0
    if cache.exists():
        footprint = sum(path.stat().st_size for path in cache.rglob("*") if path.is_file())
    peak_rss = peak_memory(work, env)
    return {
        "total_ms": round(total, 2),
        "phases": entries,
        "repeated": {
            "count": len(repeated),
            "p50_ms": round(statistics.median(repeated), 2) if repeated else None,
            "p95_ms": round(percentile(repeated, 95), 2) if repeated else None,
        },
        "cache_bytes": footprint,
        "peak_rss_kb": peak_rss,
        "decisions": decisions,
    }


def percentile(values: list[float], percent: int) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percent / 100.0) * len(ordered) + 0.5) - 1))
    return ordered[index]


def peak_memory(work: Path, env: dict) -> int | None:
    # One representative tool invocation under `/usr/bin/time`; a session-wide peak would need a
    # cgroup, which an unprivileged process without systemd delegation cannot create here.
    if not Path("/usr/bin/time").is_file():
        return None
    if (work / "minigzip").is_file():
        command, stdin_path = ["./minigzip"], work / "corpus.bin"
    elif (work / "pngtest").is_file():
        command, stdin_path = ["./pngtest", "pngtest.png"], None
    else:
        command, stdin_path = ["./programs/lz4", "-1", "-c"], work / "corpus.bin"
    source = open(stdin_path, "rb") if stdin_path is not None else subprocess.DEVNULL
    completed = subprocess.run(
        ["/usr/bin/time", "-f", "%M", *command],
        cwd=work, env=env, stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        check=False,
    )
    if stdin_path is not None:
        source.close()
    try:
        return int(completed.stderr.decode().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="a")
    parser.add_argument("--repos", default="zlib,libpng,lz4")
    parser.add_argument("--policies", default=",".join(POLICIES))
    parser.add_argument("--output-dir", default="benchmarks/results/phase2j/sessions")
    args = parser.parse_args()
    keys = [item for item in args.repos.split(",") if item]
    policies = [item for item in args.policies.split(",") if item]
    root = Path(tempfile.mkdtemp(prefix="tracejit-sessions-"))
    results = {"session": args.session, "contract": CONTRACT, "repos": {}}
    for key in keys:
        scenario = SCENARIOS[key]
        if not Path(scenario["source"]).is_dir():
            raise SystemExit(f"missing checkout for {key}: {scenario['source']}")
        entry = {
            "name": scenario["name"],
            "commit": scenario["commit"],
            "policies": {},
        }
        for policy in policies:
            entry["policies"][policy] = session(key, root / f"{key}-{policy}", policy)
        direct = entry["policies"].get("direct", {}).get("total_ms") or 1.0
        for policy, measured in entry["policies"].items():
            measured["speedup"] = round(direct / measured["total_ms"], 3)
            measured["slowdown"] = round(measured["total_ms"] / direct, 3)
        results["repos"][key] = entry
        print(f"{key} {args.session}: " + ", ".join(
            f"{policy}={entry['policies'][policy]['total_ms']}ms/"
            f"{entry['policies'][policy]['speedup']}x" for policy in policies
        ))
    output = REPO / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"session-{args.session}.json"
    if target.exists():
        # Repositories are measured in separate invocations so a single command stays inside the
        # runner's time limit; keep the earlier repositories in the same session record.
        previous = json.loads(target.read_text())
        merged = previous.get("repos", {})
        for name, fresh in results["repos"].items():
            merged.setdefault(name, {"name": fresh["name"], "commit": fresh["commit"], "policies": {}})
            merged[name]["policies"].update(fresh["policies"])
            direct = merged[name]["policies"].get("direct", {}).get("total_ms")
            if direct:
                for measured in merged[name]["policies"].values():
                    measured["speedup"] = round(direct / measured["total_ms"], 3)
                    measured["slowdown"] = round(measured["total_ms"] / direct, 3)
        results["repos"] = merged
    target.write_text(json.dumps(results, indent=2) + "\n")
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

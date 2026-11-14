#!/usr/bin/env python3
"""Phase K8: independent competitive re-evaluation on current tip.

Arms: native, make, ninja, simple CAS (hashcache), TraceJIT.
Honest skips for tools that do not apply (ccache/sccache are compiler wrappers).
Does not invent numbers. Writes JSON + markdown under --output-dir.

Usage:
    cargo build --workspace --release
    python3 benchmarks/repos/phase_k8_competitive.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BINARY = REPO / "target/release/tracejit"
CONTRACT = "allocator-entropy-v1"
ASSETS = ("app.js", "vendor.js", "worker.js")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def which_or_none(name: str) -> str | None:
    return shutil.which(name)


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "sha256": sha256_file(path),
        "size": stat.st_size,
        "mode": oct(stat.st_mode & 0o7777),
        "mtime_ns": stat.st_mtime_ns,
    }


def summarize(samples_ms: list[float]) -> dict:
    if not samples_ms:
        return {"runs": 0}
    ordered = sorted(samples_ms)
    median = statistics.median(samples_ms)
    pstdev = statistics.pstdev(samples_ms) if len(samples_ms) > 1 else 0.0
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    return {
        "runs": len(samples_ms),
        "median_ms": round(median, 3),
        "p95_ms": round(p95, 3),
        "min_ms": round(min(samples_ms), 3),
        "max_ms": round(max(samples_ms), 3),
        "pstdev_ms": round(pstdev, 3),
        "samples_ms": [round(v, 3) for v in samples_ms],
    }


def base_env(cache: Path | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run_timed(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> tuple[float, subprocess.CompletedProcess[bytes]]:
    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    return (time.perf_counter() - started) * 1000.0, completed


def parse_report(stdout: bytes) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"kind": "NO_JSON", "raw": stdout.decode(errors="replace")[:500]}


def host_facts() -> dict:
    tools = {
        "make": which_or_none("make"),
        "ninja": which_or_none("ninja"),
        "ccache": which_or_none("ccache"),
        "sccache": which_or_none("sccache"),
        "bzip2": which_or_none("bzip2"),
        "cc": which_or_none("cc"),
    }
    return {
        "platform": platform.platform(),
        "kernel": platform.release(),
        "cpus": os.cpu_count(),
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "tools": tools,
    }


def write_assets(assets: Path) -> None:
    assets.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(ASSETS):
        (assets / name).write_text(
            "".join(f"const v{index}_{row}={row};\n" for row in range(8000))
        )


def write_makefile(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "BZ2 := " + " ".join(f"assets/{name}.bz2" for name in ASSETS),
                "all: $(BZ2)",
                "",
                "assets/%.bz2: assets/%",
                "\tbzip2 -9 -k -f $<",
                "\ttouch $@",
                "",
            ]
        )
    )


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
cache = Path('.hashcache'); objects = cache / 'objects'; objects.mkdir(parents=True, exist_ok=True)
hits = misses = 0
for name in sys.argv[1:]:
    source = Path(name); output = Path(name + '.bz2')
    content = hashlib.sha256(source.read_bytes()).hexdigest()
    key = hashlib.sha256((str(source) + '\\0' + content).encode()).hexdigest()
    stored = objects / (key + '.bz2')
    if stored.is_file():
        hits += 1
    else:
        misses += 1
        tmp = objects / (key + '.tmp')
        subprocess.run(['bzip2', '-9', '-c', str(source)], stdout=tmp.open('wb'), check=True)
        os.replace(tmp, stored)
    tmp = output.with_name(output.name + '.tmp')
    tmp.write_bytes(stored.read_bytes()); os.replace(tmp, output)
(cache / 'last.json').write_text(json.dumps({'hits': hits, 'misses': misses}) + '\\n')
"""


def competitive_build_suite(binary: Path, warmups: int, runs: int) -> dict:
    make_path = which_or_none("make")
    ninja_path = which_or_none("ninja")
    if not which_or_none("bzip2"):
        return {"scenario": "build-edit-recovery", "skipped": True, "reason": "bzip2 missing"}

    root = Path(tempfile.mkdtemp(prefix="phase-k8-build-"))
    try:
        assets = root / "assets"
        write_assets(assets)
        (root / "notes.txt").write_text("note\n")
        write_makefile(root / "Makefile")
        write_ninja(root / "build.ninja")
        (root / "hashcache.py").write_text(HASHCACHE)

        def delete_outputs() -> None:
            for name in ASSETS:
                (assets / f"{name}.bz2").unlink(missing_ok=True)

        def reference_outputs() -> dict[str, dict]:
            ref = root / "ref"
            if ref.exists():
                shutil.rmtree(ref)
            ref.mkdir()
            (ref / "assets").mkdir()
            result = {}
            for name in ASSETS:
                shutil.copy2(assets / name, ref / "assets" / name)
                subprocess.run(
                    ["bzip2", "-9", "-k", "-f", f"assets/{name}"],
                    cwd=ref,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                result[name] = fingerprint(ref / "assets" / f"{name}.bz2")
            return result

        def content_ok(expected: dict[str, dict]) -> tuple[bool, list[str]]:
            fails = []
            for name, exp in expected.items():
                path = assets / f"{name}.bz2"
                if not path.is_file():
                    fails.append(f"{name}: missing")
                    continue
                if fingerprint(path)["sha256"] != exp["sha256"]:
                    fails.append(f"{name}: content differs")
            return not fails, fails

        def run_native() -> tuple[float, list[str]]:
            started = time.perf_counter()
            for name in ASSETS:
                subprocess.run(
                    ["bzip2", "-9", "-k", "-f", f"assets/{name}"],
                    cwd=root,
                    env=base_env(),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return (time.perf_counter() - started) * 1000.0, []

        def run_make() -> tuple[float, list[str]]:
            ms, completed = run_timed(["make", "-s"], cwd=root, env=base_env())
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.decode(errors="replace"))
            return ms, ["make"]

        def run_ninja() -> tuple[float, list[str]]:
            assert ninja_path
            ms, completed = run_timed([ninja_path, "-f", "build.ninja"], cwd=root, env=base_env())
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.decode(errors="replace"))
            return ms, ["ninja"]

        def run_hashcache() -> tuple[float, list[str]]:
            ms, completed = run_timed(
                ["python3", "hashcache.py", *[f"assets/{name}" for name in ASSETS]],
                cwd=root,
                env=base_env(),
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.decode(errors="replace"))
            return ms, []

        tj_cache = root / "tj-cache"

        def run_tracejit() -> tuple[float, list[str]]:
            started = time.perf_counter()
            kinds = []
            for name in ASSETS:
                _ms, completed = run_timed(
                    [
                        str(binary),
                        "run",
                        "--json",
                        "--admission",
                        "always",
                        "--contract",
                        CONTRACT,
                        "--",
                        "bzip2",
                        "-9",
                        "-k",
                        "-f",
                        f"assets/{name}",
                    ],
                    cwd=root,
                    env=base_env(tj_cache),
                )
                report = parse_report(completed.stdout)
                kinds.append(str(report.get("kind") or report.get("cache_decision") or "UNKNOWN"))
            return (time.perf_counter() - started) * 1000.0, kinds

        phases = [
            "1_first_build",
            "2_identical_rerun",
            "3_outputs_deleted",
            "4_one_input_modified",
            "5_mtime_preserved_edit",
            "6_corrupted_output",
        ]

        arms: dict[str, object] = {}
        runners = {
            "native": run_native,
            "make": run_make if make_path else None,
            "ninja": run_ninja if ninja_path else None,
            "simple_cas": run_hashcache,
            "tracejit": run_tracejit,
        }

        for arm_name, runner in runners.items():
            if runner is None:
                arms[arm_name] = {
                    "skipped": True,
                    "reason": f"{arm_name} not installed",
                }
                continue

            delete_outputs()
            if arm_name == "simple_cas":
                shutil.rmtree(root / ".hashcache", ignore_errors=True)
            if arm_name == "tracejit":
                shutil.rmtree(tj_cache, ignore_errors=True)

            rows = []

            def measure_once(label: str, before=None) -> None:
                """Single establishing invocation (correctness-critical / cold-ish)."""
                if before:
                    before()
                expected = reference_outputs()
                ms, kinds = runner()
                ok, fails = content_ok(expected)
                rows.append(
                    {
                        "phase": label,
                        "timing": summarize([ms]),
                        "kinds": kinds,
                        "content_correct": ok,
                        "failures": fails,
                        "method": "single-invocation",
                    }
                )

            def measure_steady(label: str) -> None:
                """Warm identical-state samples after the workspace is already built."""
                expected = reference_outputs()
                for _ in range(warmups):
                    runner()
                measured = []
                kinds_last: list[str] = []
                for _ in range(max(1, runs)):
                    ms, kinds_last = runner()
                    measured.append(ms)
                ok, fails = content_ok(expected)
                rows.append(
                    {
                        "phase": label,
                        "timing": summarize(measured),
                        "kinds": kinds_last,
                        "content_correct": ok,
                        "failures": fails,
                        "method": "steady-state-after-warmup",
                    }
                )

            measure_once("1_first_build")
            measure_steady("2_identical_rerun")

            def delete_before() -> None:
                delete_outputs()

            measure_once("3_outputs_deleted", before=delete_before)

            def edit_one() -> None:
                path = assets / "app.js"
                path.write_text(path.read_text() + "\n// edited\n")

            measure_once("4_one_input_modified", before=edit_one)

            def mtime_edit() -> None:
                path = assets / "vendor.js"
                meta = path.stat()
                path.write_text(path.read_text() + "\n// stealth\n")
                os.utime(path, ns=(meta.st_atime_ns, meta.st_mtime_ns))

            measure_once("5_mtime_preserved_edit", before=mtime_edit)

            def corrupt() -> None:
                path = assets / "worker.js.bz2"
                if path.is_file():
                    path.write_bytes(b"CORRUPT")

            measure_once("6_corrupted_output", before=corrupt)

            arms[arm_name] = {"phases": rows}

        # ccache/sccache: not applicable to transparent bzip2 command caching.
        arms["ccache"] = {
            "skipped": True,
            "reason": "compiler wrapper; not a drop-in arm for transparent bzip2 command reuse",
            "installed": bool(which_or_none("ccache")),
        }
        arms["sccache"] = {
            "skipped": True,
            "reason": "compiler wrapper; not installed or not applicable to this workload",
            "installed": bool(which_or_none("sccache")),
        }

        return {
            "scenario": "build-edit-recovery",
            "phases": phases,
            "arms": arms,
            "asset_lines_each": 8000,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def short_etl_overhead(binary: Path, warmups: int, runs: int) -> dict:
    workload = REPO / "benchmarks/workloads/c-etl"
    etl = workload / "etl"
    subprocess.run(
        ["cc", "-O2", "-o", str(etl), str(workload / "main.c")],
        check=True,
    )
    (workload / "output").mkdir(exist_ok=True)

    def direct_once() -> float:
        ms, completed = run_timed([str(etl)], cwd=REPO, env=base_env())
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode(errors="replace"))
        return ms

    for _ in range(warmups):
        direct_once()
    direct_samples = [direct_once() for _ in range(runs)]

    root = Path(tempfile.mkdtemp(prefix="phase-k8-etl-"))
    try:
        cache = root / "cache"

        def tj_once() -> tuple[float, str]:
            ms, completed = run_timed(
                [str(binary), "run", "--json", "--admission", "always", "--", str(etl)],
                cwd=REPO,
                env=base_env(cache),
            )
            report = parse_report(completed.stdout)
            return ms, str(report.get("kind") or report.get("cache_decision") or "UNKNOWN")

        cold_ms, cold_kind = tj_once()
        for _ in range(warmups):
            tj_once()
        warm = []
        kinds = []
        for _ in range(runs):
            ms, kind = tj_once()
            warm.append(ms)
            kinds.append(kind)
        return {
            "scenario": "short-command-etl-overhead",
            "direct": summarize(direct_samples),
            "tracejit_cold_ms": round(cold_ms, 3),
            "tracejit_cold_kind": cold_kind,
            "tracejit_warm": summarize(warm),
            "tracejit_warm_kinds": kinds,
            "net_loss": summarize(warm)["median_ms"] > summarize(direct_samples)["median_ms"],
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write_markdown(document: dict, path: Path) -> None:
    lines = [
        "# Phase K8 competitive evaluation",
        "",
        f"- commit: `{document['commit']}`",
        f"- dirty: `{document['working_tree_dirty']}`",
        f"- binary sha256: `{document['binary_sha256'][:16]}…`",
        f"- warmups/runs: {document['warmups']}/{document['runs']}",
        "",
        "## Host tools",
        "",
        "```",
        json.dumps(document["host"]["tools"], indent=2),
        "```",
        "",
        "## Build/edit recovery (medians, content correctness)",
        "",
        "| Phase | native | make | ninja | simple_cas | TraceJIT |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    build = next(s for s in document["suite"] if s.get("scenario") == "build-edit-recovery")
    if build.get("skipped"):
        lines.append(f"Skipped: {build.get('reason')}")
    else:
        phases = build["phases"]
        for phase in phases:
            cells = [phase]
            for arm in ("native", "make", "ninja", "simple_cas", "tracejit"):
                arm_doc = build["arms"].get(arm, {})
                if arm_doc.get("skipped"):
                    cells.append("SKIP")
                    continue
                row = next(r for r in arm_doc["phases"] if r["phase"] == phase)
                med = row["timing"]["median_ms"]
                ok = "ok" if row["content_correct"] else "WRONG"
                cells.append(f"{med} / {ok}")
            lines.append("| " + " | ".join(str(c) for c in cells) + " |")

    etl = next(s for s in document["suite"] if s.get("scenario") == "short-command-etl-overhead")
    lines += [
        "",
        "## Short-command ETL overhead (retained loss)",
        "",
        f"- direct median: **{etl['direct']['median_ms']} ms**",
        f"- TraceJIT warm median: **{etl['tracejit_warm']['median_ms']} ms** kinds={etl['tracejit_warm_kinds']}",
        f"- net_loss: `{etl['net_loss']}`",
        "",
        "## Non-applicable baselines",
        "",
        "- ccache / sccache: compiler wrappers; not timed as transparent bzip2 command caches.",
        "",
        f"Raw JSON: `{document['json_path']}`",
        "",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        default=str(REPO / "benchmarks/results/phase_k8"),
    )
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    if not binary.is_file():
        print(f"missing binary: {binary}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip()
    )

    print("scenario build-edit-recovery", flush=True)
    build = competitive_build_suite(binary, args.warmups, args.runs)
    print("scenario short-command-etl", flush=True)
    etl = short_etl_overhead(binary, args.warmups, args.runs)

    json_path = output_dir / "competitive.json"
    md_path = output_dir / "competitive.md"
    document = {
        "label": "phase-k8",
        "commit": commit,
        "working_tree_dirty": dirty,
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
        "warmups": args.warmups,
        "runs": args.runs,
        "host": host_facts(),
        "suite": [build, etl],
        "json_path": str(json_path.relative_to(REPO)),
    }
    json_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    write_markdown(document, md_path)
    print(f"wrote {json_path}", flush=True)
    print(f"wrote {md_path}", flush=True)
    print(
        f"RESULT phase-k8 commit={commit[:12]} dirty={dirty} "
        f"etl_loss={etl.get('net_loss')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

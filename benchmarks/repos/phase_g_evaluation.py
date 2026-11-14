#!/usr/bin/env python3
"""Phase G: competitive evaluation, held-out sessions, and ablations.

Honest measured evidence only. Skips baselines that are not installed.
Does not invent numbers. Writes JSON + markdown under --output-dir.

Usage:
    cargo build --workspace --release
    python3 benchmarks/repos/phase_g_evaluation.py \\
        --phase-e-binary /path/to/7801748/tracejit
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

MULTI_OUTPUT_C = r"""
#define _POSIX_C_SOURCE 200809L
#include <fcntl.h>
#include <unistd.h>
#include <string.h>

static int write_all(int fd, const char *bytes, size_t n) {
    while (n) {
        ssize_t w = write(fd, bytes, n);
        if (w < 0) return -1;
        bytes += w; n -= (size_t)w;
    }
    return 0;
}

int main(void) {
    int in = open("input.txt", O_RDONLY);
    if (in < 0) return 1;
    char buf[4096];
    ssize_t n = read(in, buf, sizeof(buf));
    close(in);
    if (n < 0) return 1;
    int a = open("out_a.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    int b = open("out_b.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (a < 0 || b < 0) return 1;
    if (write_all(a, "A:", 2) || write_all(a, buf, (size_t)n)) return 1;
    if (write_all(b, "B:", 2) || write_all(b, buf, (size_t)n)) return 1;
    close(a); close(b);
    return 0;
}
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def which_or_none(name: str) -> str | None:
    return shutil.which(name)


def host_facts() -> dict:
    tools = {
        "make": which_or_none("make"),
        "ninja": which_or_none("ninja"),
        "ccache": which_or_none("ccache"),
        "sccache": which_or_none("sccache"),
        "cc": which_or_none("cc"),
        "bzip2": which_or_none("bzip2"),
        "gzip": which_or_none("gzip"),
        "perf": which_or_none("perf"),
        "strace": which_or_none("strace"),
    }
    fs = subprocess.check_output(
        ["findmnt", "-no", "FSTYPE,TARGET,OPTIONS", "-T", str(REPO)], text=True
    ).strip()
    return {
        "uname": platform.uname()._asdict(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "cpus": os.cpu_count(),
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "filesystem": fs,
        "tools": tools,
        "cwd": str(REPO),
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
        "rsd": round(pstdev / median, 4) if median else None,
        "samples_ms": [round(v, 3) for v in samples_ms],
    }


def base_env(cache: Path | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
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
    if extra:
        env.update(extra)
    return env


def parse_report(stdout: bytes) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"kind": "NO_JSON", "raw": stdout.decode(errors="replace")[:500]}


def run_timed(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 180,
) -> tuple[float, subprocess.CompletedProcess[bytes]]:
    started = time.perf_counter()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return (time.perf_counter() - started) * 1000.0, completed


def compile_c(source: Path, binary: Path, extra_flags: list[str] | None = None) -> None:
    cmd = ["cc", "-O2", "-Wall", "-Wextra", *(extra_flags or []), "-o", str(binary), str(source)]
    subprocess.run(cmd, check=True)


def compile_fixture(root: Path) -> Path:
    binary = root / "fixture-driver"
    compile_c(
        REPO / "tests/fixtures/fixture_driver.c",
        binary,
        ["-Werror", "-pthread"],
    )
    return binary


def compile_c_etl() -> Path:
    workload = REPO / "benchmarks/workloads/c-etl"
    binary = workload / "etl"
    compile_c(workload / "main.c", binary)
    return binary


def compile_c_transform() -> Path:
    workload = REPO / "benchmarks/workloads/c-transform"
    binary = workload / "transform"
    compile_c(workload / "main.c", binary)
    return binary


def compile_multi_output(root: Path) -> Path:
    source = root / "multi_output.c"
    binary = root / "multi_output"
    source.write_text(MULTI_OUTPUT_C)
    compile_c(source, binary)
    return binary


def kind_of(report: dict) -> str:
    return str(report.get("kind") or report.get("cache_decision") or "UNKNOWN")


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "sha256": sha256_file(path),
        "size": stat.st_size,
        "mode": oct(stat.st_mode & 0o7777),
        "mtime_ns": stat.st_mtime_ns,
    }


def measure_direct(
    argv: list[str],
    *,
    cwd: Path,
    warmups: int,
    runs: int,
    require_success: bool = True,
) -> dict:
    env = base_env()
    for _ in range(warmups):
        ms, completed = run_timed(argv, cwd=cwd, env=env)
        if require_success and completed.returncode != 0:
            raise RuntimeError(
                f"direct warmup failed rc={completed.returncode} argv={argv} cwd={cwd}\n"
                f"{completed.stderr.decode(errors='replace')[:500]}"
            )
    samples = []
    statuses = []
    for _ in range(runs):
        ms, completed = run_timed(argv, cwd=cwd, env=env)
        samples.append(ms)
        statuses.append(completed.returncode)
        if require_success and completed.returncode != 0:
            raise RuntimeError(
                f"direct run failed rc={completed.returncode} argv={argv} cwd={cwd}"
            )
    return {
        "arm": "direct",
        "argv": argv,
        "exit_codes": statuses,
        "timing": summarize(samples),
    }


def measure_tracejit_lifecycle(
    name: str,
    binary: Path,
    argv_tail: list[str],
    *,
    cwd: Path,
    warmups: int,
    runs: int,
    admission: str = "always",
    contract: str | None = None,
    guard_mode: str = "strict",
    extra_env: dict[str, str] | None = None,
    invalidate: callable | None = None,
    prepare: callable | None = None,
) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"phase-g-{name}-"))
    cache = root / "cache"
    phase_path = root / "phases.json"
    try:
        if prepare:
            prepare(cwd)

        def tj_cmd() -> list[str]:
            cmd = [str(binary), "run", "--json", "--admission", admission, "--guard-mode", guard_mode]
            if contract:
                cmd += ["--contract", contract]
            cmd += ["--", *argv_tail]
            return cmd

        def once(record_phase: bool) -> tuple[float, dict, dict]:
            if record_phase:
                phase_path.unlink(missing_ok=True)
                env = base_env(
                    cache,
                    {
                        "TRACEJIT_PHASE_TIMING": "1",
                        "TRACEJIT_PHASE_TIMING_PATH": str(phase_path),
                        **(extra_env or {}),
                    },
                )
            else:
                env = base_env(cache, extra_env)
            ms, completed = run_timed(tj_cmd(), cwd=cwd, env=env)
            report = parse_report(completed.stdout)
            phases = {}
            if record_phase and phase_path.is_file():
                try:
                    raw = json.loads(phase_path.read_text())
                    data = raw.get("phases", raw)
                    for key, value in data.items():
                        if isinstance(value, (int, float)):
                            phases[key] = round(value / 1e6, 3)
                except json.JSONDecodeError:
                    phases = {}
            report["_wall_ms"] = ms
            report["_status"] = completed.returncode
            return ms, report, phases

        cold_ms, cold_report, _ = once(False)
        warm_samples = []
        warm_kinds = []
        warm_phases = []
        for index in range(warmups + runs):
            ms, report, phases = once(True)
            if index < warmups:
                continue
            warm_samples.append(ms)
            warm_kinds.append(kind_of(report))
            warm_phases.append(phases)

        invalidation = None
        if invalidate is not None:
            invalidate(cwd)
            inv_ms, inv_report, _ = once(False)
            invalidation = {
                "wall_ms": round(inv_ms, 3),
                "kind": kind_of(inv_report),
                "classification": inv_report.get("classification"),
                "status": inv_report.get("_status"),
            }

        phase_medians = {}
        keys = sorted({k for row in warm_phases for k in row})
        for key in keys:
            values = [row[key] for row in warm_phases if key in row]
            if values:
                phase_medians[key] = round(statistics.median(values), 3)

        return {
            "name": name,
            "arm": f"tracejit-{admission}",
            "admission": admission,
            "guard_mode": guard_mode,
            "contract": contract,
            "argv": argv_tail,
            "cold_ms": round(cold_ms, 3),
            "cold_kind": kind_of(cold_report),
            "cold_classification": cold_report.get("classification"),
            "warm": summarize(warm_samples),
            "warm_kinds": warm_kinds,
            "all_warm_reused": all(k == "Reused" for k in warm_kinds) if warm_kinds else False,
            "phases_median_ms": phase_medians,
            "invalidation": invalidation,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def simple_cas_script() -> str:
    return """#!/usr/bin/env python3
import hashlib, os, subprocess, sys
from pathlib import Path
cache = Path('.simplecas')
objects = cache / 'objects'
objects.mkdir(parents=True, exist_ok=True)
# Usage: simplecas.py <input> <output> -- <command...>
args = sys.argv[1:]
sep = args.index('--')
inp, out = Path(args[0]), Path(args[1])
cmd = args[sep + 1:]
key = hashlib.sha256(inp.read_bytes() + b'\\0' + ' '.join(cmd).encode()).hexdigest()
stored = objects / key
if stored.is_file():
    out.write_bytes(stored.read_bytes())
    print(json.dumps({'hit': True, 'key': key}))
else:
    subprocess.run(cmd, check=True)
    stored.write_bytes(out.read_bytes())
    print(json.dumps({'hit': False, 'key': key}))
"""


# ---------------------------------------------------------------------------
# Suite scenarios
# ---------------------------------------------------------------------------


def scenario_cpu_transform(binary: Path, warmups: int, runs: int) -> dict:
    # Paths inside main.c are repo-relative; cwd must be the repository root.
    transform = compile_c_transform()
    (REPO / "benchmarks/workloads/c-transform/output").mkdir(exist_ok=True)
    numbers = REPO / "benchmarks/workloads/c-transform/numbers.txt"
    direct = measure_direct([str(transform)], cwd=REPO, warmups=warmups, runs=runs)
    tj = measure_tracejit_lifecycle(
        "cpu-heavy-transform",
        binary,
        [str(transform)],
        cwd=REPO,
        warmups=warmups,
        runs=runs,
        invalidate=lambda _work: numbers.write_bytes(numbers.read_bytes() + b"\n999\n"),
    )
    subprocess.run(
        ["git", "checkout", "--", "benchmarks/workloads/c-transform/numbers.txt"],
        cwd=REPO,
        check=False,
    )
    return {"scenario": "cpu-heavy-transform", "direct": direct, "tracejit": tj}


def scenario_short_etl(binary: Path, warmups: int, runs: int) -> dict:
    # Paths inside main.c are repo-relative; cwd must be the repository root.
    etl = compile_c_etl()
    (REPO / "benchmarks/workloads/c-etl/output").mkdir(exist_ok=True)
    direct = measure_direct([str(etl)], cwd=REPO, warmups=warmups, runs=runs)
    tj = measure_tracejit_lifecycle(
        "short-command-etl",
        binary,
        [str(etl)],
        cwd=REPO,
        warmups=warmups,
        runs=runs,
    )
    return {"scenario": "short-command-overhead-loss", "direct": direct, "tracejit": tj}


def scenario_compression(binary: Path, warmups: int, runs: int) -> dict:
    if not which_or_none("bzip2"):
        return {"scenario": "compression-bzip2", "skipped": True, "reason": "bzip2 not installed"}
    root = Path(tempfile.mkdtemp(prefix="phase-g-bz2-"))
    try:
        payload = root / "payload.bin"
        payload.write_bytes(os.urandom(256 * 1024) + b"tracejit-phase-g\n" * 1024)
        # Stable content for reuse across warm runs: rewrite once then keep.
        payload.write_bytes(b"phase-g-bzip2-" * 20000)
        out = root / "payload.bin.bz2"

        def prepare_delete(_cwd: Path) -> None:
            out.unlink(missing_ok=True)

        direct_samples = []
        env = base_env()
        for _ in range(warmups):
            out.unlink(missing_ok=True)
            run_timed(["bzip2", "-9", "-k", "-f", "payload.bin"], cwd=root, env=env)
        for _ in range(runs):
            out.unlink(missing_ok=True)
            ms, _ = run_timed(["bzip2", "-9", "-k", "-f", "payload.bin"], cwd=root, env=env)
            direct_samples.append(ms)

        # TraceJIT with contract; delete output each warm run so presence does not deopt.
        # Actually bzip2 with retained output can deopt on FileMetadata of destination.
        # Match Phase 2T: keep output and accept identical-rerun behaviour, also measure
        # deleted-output warm path separately.
        tj_always = measure_tracejit_lifecycle(
            "compression-bzip2-always",
            binary,
            ["bzip2", "-9", "-k", "-f", "payload.bin"],
            cwd=root,
            warmups=warmups,
            runs=runs,
            contract=CONTRACT,
            prepare=prepare_delete,
        )
        # Adaptive admission: first run measures, may skip tracing short work.
        tj_auto = measure_tracejit_lifecycle(
            "compression-bzip2-auto",
            binary,
            ["bzip2", "-9", "-k", "-f", "payload.bin"],
            cwd=root,
            warmups=max(1, warmups),
            runs=runs,
            admission="auto",
            contract=CONTRACT,
            prepare=prepare_delete,
        )
        return {
            "scenario": "compression-bzip2",
            "input_bytes": payload.stat().st_size,
            "direct": {"timing": summarize(direct_samples)},
            "tracejit_always": tj_always,
            "tracejit_auto": tj_auto,
            "correctness_model_note": (
                "TraceJIT discovers deps via tracing + guards; bzip2 stores input mtime. "
                "Content-addressed tools key on bytes only and may ignore metadata."
            ),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_c_compile(binary: Path, warmups: int, runs: int) -> dict:
    if not which_or_none("cc"):
        return {"scenario": "c-compile", "skipped": True, "reason": "cc not installed"}
    root = Path(tempfile.mkdtemp(prefix="phase-g-cc-"))
    try:
        src = root / "sample.c"
        src.write_text("int add(int a, int b) { return a + b; }\n")
        obj = root / "sample.o"
        direct_samples = []
        env = base_env()
        for _ in range(warmups):
            obj.unlink(missing_ok=True)
            run_timed(["cc", "-O2", "-c", "sample.c", "-o", "sample.o"], cwd=root, env=env)
        for _ in range(runs):
            obj.unlink(missing_ok=True)
            ms, _ = run_timed(["cc", "-O2", "-c", "sample.c", "-o", "sample.o"], cwd=root, env=env)
            direct_samples.append(ms)

        # Expected refuse (getrusage / getrandom) — retain as negative evidence.
        tj = measure_tracejit_lifecycle(
            "c-compile",
            binary,
            ["cc", "-O2", "-c", "sample.c", "-o", "sample.o"],
            cwd=root,
            warmups=2,
            runs=max(3, runs // 3),
            prepare=lambda _c: obj.unlink(missing_ok=True),
        )
        return {
            "scenario": "c-compile",
            "direct": {"timing": summarize(direct_samples)},
            "tracejit": tj,
            "expected": "refuse-or-ineligible (getrusage/getrandom typical)",
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_build_edit_and_recovery(binary: Path, warmups: int, runs: int) -> dict:
    """Make + simple CAS vs TraceJIT on bzip2 assets; includes mtime-preserved and corrupt."""
    if not which_or_none("bzip2"):
        return {"scenario": "build-edit-recovery", "skipped": True, "reason": "bzip2 missing"}
    make_path = which_or_none("make")
    ninja_path = which_or_none("ninja")
    ccache_path = which_or_none("ccache")
    sccache_path = which_or_none("sccache")
    skips = []
    if not make_path:
        skips.append("make")
    if not ninja_path:
        skips.append("ninja")
    if not ccache_path:
        skips.append("ccache")
    if not sccache_path:
        skips.append("sccache")

    root = Path(tempfile.mkdtemp(prefix="phase-g-build-"))
    try:
        assets = root / "assets"
        assets.mkdir()
        for index, name in enumerate(("app.js", "vendor.js", "worker.js")):
            (assets / name).write_text(
                "".join(f"const v{index}_{row}={row};\n" for row in range(8000))
            )
        (root / "notes.txt").write_text("note\n")

        makefile = root / "Makefile"
        makefile.write_text(
            "\n".join(
                [
                    "BZ2 := assets/app.js.bz2 assets/vendor.js.bz2 assets/worker.js.bz2",
                    "all: $(BZ2)",
                    "",
                    "assets/%.bz2: assets/%",
                    "\tbzip2 -9 -k -f $<",
                    "\ttouch $@",
                    "",
                ]
            )
        )

        # Simple CAS (hashcache) arm
        (root / "hashcache.py").write_text(
            """#!/usr/bin/env python3
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
        )

        def delete_outputs() -> None:
            for name in ("app.js", "vendor.js", "worker.js"):
                (assets / f"{name}.bz2").unlink(missing_ok=True)

        def edit(path: Path, text: str, preserve_mtime: bool = False) -> None:
            meta = path.stat()
            path.write_text(path.read_text() + text)
            if preserve_mtime:
                os.utime(path, ns=(meta.st_atime_ns, meta.st_mtime_ns))

        def fingerprint_outputs() -> dict[str, dict]:
            return {
                name: fingerprint(assets / f"{name}.bz2")
                for name in ("app.js", "vendor.js", "worker.js")
                if (assets / f"{name}.bz2").is_file()
            }

        def reference_outputs() -> dict[str, dict]:
            ref = root / "ref"
            if ref.exists():
                shutil.rmtree(ref)
            ref.mkdir()
            (ref / "assets").mkdir()
            result = {}
            for name in ("app.js", "vendor.js", "worker.js"):
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

        arms_results = {}

        # --- native ---
        def run_native() -> float:
            started = time.perf_counter()
            for name in ("app.js", "vendor.js", "worker.js"):
                subprocess.run(
                    ["bzip2", "-9", "-k", "-f", f"assets/{name}"],
                    cwd=root,
                    env=base_env(),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return (time.perf_counter() - started) * 1000.0

        # --- make ---
        def run_make() -> float:
            if not make_path:
                return float("nan")
            ms, completed = run_timed(["make", "-s"], cwd=root, env=base_env())
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.decode(errors="replace"))
            return ms

        # --- hashcache ---
        def run_hashcache() -> float:
            ms, completed = run_timed(
                [
                    "python3",
                    "hashcache.py",
                    "assets/app.js",
                    "assets/vendor.js",
                    "assets/worker.js",
                ],
                cwd=root,
                env=base_env(),
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.decode(errors="replace"))
            return ms

        # --- TraceJIT ---
        tj_cache = root / "tj-cache"

        def run_tracejit() -> tuple[float, list[str]]:
            started = time.perf_counter()
            kinds = []
            for name in ("app.js", "vendor.js", "worker.js"):
                ms, completed = run_timed(
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
                kinds.append(kind_of(report))
            return (time.perf_counter() - started) * 1000.0, kinds

        phases = [
            "1_first_build",
            "2_identical_rerun",
            "3_outputs_deleted",
            "4_one_input_modified",
            "5_mtime_preserved_edit",
            "6_corrupted_output",
        ]

        for arm_name, runner in (
            ("native", lambda: (run_native(), [])),
            ("make", lambda: (run_make(), ["make"])),
            ("simple_cas", lambda: (run_hashcache(), [])),
            ("tracejit", run_tracejit),
        ):
            if arm_name == "make" and not make_path:
                arms_results[arm_name] = {"skipped": True, "reason": "make not installed"}
                continue
            # Fresh workspace copy per arm would be cleaner; reset outputs between arms.
            delete_outputs()
            if arm_name == "simple_cas":
                shutil.rmtree(root / ".hashcache", ignore_errors=True)
            if arm_name == "tracejit":
                shutil.rmtree(tj_cache, ignore_errors=True)

            rows = []

            def measure(label: str, before=None) -> None:
                if before:
                    before()
                expected = reference_outputs()
                if arm_name == "tracejit":
                    ms, kinds = runner()
                else:
                    ms, kinds = runner()
                ok, fails = content_ok(expected)
                rows.append(
                    {
                        "scenario": label,
                        "ms": round(ms, 3) if ms == ms else None,
                        "kinds": kinds,
                        "content_correct": ok,
                        "failures": fails,
                        "outputs": fingerprint_outputs(),
                    }
                )

            measure("1_first_build")
            measure("2_identical_rerun")
            measure("3_outputs_deleted", before=delete_outputs)
            measure(
                "4_one_input_modified",
                before=lambda: edit(assets / "app.js", "\n// edit\n"),
            )
            measure(
                "5_mtime_preserved_edit",
                before=lambda: edit(assets / "vendor.js", "\n// mtime\n", preserve_mtime=True),
            )

            def corrupt() -> None:
                out = assets / "worker.js.bz2"
                if out.is_file():
                    out.write_bytes(b"CORRUPTED\n")

            measure("6_corrupted_output", before=corrupt)
            arms_results[arm_name] = {"phases": rows}

        return {
            "scenario": "build-edit-recovery",
            "skips": skips,
            "correctness_model_notes": {
                "make": (
                    "mtime/graph based; preserved-mtime content edit and corrupted output "
                    "can leave stale artifacts unless a content check is added."
                ),
                "simple_cas": (
                    "Hashes input bytes only; ignores TraceJIT-style path/metadata deps; "
                    "recovers corrupted outputs on next run if input hash still matches."
                ),
                "tracejit": (
                    "Synchronous guards on observed deps; discovers deps automatically; "
                    "may be slower on identical rerun but should not return stale bytes."
                ),
                "ccache_sccache_ninja": "Not installed on this host — skipped, not claimed.",
            },
            "arms": arms_results,
            "warmup_note": "single-shot phases (not median of many); competitive correctness focus",
            "warmups_unused": warmups,
            "runs_unused": runs,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_aba(binary: Path, warmups: int, runs: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-aba-"))
    try:
        fixture = compile_fixture(root)
        sessions = []
        for session in range(max(3, runs // 5)):
            work = root / f"s{session}"
            work.mkdir()
            cache = work / "cache"
            records = []
            for state in ("one", "two", "one"):
                (work / "input.txt").write_text(f"input {state}\n")
                (work / "output.txt").unlink(missing_ok=True)
                ms, completed = run_timed(
                    [
                        str(binary),
                        "run",
                        "--json",
                        "--admission",
                        "always",
                        "--",
                        str(fixture),
                        "plain_file_read",
                        str(work),
                    ],
                    cwd=work,
                    env=base_env(cache),
                )
                report = parse_report(completed.stdout)
                records.append(
                    {
                        "input": state,
                        "kind": kind_of(report),
                        "wall_ms": round(ms, 3),
                        "output": (work / "output.txt").read_text()
                        if (work / "output.txt").is_file()
                        else None,
                    }
                )
            sessions.append({"session": session, "records": records})
        thirds = [s["records"][2] for s in sessions]
        return {
            "scenario": "aba-candidate-reuse",
            "sessions": sessions,
            "third_invocation_kinds": [t["kind"] for t in thirds],
            "third_reused_count": sum(1 for t in thirds if t["kind"] == "Reused"),
            "third_wall": summarize([t["wall_ms"] for t in thirds]),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_large_hash(binary: Path, warmups: int, runs: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-large-"))
    try:
        fixture = compile_fixture(root)
        work = root / "work"
        work.mkdir()
        # ~8 MiB so hashing + CAS restore are visible above the timer floor.
        (work / "input.txt").write_bytes(b"phase-g-large\n" * ((8 << 20) // 14 + 1))
        direct = measure_direct(
            [str(fixture), "plain_file_read", str(work)],
            cwd=work,
            warmups=warmups,
            runs=runs,
        )
        # Clean output between direct samples already happened per invoke via overwrite.
        tj = measure_tracejit_lifecycle(
            "large-input-hash",
            binary,
            [str(fixture), "plain_file_read", str(work)],
            cwd=work,
            warmups=warmups,
            runs=runs,
            invalidate=lambda w: (w / "input.txt").write_bytes(
                (w / "input.txt").read_bytes() + b"X"
            ),
        )
        return {
            "scenario": "large-input-hashing",
            "input_bytes": (work / "input.txt").stat().st_size,
            "direct": direct,
            "tracejit": tj,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_multi_output(binary: Path, warmups: int, runs: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-multi-"))
    try:
        prog = compile_multi_output(root)
        (root / "input.txt").write_text("multi-output-payload\n")

        def wipe(_cwd: Path) -> None:
            (root / "out_a.txt").unlink(missing_ok=True)
            (root / "out_b.txt").unlink(missing_ok=True)

        direct = measure_direct([str(prog)], cwd=root, warmups=warmups, runs=runs)
        tj = measure_tracejit_lifecycle(
            "multi-output-restore",
            binary,
            [str(prog)],
            cwd=root,
            warmups=warmups,
            runs=runs,
            prepare=wipe,
        )
        # Validate both outputs after a warm hit.
        wipe(root)
        cache = root / "validate-cache"
        # cold
        run_timed(
            [str(binary), "run", "--json", "--admission", "always", "--", str(prog)],
            cwd=root,
            env=base_env(cache),
        )
        wipe(root)
        ms, completed = run_timed(
            [str(binary), "run", "--json", "--admission", "always", "--", str(prog)],
            cwd=root,
            env=base_env(cache),
        )
        report = parse_report(completed.stdout)
        a = (root / "out_a.txt").read_bytes() if (root / "out_a.txt").is_file() else b""
        b = (root / "out_b.txt").read_bytes() if (root / "out_b.txt").is_file() else b""
        return {
            "scenario": "multi-output-restore",
            "direct": direct,
            "tracejit": tj,
            "validation_hit": {
                "kind": kind_of(report),
                "wall_ms": round(ms, 3),
                "out_a_sha256": sha256_bytes(a),
                "out_b_sha256": sha256_bytes(b),
                "both_present": bool(a) and bool(b),
            },
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_nondeterministic(binary: Path, warmups: int, runs: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-nd-"))
    try:
        fixture = compile_fixture(root)
        (root / "input.txt").write_text("x\n")
        tj = measure_tracejit_lifecycle(
            "nondeterministic-refuse",
            binary,
            [str(fixture), "getrandom", str(root)],
            cwd=root,
            warmups=2,
            runs=max(3, runs // 3),
        )
        return {
            "scenario": "nondeterministic-refuse",
            "tracejit": tj,
            "expected": "Nondeterministic / not reused",
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_candidate_lookup(binary: Path, warmups: int, runs: int) -> dict:
    """High candidate-count lookup: fill bound then hit newest vs force miss walk."""
    root = Path(tempfile.mkdtemp(prefix="phase-g-cand-"))
    try:
        fixture = compile_fixture(root)
        results = []
        for bound in (1, 8, 32):
            work = root / f"b{bound}"
            work.mkdir()
            cache = work / "cache"
            phase_path = work / "phases.json"
            # Populate distinct input states up to bound.
            for state in range(bound):
                (work / "input.txt").write_bytes(f"state-{state}\n".encode() * 64)
                (work / "output.txt").unlink(missing_ok=True)
                run_timed(
                    [
                        str(binary),
                        "run",
                        "--json",
                        "--admission",
                        "always",
                        "--",
                        str(fixture),
                        "plain_file_read",
                        str(work),
                    ],
                    cwd=work,
                    env=base_env(cache, {"TRACEJIT_CANDIDATE_BOUND": str(bound)}),
                )
            # Newest hit
            (work / "input.txt").write_bytes(f"state-{bound - 1}\n".encode() * 64)
            newest_samples = []
            newest_phases = []
            for index in range(warmups + runs):
                phase_path.unlink(missing_ok=True)
                ms, completed = run_timed(
                    [
                        str(binary),
                        "run",
                        "--json",
                        "--admission",
                        "always",
                        "--",
                        str(fixture),
                        "plain_file_read",
                        str(work),
                    ],
                    cwd=work,
                    env=base_env(
                        cache,
                        {
                            "TRACEJIT_CANDIDATE_BOUND": str(bound),
                            "TRACEJIT_PHASE_TIMING": "1",
                            "TRACEJIT_PHASE_TIMING_PATH": str(phase_path),
                        },
                    ),
                )
                if index < warmups:
                    continue
                newest_samples.append(ms)
                if phase_path.is_file():
                    try:
                        payload = json.loads(phase_path.read_text())
                        raw = payload.get("phases", payload)
                        newest_phases.append(
                            {
                                k: round(v / 1e6, 3)
                                for k, v in raw.items()
                                if isinstance(v, (int, float))
                            }
                        )
                    except json.JSONDecodeError:
                        pass
            # Oldest target (may need to walk candidates)
            (work / "input.txt").write_bytes(b"state-0\n" * 64)
            oldest_samples = []
            oldest_kinds = []
            for index in range(warmups + runs):
                ms, completed = run_timed(
                    [
                        str(binary),
                        "run",
                        "--json",
                        "--admission",
                        "always",
                        "--",
                        str(fixture),
                        "plain_file_read",
                        str(work),
                    ],
                    cwd=work,
                    env=base_env(cache, {"TRACEJIT_CANDIDATE_BOUND": str(bound)}),
                )
                if index < warmups:
                    continue
                oldest_samples.append(ms)
                oldest_kinds.append(kind_of(parse_report(completed.stdout)))

            phase_med = {}
            keys = sorted({k for row in newest_phases for k in row})
            for key in keys:
                vals = [row[key] for row in newest_phases if key in row]
                if vals:
                    phase_med[key] = round(statistics.median(vals), 3)

            results.append(
                {
                    "bound": bound,
                    "newest_hit": summarize(newest_samples),
                    "newest_phases_median_ms": phase_med,
                    "oldest_target": summarize(oldest_samples),
                    "oldest_kinds": oldest_kinds,
                }
            )
        return {"scenario": "high-candidate-count-lookup", "bounds": results}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scenario_mixed_sequence(binary: Path, warmups: int, runs: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-mixed-"))
    try:
        fixture = compile_fixture(root)
        etl = compile_c_etl()
        (REPO / "benchmarks/workloads/c-etl/output").mkdir(exist_ok=True)
        (root / "input.txt").write_text("mixed\n")
        cache = root / "cache"
        sequence = []
        steps = [
            ("eligible-etl", [str(etl)], REPO, None),
            ("ineligible-getrandom", [str(fixture), "getrandom", str(root)], root, None),
            ("eligible-etl-again", [str(etl)], REPO, None),
            (
                "eligible-plain",
                [str(fixture), "plain_file_read", str(root)],
                root,
                None,
            ),
            ("ineligible-clock", [str(fixture), "clock_realtime", str(root)], root, None),
        ]
        # One cold pass through the sequence, then a warm pass.
        for label, argv, cwd, _ in steps:
            ms, completed = run_timed(
                [str(binary), "run", "--json", "--admission", "always", "--", *argv],
                cwd=cwd,
                env=base_env(cache),
            )
            report = parse_report(completed.stdout)
            sequence.append(
                {
                    "phase": "cold-pass",
                    "label": label,
                    "kind": kind_of(report),
                    "classification": report.get("classification"),
                    "wall_ms": round(ms, 3),
                }
            )
        for label, argv, cwd, _ in steps:
            ms, completed = run_timed(
                [str(binary), "run", "--json", "--admission", "always", "--", *argv],
                cwd=cwd,
                env=base_env(cache),
            )
            report = parse_report(completed.stdout)
            sequence.append(
                {
                    "phase": "warm-pass",
                    "label": label,
                    "kind": kind_of(report),
                    "classification": report.get("classification"),
                    "wall_ms": round(ms, 3),
                }
            )
        return {
            "scenario": "mixed-eligible-ineligible-sequence",
            "sequence": sequence,
            "warmups_unused": warmups,
            "runs_unused": runs,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Ablations
# ---------------------------------------------------------------------------


def ablation_candidate_limit(binary: Path, warmups: int, runs: int) -> dict:
    return scenario_candidate_lookup(binary, warmups, runs)


def ablation_guard_mode(binary: Path, warmups: int, runs: int) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-guard-"))
    try:
        fixture = compile_fixture(root)
        work = root / "work"
        work.mkdir()
        (work / "input.txt").write_bytes(b"guard-mode\n" * 200000)  # ~1.8 MiB
        rows = {}
        for mode in ("strict", "fast"):
            rows[mode] = measure_tracejit_lifecycle(
                f"guard-{mode}",
                binary,
                [str(fixture), "plain_file_read", str(work)],
                cwd=work,
                warmups=warmups,
                runs=runs,
                guard_mode=mode,
            )
        return {
            "ablation": "guard-mode-strict-vs-fast",
            "note": (
                "Fast may skip content hash after metadata match; Strict always hashes. "
                "Not a reordering toggle — measures pair validation cost difference."
            ),
            "modes": rows,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def ablation_adaptive_admission(binary: Path, warmups: int, runs: int) -> dict:
    etl = compile_c_etl()
    transform = compile_c_transform()
    (REPO / "benchmarks/workloads/c-etl/output").mkdir(exist_ok=True)
    (REPO / "benchmarks/workloads/c-transform/output").mkdir(exist_ok=True)
    rows = {}
    for admission in ("always", "auto", "never"):
        rows[f"etl-{admission}"] = measure_tracejit_lifecycle(
            f"etl-{admission}",
            binary,
            [str(etl)],
            cwd=REPO,
            warmups=warmups,
            runs=runs,
            admission=admission,
        )
        rows[f"transform-{admission}"] = measure_tracejit_lifecycle(
            f"transform-{admission}",
            binary,
            [str(transform)],
            cwd=REPO,
            warmups=max(1, warmups // 2),
            runs=max(5, runs // 2),
            admission=admission,
        )
    return {
        "ablation": "adaptive-admission",
        "note": "auto should avoid tracing short ETL; always pays cold+warm; never never caches",
        "rows": rows,
    }


def ablation_phase_f_opts(
    tip_binary: Path,
    phase_e_binary: Path | None,
    warmups: int,
    runs: int,
) -> dict:
    root = Path(tempfile.mkdtemp(prefix="phase-g-pf-"))
    try:
        fixture = compile_fixture(root)
        work = root / "work"
        work.mkdir()
        (work / "input.txt").write_bytes(b"phase-f-ablation\n" * ((4 << 20) // 16 + 1))
        tip = measure_tracejit_lifecycle(
            "phase-f-tip-large",
            tip_binary,
            [str(fixture), "plain_file_read", str(work)],
            cwd=work,
            warmups=warmups,
            runs=runs,
        )
        baseline = None
        if phase_e_binary and phase_e_binary.is_file():
            baseline = measure_tracejit_lifecycle(
                "phase-e-tip-large",
                phase_e_binary,
                [str(fixture), "plain_file_read", str(work)],
                cwd=work,
                warmups=warmups,
                runs=runs,
            )
        etl = compile_c_etl()
        (REPO / "benchmarks/workloads/c-etl/output").mkdir(exist_ok=True)
        short = measure_tracejit_lifecycle(
            "phase-f-tip-short",
            tip_binary,
            [str(etl)],
            cwd=REPO,
            warmups=warmups,
            runs=runs,
        )
        short_base = None
        if phase_e_binary and phase_e_binary.is_file():
            short_base = measure_tracejit_lifecycle(
                "phase-e-tip-short",
                phase_e_binary,
                [str(etl)],
                cwd=REPO,
                warmups=warmups,
                runs=runs,
            )
        return {
            "ablation": "phase-f-opts-vs-phase-e-tip",
            "phase_e_binary": str(phase_e_binary) if phase_e_binary else None,
            "phase_e_sha256": sha256_file(phase_e_binary)
            if phase_e_binary and phase_e_binary.is_file()
            else None,
            "tip_sha256": sha256_file(tip_binary),
            "large_file": {"tip": tip, "phase_e": baseline},
            "short_etl": {"tip": short, "phase_e": short_base},
            "lazy_decode_note": (
                "CandidateBytes lazy decode is always on; no runtime eager toggle. "
                "Complexity measured via record_decode_ns / sqlite_query_ns under "
                "high-candidate-count-lookup bounds."
            ),
            "stream_staging_note": (
                "Stream-hash CAS staging is compile-time in Phase F tip; "
                "compare tip vs Phase E tip warm large_file cas_restore_ns."
            ),
            "limit_note": (
                "SQL LIMIT equals TRACEJIT_CANDIDATE_BOUND; measured in "
                "high-candidate-count-lookup."
            ),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write_markdown(document: dict, path: Path) -> None:
    lines = [
        "# Phase G evaluation",
        "",
        f"Commit `{document['commit']}` · binary `{document['binary_sha256'][:16]}` · "
        f"{document['warmups']} warmups + {document['runs']} runs (suite defaults).",
        "",
        "## Host",
        "",
        f"- kernel: `{document['host']['kernel']}`",
        f"- rustc: `{document['host']['rustc']}`",
        f"- filesystem: `{document['host']['filesystem']}`",
        f"- cpus: `{document['host']['cpus']}`",
        "",
        "### Tooling availability",
        "",
        "| Tool | Path |",
        "| --- | --- |",
    ]
    for name, tool_path in document["host"]["tools"].items():
        lines.append(f"| {name} | `{tool_path or 'SKIPPED (not installed)'}` |")

    lines += ["", "## Suite summary", "", "| Scenario | Verdict / key number |", "| --- | --- |"]

    for row in document.get("suite", []):
        name = row.get("scenario", "?")
        if row.get("skipped"):
            lines.append(f"| {name} | SKIPPED: {row.get('reason')} |")
            continue
        if name == "cpu-heavy-transform":
            d = row["direct"]["timing"]["median_ms"]
            w = row["tracejit"]["warm"]["median_ms"]
            lines.append(
                f"| {name} | direct {d} ms → warm {w} ms "
                f"(reused={row['tracejit']['all_warm_reused']}) |"
            )
        elif name == "short-command-overhead-loss":
            d = row["direct"]["timing"]["median_ms"]
            w = row["tracejit"]["warm"]["median_ms"]
            lines.append(f"| {name} | direct {d} ms vs warm {w} ms (expect loss) |")
        elif name == "compression-bzip2":
            d = row["direct"]["timing"]["median_ms"]
            w = row["tracejit_always"]["warm"]["median_ms"]
            lines.append(
                f"| {name} | direct {d} ms → always-warm {w} ms "
                f"(reused={row['tracejit_always']['all_warm_reused']}) |"
            )
        elif name == "c-compile":
            lines.append(
                f"| {name} | cold_kind={row['tracejit']['cold_kind']} "
                f"class={row['tracejit'].get('cold_classification')} |"
            )
        elif name == "build-edit-recovery":
            tj = row["arms"].get("tracejit", {})
            make = row["arms"].get("make", {})
            lines.append(
                f"| {name} | skips={row.get('skips')}; "
                f"tracejit phases={len(tj.get('phases', []))}; "
                f"make skipped={make.get('skipped', False)} |"
            )
        elif name == "aba-candidate-reuse":
            lines.append(
                f"| {name} | third Reused {row['third_reused_count']}/"
                f"{len(row['third_invocation_kinds'])} |"
            )
        elif name == "large-input-hashing":
            d = row["direct"]["timing"]["median_ms"]
            w = row["tracejit"]["warm"]["median_ms"]
            lines.append(f"| {name} | direct {d} ms → warm {w} ms |")
        elif name == "multi-output-restore":
            v = row["validation_hit"]
            lines.append(
                f"| {name} | hit kind={v['kind']} both_present={v['both_present']} |"
            )
        elif name == "nondeterministic-refuse":
            lines.append(
                f"| {name} | cold_kind={row['tracejit']['cold_kind']} "
                f"warm_reused={row['tracejit']['all_warm_reused']} |"
            )
        elif name == "high-candidate-count-lookup":
            bits = []
            for b in row["bounds"]:
                bits.append(f"b{b['bound']} newest={b['newest_hit']['median_ms']}ms")
            lines.append(f"| {name} | {'; '.join(bits)} |")
        elif name == "mixed-eligible-ineligible-sequence":
            warm = [s for s in row["sequence"] if s["phase"] == "warm-pass"]
            lines.append(
                f"| {name} | warm kinds={[s['kind'] for s in warm]} |"
            )
        else:
            lines.append(f"| {name} | (see JSON) |")

    lines += ["", "## Ablations", ""]
    for row in document.get("ablations", []):
        lines.append(f"### {row.get('ablation') or row.get('scenario')}")
        lines.append("")
        lines.append("```")
        lines.append(json.dumps(row, indent=2)[:4000])
        lines.append("```")
        lines.append("")

    lines += [
        "",
        "## Raw paths",
        "",
        f"- JSON: `{document.get('json_path')}`",
        f"- Markdown: `{path}`",
        "",
        "Controlled-runtime claims: **not claimed** (not on main).",
        "",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument(
        "--phase-e-binary",
        default="",
        help="Optional Phase E tip binary (7801748) for Phase F ablation",
    )
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument(
        "--output-dir",
        default=str(REPO / "benchmarks/results/phase_g"),
    )
    parser.add_argument("--label", default="session-a")
    parser.add_argument(
        "--skip-slow-transform",
        action="store_true",
        help="Skip 250M-round c-transform (still recorded as skipped)",
    )
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    if not binary.is_file():
        print(f"missing binary: {binary}", file=sys.stderr)
        return 2
    phase_e = Path(args.phase_e_binary).resolve() if args.phase_e_binary else None

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO, text=True
        ).strip()
    )

    host = host_facts()
    print("RESULT phase-g-host tools=" + json.dumps(host["tools"]), flush=True)

    suite = []
    if args.skip_slow_transform:
        suite.append(
            {
                "scenario": "cpu-heavy-transform",
                "skipped": True,
                "reason": "skip-slow-transform flag",
            }
        )
    else:
        print("scenario cpu-heavy-transform", flush=True)
        suite.append(scenario_cpu_transform(binary, args.warmups, args.runs))

    print("scenario short-command-etl", flush=True)
    suite.append(scenario_short_etl(binary, args.warmups, args.runs))

    print("scenario compression", flush=True)
    suite.append(scenario_compression(binary, args.warmups, args.runs))

    print("scenario c-compile", flush=True)
    suite.append(scenario_c_compile(binary, args.warmups, args.runs))

    print("scenario build-edit-recovery", flush=True)
    suite.append(scenario_build_edit_and_recovery(binary, args.warmups, args.runs))

    print("scenario aba", flush=True)
    suite.append(scenario_aba(binary, args.warmups, args.runs))

    print("scenario large-hash", flush=True)
    suite.append(scenario_large_hash(binary, args.warmups, args.runs))

    print("scenario multi-output", flush=True)
    suite.append(scenario_multi_output(binary, args.warmups, args.runs))

    print("scenario nondeterministic", flush=True)
    suite.append(scenario_nondeterministic(binary, args.warmups, args.runs))

    print("scenario candidate-lookup", flush=True)
    suite.append(scenario_candidate_lookup(binary, args.warmups, max(8, args.runs // 2)))

    print("scenario mixed-sequence", flush=True)
    suite.append(scenario_mixed_sequence(binary, args.warmups, args.runs))

    ablations = []
    print("ablation guard-mode", flush=True)
    ablations.append(ablation_guard_mode(binary, args.warmups, args.runs))
    print("ablation adaptive-admission", flush=True)
    ablations.append(ablation_adaptive_admission(binary, args.warmups, max(8, args.runs // 2)))
    print("ablation phase-f-opts", flush=True)
    ablations.append(
        ablation_phase_f_opts(binary, phase_e, args.warmups, args.runs)
    )

    json_path = output_dir / f"evaluation-{args.label}.json"
    md_path = output_dir / f"evaluation-{args.label}.md"
    document = {
        "label": args.label,
        "commit": commit,
        "working_tree_dirty": dirty,
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
        "warmups": args.warmups,
        "runs": args.runs,
        "host": host,
        "suite": suite,
        "ablations": ablations,
        "json_path": str(json_path.relative_to(REPO)),
        "controlled_runtime_claimed": False,
    }
    json_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    write_markdown(document, md_path)
    print(f"wrote {json_path}", flush=True)
    print(f"wrote {md_path}", flush=True)
    print(
        "RESULT phase-g-evaluation "
        f"label={args.label} commit={commit[:12]} dirty={dirty} "
        f"suite={len(suite)} ablations={len(ablations)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

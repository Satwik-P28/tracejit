#!/usr/bin/env python3
"""Phase 2T: recurrence on existing installed projects, not synthetic assets.

Three real project artifacts are copied into isolated workspaces and compressed with the tool a
deployment or documentation job would normally use. The normal invocation is recorded before
TraceJIT is introduced. Each source is evaluated through a cold run, repeated runs, output loss,
a source edit, a fresh workspace with the same cache, and an environment change.

Usage:
    python3 benchmarks/repos/phase2t_real_workflows.py
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRACEJIT = REPO / "target/release/tracejit"
ROOT = Path("/tmp/tracejit-phase2t-real")
RESULTS = REPO / "benchmarks/results/phase2t"
CONTRACT = "allocator-entropy-v1"

SOURCE = [
    {
        "id": "jquery",
        "project": "jQuery",
        "path": "/usr/share/javascript/jquery/jquery.js",
        "normal": "bzip2 -9 -k -f jquery.js",
        "output": "jquery.js.bz2",
        "argv": ["bzip2", "-9", "-k", "-f", "jquery.js"],
        "stdout_output": False,
    },
    {
        "id": "expat",
        "project": "Expat",
        "path": "/usr/share/doc/libexpat1-dev/expat.html/reference.html",
        "normal": "gzip -9 -c reference.html > reference.html.gz",
        "output": "reference.html.gz",
        "argv": ["gzip", "-9", "-c", "reference.html"],
        "stdout_output": True,
    },
    {
        "id": "socat",
        "project": "Socat",
        "path": "/usr/share/doc/socat/socat.html",
        "normal": "gzip -9 -c socat.html > socat.html.gz",
        "output": "socat.html.gz",
        "argv": ["gzip", "-9", "-c", "socat.html"],
        "stdout_output": True,
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def environment(cache: Path | None) -> dict:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def run(argv: list[str], cwd: Path, env: dict) -> tuple[float, subprocess.CompletedProcess]:
    started = time.perf_counter()
    completed = subprocess.run(
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return (time.perf_counter() - started) * 1000.0, completed


def native(source: dict, work: Path, env: dict) -> tuple[float, bytes, int]:
    elapsed, completed = run(source["argv"], work, env)
    if source["stdout_output"]:
        (work / source["output"]).write_bytes(completed.stdout)
    return elapsed, completed.stdout, completed.returncode


def traced(source: dict, work: Path, env: dict) -> tuple[float, dict, int]:
    argv = [
        str(TRACEJIT), "run", "--json", "--contract", CONTRACT,
        "--", *source["argv"],
    ]
    elapsed, completed = run(argv, work, env)
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {"cache_decision": "NO_JSON", "error": completed.stderr.decode(errors="replace")[-300:]}
    if source["stdout_output"] and isinstance(report.get("stdout_bytes"), list):
        (work / source["output"]).write_bytes(bytes(report["stdout_bytes"]))
    return elapsed, report, completed.returncode


def reference(source: dict, work: Path) -> dict:
    temporary = ROOT / "references" / source["id"]
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    shutil.copy2(work / Path(source["path"]).name, temporary / Path(source["path"]).name)
    native(source, temporary, environment(None))
    output = temporary / source["output"]
    return {"sha256": sha256(output), "size": output.stat().st_size}


def case(source: dict, session: int) -> dict:
    work = ROOT / f"session-{session}" / source["id"]
    cache = ROOT / f"session-{session}" / f"{source['id']}-cache"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy2(source["path"], work / Path(source["path"]).name)
    env = environment(cache)
    expected = reference(source, work)
    rows = []

    def record(label: str, current_work: Path, current_env: dict, use_tracejit: bool) -> None:
        prior = sha256(current_work / source["output"]) if (current_work / source["output"]).is_file() else None
        if use_tracejit:
            ms, report, exit_code = traced(source, current_work, current_env)
            decision = report.get("cache_decision")
            classification = report.get("classification")
            reason = report.get("decision_reason")
        else:
            ms, _, exit_code = native(source, current_work, current_env)
            decision = classification = reason = None
        output = current_work / source["output"]
        rows.append({
            "case": label,
            "arm": "tracejit" if use_tracejit else "native",
            "ms": round(ms, 2),
            "exit": exit_code,
            "decision": decision,
            "classification": classification,
            "reason": reason,
            "sha256": sha256(output) if output.is_file() else None,
            "size": output.stat().st_size if output.is_file() else None,
            "matches_native_reference": output.is_file() and sha256(output) == expected["sha256"],
            "output_existed_before": prior is not None,
        })

    record("normal-first", work, env, False)
    record("tracejit-cold", work, env, True)
    for index in range(3):
        record(f"tracejit-repeat-{index + 1}", work, env, True)
    (work / source["output"]).unlink(missing_ok=True)
    record("output-deleted", work, env, True)
    with (work / Path(source["path"]).name).open("a") as handle:
        handle.write("\n<!-- phase2t source edit -->\n")
    expected = reference(source, work)
    record("source-edited", work, env, True)
    fresh = work.parent / f"{source['id']}-fresh"
    if fresh.exists():
        shutil.rmtree(fresh)
    fresh.mkdir()
    shutil.copy2(work / Path(source["path"]).name, fresh / Path(source["path"]).name)
    record("fresh-workspace-same-cache", fresh, env, True)
    changed_env = dict(env)
    changed_env["TZ"] = "Europe/Berlin"
    record("environment-changed", work, changed_env, True)
    warm = [row["ms"] for row in rows if row["case"].startswith("tracejit-repeat")]
    return {
        "project": source["project"],
        "source": source["path"],
        "source_bytes": (work / Path(source["path"]).name).stat().st_size,
        "source_sha256": sha256(work / Path(source["path"]).name),
        "normal_invocation": source["normal"],
        "warm_median_ms": round(statistics.median(warm), 2),
        "rows": rows,
        "cache_bytes": sum(path.stat().st_size for path in cache.rglob("*") if path.is_file()),
        "artifacts_correct": all(row["matches_native_reference"] for row in rows),
    }


def main() -> int:
    if not TRACEJIT.is_file():
        raise SystemExit("build the release workspace first")
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    results = []
    for source in SOURCE:
        if not Path(source["path"]).is_file():
            results.append({"project": source["project"], "available": False})
            continue
        entry = case(source, 1)
        entry["available"] = True
        results.append(entry)
    report = {
        "phase": "2T",
        "tracejit_sha256": sha256(TRACEJIT),
        "host": {"platform": platform.platform(), "kernel": platform.release()},
        "projects": results,
        "method": "real installed artifacts; no artificial repeat loop beyond the documented compression invocation",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "real_workflows.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        entry["project"]: {
            "available": entry.get("available"),
            "warm_median_ms": entry.get("warm_median_ms"),
            "correct": entry.get("artifacts_correct"),
            "decisions": [
                row["decision"] for row in entry.get("rows", [])
            ],
        }
        for entry in results
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reproduce the Phase 3H controlled-Python observations.

The workload is the original `python-csv-json` workload from the census:
`benchmarks/realworld/workloads/etl.py` over the same generated sales and
customer rows. Results are written under benchmarks/results/phase3h/.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = ROOT / "benchmarks/realworld/workloads/etl.py"
PROBES = ROOT / "benchmarks/phase3h/probes.py"
RESULTS = ROOT / "benchmarks/results/phase3h"
TRACEJIT = ROOT / "target/release/tracejit"
PYTHON = Path("/usr/bin/python3.12") if Path("/usr/bin/python3.12").exists() else Path(sys.executable)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_id(path: Path) -> str:
    output = subprocess.run(
        ["readelf", "-n", str(path)], capture_output=True, text=True, check=True
    ).stdout
    for line in output.splitlines():
        if "Build ID:" in line:
            return line.split("Build ID:", 1)[1].strip()
    return ""


def run(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=None if env is None else {**os.environ, **env},
        close_fds=True,
    )


def make_data(directory: Path) -> tuple[Path, Path]:
    sales = directory / "sales.csv"
    customers = directory / "customers.csv"
    sales.write_text(
        "sale_id,customer_id,amount_cents\n"
        + "".join(f"s{index:04d},c{index % 12:03d},{(index * 37) % 5000}\n" for index in range(1, 401)),
        encoding="utf-8",
    )
    customers.write_text(
        "customer_id,region\n"
        + "".join(
            f"c{index:03d},{['north', 'south', 'east', 'west'][index % 4]}\n"
            for index in range(12)
        ),
        encoding="utf-8",
    )
    return sales, customers


def trace_run(
    cache: Path,
    output: Path,
    sales: Path,
    customers: Path,
    env: dict[str, str],
    contract: str | None,
):
    command = [
        str(TRACEJIT),
        "run",
        "--json",
    ]
    if contract:
        command += ["--contract", contract]
    command += [
        "--",
        str(PYTHON),
        str(WORKLOAD),
        str(sales),
        str(customers),
        str(output),
    ]
    return run(command, {"TRACEJIT_CACHE_DIR": str(cache), **env})


def direct_run(output: Path, sales: Path, customers: Path, env: dict[str, str]):
    return run(
        [str(PYTHON), str(WORKLOAD), str(sales), str(customers), str(output)],
        env,
    )


def report(stdout: str):
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not TRACEJIT.exists():
        raise SystemExit(f"missing release binary: {TRACEJIT}; run cargo build --release")

    work = Path(tempfile.mkdtemp(prefix="tracejit-p3h-"))
    sales, customers = make_data(work)
    probe_identity = {
        "path": str(PYTHON),
        "sha256": sha256(PYTHON),
        "build_id": build_id(PYTHON),
        "version": subprocess.run(
            [str(PYTHON), "-V"], capture_output=True, text=True, check=True
        ).stdout.strip(),
    }
    libc = Path("/lib/x86_64-linux-gnu/libc.so.6")
    libc_identity = {"path": str(libc), "sha256": sha256(libc), "build_id": build_id(libc)}

    baseline_env = {"PYTHONDONTWRITEBYTECODE": "1", "MALLOC_ARENA_MAX": "1"}
    seeded_env = {**baseline_env, "PYTHONHASHSEED": "0"}

    variants = {}
    for name, env, contract in [
        ("unset", baseline_env, None),
        ("seeded", seeded_env, None),
        ("seeded_allocator_contract", seeded_env, "allocator-entropy-v1"),
        ("seeded_python_runtime_contract", seeded_env, "python-runtime-v1"),
    ]:
        direct_output = work / f"{name}-direct.json"
        direct = direct_run(direct_output, sales, customers, env)
        cache = work / f"{name}-cache"
        # The output path is part of argv and therefore part of the cache identity. Both
        # traced invocations must use the same path or the second run cannot match the first.
        traced_output = work / f"{name}-traced.json"
        first = trace_run(cache, traced_output, sales, customers, env, contract)
        first_output_hash = sha256(traced_output)
        second = trace_run(cache, traced_output, sales, customers, env, contract)
        first_report = report(first.stdout)
        second_report = report(second.stdout)
        variants[name] = {
            "env": env,
            "contract": contract,
            "direct": {
                "status": direct.returncode,
                "stdout": direct.stdout,
                "stderr": direct.stderr,
                "output_sha256": sha256(direct_output),
            },
            "first": {
                "status": first.returncode,
                "stderr": first.stderr,
                "report": first_report,
                "output_sha256": first_output_hash,
            },
            "second": {
                "status": second.returncode,
                "stderr": second.stderr,
                "report": second_report,
                "output_sha256": sha256(traced_output),
            },
        }

    # Direct syscall and stack evidence. The vDSO is intentionally not disarmed
    # here, so absence of a clock syscall is evidence that direct strace alone
    # cannot see all clock reads.
    strace_dir = RESULTS / "strace"
    strace_dir.mkdir(exist_ok=True)
    traces = {}
    for mode in ["startup", "clocks", "identity", "entropy", "counterexample"]:
        path = strace_dir / f"{mode}.strace"
        result = run(
            [
                "strace",
                "-f",
                "-k",
                "-qq",
                "-e",
                "trace=clock_gettime,gettimeofday,time,gettid,getpid,getppid,getrandom",
                "-o",
                str(path),
                str(PYTHON),
                str(PROBES),
                mode,
            ],
            baseline_env,
        )
        traces[mode] = {
            "status": result.returncode,
            "stdout": result.stdout,
            "strace": str(path.relative_to(ROOT)),
            "lines": path.read_text(encoding="utf-8", errors="replace").splitlines(),
        }

    # Research-only prototype: a symbol-level virtualization shows which
    # observations can be changed by LD_PRELOAD and which cannot (getttid is a
    # direct CPython syscall, so LD_PRELOAD cannot intercept it).
    shim = work / "virtualize.so"
    build = run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-O2",
            "-o",
            str(shim),
            str(ROOT / "benchmarks/phase3h/virtualize.c"),
            "-ldl",
        ]
    )
    prototypes = {}
    if build.returncode == 0:
        for mode in ["clocks", "identity", "both"]:
            result = run(
                [str(PYTHON), str(PROBES), "counterexample"],
                {
                    **baseline_env,
                    "LD_PRELOAD": str(shim),
                    "PHASE3H_VIRTUALIZE": mode,
                },
            )
            prototypes[mode] = {
                "status": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

    document = {
        "phase": "3H",
        "workload": "python-csv-json",
        "interpreter": probe_identity,
        "libc": libc_identity,
        "variants": variants,
        "traces": traces,
        "prototypes": prototypes,
        "note": (
            "Tracing the original workload is not equivalent to a controlled cache hit. "
            "The contract result is reported separately; no reuse is claimed unless "
            "the acceptance checks pass."
        ),
    }
    destination = RESULTS / "python-observations.json"
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(destination)
    for name, variant in variants.items():
        print(
            name,
            "direct", variant["direct"]["output_sha256"],
            "first", variant["first"]["output_sha256"],
            "second", variant["second"]["output_sha256"],
            "second_kind", (variant["second"]["report"] or {}).get("kind"),
        )
    print("prototypes", json.dumps(prototypes, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

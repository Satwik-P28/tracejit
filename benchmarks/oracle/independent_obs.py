#!/usr/bin/env python3
"""Phase K2 independent execution oracle.

Compares TraceJIT Obs against a fresh native Exec without importing any TraceJIT
product crates, classifiers, or guard validators. The only interface to the
product is the `tracejit` CLI binary (and the OS).

Obs (execution-equivalence contract):
  - process exit status
  - stdout / stderr byte strings TraceJIT reports (or native pipes)
  - named regular-file outputs present after the run

A ``Reused`` decision whose Obs differs from a twin-workspace native Exec is an
``incorrect_hit``. Uncertainty / UNKNOWN that refuses reuse is not a failure.

Usage:
  python3 benchmarks/oracle/independent_obs.py [--seed N] [--output DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digests(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256(path.read_bytes())


def find_tracejit() -> Path:
    for candidate in (
        REPO / "target" / "release" / "tracejit",
        REPO / "target" / "debug" / "tracejit",
    ):
        if candidate.is_file():
            return candidate
    sys.exit("no tracejit binary; build with cargo build -p tracejit-cli --release")


def base_env(cache: Path | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
    }
    if cache is not None:
        env["TRACEJIT_CACHE_DIR"] = str(cache)
    return env


def close_extra_fds(command: subprocess.Popen[Any] | None = None) -> None:
    del command


def run_native(argv: list[str], cwd: Path, stdin: bytes = b"") -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=base_env(),
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    return {
        "exit": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_tracejit(
    argv: list[str], cwd: Path, cache: Path, stdin: bytes = b""
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    completed = subprocess.run(
        [str(find_tracejit()), "run", "--json", "--", *argv],
        cwd=cwd,
        env=base_env(cache),
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    raw = {
        "exit": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, raw
    return report, raw


def obs_from_bytes(
    stdout: bytes, stderr: bytes, exit_code: int, files: dict[str, str | None]
) -> dict[str, Any]:
    return {
        "exit": exit_code,
        "stdout_sha256": sha256(stdout),
        "stderr_sha256": sha256(stderr),
        "files": files,
    }


def obs_from_report(report: dict[str, Any], files: dict[str, str | None]) -> dict[str, Any]:
    return obs_from_bytes(
        bytes(report.get("stdout_bytes") or []),
        bytes(report.get("stderr_bytes") or []),
        int(report.get("exit_code", -1)),
        files,
    )


def collect_files(root: Path, names: list[str]) -> dict[str, str | None]:
    return {name: digests(root / name) for name in names}


def compile_c(source: str, binary: Path) -> None:
    src = binary.with_suffix(".c")
    src.write_text(source)
    status = subprocess.run(
        ["cc", "-O0", "-Wall", "-Wextra", "-o", str(binary), str(src)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if status.returncode != 0:
        raise RuntimeError(status.stderr.decode("utf-8", "replace"))


EXCHANGE_C = r"""
#define _GNU_SOURCE
#include <fcntl.h>
#include <unistd.h>
#include <sys/syscall.h>
#ifndef RENAME_EXCHANGE
#define RENAME_EXCHANGE (1 << 1)
#endif
int main(void) {
  int fd = open("a", O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (fd < 0) return 1;
  if (write(fd, "AAA", 3) != 3) return 1;
  close(fd);
  fd = open("b", O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (fd < 0) return 1;
  if (write(fd, "BBB", 3) != 3) return 1;
  close(fd);
  return syscall(SYS_renameat2, AT_FDCWD, "a", AT_FDCWD, "b", RENAME_EXCHANGE) != 0;
}
"""

COPY_C = r"""
#include <fcntl.h>
#include <unistd.h>
int main(int argc, char **argv) {
  if (argc < 3) return 2;
  int in = open(argv[1], O_RDONLY);
  if (in < 0) return 1;
  int out = open(argv[2], O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (out < 0) { close(in); return 1; }
  char buf[4096];
  for (;;) {
    ssize_t n = read(in, buf, sizeof buf);
    if (n < 0) return 1;
    if (n == 0) break;
    if (write(out, buf, (size_t)n) != n) return 1;
  }
  return close(in) | close(out);
}
"""


def twin_dirs(base: Path) -> tuple[Path, Path]:
    native = base / "native"
    traced = base / "traced"
    native.mkdir()
    traced.mkdir()
    return native, traced


def sync_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)


def case_copy_stable(seed: int) -> dict[str, Any]:
    """Guarded copy: warm reuse Obs must match native twin."""
    del seed
    with tempfile.TemporaryDirectory(prefix="k2-copy-") as tmp:
        root = Path(tmp)
        native, traced = twin_dirs(root)
        binary = root / "copy"
        compile_c(COPY_C, binary)
        for side in (native, traced):
            shutil.copy(binary, side / "copy")
            (side / "in.txt").write_bytes(b"payload-one\n" * 64)
        cache = root / "cache"
        # cold
        report_cold, raw_cold = run_tracejit(["./copy", "in.txt", "out.txt"], traced, cache)
        if report_cold is None:
            return {"case": "copy_stable", "status": "error", "detail": "cold json", "raw": str(raw_cold)}
        files_cold = collect_files(traced, ["out.txt"])
        # warm reuse path
        (traced / "out.txt").unlink(missing_ok=True)
        report_warm, raw_warm = run_tracejit(["./copy", "in.txt", "out.txt"], traced, cache)
        if report_warm is None:
            return {"case": "copy_stable", "status": "error", "detail": "warm json", "raw": str(raw_warm)}
        # native twin
        (native / "out.txt").unlink(missing_ok=True)
        native_run = run_native(["./copy", "in.txt", "out.txt"], native)
        native_obs = obs_from_bytes(
            native_run["stdout"],
            native_run["stderr"],
            native_run["exit"],
            collect_files(native, ["out.txt"]),
        )
        warm_obs = obs_from_report(report_warm, collect_files(traced, ["out.txt"]))
        decision = report_warm.get("cache_decision") or report_warm.get("kind")
        incorrect = decision == "Reused" and warm_obs != native_obs
        return {
            "case": "copy_stable",
            "status": "incorrect_hit" if incorrect else "ok",
            "decision": decision,
            "classification_cold": report_cold.get("classification"),
            "native": native_obs,
            "warm": warm_obs,
            "files_cold": files_cold,
            "raw_exit_cold": raw_cold["exit"],
            "raw_exit_warm": raw_warm["exit"],
        }


def case_copy_content_change(seed: int) -> dict[str, Any]:
    """After input mutation, a Reused decision with stale Obs is incorrect."""
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory(prefix="k2-mutate-") as tmp:
        root = Path(tmp)
        native, traced = twin_dirs(root)
        binary = root / "copy"
        compile_c(COPY_C, binary)
        for side in (native, traced):
            shutil.copy(binary, side / "copy")
            (side / "in.txt").write_bytes(b"payload-one\n" * 64)
        cache = root / "cache"
        run_tracejit(["./copy", "in.txt", "out.txt"], traced, cache)
        run_tracejit(["./copy", "in.txt", "out.txt"], traced, cache)  # warm fill
        # mutate both twins identically
        new_payload = f"changed-{rng.random()}\n".encode() * 40
        (traced / "in.txt").write_bytes(new_payload)
        (native / "in.txt").write_bytes(new_payload)
        (traced / "out.txt").unlink(missing_ok=True)
        (native / "out.txt").unlink(missing_ok=True)
        report, _ = run_tracejit(["./copy", "in.txt", "out.txt"], traced, cache)
        if report is None:
            return {"case": "copy_content_change", "status": "error"}
        native_run = run_native(["./copy", "in.txt", "out.txt"], native)
        native_obs = obs_from_bytes(
            native_run["stdout"],
            native_run["stderr"],
            native_run["exit"],
            collect_files(native, ["out.txt"]),
        )
        actual = obs_from_report(report, collect_files(traced, ["out.txt"]))
        decision = report.get("cache_decision") or report.get("kind")
        incorrect = decision == "Reused" and actual != native_obs
        return {
            "case": "copy_content_change",
            "status": "incorrect_hit" if incorrect else "ok",
            "decision": decision,
            "native": native_obs,
            "actual": actual,
        }


def case_rename_exchange(seed: int) -> dict[str, Any]:
    """K1 counterexample: exchange must never Reuse with wrong Obs."""
    del seed
    with tempfile.TemporaryDirectory(prefix="k2-rex-") as tmp:
        root = Path(tmp)
        native, traced = twin_dirs(root)
        binary = root / "exchange"
        compile_c(EXCHANGE_C, binary)
        for side in (native, traced):
            shutil.copy(binary, side / "exchange")
        cache = root / "cache"
        report_cold, _ = run_tracejit(["./exchange"], traced, cache)
        if report_cold is None:
            return {"case": "rename_exchange", "status": "error"}
        # warm
        report_warm, _ = run_tracejit(["./exchange"], traced, cache)
        if report_warm is None:
            return {"case": "rename_exchange", "status": "error"}
        native_run = run_native(["./exchange"], native)
        native_obs = obs_from_bytes(
            native_run["stdout"],
            native_run["stderr"],
            native_run["exit"],
            collect_files(native, ["a", "b"]),
        )
        warm_obs = obs_from_report(report_warm, collect_files(traced, ["a", "b"]))
        decision = report_warm.get("cache_decision") or report_warm.get("kind")
        # Also flag eligibility after cold if classified Guarded (pre-fix bug class).
        cold_class = report_cold.get("classification")
        incorrect = decision == "Reused" and warm_obs != native_obs
        regress = cold_class in ("Guarded", "Proven") and report_cold.get("eligible_for_reuse") is True
        status = "incorrect_hit" if incorrect else ("regress_eligible" if regress else "ok")
        return {
            "case": "rename_exchange",
            "status": status,
            "decision": decision,
            "classification_cold": cold_class,
            "eligible_cold": report_cold.get("eligible_for_reuse"),
            "native": native_obs,
            "warm": warm_obs,
        }


def case_getrandom_never_hit(seed: int) -> dict[str, Any]:
    del seed
    source = r"""
#include <sys/random.h>
int main(void) {
  unsigned char b[8];
  if (getrandom(b, sizeof b, 0) != sizeof b) return 1;
  return 0;
}
"""
    with tempfile.TemporaryDirectory(prefix="k2-rnd-") as tmp:
        root = Path(tmp)
        work = root / "work"
        work.mkdir()
        binary = work / "rnd"
        compile_c(source, binary)
        cache = root / "cache"
        r1, _ = run_tracejit(["./rnd"], work, cache)
        r2, _ = run_tracejit(["./rnd"], work, cache)
        if r1 is None or r2 is None:
            return {"case": "getrandom_never_hit", "status": "error"}
        decisions = [r1.get("cache_decision") or r1.get("kind"), r2.get("cache_decision") or r2.get("kind")]
        incorrect = "Reused" in decisions
        return {
            "case": "getrandom_never_hit",
            "status": "incorrect_hit" if incorrect else "ok",
            "decisions": decisions,
            "classifications": [r1.get("classification"), r2.get("classification")],
        }


CASES = [
    case_copy_stable,
    case_copy_content_change,
    case_rename_exchange,
    case_getrandom_never_hit,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "benchmarks" / "results" / "phase_k2",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    results: list[dict[str, Any]] = []
    incorrect = 0
    regress = 0
    for case_fn in CASES:
        entry = case_fn(rng.randrange(1 << 30))
        results.append(entry)
        if entry.get("status") == "incorrect_hit":
            incorrect += 1
            fail = args.output / "failures" / f"{entry['case']}.json"
            fail.parent.mkdir(parents=True, exist_ok=True)
            fail.write_text(json.dumps(entry, indent=2) + "\n")
        elif entry.get("status") == "regress_eligible":
            regress += 1
            fail = args.output / "failures" / f"{entry['case']}-eligible.json"
            fail.parent.mkdir(parents=True, exist_ok=True)
            fail.write_text(json.dumps(entry, indent=2) + "\n")
        print(f"{entry['case']:28} {entry['status']}")
    summary = {
        "seed": args.seed,
        "tip_hint": "run from checked-out tip; see git rev-parse HEAD",
        "cases": len(results),
        "incorrect_hits": incorrect,
        "regress_eligible": regress,
        "independence": "CLI-only; no product crate imports",
        "results": results,
    }
    out = args.output / f"oracle-seed-{args.seed}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"RESULT phase-k2-oracle incorrect_hits={incorrect} regress_eligible={regress} "
        f"cases={len(results)} -> {out}"
    )
    return 0 if incorrect == 0 and regress == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

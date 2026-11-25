#!/usr/bin/env python3
"""Phase AE: one environment's exact fingerprint and capability probe.

The output is deliberately small and machine-readable so a workflow can publish it as a
build annotation (annotations are public on a run page; step logs need authentication).

It runs:

* ``uname``, ``/etc/os-release``, the glibc version,
* the active LSM list and the Landlock selftest the kernel exposes,
* the filesystem type of the workspace and of a tmpfs scratch directory,
* TraceJIT's own ``doctor --json`` capability view,
* an enforcement probe: two runs of the same command with ``--enforce``, recording whether
  the first is traced and whether the second is reused *under enforcement*, and whether a
  non-capable host refuses to label the reuse as PROVEN.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

sys.path.insert(0, str(REPO / "benchmarks" / "realworld_v2"))
import runner  # noqa: E402


def read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def command(argv: list[str]) -> str | None:
    completed = subprocess.run(argv, capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        return None
    return (completed.stdout or completed.stderr).strip()


def filesystem(path: Path) -> dict:
    # `stat -f %T` reports the magic's generic family (ext2/ext3 for ext4), so prefer
    # findmnt, which reports the mounted filesystem's actual type.
    completed = subprocess.run(["findmnt", "-no", "FSTYPE", "--target", str(path)],
                               capture_output=True, text=True)
    return {"path": str(path), "type": completed.stdout.strip() or None}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseae-probe")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    scratch = args.scratch
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    lsms = read("/sys/kernel/security/lsm")
    landlock_selftest = Path("/sys/kernel/security/landlock")

    doctor_text = command([str(args.tracejit), "doctor", "--json"])
    doctor = json.loads(doctor_text) if doctor_text else None

    probe = {
        "host": {
            "uname": platform.uname()._asdict(),
            "os_release": read("/etc/os-release"),
            "glibc": command(["ldd", "--version"]),
            "cpu_count": os.cpu_count(),
            "lsms": lsms,
            "landlock_selftest_dir": landlock_selftest.exists(),
            "cgroup": read("/proc/self/cgroup"),
            "container": read("/run/.containerenv") is not None or Path("/.dockerenv").exists(),
        },
        "filesystems": [filesystem(REPO), filesystem(Path("/dev/shm"))],
        "doctor": doctor,
        "enforcement": {},
    }

    # Enforcement probe: the same command twice with --enforce.  A capable host must install
    # seccomp + Landlock and then reuse; an incapable host must say so rather than silently
    # presenting GUARDED reuse as PROVEN.
    ws = scratch / "ws"
    ws.mkdir()
    (ws / "corpus.txt").write_bytes(b"probe line\n" * 20_000)
    cache = scratch / "cache"
    env = runner.cache_env(dict(os.environ), cache)
    runs = []
    for _ in range(2):
        (ws / "corpus.txt.gz").unlink(missing_ok=True)
        completed = subprocess.run(
            [str(args.tracejit), "run", "--enforce", "--contract", "allocator-entropy-v1",
             "--verbose", "--", "gzip", "-9", "-n", "-k", "-f", "corpus.txt"],
            cwd=ws, env=env, capture_output=True, check=False,
        )
        report = completed.stderr.decode(errors="replace")
        decision = runner.parse_plain_decision(completed.stderr)
        runs.append({
            "exit": completed.returncode,
            "kind": (decision or {}).get("kind"),
            "cache_decision": (decision or {}).get("cache_decision"),
            "enforced": "enforced       yes" in report,
            "policy_lines": [line for line in report.splitlines()
                             if line.startswith(("enforce", "policy", "sandbox", "problem", "guards"))],
            "output_ok": (ws / "corpus.txt.gz").is_file(),
        })
    probe["enforcement"] = {
        "runs": runs,
        "second_run_reused": bool(runs[1]["kind"] == "Reused"),
        "second_run_enforced": bool(runs[1]["enforced"]),
        "label_consistent": (not runs[1]["enforced"]) or bool((doctor or {}).get("proven")),
    }

    text = json.dumps(probe, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

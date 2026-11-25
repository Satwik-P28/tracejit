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
    # The probe runs commands with cwd set to a scratch directory, so a relative --tracejit
    # path would resolve against the wrong directory.
    tracejit = args.tracejit.resolve()
    lsms = read("/sys/kernel/security/lsm")
    landlock_selftest = Path("/sys/kernel/security/landlock")

    doctor_text = command([str(tracejit), "doctor", "--json"])
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

    # Two probes, because they measure different things:
    #
    # * ``guarded``  the same command twice with no ``--enforce``: this is the reuse path a
    #                host without Landlock actually supports, and its second run must reuse.
    # * ``enforce``  the same command twice with ``--enforce``: reuse here requires a PROVEN
    #                candidate (``lib.rs``: ``!options.enforce || classification == Proven``),
    #                so a host that cannot install seccomp+Landlock must never reuse, must
    #                never label the run PROVEN, and must not fail the command either.
    #
    # Inferring enforcement from whether the *label* matched ``doctor.proven`` is a tautology
    # when both are false, which is what the Phase AD/AE probe did before this correction.
    ws = scratch / "ws"
    ws.mkdir()
    (ws / "corpus.txt").write_bytes(b"probe line\n" * 20_000)
    workload_argv = ["gzip", "-9", "-n", "-k", "-f", "corpus.txt"]
    # The enforce arm uses a read-only command: a restrictive policy must not fail merely
    # because it denies an output write, which would hide the decision we are probing.
    enforce_argv = ["sha256sum", "corpus.txt"]
    proven = bool((doctor or {}).get("proven"))
    landlock_abi = (doctor or {}).get("landlock_abi")

    def arm(label: str, enforce: bool) -> list[dict]:
        cache = scratch / f"cache-{label}"
        env = runner.cache_env(dict(os.environ), cache)
        child = enforce_argv if enforce else workload_argv
        runs = []
        for _ in range(2):
            if not enforce:
                (ws / "corpus.txt.gz").unlink(missing_ok=True)
            argv = [str(tracejit), "run"]
            if enforce:
                argv.append("--enforce")
            argv += ["--contract", "allocator-entropy-v1", "--verbose", "--", *child]
            completed = subprocess.run(argv, cwd=ws, env=env, capture_output=True, check=False)
            report = completed.stderr.decode(errors="replace")
            decision = runner.parse_plain_decision(completed.stderr)
            classified = next((line.split()[-1] for line in report.splitlines()
                               if line.startswith("classified")), None)
            runs.append({
                "exit": completed.returncode,
                "kind": (decision or {}).get("kind"),
                "cache_decision": (decision or {}).get("cache_decision"),
                "classification": classified,
                "labelled_proven": classified == "PROVEN",
                "policy_lines": [line for line in report.splitlines()
                                 if line.startswith(("enforce", "policy", "sandbox", "problem",
                                                     "guards", "reason"))],
                "output_ok": (completed.returncode == 0 and bool(completed.stdout.strip())
                              if enforce else (ws / "corpus.txt.gz").is_file()),
            })
        return runs

    guarded_runs = arm("guarded", enforce=False)
    enforce_runs = arm("enforce", enforce=True)
    probe["enforcement"] = {
        "capability": {"proven": proven, "landlock_abi": landlock_abi,
                       "seccomp": (doctor or {}).get("seccomp")},
        "guarded_runs": guarded_runs,
        "enforce_runs": enforce_runs,
        "guarded_second_run_reused": bool(guarded_runs[1]["kind"] == "Reused"),
        "enforce_second_run_reused": bool(enforce_runs[1]["kind"] == "Reused"),
        "enforce_second_run_labelled_proven": bool(enforce_runs[1]["labelled_proven"]),
        # The only claim this probe can make: no run may be labelled PROVEN when the host
        # cannot install the policy, and guarded reuse must not depend on the label.
        "label_never_exceeds_capability": all(
            not run["labelled_proven"] for run in guarded_runs + enforce_runs
        ) if not proven else True,
        "enforce_refuses_reuse_without_proven_capability": (
            proven or not any(run["kind"] == "Reused" for run in enforce_runs)
        ),
        "enforce_commands_still_succeed": all(run["exit"] == 0 for run in enforce_runs),
    }

    text = json.dumps(probe, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    # A probe must never fail the job silently: the fingerprint is evidence, so a crash is
    # written into the published JSON and the public annotation carries it.
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - the traceback is the evidence
        import traceback

        print(json.dumps({"error": repr(error), "traceback": traceback.format_exc()}))
        raise SystemExit(0)

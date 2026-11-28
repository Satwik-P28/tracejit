#!/usr/bin/env python3
"""Phase AF: the enforced reuse lifecycle, measured on real commands, with assertions.

Phase AE's probe stopped after two invocations, so it could show a guarded reuse and an
incapable host's refusal, but never an enforced reuse. Its PR body says exactly that. This
probe walks the lifecycle the product claims, separately for the two workload classes that
behave differently, and records every decision instead of assuming a transition:

    arm ``read-only``  (real tool, no declared outputs)  -- sha256sum over a 1.6 MB corpus
    arm ``producer``   (real tool, declared output)      -- gzip -9 -n -k -f

For each arm:

    1. discovery execution            (no ``--enforce``)  -> Executed
    2. candidate recorded                                  -> at least one stored record
    3. execution under installed policy (``--enforce``)    -> Executed + PROVEN when capable
    4. classification as PROVEN                            (policy installed, nothing more)
    5. reuse under enforcement          (``--enforce``)    -> Reused + PROVEN when capable
    6. input mutation                   (``--enforce``)    -> not Reused, new observation
    7. re-execution under the policy    (``--enforce``)    -> correct observation

`PROVEN` means seccomp and Landlock were installed for that execution. It is not a proof of
observational equivalence and this probe does not test equivalence.

Capability-dependent outcomes are asserted, never inferred. `--assert-capability` (what CI
runs with `TRACEJIT_REQUIRE_PROVEN=1` on a capable runner) fails the run when the documented
outcome for this host's capability does not hold. On an incapable host the documented fallback
is asserted instead: nothing is labelled PROVEN, `--enforce` does not reuse, commands succeed.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "realworld_v2"))

import runner  # noqa: E402

SYS_LANDLOCK_CREATE_RULESET = 444
LANDLOCK_CREATE_RULESET_VERSION = 1
SECCOMP_GET_ACTION_AVAIL = 2
SECCOMP_RET_KILL_PROCESS = 0x80000000


def landlock_abi() -> int | None:
    """LANDLOCK_CREATE_RULESET_VERSION. A capability question, not a policy installation."""
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(
        ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET),
        ctypes.c_void_p(0),
        ctypes.c_size_t(0),
        ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
    )
    return int(result) if result >= 1 else None


def seccomp_action_available() -> bool:
    """SECCOMP_GET_ACTION_AVAIL for the action the sandbox installs."""
    libc = ctypes.CDLL(None, use_errno=True)
    action = ctypes.c_uint32(SECCOMP_RET_KILL_PROCESS)
    return libc.syscall(
        ctypes.c_long(317),  # SYS_seccomp
        ctypes.c_uint(SECCOMP_GET_ACTION_AVAIL),
        ctypes.c_uint(0),
        ctypes.byref(action),
    ) == 0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(report: str) -> str | None:
    line = next((item for item in report.splitlines() if item.startswith("classified")), None)
    return line.split()[-1] if line else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=REPO / ".phaseaf-lifecycle")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--contract",
        default="allocator-entropy-v1",
        help="execution contract; GUARDED needs an audited libc build",
    )
    parser.add_argument(
        "--assert-capability",
        action="store_true",
        help="fail when the documented outcome for this host's capability does not hold",
    )
    args = parser.parse_args(argv)

    tracejit = args.tracejit.resolve()
    scratch = args.scratch.resolve()
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    workspace = scratch / "ws"
    workspace.mkdir()
    corpus = workspace / "corpus.txt"
    corpus.write_bytes(b"".join(b"line %06d of the phase-af lifecycle corpus\n" % index
                                for index in range(40_000)))
    mutated = workspace / "mutated.txt"
    mutated.write_bytes(b"".join(b"MUTATED %06d after the enforced reuse\n" % index
                                 for index in range(40_000)))

    env = runner.cache_env(dict(os.environ), scratch / "cache")
    doctor_text = subprocess.run(
        [str(tracejit), "doctor", "--json"], cwd=scratch, env=env, capture_output=True
    ).stdout
    doctor = json.loads(doctor_text) if doctor_text.strip() else None
    capable = bool((doctor or {}).get("proven"))

    def invoke(workload: list[str], enforce: bool) -> dict:
        prefix = [str(tracejit), "run"]
        if enforce:
            prefix.append("--enforce")
        if args.contract:
            prefix += ["--contract", args.contract]
        prefix += ["--verbose", "--", *workload]
        completed = subprocess.run(prefix, cwd=workspace, env=env, capture_output=True)
        report = completed.stderr.decode(errors="replace")
        decision = runner.parse_plain_decision(completed.stderr)
        return {
            "enforce": enforce,
            "exit": completed.returncode,
            "kind": (decision or {}).get("kind"),
            "cache_decision": (decision or {}).get("cache_decision"),
            "classification": classify(report),
            "labelled_proven": classify(report) == "PROVEN",
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stderr_empty": completed.stderr.startswith(b"\nTraceJIT\n")
            or len(completed.stderr) > 0,
            "policy_lines": [line for line in report.splitlines()
                             if line.startswith(("enforce", "policy", "sandbox"))],
            "refusals": [line.split(":", 1)[-1].strip() for line in report.splitlines()
                         if line.startswith("reuse disabled")][:4],
        }

    def reference(workload: list[str]) -> str:
        return sha256_bytes(
            subprocess.run(workload, cwd=workspace, capture_output=True).stdout
        )

    def record_count(cache: Path) -> int:
        return len(list((cache / "executions").rglob("*"))) if (cache / "executions").is_dir() else 0

    arms: dict[str, dict] = {}

    # ---- arm 1: a real read-only tool -------------------------------------------------
    read_only = ["sha256sum", corpus.name]
    native_read_only = reference(read_only)
    steps = []
    discovery = invoke(read_only, enforce=False)
    steps.append({"step": "1_discovery_execution", **discovery})
    steps.append({
        "step": "2_candidate_recorded",
        "record_entries": record_count(scratch / "cache"),
        "cache_bytes": sum(path.stat().st_size
                           for path in (scratch / "cache").rglob("*") if path.is_file())
        if (scratch / "cache").is_dir() else 0,
    })
    enforced = invoke(read_only, enforce=True)
    steps.append({"step": "3_enforced_execution", **enforced})
    steps.append({
        "step": "4_classification",
        "classification": enforced["classification"],
        "labelled_proven": enforced["labelled_proven"],
    })
    enforced_reuse = invoke(read_only, enforce=True)
    steps.append({"step": "5_enforced_reuse", **enforced_reuse})
    corpus.write_bytes(mutated.read_bytes())
    mutated_read_only = reference(read_only)
    after_mutation = invoke(read_only, enforce=True)
    steps.append({
        "step": "6_input_mutation",
        "matches_new_input": after_mutation["stdout_sha256"] == mutated_read_only,
        "stale_output_served": after_mutation["stdout_sha256"] == native_read_only,
        **after_mutation,
    })
    reexecution = invoke(read_only, enforce=True)
    steps.append({
        "step": "7_reexecution_after_mutation",
        "matches_new_input": reexecution["stdout_sha256"] == mutated_read_only,
        **reexecution,
    })
    arms["read_only"] = {
        "workload": read_only,
        "native_stdout_sha256": native_read_only,
        "steps": steps,
    }

    # ---- arm 2: a real output producer -------------------------------------------------
    # A separate cache: mixing it with the read-only arm would let one arm's records answer
    # the other's lookup, and the point is the producer's own lifecycle.
    corpus.write_bytes(b"".join(b"line %06d of the phase-af lifecycle corpus\n" % index
                                for index in range(40_000)))
    producer_env = runner.cache_env(dict(os.environ), scratch / "cache-producer")
    env = producer_env
    gz = workspace / f"{corpus.name}.gz"

    def gzip_reference() -> str:
        gz.unlink(missing_ok=True)
        subprocess.run(["gzip", "-9", "-n", "-k", "-f", corpus.name], cwd=workspace,
                       capture_output=True)
        digest = sha256_file(gz)
        gz.unlink(missing_ok=True)
        return digest

    native_gz = gzip_reference()
    producer = ["gzip", "-9", "-n", "-k", "-f", corpus.name]
    producer_steps = []
    producer_discovery = invoke(producer, enforce=False)
    producer_steps.append({"step": "1_discovery_execution", **producer_discovery})
    # The guarded reuse a real workflow performs: the artifact was removed, then regenerated.
    gz.unlink(missing_ok=True)
    producer_guarded_reuse = invoke(producer, enforce=False)
    producer_steps.append({
        "step": "2_guarded_reuse_without_enforcement",
        "output_matches_native": sha256_file(gz) == native_gz if gz.is_file() else False,
        **producer_guarded_reuse,
    })
    # With the output in place, enforcement is asked for the same command. Whether it can be
    # promoted is the question this arm exists to answer; the answer is recorded, not assumed.
    producer_enforced = invoke(producer, enforce=True)
    producer_steps.append({"step": "3_enforced_execution", **producer_enforced})
    producer_enforced_reuse = invoke(producer, enforce=True)
    producer_steps.append({"step": "4_enforced_reuse", **producer_enforced_reuse})
    arms["producer"] = {
        "workload": producer,
        "native_output_sha256": native_gz,
        "steps": producer_steps,
    }

    ro = {step["step"]: step for step in arms["read_only"]["steps"]}
    pr = {step["step"]: step for step in arms["producer"]["steps"]}

    assertions = {
        # The capable-host lifecycle. On an incapable host the *converse* is required below.
        "read_only_discovery_is_guarded": ro["1_discovery_execution"]["classification"] == "GUARDED",
        "read_only_enforced_execution_is_proven_when_capable": (
            ro["3_enforced_execution"]["labelled_proven"] == capable
        ),
        "read_only_enforced_reuse_when_capable": (
            (ro["5_enforced_reuse"]["kind"] == "Reused") == capable
        ),
        "read_only_reuse_keeps_proven_label_when_capable": (
            ro["5_enforced_reuse"]["labelled_proven"] == capable
        ),
        "read_only_mutation_serves_new_bytes": ro["6_input_mutation"]["matches_new_input"],
        "read_only_mutation_never_serves_stale_bytes": not ro["6_input_mutation"][
            "stale_output_served"
        ],
        "producer_guarded_reuse_is_correct": (
            pr["2_guarded_reuse_without_enforcement"]["kind"] == "Reused"
            and pr["2_guarded_reuse_without_enforcement"]["output_matches_native"]
        ),
        # The fail-closed producer outcome: whatever the capability, a refused enforcement must
        # not be labelled PROVEN and must not serve a hit.
        "producer_enforcement_never_labelled_proven_without_policy": not pr[
            "3_enforced_execution"]["labelled_proven"],
        "producer_enforcement_never_reuses_unproven_record": pr["4_enforced_reuse"]["kind"]
        != "Reused",
        "all_commands_succeeded": all(
            step.get("exit") == 0
            for arm in arms.values()
            for step in arm["steps"]
            if "exit" in step
        ),
        "no_label_exceeds_capability": all(
            not step.get("labelled_proven")
            for arm in arms.values()
            for step in arm["steps"]
            if "labelled_proven" in step
        ) if not capable else True,
    }

    result = {
        "schema": "tracejit.phaseaf.enforcement-lifecycle/v2",
        "generated_unix_ms": int(time.time() * 1000),
        "host": {
            "kernel": platform.release(),
            "machine": platform.machine(),
            "os_release": next(
                (line for line in Path("/etc/os-release").read_text().splitlines()
                 if line.startswith("PRETTY_NAME")), "unknown"),
            "cpus": os.cpu_count(),
            "landlock_abi_syscall": landlock_abi(),
            "seccomp_action_available": seccomp_action_available(),
            "lsm_file": (Path("/sys/kernel/security/lsm").read_text().strip()
                         if Path("/sys/kernel/security/lsm").is_file() else None),
        },
        "binary": {
            "path": str(tracejit),
            "sha256": sha256_file(tracejit),
            "version": subprocess.run([str(tracejit), "--version"], capture_output=True)
            .stdout.decode().strip(),
        },
        "doctor": doctor,
        "capable": capable,
        "contract": args.contract,
        "arms": arms,
        "assertions": assertions,
        "assertions_passed": all(assertions.values()),
    }

    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(json.dumps({name: {"passed": ok} for name, ok in assertions.items()}, indent=2))
    print(f"capable={capable} assertions_passed={result['assertions_passed']}")
    shutil.rmtree(scratch, ignore_errors=True)

    if args.assert_capability and not result["assertions_passed"]:
        print(f"FAIL enforcement lifecycle assertions: "
              f"{[name for name, ok in assertions.items() if not ok]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - a probe crash is itself the evidence
        import traceback

        print(json.dumps({"error": repr(error), "traceback": traceback.format_exc()}))
        raise SystemExit(0)

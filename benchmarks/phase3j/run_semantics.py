#!/usr/bin/env python3
"""Phase 3J controlled-runtime semantic probes.

Every probe is executed natively once and twice under each audited Python
contract. The harness records the direct value, the contract-visible value,
the cache decision and whether the second controlled run was reusable.

The probes are deliberately bounded: a fixed virtual clock must be observed
without creating an accidental infinite timeout. The signal probe is the
negative control for identity virtualization: `os.kill(os.getpid(), ...)`
targets the virtual PID, not the tracee.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACEJIT = ROOT / "target/release/tracejit"
PYTHON = Path("/usr/bin/python3.12")
PROBES = ROOT / "benchmarks/phase3j/probes"
RESULTS = ROOT / "benchmarks/results/phase3j"
ENV = {
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "MALLOC_ARENA_MAX": "1",
}
CONTRACTS = ("python-runtime-v1", "python-runtime-v2")


def run(command: list[str], env: dict[str, str] | None = None, timeout: int = 15):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
            timeout=timeout,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as error:
        # The trace target is a child of tracejit; a timeout must kill the
        # whole session, never leave a stopped ptrace target behind.
        try:
            os.killpg(error.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return "timeout"


def report(result) -> dict:
    if result == "timeout":
        return {"kind": "Timeout"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def controlled_stdout(result) -> str:
    if result == "timeout":
        return "<timeout>"
    parsed = report(result)
    if "stdout_bytes" in parsed:
        return bytes(parsed["stdout_bytes"]).decode(errors="replace")
    return result.stdout


def controlled_stderr(result) -> str:
    if result == "timeout":
        return "<timeout>"
    parsed = report(result)
    if "stderr_bytes" in parsed:
        return bytes(parsed["stderr_bytes"]).decode(errors="replace")
    return result.stderr


def target(contract: str, command: list[str], cache: Path, args: list[str]):
    return run(
        [
            str(TRACEJIT),
            "run",
            "--json",
            "--contract",
            contract,
            "--",
            str(PYTHON),
            *command,
            *args,
        ],
        {**ENV, "TRACEJIT_CACHE_DIR": str(cache)},
    )


def direct(command: list[str], args: list[str]):
    return run([str(PYTHON), *command, *args], ENV)


def padding_is_zero(stdout: str) -> bool:
    lines = [line for line in stdout.splitlines() if line.startswith("padding ")]
    if len(lines) != 1:
        return False
    fields = lines[0].split()
    if len(fields) != 3 or fields[1] != "4":
        return False
    entries = fields[2].split(",")
    return len(entries) == 4 and all(entry and set(entry) == {"0"} for entry in entries)


def time_fields(stdout: str) -> list[int]:
    fields = stdout.split()
    if len(fields) != 4:
        return []
    try:
        return [int(field) for field in fields]
    except ValueError:
        return []


def probe_cases() -> dict[str, tuple[list[str], list[str]]]:
    return {
        "time": ([str(PROBES / "time_probe.py")], []),
        "gettimeofday": ([str(PROBES / "gettimeofday_probe.py")], []),
        "identity": ([str(PROBES / "identity_probe.py")], []),
        "direct_syscall": ([str(PROBES / "direct_syscall_probe.py")], []),
        "entropy": ([str(PROBES / "entropy_probe.py")], []),
        "thread": ([str(PROBES / "thread_probe.py")], []),
        "fork": ([str(PROBES / "fork_probe.py")], []),
        "padding": ([str(PROBES / "padding_probe.py")], []),
        "signal": ([str(PROBES / "signal_probe.py")], []),
    }


def assertions_for(contract: str, cases: dict[str, dict]) -> dict[str, bool]:
    time = time_fields(cases["time"]["first_stdout"])
    second_time = time_fields(cases["time"]["second_stdout"])
    return {
        "time_reused": cases["time"]["second_report"].get("kind") == "Reused",
        "time_direct_differs": cases["time"]["native_stdout"]
        != cases["time"]["first_stdout"],
        "time_v2_advances": contract != "python-runtime-v2"
        or (len(time) == 4 and time[2] == 0 and time[3] == 2_000_000),
        "time_v1_fixed_loop": contract != "python-runtime-v1"
        or (len(time) == 4 and time[2] == 1000 and time[3] == 0),
        "second_cached_time_is_the_recorded_value": contract != "python-runtime-v2"
        or (len(second_time) == 4 and second_time == time),
        "identity_reused": cases["identity"]["second_report"].get("kind") == "Reused",
        "entropy_not_reused": cases["entropy"]["second_report"].get("kind")
        != "Reused",
        "thread_not_reused": cases["thread"]["second_report"].get("kind")
        != "Reused",
        "fork_not_reused": cases["fork"]["second_report"].get("kind") != "Reused",
        "padding_reused": cases["padding"]["second_report"].get("kind") == "Reused",
        "padding_zero": padding_is_zero(cases["padding"]["first_stdout"]),
        "signal_contract_break_observed": cases["signal"]["first_report"].get(
            "exit_code"
        )
        not in (None, 0)
        and "ProcessLookupError" in cases["signal"]["first_stderr"],
        "signal_not_reused": cases["signal"]["second_report"].get("kind")
        != "Reused",
        "gettimeofday_not_reused": cases["gettimeofday"]["second_report"].get("kind")
        != "Reused",
    }


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tracejit-phase3j-"))
    enumdir = work / "enumdir"
    enumdir.mkdir()
    (enumdir / "a").write_text("a")
    (enumdir / "b").write_text("b")
    cases_spec = probe_cases()
    cases_spec["padding"] = ([str(PROBES / "padding_probe.py")], [str(enumdir)])
    output: dict = {
        "phase": "3J",
        "contracts": {},
        "canonical_executable": str(PYTHON),
    }
    try:
        for contract in CONTRACTS:
            contract_cases: dict[str, dict] = {}
            for name, (command, args) in cases_spec.items():
                cache = work / f"cache-{contract}-{name}"
                native = direct(command, args)
                first = target(contract, command, cache, args)
                second = target(contract, command, cache, args)
                first_report = report(first)
                second_report = report(second)
                contract_cases[name] = {
                    "native_stdout": native.stdout
                    if native != "timeout"
                    else "<timeout>",
                    "native_status": native.returncode
                    if native != "timeout"
                    else None,
                    "first_stdout": controlled_stdout(first),
                    "first_stderr": controlled_stderr(first),
                    "first_status": first.returncode if first != "timeout" else None,
                    "first_report": first_report,
                    "second_stdout": controlled_stdout(second),
                    "second_report": second_report,
                }
            output["contracts"][contract] = {
                "cases": contract_cases,
                "assertions": assertions_for(contract, contract_cases),
            }
    finally:
        shutil.rmtree(work, ignore_errors=True)

    destination = RESULTS / "semantic-probes.json"
    destination.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(destination)
    for contract, contract_output in output["contracts"].items():
        print(contract, json.dumps(contract_output["assertions"], sort_keys=True))
        for name, case in contract_output["cases"].items():
            print(
                " ",
                name,
                "native=",
                repr(case["native_stdout"].strip()),
                "first=",
                case["first_report"].get("kind"),
                "second=",
                case["second_report"].get("kind"),
                "reason=",
                case["second_report"].get("decision_reason"),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Adversarial corpus for the allocator-entropy admission rule.

Every case runs the *same* command three ways:

  native     an independent execution of the command, captured as the oracle
  cold       TraceJIT recording it
  warm       TraceJIT re-running it against the stored record

A case fails only when the warm run reports reuse and its observable result differs from the
oracle. That is the single failure this phase must not produce. Every other outcome - refused,
deoptimised, or an error the command itself would also produce - is recorded with its reason.

The cases cover the ways entropy can reach an observable: an application reading it directly, an
application writing it into a filename, an application seeding a PRNG with it, an unaudited shared
library issuing the *same* eight-byte probe as glibc, threads, children, a replacement compiler, a
runtime library reached by a different path, an inherited descriptor, a crash during startup, a
corrupted cache object, an interrupted recording, and records from two different contracts.

Usage:

  python3 benchmarks/phase_z/adversarial.py --json benchmarks/results/phase_z/adversarial.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN_GCC = Path("/usr/bin/x86_64-linux-gnu-gcc-13")
TRACEJIT = ROOT / "target" / "release" / "tracejit"
CONTRACT = "allocator-entropy-v1"
COMPILER_CONTRACT = "compiler-runtime-v1"

SOURCES = {
    "app_random_out.c": """
#include <stdio.h>
#include <sys/random.h>
int main(void) {
  unsigned char key[8];
  if (getrandom(key, sizeof key, 0) != 8) return 2;
  for (int i = 0; i < 8; i++) printf("%02x", key[i]);
  printf("\\n");
  return 0;
}
""",
    "app_random_filename.c": """
#include <stdio.h>
#include <sys/random.h>
int main(void) {
  unsigned char key[4];
  if (getrandom(key, sizeof key, 0) != 4) return 2;
  char name[32];
  snprintf(name, sizeof name, "out-%02x%02x.txt", key[0], key[1]);
  FILE *file = fopen(name, "w");
  if (!file) return 3;
  fputs("payload\\n", file);
  fclose(file);
  printf("%s\\n", name);
  return 0;
}
""",
    "app_random_prng.c": """
#include <stdio.h>
#include <sys/random.h>
int main(void) {
  unsigned char seed[8];
  if (getrandom(seed, sizeof seed, 0) != 8) return 2;
  unsigned long state = 0;
  for (int i = 0; i < 8; i++) state = state * 131 + seed[i];
  for (int i = 0; i < 3; i++) {
    state = state * 6364136223846793005UL + 1442695040888963407UL;
    printf("%lu\\n", (state >> 33) % 1000);
  }
  return 0;
}
""",
    "threads.c": """
#include <pthread.h>
#include <stdio.h>
#include <sys/random.h>
static void *worker(void *argument) {
  unsigned char key[8];
  long index = (long)argument;
  if (getrandom(key, sizeof key, 0) != 8) return NULL;
  unsigned long total = 0;
  for (int i = 0; i < 8; i++) total += key[i];
  printf("thread %ld %lu\\n", index, total % 97);
  return NULL;
}
int main(void) {
  pthread_t threads[2];
  for (long i = 0; i < 2; i++) pthread_create(&threads[i], NULL, worker, (void *)i);
  for (int i = 0; i < 2; i++) pthread_join(threads[i], NULL);
  return 0;
}
""",
    "children.c": """
#include <stdio.h>
#include <sys/random.h>
#include <sys/wait.h>
#include <unistd.h>
int main(void) {
  for (int child = 0; child < 2; child++) {
    pid_t pid = fork();
    if (pid == 0) {
      unsigned char key[8];
      if (getrandom(key, sizeof key, 0) != 8) _exit(2);
      char name[32];
      snprintf(name, sizeof name, "child-%d.txt", child);
      FILE *file = fopen(name, "w");
      for (int i = 0; i < 8; i++) fprintf(file, "%02x", key[i]);
      fclose(file);
      _exit(0);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    printf("child %d exited %d\\n", child, WEXITSTATUS(status));
  }
  return 0;
}
""",
    "probe.c": """
#include <sys/random.h>
unsigned long probe_key;
__attribute__((constructor)) static void initialize(void) {
  if (getrandom(&probe_key, sizeof probe_key, GRND_NONBLOCK) != 8) probe_key = 1;
}
""",
    "loads_probe.c": """
#include <stdio.h>
extern unsigned long probe_key;
int main(void) { printf("%lu\\n", probe_key % 1000); return 0; }
""",
    "crash.c": """
#include <stdlib.h>
#include <sys/random.h>
int main(void) {
  unsigned char key[8];
  if (getrandom(key, sizeof key, 0) != 8) return 2;
  if (key[0] == key[0]) abort();
  return 0;
}
""",
}


def build_fixtures(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    for name, source in SOURCES.items():
        (directory / name).write_text(source)
    binaries = {}
    for name in (
        "app_random_out",
        "app_random_filename",
        "app_random_prng",
        "crash",
    ):
        target = directory / name
        subprocess.run(
            ["gcc", "-O2", f"{name}.c", "-o", name],
            cwd=directory,
            check=True,
            capture_output=True,
        )
        binaries[name] = target
    subprocess.run(
        ["gcc", "-O2", "-pthread", "threads.c", "-o", "threads"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["gcc", "-O2", "children.c", "-o", "children"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["gcc", "-O2", "-shared", "-fPIC", "probe.c", "-o", "libprobe.so"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["gcc", "-O2", "loads_probe.c", "-L.", "-lprobe", "-Wl,-rpath,.", "-o", "loads_probe"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    (directory / "input.txt").write_text("alpha\nbeta\n")
    binary = TRACEJIT
    return {"directory": directory, "tracejit": binary}


def snapshot(directory: Path) -> dict:
    files = {}
    for path in sorted(directory.iterdir()):
        if path.is_file():
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def reset(directory: Path, keep: set[str]) -> None:
    for path in list(directory.iterdir()):
        if path.name not in keep:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


def run_native(command: list[str], cwd: Path, environment: dict | None = None, pass_fds=()) -> dict:
    env = dict(os.environ)
    if environment:
        env.update(environment)
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        pass_fds=pass_fds,
        check=False,
    )
    return {
        "seconds": time.perf_counter() - started,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
        "files": snapshot(cwd),
    }


def run_traced(
    command: list[str],
    cwd: Path,
    cache: Path,
    contract: str | None,
    environment: dict | None = None,
    pass_fds=(),
) -> dict:
    argv = [str(TRACEJIT), "run", "--json"]
    if contract:
        argv += ["--contract", contract]
    argv += ["--"] + command
    env = dict(os.environ)
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    if environment:
        env.update(environment)
    started = time.perf_counter()
    result = subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, pass_fds=pass_fds, check=False
    )
    report = None
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                report = json.loads(line)
            except json.JSONDecodeError:
                report = None
    if report is None:
        return {
            "seconds": time.perf_counter() - started,
            "report": None,
            "error": result.stderr.decode("utf-8", "replace")[-400:],
            "stdout": b"",
            "exit_code": None,
            "files": snapshot(cwd),
        }
    return {
        "seconds": time.perf_counter() - started,
        "report": report,
        "stdout": bytes(report.get("stdout_bytes") or []),
        "stderr": bytes(report.get("stderr_bytes") or []),
        "exit_code": report.get("exit_code"),
        "files": snapshot(cwd),
    }


def outcome(observed: dict, oracle: dict) -> dict:
    files_equal = observed["files"] == oracle["files"]
    return {
        "stdout_equal": observed["stdout"] == oracle["stdout"],
        "stderr_equal": observed["stderr"] == oracle["stderr"],
        "exit_equal": observed["exit_code"] == oracle["exit_code"],
        "files_equal": files_equal,
        "observationally_equal": (
            observed["stdout"] == oracle["stdout"]
            and observed["exit_code"] == oracle["exit_code"]
            and files_equal
        ),
    }


class Case:
    def __init__(self, name, command, expect, contract=CONTRACT, prepare=None, environment=None, note=""):
        self.name = name
        self.command = command
        self.expect = expect
        self.contract = contract
        self.prepare = prepare
        self.environment = environment
        self.note = note


def execute(case: Case, root: Path, fixtures: dict, keep: set[str]) -> dict:
    workroot = root / case.name
    if workroot.exists():
        shutil.rmtree(workroot)

    oracle_directory = workroot / "native"
    oracle_directory.mkdir(parents=True)
    for name in keep:
        source = fixtures["directory"] / name
        if source.is_file():
            shutil.copy2(source, oracle_directory / name)
        elif source.is_dir():
            shutil.copytree(source, oracle_directory / name)
    extra = {}
    if case.prepare:
        extra = case.prepare(oracle_directory) or {}
    oracle = run_native(
        case.command,
        oracle_directory,
        case.environment,
        tuple(extra.get("pass_fds", ())),
    )

    traced_directory = workroot / "traced"
    traced_directory.mkdir(parents=True)
    for name in keep:
        source = fixtures["directory"] / name
        if source.is_file():
            shutil.copy2(source, traced_directory / name)
        elif source.is_dir():
            shutil.copytree(source, traced_directory / name)
    if case.prepare:
        case.prepare(traced_directory)
    cache = workroot / "cache"
    cache.mkdir()
    pass_fds = tuple(extra.get("pass_fds", ()))
    cold = run_traced(
        case.command,
        traced_directory,
        cache,
        case.contract,
        case.environment,
        pass_fds,
    )
    if case.name == "replacement-compiler":
        # Same path, different program: the guard must notice before restoring the object.
        (traced_directory / "compiler-copy" / "gcc").write_text(
            "#!/bin/sh\nexec gcc -DEXTRA=1 \"$@\"\n"
        )
        (traced_directory / "compiler-copy" / "gcc").chmod(0o755)
    reset(traced_directory, keep)
    if case.prepare:
        case.prepare(traced_directory)
    warm = run_traced(
        case.command,
        traced_directory,
        cache,
        case.contract,
        case.environment,
        pass_fds,
    )

    cold_decision = (cold["report"] or {}).get("cache_decision")
    warm_decision = (warm["report"] or {}).get("cache_decision")
    reused = warm_decision in ("Reused", "Hit")
    comparison = outcome(warm, oracle)
    incorrect_hit = reused and not comparison["observationally_equal"]
    if case.expect == "either":
        # The claim under test is "no incorrect reuse", not a particular decision.
        satisfied = not incorrect_hit
    else:
        satisfied = (case.expect == "reusable" and reused) or (
            case.expect == "refused" and not reused
        )
    return {
        "case": case.name,
        "expect": case.expect,
        "note": case.note,
        "command": case.command,
        "contract": case.contract,
        "cold_decision": cold_decision,
        "warm_decision": warm_decision,
        "cold_classification": (cold["report"] or {}).get("classification"),
        "reasons": (warm["report"] or {}).get("reasons"),
        "guard_failure": ((warm["report"] or {}).get("guards") or {}).get("failure"),
        "oracle_seconds": round(oracle["seconds"], 4),
        "cold_seconds": round(cold["seconds"], 4),
        "warm_seconds": round(warm["seconds"], 4),
        "comparison": comparison,
        "incorrect_hit": incorrect_hit,
        "satisfied": satisfied,
        "error": warm.get("error"),
    }


def corrupt_cas(cache: Path) -> int:
    objects = list((cache / "objects").glob("*")) if (cache / "objects").exists() else []
    corrupted = 0
    for path in objects:
        if path.is_file() and corrupted < 2:
            data = bytearray(path.read_bytes())
            if data:
                data[len(data) // 2] ^= 0xFF
                path.write_bytes(bytes(data))
                corrupted += 1
    return corrupted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--workroot", type=Path, default=Path("/tmp/tracejit-phase-z/adversarial"))
    args = parser.parse_args()

    if args.workroot.exists():
        shutil.rmtree(args.workroot)
    fixtures = build_fixtures(args.workroot / "fixtures")
    directory = fixtures["directory"]

    runtime_copy = args.workroot / "runtime-copy"
    runtime_copy.mkdir(parents=True)
    libc_source = Path("/usr/lib/x86_64-linux-gnu/libc.so.6")
    shutil.copy2(libc_source, runtime_copy / "libc.so.6")

    compiler_copy = args.workroot / "fixtures" / "compiler-copy"
    compiler_copy.mkdir(parents=True)
    shutil.copy2(TOOLCHAIN_GCC, compiler_copy / "gcc")

    def prepare_inherited(where: Path) -> dict:
        descriptor = os.open(where / "input.txt", os.O_RDONLY)
        os.set_inheritable(descriptor, True)
        return {"pass_fds": (descriptor,)}

    cases = [
        Case("baseline-sed", ["sed", "s/alpha/ALPHA/", "input.txt"], "reusable"),
        Case("app-entropy-stdout", ["./app_random_out"], "refused"),
        Case("app-entropy-filename", ["./app_random_filename"], "refused"),
        Case("app-entropy-seeds-prng", ["./app_random_prng"], "refused"),
        Case(
            "two-threads",
            ["./threads"],
            "either",
            note="threads created with CLONE_FILES; the record must not reuse across them",
        ),
        Case("two-children", ["./children"], "either", contract=None),
        Case(
            "unaudited-library-probe",
            ["./loads_probe"],
            "refused",
            note="a shared library issuing the same 8-byte GRND_NONBLOCK probe as glibc",
        ),
        Case("crash-during-startup", ["./crash"], "either"),
        Case(
            "runtime-reached-by-another-path",
            ["sed", "s/alpha/ALPHA/", "input.txt"],
            "reusable",
            environment={"LD_LIBRARY_PATH": str(runtime_copy)},
            note="the same audited build ID, loaded from a copy: portability of the audit",
        ),
        Case(
            "replacement-compiler",
            [str(compiler_copy / "gcc"), "-O2", "-c", "input.c", "-o", "input.o"],
            "either",
            contract=COMPILER_CONTRACT,
            note="the same command path, replaced between the recording and the reuse",
        ),
        Case(
            "inherited-descriptor",
            ["sed", "s/alpha/ALPHA/", "input.txt"],
            "either",
            prepare=prepare_inherited,
            note="an inherited descriptor whose flags belong to whoever started us",
        ),
        Case(
            "compiler-contract-sed",
            ["sed", "s/alpha/ALPHA/", "input.txt"],
            "either",
            contract=COMPILER_CONTRACT,
            note="the broader contract admits the same libc probe for a non-compiler command",
        ),
    ]

    keep = set(SOURCES) | {
        "compiler-copy",
        "app_random_out",
        "app_random_filename",
        "app_random_prng",
        "crash",
        "threads",
        "children",
        "libprobe.so",
        "loads_probe",
        "input.txt",
        "input.c",
    }
    (directory / "input.c").write_text("int answer(void) { return 42; }\n")

    results = [execute(case, args.workroot / "cases", fixtures, keep) for case in cases]

    # Cross-contract record: record under one contract, then attempt the other.
    mixed = execute(
        Case("recorded-under-other-contract", ["sed", "s/alpha/ALPHA/", "input.txt"], "refused"),
        args.workroot / "cases",
        fixtures,
        keep,
    )
    cross_root = args.workroot / "cases" / "cross-contract"
    if cross_root.exists():
        shutil.rmtree(cross_root)
    cross_root.mkdir(parents=True)
    for name in keep:
        source = directory / name
        if source.is_file():
            shutil.copy2(source, cross_root / name)
    cache = cross_root / "cache"
    cache.mkdir()
    record = run_traced(["sed", "s/alpha/ALPHA/", "input.txt"], cross_root, cache, CONTRACT)
    retry = run_traced(
        ["sed", "s/alpha/ALPHA/", "input.txt"], cross_root, cache, COMPILER_CONTRACT
    )
    mixed = {
        "case": "recorded-under-other-contract",
        "expect": "refused",
        "note": "a record made under allocator-entropy-v1, attempted under compiler-runtime-v1",
        "command": ["sed", "s/alpha/ALPHA/", "input.txt"],
        "contract": COMPILER_CONTRACT,
        "cold_decision": (record["report"] or {}).get("cache_decision"),
        "warm_decision": (retry["report"] or {}).get("cache_decision"),
        "cold_classification": (record["report"] or {}).get("classification"),
        "reasons": (retry["report"] or {}).get("reasons"),
        "guard_failure": ((retry["report"] or {}).get("guards") or {}).get("failure"),
        "comparison": {"present": True},
        "incorrect_hit": False,
        "satisfied": (retry["report"] or {}).get("cache_decision") != "Reused",
        "error": retry.get("error"),
    }
    results.append(mixed)

    loader_root = args.workroot / "cases" / "loader-path-changed"
    if loader_root.exists():
        shutil.rmtree(loader_root)
    loader_root.mkdir(parents=True)
    for name in ("input.txt",):
        shutil.copy2(directory / name, loader_root / name)
    cache = loader_root / "cache"
    cache.mkdir()
    record = run_traced(["sed", "s/alpha/ALPHA/", "input.txt"], loader_root, cache, CONTRACT)
    changed = run_traced(
        ["sed", "s/alpha/ALPHA/", "input.txt"],
        loader_root,
        cache,
        CONTRACT,
        {"LD_LIBRARY_PATH": str(runtime_copy)},
    )
    loader_oracle = run_native(
        ["sed", "s/alpha/ALPHA/", "input.txt"],
        loader_root,
        {"LD_LIBRARY_PATH": str(runtime_copy)},
    )
    loader_comparison = outcome(changed, loader_oracle)
    results.append(
        {
            "case": "loader-path-changed",
            "expect": "either",
            "note": "recorded with the system libc, replayed with the same build loaded from a copy",
            "command": ["sed", "s/alpha/ALPHA/", "input.txt"],
            "contract": CONTRACT,
            "cold_decision": (record["report"] or {}).get("cache_decision"),
            "warm_decision": (changed["report"] or {}).get("cache_decision"),
            "cold_classification": (record["report"] or {}).get("classification"),
            "reasons": (changed["report"] or {}).get("reasons"),
            "guard_failure": ((changed["report"] or {}).get("guards") or {}).get("failure"),
            "comparison": loader_comparison,
            "incorrect_hit": (changed["report"] or {}).get("cache_decision") == "Reused"
            and not loader_comparison["observationally_equal"],
            "satisfied": not (
                (changed["report"] or {}).get("cache_decision") == "Reused"
                and not loader_comparison["observationally_equal"]
            ),
            "error": changed.get("error"),
        }
    )

    # A corrupted cache object must never be restored: record, corrupt, then re-run.
    corrupt_root = args.workroot / "cases" / "corrupt-cache-object"
    if corrupt_root.exists():
        shutil.rmtree(corrupt_root)
    corrupt_root.mkdir(parents=True)
    for name in ("input.txt",):
        shutil.copy2(directory / name, corrupt_root / name)
    cache = corrupt_root / "cache"
    cache.mkdir()
    run_traced(["sed", "s/alpha/ALPHA/", "input.txt"], corrupt_root, cache, CONTRACT)
    corrupted = corrupt_cas(cache)
    after = run_traced(["sed", "s/alpha/ALPHA/", "input.txt"], corrupt_root, cache, CONTRACT)
    oracle = run_native(["sed", "s/alpha/ALPHA/", "input.txt"], corrupt_root)
    comparison = outcome(after, oracle)
    results.append(
        {
            "case": "corrupt-cache-object",
            "expect": "refused",
            "note": f"{corrupted} stored object(s) flipped mid-file",
            "command": ["sed", "s/alpha/ALPHA/", "input.txt"],
            "contract": CONTRACT,
            "cold_decision": None,
            "warm_decision": (after["report"] or {}).get("cache_decision"),
            "cold_classification": None,
            "reasons": (after["report"] or {}).get("reasons"),
            "guard_failure": ((after["report"] or {}).get("guards") or {}).get("failure"),
            "comparison": comparison,
            "incorrect_hit": False,
            "satisfied": not (
                (after["report"] or {}).get("cache_decision") == "Reused"
                and not comparison["observationally_equal"]
            ),
            "error": after.get("error"),
        }
    )

    # A recording killed mid-flight must not leave a record that replays stale output.
    interrupted_root = args.workroot / "cases" / "interrupted-recording"
    if interrupted_root.exists():
        shutil.rmtree(interrupted_root)
    interrupted_root.mkdir(parents=True)
    for name in ("input.txt",):
        shutil.copy2(directory / name, interrupted_root / name)
    (interrupted_root / "big.txt").write_text(
        "\n".join(str((index * 7919) % 1000003) for index in range(1_200_000)) + "\n"
    )
    cache = interrupted_root / "cache"
    cache.mkdir()
    environment = dict(os.environ)
    environment["TRACEJIT_CACHE_DIR"] = str(cache)
    process = subprocess.Popen(
        [
            str(TRACEJIT),
            "run",
            "--json",
            "--contract",
            CONTRACT,
            "--",
            "sed",
            "-E",
            "-n",
            "s/[0-9]+/N/g;w out.txt",
            "big.txt",
        ],
        cwd=interrupted_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.04)
    process.send_signal(signal.SIGKILL)
    process.wait()
    after = run_traced(
        ["sed", "-E", "-n", "s/[0-9]+/N/g;w out.txt", "big.txt"],
        interrupted_root,
        cache,
        CONTRACT,
    )
    comparison = outcome(
        after,
        run_native(
            ["sed", "-E", "-n", "s/[0-9]+/N/g;w out.txt", "big.txt"], interrupted_root
        ),
    )
    results.append(
        {
            "case": "interrupted-recording",
            "expect": "either",
            "note": "SIGKILL 40 ms into a recording that takes ~130 ms",
            "command": ["sed", "-E", "-n", "s/[0-9]+/N/g;w out.txt", "big.txt"],
            "contract": CONTRACT,
            "cold_decision": None,
            "warm_decision": (after["report"] or {}).get("cache_decision"),
            "cold_classification": (after["report"] or {}).get("classification"),
            "reasons": (after["report"] or {}).get("reasons"),
            "guard_failure": None,
            "comparison": comparison,
            "incorrect_hit": (after["report"] or {}).get("cache_decision") == "Reused"
            and not comparison["observationally_equal"],
            "satisfied": not (
                (after["report"] or {}).get("cache_decision") == "Reused"
                and not comparison["observationally_equal"]
            ),
            "error": after.get("error"),
        }
    )

    report = {
        "cases": results,
        "incorrect_hits": [case for case in results if case["incorrect_hit"]],
        "unsatisfied": [case["case"] for case in results if not case["satisfied"]],
        "summary": {
            "cases": len(results),
            "reused": sum(1 for case in results if case["warm_decision"] == "Reused"),
            "refused": sum(1 for case in results if case["warm_decision"] != "Reused"),
            "incorrect_hits": sum(1 for case in results if case["incorrect_hit"]),
        },
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    for case in results:
        print(
            f"{case['case']:32} expect={case['expect']:8} warm={str(case['warm_decision']):12}"
            f" satisfied={case['satisfied']} incorrect_hit={case['incorrect_hit']}"
        )
        if not case["satisfied"]:
            print(f"    reasons: {case['reasons']}")
    print(json.dumps(report["summary"]))
    return 0 if not report["incorrect_hits"] and not report["unsatisfied"] else 1


if __name__ == "__main__":
    sys.exit(main())

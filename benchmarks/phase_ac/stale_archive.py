#!/usr/bin/env python3
"""Phase AC: reproduce the restored-mtime / stale-archive counterexample.

Phase AB observed that a warm HIT restores an output with the *recorded* mtime,
so a build system can decide the restored file is older than an existing archive
and skip the step that would have refreshed it.  This script reproduces that
sequence on real upstream projects (Lua 5.4.6 and zlib 1.3.1) and records every
timestamp and build-system decision involved.

Sequence, identical for the traced and the native control arm:

    1. extract the pristine project (tar preserves the source's old mtimes)
    2. compile one real translation unit                       -> object v1
    3. ``ar rcs`` it into the project archive                  -> archive holds v1
    4. edit the source, compile again                          -> object v2
    5. ``ar rcs`` again                                        -> archive holds v2
    6. restore the source to its pristine bytes (old mtime)
    7. compile again  [traced arm: TraceJIT, native arm: gcc]
    8. run the project's archive rule through ``make`` and observe

The traced arm's step 7 is a warm HIT: the object's *bytes* are v1, but its
mtime is the original v1 mtime, which is older than the archive built at step 5.
GNU make then reports the archive up to date and the archive keeps v2: the
archive no longer matches its members.  The native arm's step 7 stamps a fresh
mtime, make runs ``ar``, and the archive matches.

Both arms therefore end with the same object bytes and a different archive.  That
is a real limitation of timestamp-exact restoration, not a content defect, and
the script asserts exactly that so the semantics cannot change silently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "realworld_v2"))

import runner  # noqa: E402

PROJECTS = {
    "lua": {
        "tarball": Path("/tmp/ac-src/lua-5.4.6.tar.gz"),
        "top": "lua-5.4.6",
        "source": "src/lapi.c",
        "object": "src/lapi.o",
        "archive": "src/liblua.a",
        "flags_a": ["-O2", "-Wall", "-Wextra", "-std=gnu99"],
        "flags_b": ["-O0", "-g", "-Wall", "-std=gnu99"],
        "workdir": "src",
        "upstream_rule": "ar rcs $@ $(OBJS)",
    },
    "zlib": {
        "tarball": Path("/tmp/ac-vendor/zlib-1.3.1.tar.gz"),
        "top": "zlib-1.3.1",
        "source": "deflate.c",
        "object": "deflate.o",
        "archive": "libz.a",
        "flags_a": ["-O2", "-Wall"],
        "flags_b": ["-O0", "-g", "-Wall"],
        "workdir": ".",
        "upstream_rule": "$(AR) $(ARFLAGS) $@ $(OBJS)",
    },
}

#: The execution policy the traced arm runs under.  gcc calls ``getrusage``,
#: which native classification refuses; ``compiler-runtime-v1`` is the audited
#: compiler profile that admits it, and is the policy a compiler workload would
#: actually be used with.
CONTRACT = "compiler-runtime-v1"

MAKEFILE = """\
{archive}: {object}
\tar rcs {archive} {object}
"""


def run(argv: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False, timeout=900)


def extract(tarball: Path, into: Path, top: str) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as archive:
        archive.extractall(into)
    return into / top


def extract_member(tarball: Path, top: str, member: str, into: Path) -> None:
    """Re-extracts one file, preserving the *archived* mtime.

    This is how a source returns to its original content in a reproducible
    pipeline: from the pinned tarball, not from a checkout that would stamp a new
    mtime and make the build system's decision trivial.
    """

    with tarfile.open(tarball) as archive:
        info = archive.getmember(f"{top}/{member}")
        data = archive.extractfile(info).read()
    target = into / top / member
    target.write_bytes(data)
    os.utime(target, (info.mtime, info.mtime))


def first_difference(left: bytes, right: bytes) -> int | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def archive_member(archive: Path, member: str, cwd: Path) -> bytes:
    completed = run(["ar", "p", str(archive), member], cwd)
    return completed.stdout


def arm(
    name: str,
    project: dict,
    scratch: Path,
    tracejit: Path | None,
    base_env: dict,
) -> dict:
    root = scratch / name
    shutil.rmtree(root, ignore_errors=True)
    tree = extract(project["tarball"], root, project["top"])
    workdir = tree / project["workdir"]
    source = tree / project["source"]
    object_path = tree / project["object"]
    archive_path = tree / project["archive"]

    def compile_argv(flags: list[str]) -> list[str]:
        return ["gcc", *flags, "-c", source.name, "-o", object_path.name]

    (workdir / "Makefile.phaseac").write_text(
        MAKEFILE.format(archive=archive_path.name, object=object_path.name)
    )

    cache = root / "cache"
    env = runner.cache_env(base_env, cache) if tracejit else dict(base_env)
    steps: list[dict] = []

    def compile_step(label: str, flags: list[str]) -> dict:
        compile_argv_value = compile_argv(flags)
        if tracejit:
            # gcc calls getrusage (syscall 98), which native classification
            # refuses; the audited compiler profile is what admits it.
            _, decision, report, _, _ = runner.run_traced(
                tracejit, compile_argv_value, workdir, env, CONTRACT
            )
            reused = runner.is_hit(decision)
            exit_status = int((report or {}).get("exit_code", -1))
            info = {"kind": (decision or {}).get("kind"),
                    "cache_decision": (decision or {}).get("cache_decision")}
        else:
            completed = run(compile_argv_value, workdir, env)
            reused = False
            exit_status = completed.returncode
            info = {"kind": "native"}
        mtime = object_path.stat().st_mtime_ns
        steps.append({"step": label, "exit": exit_status, "reused": reused, **info,
                      "object_mtime_ns": mtime, "object_sha256": hashlib.sha256(object_path.read_bytes()).hexdigest()[:16]})
        return steps[-1]

    def archive_step(label: str) -> dict:
        completed = run(["ar", "rcs", archive_path.name, object_path.name], workdir, env)
        member = archive_member(archive_path, object_path.name, workdir)
        entry = {
            "step": label,
            "exit": completed.returncode,
            "archive_mtime_ns": archive_path.stat().st_mtime_ns,
            "member_matches_object": member == object_path.read_bytes(),
            "member_sha256": hashlib.sha256(member).hexdigest()[:16],
        }
        steps.append(entry)
        return entry

    # The source is never edited: a rewrite changes its ctime, and the metadata
    # guard correctly refuses the hit.  The realistic cache-shape that reaches
    # restoration is a *flags flip* (debug on, then off) over an unchanged tree,
    # which is why the two builds differ and the third matches the first exactly.
    time.sleep(0.02)
    compile_step("compile_flags_a", project["flags_a"])       # 2
    archive_step("archive_flags_a")                            # 3
    time.sleep(1.05)  # make the second build strictly newer than the first archive
    compile_step("compile_flags_b", project["flags_b"])       # 4
    archive_step("archive_flags_b")                            # 5
    time.sleep(0.05)
    source_mtime_ns = source.stat().st_mtime_ns
    # The object is removed before the rebuild: that is the shape a cache serves
    # (a deleted or never-built object is what ccache/TraceJIT put back). Keeping
    # the old object in place would change the recorded output precondition and
    # correctly deoptimise the hit instead of demonstrating restoration.
    object_path.unlink()
    recompile = compile_step("compile_flags_a_again", project["flags_a"])   # 6+7

    make = run(["make", "-f", "Makefile.phaseac"], workdir, env)   # 8
    make_dry = run(["make", "-n", "-f", "Makefile.phaseac"], workdir, env)
    member = archive_member(archive_path, object_path.name, workdir)
    object_bytes = object_path.read_bytes()

    result = {
        "arm": name,
        "policy": CONTRACT if tracejit else "native",
        "project": project["top"],
        "source_file": project["source"],
        "upstream_rule": project["upstream_rule"],
        "source_mtime_ns": source_mtime_ns,
        "recompile": recompile,
        "make": {
            "exit": make.returncode,
            "stdout": make.stdout.decode("utf-8", "replace"),
            "stderr": make.stderr.decode("utf-8", "replace"),
            "dry_run": make_dry.stdout.decode("utf-8", "replace"),
            "ran_ar": b"ar rcs" in make.stdout,
        },
        "final": {
            "object_mtime_ns": object_path.stat().st_mtime_ns,
            "archive_mtime_ns": archive_path.stat().st_mtime_ns,
            "member_matches_object": member == object_bytes,
            "member_sha256": hashlib.sha256(member).hexdigest()[:16],
            "object_sha256": hashlib.sha256(object_bytes).hexdigest()[:16],
            "first_byte_difference": first_difference(member, object_bytes),
        },
        "steps": steps,
    }
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", action="append", choices=sorted(PROJECTS), default=None)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=Path("/tmp/ac-stale-archive"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--expect",
        choices=["documented", "any"],
        default="documented",
        help="documented: fail unless the recorded stale-archive semantics still hold "
             "(traced arm reuses, make skips ar, archive keeps the other object; the "
             "native arm updates it). any: only record.",
    )
    args = parser.parse_args(argv)

    base_env = dict(os.environ)
    projects = args.project or sorted(PROJECTS)
    payload: dict = {"arms": []}
    for project_id in projects:
        project = PROJECTS[project_id]
        if not project["tarball"].is_file():
            payload.setdefault("missing_sources", []).append(str(project["tarball"]))
            continue
        traced = arm(f"{project_id}-tracejit", project, args.scratch, args.tracejit, base_env)
        native = arm(f"{project_id}-native", project, args.scratch, None, base_env)
        payload["arms"].extend([traced, native])
        payload[f"{project_id}_verdict"] = {
            "traced_reused": traced["recompile"]["reused"],
            "traced_make_ran_ar": traced["make"]["ran_ar"],
            "traced_archive_member_matches_object": traced["final"]["member_matches_object"],
            "native_make_ran_ar": native["make"]["ran_ar"],
            "native_archive_member_matches_object": native["final"]["member_matches_object"],
            "traced_object_before_native_object": (
                traced["final"]["object_sha256"] == native["final"]["object_sha256"]
            ),
            "restored_object_older_than_archive": (
                traced["final"]["object_mtime_ns"] < traced["final"]["archive_mtime_ns"]
            ),
        }

    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
        for project_id in projects:
            print(project_id, json.dumps(payload.get(f"{project_id}_verdict"), sort_keys=True))
        if payload.get("missing_sources"):
            print("missing sources:", payload["missing_sources"])
    else:
        print(text)

    if args.expect == "documented":
        failures: list[str] = []
        for project_id in projects:
            verdict = payload.get(f"{project_id}_verdict")
            if verdict is None:
                failures.append(f"{project_id}: not measured")
                continue
            if not verdict["traced_reused"]:
                failures.append(f"{project_id}: the traced rebuild was not a HIT")
            if verdict["traced_make_ran_ar"]:
                failures.append(f"{project_id}: make ran ar on the traced side")
            if verdict["traced_archive_member_matches_object"]:
                failures.append(f"{project_id}: the traced archive was refreshed")
            if not verdict["native_make_ran_ar"] or not verdict["native_archive_member_matches_object"]:
                failures.append(f"{project_id}: the native control did not refresh the archive")
            if not verdict["traced_object_before_native_object"]:
                failures.append(f"{project_id}: the restored object differs from the native object")
        if failures:
            print("STALE-ARCHIVE SEMANTICS CHANGED: " + "; ".join(failures), file=sys.stderr)
            return 1
        print("documented stale-archive semantics hold for: " + ", ".join(projects))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

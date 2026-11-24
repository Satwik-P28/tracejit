#!/usr/bin/env python3
"""Phase AC: is timestamp-exact restoration observable, and is it consistent?

Two questions, measured rather than argued.

1. *Consistency.* A program whose stdout reports its own output's mtime is the
   sharpest test of "restore the recorded metadata": a warm HIT replays the
   cached stdout, so the restored file's mtime must equal the value that stdout
   names, or the replayed observation describes a workspace that no longer exists.

2. *What a fresh timestamp would do.* The alternative policy (B in
   `docs/OUTPUT_RESTORE_SEMANTICS.md`) restores content and stamps a new mtime.
   It is simulated here by touching the restored file after an accepted hit and
   re-reading the same field the program printed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "realworld_v2"))

import oracle  # noqa: E402
import runner  # noqa: E402

# The command prints the mtime of the file it just wrote, so its stdout is a
# legitimate observable function of output metadata.  It is a tiny compiled
# fixture rather than `sh -c`, because a shell's own runtime effects are
# unmodelled and the point here is the hit path, not shell eligibility.
FIXTURE_SOURCE = r"""
#include <stdio.h>
#include <sys/stat.h>

int main(void) {
    FILE *in = fopen("seed.txt", "r");
    if (!in) return 1;
    FILE *out = fopen("out.txt", "w");
    if (!out) return 1;
    int c;
    while ((c = fgetc(in)) != EOF) fputc(c, out);
    fclose(in);
    if (fclose(out) != 0) return 1;
    struct stat info;
    if (stat("out.txt", &info) != 0) return 1;
    printf("%lld\n", (long long)info.st_mtime);
    return 0;
}
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=Path("/tmp/ac-metadata-observation"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--policy", default="native")
    args = parser.parse_args(argv)

    shutil.rmtree(args.scratch, ignore_errors=True)
    args.scratch.mkdir(parents=True)
    source = args.scratch / "metadata_echo.c"
    source.write_text(FIXTURE_SOURCE)
    binary = args.scratch / "metadata-echo"
    subprocess.run(["cc", "-O2", "-o", str(binary), str(source)], check=True)
    command = [str(binary)]
    native_ws = args.scratch / "native"
    traced_ws = args.scratch / "traced"
    for ws in (native_ws, traced_ws):
        ws.mkdir(parents=True)
        (ws / "seed.txt").write_text("".join(f"line {i}\n" for i in range(500)))
    os.utime(native_ws / "seed.txt", ns=(1_600_000_000 * 10**9, 1_600_000_000 * 10**9))
    os.utime(traced_ws / "seed.txt", ns=(1_600_000_000 * 10**9, 1_600_000_000 * 10**9))

    env = runner.cache_env(dict(os.environ), args.scratch / "cache")

    native = subprocess.run(command, cwd=native_ws, env=env, capture_output=True, check=False)
    native_obs = oracle.process_observation(
        native.returncode, native.stdout, native.stderr, oracle.observe_workspace(native_ws)
    )

    _, cold_decision, _, cold_stdout, cold_stderr = runner.run_traced(
        args.tracejit, command, traced_ws, env, args.policy
    )
    cold_obs = oracle.process_observation(
        0, cold_stdout, cold_stderr, oracle.observe_workspace(traced_ws)
    )
    cold_compare = oracle.compare(native_obs, cold_obs)

    # Remove the output so the hit has to restore it, then reuse.
    (traced_ws / "out.txt").unlink()
    _, warm_decision, _, warm_stdout, warm_stderr = runner.run_traced(
        args.tracejit, command, traced_ws, env, args.policy
    )
    warm_obs = oracle.process_observation(
        0, warm_stdout, warm_stderr, oracle.observe_workspace(traced_ws)
    )
    warm_compare = oracle.compare(native_obs, warm_obs)

    printed_after_hit = int(warm_stdout.strip()) if warm_stdout.strip().isdigit() else None
    restored_ns = (traced_ws / "out.txt").stat().st_mtime_ns
    consistent = printed_after_hit is not None and printed_after_hit == restored_ns // 10**9

    # Policy B simulation: same content, fresh timestamp.  The sleep makes the
    # divergence unambiguous even with whole-second timestamps.
    import time as _time
    _time.sleep(2.05)
    os.utime(traced_ws / "out.txt", None)
    fresh_ns = (traced_ws / "out.txt").stat().st_mtime_ns
    after_touch = subprocess.run(
        ["stat", "-c", "%Y", "out.txt"], cwd=traced_ws, capture_output=True, text=True
    )
    observed_after_b = int(after_touch.stdout.strip())
    payload = {
        "policy": args.policy,
        "command": [Path(command[0]).name],
        "native_stdout": native.stdout.decode().strip(),
        "cold_match": cold_compare["match"],
        "cold_decision": (cold_decision or {}).get("cache_decision"),
        "warm_reused": runner.is_hit(warm_decision),
        "warm_match": warm_compare["match"],
        "warm_stdout": warm_stdout.decode().strip(),
        "restored_mtime_s": restored_ns // 10**9,
        "stdout_names_restored_mtime": consistent,
        "policy_b_simulated": {
            "stdout_still_says": printed_after_hit,
            "file_now_says": observed_after_b,
            "divergence_s": observed_after_b - printed_after_hit if printed_after_hit else None,
            "fresh_mtime_ns": fresh_ns,
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

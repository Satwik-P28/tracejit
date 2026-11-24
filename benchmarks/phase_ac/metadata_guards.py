#!/usr/bin/env python3
"""Phase AC: adversarial input-metadata matrix for the guard audit.

For each mutation the same change is applied to a native twin and to the traced
workspace, so the oracle compares "what the command does after this mutation"
against "what TraceJIT does after the same mutation".  A HIT whose observation
differs is an incorrect hit; a DEOPT is the conservative, correct outcome.

The command is `gzip -9 -c`, chosen because it has real compute, no workspace
output (so the comparison isolates *input* guards) and it already reuses under
`allocator-entropy-v1` with an unchanged input.
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

COMMAND = ["gzip", "-9", "-c", "corpus.txt"]
POLICY = "allocator-entropy-v1"


def fixture() -> bytes:
    return b"".join(f"row {i:06d} value {(i * 7919) % 100003}\n".encode() for i in range(3000))


def mutate(name: str, ws: Path) -> str:
    target = ws / "corpus.txt"
    info = target.stat()
    if name == "unchanged":
        return "no change"
    if name == "mtime_only":
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 5 * 10**9))
        return "mtime +5 s, identical content"
    if name == "atime_only":
        os.utime(target, ns=(info.st_atime_ns + 5 * 10**9, info.st_mtime_ns))
        return "atime +5 s, identical content and mtime"
    if name == "ctime_only":
        os.chmod(target, 0o640)
        os.chmod(target, 0o644)
        return "chmod 640 then 644: same mode, new ctime"
    if name == "same_size_same_content_rewrite":
        target.write_bytes(fixture())
        os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
        return "rewrote identical bytes and restored mtime (new ctime, new inode data)"
    if name == "equal_bytes_replacement":
        replacement = ws / "replacement.txt"
        replacement.write_bytes(fixture())
        os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(replacement, target)
        return "unlink + recreate with identical bytes and mtime (new inode)"
    if name == "permission_change":
        os.chmod(target, 0o600)
        return "mode 0644 -> 0600"
    if name == "hardlink_substitution":
        other = ws / "other.txt"
        other.write_bytes(fixture())
        os.utime(other, ns=(info.st_atime_ns, info.st_mtime_ns))
        target.unlink()
        os.link(other, target)
        return "input replaced by a hard link to an identical copy (nlink 2)"
    if name == "symlink_replacement":
        other = ws / "other.txt"
        other.write_bytes(fixture())
        os.utime(other, ns=(info.st_atime_ns, info.st_mtime_ns))
        target.unlink()
        os.symlink("other.txt", target)
        return "input replaced by a symlink to an identical copy"
    raise SystemExit(f"unknown mutation {name}")


MUTATIONS = [
    "unchanged",
    "mtime_only",
    "atime_only",
    "ctime_only",
    "same_size_same_content_rewrite",
    "equal_bytes_replacement",
    "permission_change",
    "hardlink_substitution",
    "symlink_replacement",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=Path("/tmp/ac-metadata-guards"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = fixture()
    rows = []
    for name in MUTATIONS:
        root = args.scratch / name
        shutil.rmtree(root, ignore_errors=True)
        native_ws = root / "native"
        traced_ws = root / "traced"
        for ws in (native_ws, traced_ws):
            ws.mkdir(parents=True)
            (ws / "corpus.txt").write_bytes(payload)
            os.utime(ws / "corpus.txt", ns=(1_600_000_000 * 10**9, 1_600_000_000 * 10**9))
        env = runner.cache_env(dict(os.environ), root / "cache")
        _, cold, _, _, _ = runner.run_traced(args.tracejit, COMMAND, traced_ws, env, POLICY)
        description = mutate(name, native_ws)
        mutate(name, traced_ws)
        native = subprocess.run(COMMAND, cwd=native_ws, env=env, capture_output=True)
        native_obs = oracle.process_observation(
            native.returncode, native.stdout, native.stderr, oracle.observe_workspace(native_ws)
        )
        _, warm, _, warm_stdout, warm_stderr = runner.run_traced(
            args.tracejit, COMMAND, traced_ws, env, POLICY
        )
        warm_obs = oracle.process_observation(
            native.returncode, warm_stdout, warm_stderr, oracle.observe_workspace(traced_ws)
        )
        compare = oracle.compare(native_obs, warm_obs)
        hit = runner.is_hit(warm)
        rows.append(
            {
                "mutation": name,
                "description": description,
                "cold_decision": (cold or {}).get("cache_decision"),
                "warm_decision": (warm or {}).get("kind"),
                "warm_cache_decision": (warm or {}).get("cache_decision"),
                "reused": hit,
                "observation_matches_native": compare["match"],
                "covered_differences": compare["covered_differences"],
                "incorrect_hit": hit and not compare["match"],
            }
        )
        shutil.rmtree(root, ignore_errors=True)

    summary = {
        "command": COMMAND,
        "policy": POLICY,
        "mutations": len(rows),
        "incorrect_hits": sum(1 for row in rows if row["incorrect_hit"]),
        "reused_after_mutation": sum(1 for row in rows if row["reused"]),
        "deoptimised": sum(1 for row in rows if row["warm_cache_decision"] == "Deoptimized"),
    }
    text = json.dumps({"summary": summary, "rows": rows}, indent=2, sort_keys=True)
    target = args.output or HERE.parent / "results/phaseac/metadata_guards.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n")
    for row in rows:
        print(f"{row['mutation']:34s} {str(row['warm_cache_decision']):12s} "
              f"reused={row['reused']} match={row['observation_matches_native']} "
              f"incorrect={row['incorrect_hit']}")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

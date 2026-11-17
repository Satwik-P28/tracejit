#!/usr/bin/env python3
"""Phase S: fs-verity prototype effect and adversarial content checks.

The kernel used here does not implement FS_IOC_MEASURE_VERITY (EOPNOTSUPP), so the
prototype can only take the strict-hash fallback. This script therefore measures two
things honestly:

  * the cost of the capability probe with TRACEJIT_VERITY=1 on a non-verity filesystem
    (paired, interleaved, so drift cannot masquerade as an effect), and
  * that every adversarial content change still deoptimises instead of producing a hit.

The hashing ceiling that acceleration could remove is reported separately from the
guard phase timings in `phases.json`.
"""

import argparse
import json
import os
import random
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZES = [64 * 1024, 4 * 1024 * 1024, 64 * 1024 * 1024]


def invoke(binary, args, cwd, cache, verity):
    env = dict(os.environ)
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    env["TRACEJIT_CACHE_DIR"] = str(cache)
    if verity:
        env["TRACEJIT_VERITY"] = "1"
    started = time.perf_counter()
    proc = subprocess.run(
        [str(binary), *args], cwd=cwd, env=env, capture_output=True, close_fds=True
    )
    wall = (time.perf_counter() - started) * 1000.0
    return proc, wall


def bootstrap_ci(values, iterations=2000, seed=11):
    rng = random.Random(seed)
    n = len(values)
    medians = sorted(
        statistics.median([values[rng.randrange(n)] for _ in range(n)])
        for _ in range(iterations)
    )
    return medians[int(0.025 * iterations)], medians[int(0.975 * iterations) - 1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--output", default=str(ROOT / "research/phase_s/results/verity.json"))
    args = parser.parse_args()
    binary = ROOT / "target/release/tracejit"
    rows = []
    with tempfile.TemporaryDirectory(prefix="tj-verity-") as tmp:
        tmp = Path(tmp)
        fixture = tmp / "fixture"
        subprocess.run(
            ["gcc", "-O2", "-o", str(fixture), str(ROOT / "tests/fixtures/fixture_driver.c")],
            check=True,
        )
        for size in SIZES:
            work = tmp / f"w{size}"
            work.mkdir()
            cachedir = work / "cache"
            cachedir.mkdir()
            (work / "input.txt").write_bytes(os.urandom(size))
            run_args = ["run", "--json", "--", str(fixture), "plain_file_read", str(work)]
            for verity in (False, True):
                proc, _ = invoke(binary, run_args, work, cachedir, verity)
                assert proc.returncode == 0, proc.stderr.decode()
                assert json.loads(proc.stdout)["kind"] == "Executed"
            off, on = [], []
            for _ in range(args.runs):
                for verity, sink in ((False, off), (True, on)):
                    proc, wall = invoke(binary, run_args, work, cachedir, verity)
                    assert proc.returncode == 0, proc.stderr.decode()
                    kind = json.loads(proc.stdout)["kind"]
                    assert kind == "Reused", f"{size}: {kind}"
                    sink.append(wall)
            diffs = [b - a for a, b in zip(off, on)]
            low, high = bootstrap_ci(diffs)
            rows.append(
                {
                    "size_bytes": size,
                    "off_median_ms": statistics.median(off),
                    "on_median_ms": statistics.median(on),
                    "paired_diff_ms": statistics.median(diffs),
                    "diff_ci95_ms": [low, high],
                }
            )
            print(
                f"{size/1024:>8.0f} KiB off={statistics.median(off):7.3f} "
                f"on={statistics.median(on):7.3f} diff={statistics.median(diffs):+6.3f} "
                f"[{low:+.3f},{high:+.3f}]"
            )
            # Adversarial: every content mutation must not reuse.
            before = len(off) + len(on)
            target = work / "input.txt"
            checks = []
            target.write_bytes(os.urandom(size))  # same inode, new content
            proc, _ = invoke(binary, run_args, work, cachedir, True)
            checks.append(("same-inode-new-content", json.loads(proc.stdout)["kind"]))
            target.write_bytes(os.urandom(size))
            proc, _ = invoke(binary, run_args, work, cachedir, True)
            checks.append(("second-mutation", json.loads(proc.stdout)["kind"]))
            for name, kind in checks:
                assert kind != "Reused", f"{size}: incorrect hit after {name}"
            print(f"  adversarial: {checks}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"results": rows}, indent=2))
    print(f"wrote {output}")


if __name__ == "__main__":
    main()

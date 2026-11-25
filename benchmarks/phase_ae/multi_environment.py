#!/usr/bin/env python3
"""Phase AE: run the same TraceJIT capability and reuse probes in a second Linux userspace.

The host that produced every Phase AD number has one userspace (Ubuntu 24.04, glibc 2.39).
This harness executes TraceJIT inside an unpacked, pinned *other* distribution root with a
user+mount namespace, so the same binary meets a different glibc, a different linker and a
different coreutils, on the same kernel.  It is deliberately explicit about what that is and
is not:

* it **is** a different userspace (glibc build, loader, distribution),
* it is **not** a different kernel, and it is **not** third-party reproduction: the operator,
  CPU and kernel are the same.

Inside the root the harness records the distribution fingerprint, the glibc version, the
mount type of the workspace, the kernel (inherited), and two measurements:

``guarded_reuse``   two identical ``gzip -9 -n -c`` runs; the second must report reuse and
                    produce byte-identical stdout,
``enforce``         two ``--enforce`` runs; reuse may only happen when the root can install
                    seccomp and the Landlock ABI, and no run may be labelled ``PROVEN``
                    otherwise.

Run: ``python3 benchmarks/phase_ae/multi_environment.py --root .phaseae-rootfs/root \
        --label ubuntu-25.10-glibc2.42 --tracejit target/release/tracejit``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

SCRIPT = r"""
set -u
echo "=== os-release ==="
cat /etc/os-release 2>/dev/null | head -4
echo "=== glibc ==="
ldd --version 2>/dev/null | head -1
echo "=== kernel ==="
uname -r
echo "=== filesystem ==="
stat -f -c %T /work 2>/dev/null || echo unknown
echo "=== lsms ==="
cat /sys/kernel/security/lsm 2>/dev/null || echo unavailable
echo "=== guarded reuse ==="
mkdir -p /work && cd /work || exit 1
rm -rf /cache out*.gz e*.txt
# input.bin is written from the host: the namespace has no /dev/zero and no cp.
for i in 1 2; do
  TRACEJIT_CACHE_DIR=/cache /opt/tracejit run --contract allocator-entropy-v1 -- \
    gzip -9 -n -c input.bin > "out$i.gz" 2> "e$i.txt"
  echo "run$i exit=$?"
done
if cmp -s out1.gz out2.gz; then echo "stdout_identical=yes"; else echo "stdout_identical=no"; fi
for i in 1 2; do
  echo "run$i decision: $(grep -E '^(cache|classified) ' "e$i.txt" | tr '\n' ' ')"
done
echo "=== native policy ==="
rm -rf /cache3 outn*.gz en*.txt
for i in 1 2; do
  TRACEJIT_CACHE_DIR=/cache3 /opt/tracejit run -- gzip -9 -n -c input.bin > "outn$i.gz" 2> "en$i.txt"
  echo "native_run$i exit=$? decision: $(grep -E '^(cache|classified) ' "en$i.txt" | tr '\n' ' ')"
done
if cmp -s outn1.gz outn2.gz; then echo "native_stdout_identical=yes"; else echo "native_stdout_identical=no"; fi
if cmp -s out1.gz outn1.gz; then echo "contract_equals_native=yes"; else echo "contract_equals_native=no"; fi
echo "=== enforce ==="
rm -rf /cache2 oute*.gz ee*.txt
for i in 1 2; do
  TRACEJIT_CACHE_DIR=/cache2 /opt/tracejit run --enforce --contract allocator-entropy-v1 -- \
    gzip -9 -n -k -f input.bin > "oute$i.txt" 2> "ee$i.txt"
  echo "enforce_run$i exit=$? decision: $(grep -E '^(cache|classified) ' "ee$i.txt" | tr '\n' ' ')"
done
echo "=== end ==="
"""


def run_in_root(root: Path, script: Path) -> subprocess.CompletedProcess:
    # The tracer needs /proc inside the root (it resolves /proc/self/fd), and procfs can only
    # be mounted from a user namespace that also owns a PID namespace, so unshare -Urmpf.
    # A bind mount of the host's /proc is refused across user namespaces; a fresh tmpfs /dev
    # with the three standard descriptor links is enough for the tracer and its children.
    for name in ("proc", "dev"):
        (root / name).mkdir(exist_ok=True)
    inner = (
        f"mount -t proc proc {root}/proc || exit 90; "
        f"mount -t tmpfs tmpfs {root}/dev || exit 91; "
        f"ln -sf /proc/self/fd/0 {root}/dev/stdin; "
        f"ln -sf /proc/self/fd/1 {root}/dev/stdout; "
        f"ln -sf /proc/self/fd/2 {root}/dev/stderr; "
        f"chroot {root} /bin/sh /probe.sh"
    )
    return subprocess.run(["unshare", "-Urmpf", "--map-root-user", "sh", "-c", inner],
                          capture_output=True, text=True, check=False)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tracejit", type=Path, default=REPO / "target/release/tracejit")
    parser.add_argument("--label", required=True)
    parser.add_argument("--gzip", type=Path, default=Path("/usr/bin/gzip"))
    parser.add_argument("--output", type=Path,
                        default=REPO / "benchmarks/results/phaseae/multi_environment.json")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracejit = args.tracejit.resolve()
    if not (root / "etc" / "os-release").is_file():
        raise SystemExit(f"{root} does not look like an unpacked root filesystem")

    (root / "opt").mkdir(exist_ok=True)
    shutil.copy2(tracejit, root / "opt" / "tracejit")
    (root / "opt" / "tracejit").chmod(0o755)
    if args.gzip.is_file() and not (root / "usr/bin/gzip").exists():
        (root / "usr/bin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.gzip, root / "usr/bin/gzip")
    (root / "work").mkdir(exist_ok=True)
    # Deterministic, compressible payload; written from the host because the namespace has no
    # /dev/zero, no cp and no python.
    (root / "work" / "input.bin").write_bytes(
        b"".join(f"row-{i:07d} key={(i * 7919) % 100003}\n".encode() for i in range(1, 40_001))
    )
    (root / "probe.sh").write_text(SCRIPT)

    completed = run_in_root(root, root / "probe.sh")
    sections: dict[str, list[str]] = {}
    current = None
    for line in completed.stdout.splitlines():
        if line.startswith("=== ") and line.endswith(" ==="):
            current = line.strip("= ").strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    result = {
        "label": args.label,
        "root": str(root),
        "kernel": (sections.get("kernel") or ["unknown"])[0],
        "os_release": sections.get("os-release", []),
        "glibc": (sections.get("glibc") or ["unknown"])[0],
        "workspace_filesystem": (sections.get("filesystem") or ["unknown"])[0],
        "lsms": (sections.get("lsms") or ["unknown"])[0],
        "tracejit_sha256": sha256_file(tracejit),
        "host_kernel": os.uname().release,
        "host_glibc": subprocess.run(["ldd", "--version"], capture_output=True, text=True)
                              .stdout.splitlines()[0],
        "guarded_reuse": sections.get("guarded reuse", []),
        "native_policy": sections.get("native policy", []),
        "enforce": sections.get("enforce", []),
        "exit": completed.returncode,
        "stderr_tail": completed.stderr[-1000:],
        "note": ("same kernel as the host; a different userspace, not third-party reproduction"),
    }
    joined = "\n".join(result["guarded_reuse"])
    result["guarded_second_run_reused"] = "decision: cache          REUSED" in joined or \
        "cache          HIT" in joined or "cache          Reused" in joined
    result["guarded_stdout_identical"] = "stdout_identical=yes" in joined
    native_joined = "\n".join(result["native_policy"])
    result["native_policy_any_reuse"] = "cache          HIT" in native_joined or \
        "cache          Reused" in native_joined
    enforce_joined = "\n".join(result["enforce"])
    result["enforce_any_proven"] = "classified     PROVEN" in enforce_joined
    result["enforce_any_reuse"] = "cache          HIT" in enforce_joined or \
        "cache          Reused" in enforce_joined

    existing = {}
    if args.output.is_file():
        existing = json.loads(args.output.read_text())
    existing[args.label] = result
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("stderr_tail",)}, indent=2)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

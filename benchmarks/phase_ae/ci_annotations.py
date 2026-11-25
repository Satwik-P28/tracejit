#!/usr/bin/env python3
"""Publish an environment probe as GitHub Actions annotations.

Annotations are visible on a public run page without authentication, which is what makes a
CI-runner fingerprint auditable from outside the repository.  The script is deliberately
forgiving: a formatting problem must never fail the probe step.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def notice(title: str, message: str) -> None:
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::notice title={title}::{message}")


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else Path("/tmp/environment.json")
    probe = json.loads(path.read_text())
    if "error" in probe:
        notice("phase-ae-probe-error", str(probe["error"])[:1500])
        notice("phase-ae-probe-traceback", str(probe.get("traceback", ""))[-2500:])
    host = probe.get("host") or {}
    doctor = probe.get("doctor") or {}
    enforcement = probe.get("enforcement") or {}
    filesystems = ", ".join(f'{entry["path"]}={entry["type"]}' for entry in probe.get("filesystems", []))
    os_release = next(
        (line for line in (host.get("os_release") or "").splitlines() if line.startswith("PRETTY_NAME")),
        "PRETTY_NAME=unknown",
    )
    glibc = ((host.get("glibc") or "").splitlines() or ["unknown"])[0]

    notice("phase-ae-kernel", f"kernel={host.get('uname', {}).get('release')} "
                              f"arch={host.get('uname', {}).get('machine')} "
                              f"cpus={host.get('cpu_count')} {os_release} glibc={glibc}")
    notice("phase-ae-security", f"lsms={host.get('lsms')} "
                                f"landlock_selftest={host.get('landlock_selftest_dir')} "
                                f"container={host.get('container')} filesystems={filesystems}")
    notice("phase-ae-doctor", json.dumps(doctor, sort_keys=True)[:3000])
    notice("phase-ae-enforcement", json.dumps(enforcement, sort_keys=True)[:3000])
    notice("phase-ae-enforcement-ok", str(bool(
        enforcement.get("label_never_exceeds_capability")
        and enforcement.get("enforce_refuses_reuse_without_proven_capability")
    )).lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

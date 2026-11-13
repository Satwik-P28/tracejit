#!/usr/bin/env python3
"""Observation probes for the Phase 3H controlled-Python study.

Each mode isolates one observation class. `counterexample` deliberately prints
the observed values so byte equality across two native runs cannot be mistaken
for causal noninterference.
"""

from __future__ import annotations

import os
import sys
import threading
import time


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "startup"
    if mode == "startup":
        print("startup-only")
    elif mode == "clocks":
        print("time", time.time_ns())
        print("monotonic", time.monotonic_ns())
        print("perf_counter", time.perf_counter_ns())
    elif mode == "identity":
        print("pid", os.getpid())
        print("ppid", os.getppid())
        print("tid", threading.get_native_id())
    elif mode == "entropy":
        print("urandom", os.urandom(16).hex())
    elif mode == "counterexample":
        print("time", time.time_ns())
        print("monotonic", time.monotonic_ns())
        print("pid", os.getpid())
        print("tid", threading.get_native_id())
        print("urandom", os.urandom(8).hex())
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

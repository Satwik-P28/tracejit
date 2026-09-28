#!/bin/sh
set -eu

cargo build --release --workspace
exec python3 benchmarks/harness/benchmark.py "$@"


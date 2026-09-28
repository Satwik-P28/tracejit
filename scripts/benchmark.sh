#!/bin/sh
set -eu

cargo build --workspace --release
exec python3 benchmarks/harness/benchmark.py "$@"

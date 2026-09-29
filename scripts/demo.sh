#!/bin/sh
# One real Linux x86_64 run: cold trace, guarded hit, explain, then deopt.
# Timings here are a single execution. Medians are in benchmarks/results/break-even.md.
set -eu

cd "$(dirname "$0")/.."
if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "This demo runs on Linux x86_64." >&2
  exit 1
fi

tracejit=${TRACEJIT:-./target/release/tracejit}
if [ ! -x "$tracejit" ]; then
  echo "Build first: cargo build --workspace --release" >&2
  exit 1
fi

input=benchmarks/workloads/c-transform/numbers.txt
binary=benchmarks/workloads/c-transform/transform
report=benchmarks/workloads/c-transform/output/report.txt
input_hash=$(sha256sum "$input" | awk '{print $1}')
saved=$(mktemp)
cp "$input" "$saved"
cache=$(mktemp -d)
logdir=$(mktemp -d)

cleanup() {
  cp "$saved" "$input"
  restored=$(sha256sum "$input" | awk '{print $1}')
  rm -f "$saved"
  rm -rf "$cache" "$logdir"
  rm -f "$binary" "$report"
  rmdir benchmarks/workloads/c-transform/output 2>/dev/null || true
  if [ "$restored" != "$input_hash" ]; then
    echo "input was not restored" >&2
    exit 1
  fi
}
trap cleanup EXIT

cc -O2 -Wall -Wextra -Werror benchmarks/workloads/c-transform/main.c -o "$binary"

export TRACEJIT_CACHE_DIR="$cache"
export GLIBC_TUNABLES=glibc.malloc.tcache_count=0
export MALLOC_ARENA_MAX=1
command="./benchmarks/workloads/c-transform/transform"

show_run() {
  label=$1
  shift
  echo "=== $label ==="
  set +e
  "$@" >"$logdir/out" 2>"$logdir/err"
  status=$?
  set -e
  cat "$logdir/out"
  cat "$logdir/err" >&2
  if [ "$status" -ne 0 ]; then
    echo "$label exited $status" >&2
    exit "$status"
  fi
}

require() {
  if ! grep -q "$1" "$2"; then
    echo "missing '$1' in $3" >&2
    exit 1
  fi
}

show_run "first traced run" "$tracejit" run -- "$command"
require "cache          MISS" "$logdir/err" "first run"
require "classified     GUARDED" "$logdir/err" "first run"
require "next run is eligible for guarded reuse" "$logdir/err" "first run"

show_run "second guarded hit" "$tracejit" run -- "$command"
require "cache          HIT" "$logdir/err" "second run"
require "speedup        " "$logdir/err" "second run"
require "saved          " "$logdir/err" "second run"

echo "=== explain ==="
"$tracejit" explain >"$logdir/explain"
awk 'BEGIN { show = 1 } /^effect detail$/ { show = 0 } show' "$logdir/explain"
require "TraceJIT explanation" "$logdir/explain" "explain"
require "classification GUARDED" "$logdir/explain" "explain"
require "cache decision Reused" "$logdir/explain" "explain"

echo "=== mutate input ==="
printf '1\n' >> "$input"
show_run "run after mutation" "$tracejit" run -- "$command"
require "cache          DEOPT" "$logdir/err" "mutated run"
if grep -q "cache          HIT" "$logdir/err"; then
  echo "mutated run reused a stale result" >&2
  exit 1
fi

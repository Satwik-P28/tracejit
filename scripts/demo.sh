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

echo "TraceJIT demo. One run each. Medians are in benchmarks/results/break-even.md."
echo "Workload: fold numbers.txt, then 250000000 extra mix rounds. This is synthetic."

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

epoch_ns() {
  value=$(date +%s%N) || {
    echo "date +%s%N failed" >&2
    exit 1
  }
  case "$value" in
    ''|*[!0-9]*)
      echo "date +%s%N did not return an integer: $value" >&2
      exit 1
      ;;
  esac
  printf '%s\n' "$value"
}

echo "=== direct run ==="
start_ns=$(epoch_ns)
set +e
"$command" >"$logdir/direct.out" 2>"$logdir/direct.err"
direct_status=$?
set -e
end_ns=$(epoch_ns)
cat "$logdir/direct.out"
cat "$logdir/direct.err" >&2
if [ "$direct_status" -ne 0 ]; then
  echo "direct run exited $direct_status" >&2
  exit "$direct_status"
fi
if [ "$end_ns" -le "$start_ns" ]; then
  echo "timer did not advance: start $start_ns end $end_ns" >&2
  exit 1
fi
echo "direct runtime $(( (end_ns - start_ns) / 1000000 )) ms (one run, not a median)"
echo "RESULT direct PASS"

show_run "first traced run" "$tracejit" run -- "$command"
require "cache          MISS" "$logdir/err" "first run"
require "classified     GUARDED" "$logdir/err" "first run"
require "next run is eligible for guarded reuse" "$logdir/err" "first run"
cmp "$logdir/direct.out" "$logdir/out"
echo "RESULT miss PASS"

cp "$logdir/out" "$logdir/first.out"
show_run "second guarded hit" "$tracejit" run -- "$command"
require "cache          HIT" "$logdir/err" "second run"
require "speedup        " "$logdir/err" "second run"
require "saved          " "$logdir/err" "second run"
cmp "$logdir/first.out" "$logdir/out"
echo "RESULT hit PASS"

echo "=== explain ==="
"$tracejit" explain >"$logdir/explain"
awk 'BEGIN { show = 1 } /^effect detail$/ { show = 0 } show' "$logdir/explain"
require "TraceJIT explanation" "$logdir/explain" "explain"
require "classification GUARDED" "$logdir/explain" "explain"
require "cache decision Reused" "$logdir/explain" "explain"
require "observed inputs" "$logdir/explain" "explain"
require "numbers.txt" "$logdir/explain" "explain"
require "guards" "$logdir/explain" "explain"
echo "RESULT explain PASS"

echo "=== mutate input ==="
printf '1\n' >> "$input"
if cmp -s "$saved" "$input"; then
  echo "mutation did not change the input" >&2
  exit 1
fi
show_run "run after mutation" "$tracejit" run -- "$command"
require "cache          DEOPT" "$logdir/err" "mutated run"
if grep -q "cache          HIT" "$logdir/err"; then
  echo "mutated run reused a stale result" >&2
  exit 1
fi
echo "RESULT mutation DEOPT"

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

cc -O2 -Wall -Wextra -Werror benchmarks/workloads/c-transform/main.c -o benchmarks/workloads/c-transform/transform
input=benchmarks/workloads/c-transform/numbers.txt
saved=$(mktemp)
cp "$input" "$saved"
cache=$(mktemp -d)
trap 'cp "$saved" "$input"; rm -f "$saved"; rm -rf "$cache"' EXIT

export TRACEJIT_CACHE_DIR="$cache"
export GLIBC_TUNABLES=glibc.malloc.tcache_count=0
export MALLOC_ARENA_MAX=1
command="./benchmarks/workloads/c-transform/transform"

echo "=== first traced run ==="
"$tracejit" run -- "$command"
echo "=== second guarded hit ==="
"$tracejit" run -- "$command"
echo "=== explain ==="
"$tracejit" explain
echo "=== mutate input ==="
printf '1\n' >> "$input"
echo "=== run after mutation ==="
"$tracejit" run -- "$command"

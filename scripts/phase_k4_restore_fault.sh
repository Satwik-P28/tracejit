#!/usr/bin/env bash
# Phase K4: soft-fail (rollback then retrace) + hard-kill mixed-workspace recovery.
#
# Soft fail: TRACEJIT_TEST_RESTORE_FAIL_PATH aborts apply after rollback; core retraces.
# Hard kill: TRACEJIT_TEST_RESTORE_PAUSE_PATH sleeps mid-apply; harness SIGKILLs; next run
# must restore correct Obs (reuse or re-exec). Multi-output restore is not crash-atomic.
#
# Usage: phase_k4_restore_fault.sh [path-to-tracejit]
set -eu

cd "$(dirname "$0")/.."
tracejit=${1:-./target/release/tracejit}
if [ ! -x "$tracejit" ]; then
  echo "Build first: cargo build -p tracejit-cli --release" >&2
  exit 2
fi
command -v cc >/dev/null || { echo "cc required" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 required" >&2; exit 2; }

# CI / cargo-test runners inherit many non-CLOEXEC descriptors. Closing them before
# exec keeps the product's inherited-fd refusal intact while making the harness CI-safe.
tracejit_run() (
  for entry in /proc/self/fd/*; do
    fd=${entry##*/}
    case "$fd" in
      0|1|2) ;;
      *) eval "exec ${fd}>&-" 2>/dev/null || true ;;
    esac
  done
  exec "$tracejit" "$@"
)

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT INT TERM

mkdir -p "$work/sub"
printf 'input one\n' >"$work/input.txt"
cc -O2 -Wall -Wextra -Werror -o "$work/two_outputs" benchmarks/realworld/repro/two_outputs.c

export TRACEJIT_CACHE_DIR="$work/cache"
export GLIBC_TUNABLES=glibc.malloc.tcache_count=0
export MALLOC_ARENA_MAX=1

tracejit_run run -- "$work/two_outputs" "$work" >/dev/null
tracejit_run run -- "$work/two_outputs" "$work" >/dev/null 2>"$work/warm.err"
grep -q 'cache          HIT' "$work/warm.err"

# --- Soft fail: inject failure on second output. Rollback then retrace. ---
printf 'user-a\n' >"$work/a.txt"
printf 'user-b\n' >"$work/sub/b.txt"
TRACEJIT_TEST_RESTORE_FAIL_PATH="$work/sub/b.txt" \
  tracejit_run run --json -- "$work/two_outputs" "$work" >"$work/soft.json" 2>"$work/soft.err"
PHASE_K4_WORK="$work" python3 - <<'PY'
import json, os
from pathlib import Path
work = Path(os.environ["PHASE_K4_WORK"])
report = json.loads((work / "soft.json").read_text())
decision = report.get("cache_decision") or report.get("kind")
assert decision != "Reused", report
assert (work / "a.txt").read_text() == "input one\n"
assert (work / "sub" / "b.txt").read_text() == "input one\n"
print(f"RESULT phase-k4-soft-fail-retrace PASS decision={decision}")
PY

# --- Hard kill: pause on second output, SIGKILL, then recover ---
printf 'user-a\n' >"$work/a.txt"
printf 'user-b\n' >"$work/sub/b.txt"
set +e
TRACEJIT_TEST_RESTORE_PAUSE_PATH="$work/sub/b.txt" \
  tracejit_run run -- "$work/two_outputs" "$work" >/dev/null 2>"$work/pause.err" &
pid=$!
sleep 0.5
kill -KILL "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
set -e
echo "after kill a=$(cat "$work/a.txt") b=$(cat "$work/sub/b.txt")"
# Recovery without hooks.
tracejit_run run --json -- "$work/two_outputs" "$work" >"$work/recover.json" 2>"$work/recover.err"
PHASE_K4_WORK="$work" python3 - <<'PY'
import json, os
from pathlib import Path
work = Path(os.environ["PHASE_K4_WORK"])
report = json.loads((work / "recover.json").read_text())
assert report.get("exit_code") == 0, report
assert (work / "a.txt").read_text() == "input one\n"
assert (work / "sub" / "b.txt").read_text() == "input one\n"
decision = report.get("cache_decision") or report.get("kind")
print(f"RESULT phase-k4-hard-kill-recovery PASS decision={decision}")
PY

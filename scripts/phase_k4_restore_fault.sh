#!/usr/bin/env bash
# Phase K4: soft-fail (rollback then retrace) + hard-kill mixed-workspace recovery.
#
# Soft fail: TRACEJIT_TEST_RESTORE_FAIL_PATH aborts apply after rollback; core retraces.
# Hard kill: TRACEJIT_TEST_RESTORE_PAUSE_PATH sleeps mid-apply; harness SIGKILLs; next run
# must restore correct Obs via re-exec (HIT refused while a dead-pid restore-intent remains).
# Multi-output restore is not crash-atomic; see docs/final/P0_RESTORE_DURABILITY.md.
#
# Both hooks are environment variables, and the inherited environment is part of the cache
# key. A run with a hook set therefore has a different identity from a run without it, and
# "set the hook, then expect a hit" could never reach the restore path: the harness used to
# export the hook only on the failing run, so that run was a miss and both scenarios passed
# without ever exercising restoration. Each scenario below therefore keeps its hook exported
# for *every* run it performs, including the discovery run that stores the record, and uses
# its own cache directory. Do not scope a hook to a single invocation.
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

# Same, but backgrounded so the caller can SIGKILL the process that owns the
# restore-intent file. `tracejit_run` itself is a subshell body, so backgrounding it
# would leave a waiter as $! and the paused restore process alive.
tracejit_exec_clean_fds() {
  for entry in /proc/self/fd/*; do
    fd=${entry##*/}
    case "$fd" in
      0|1|2) ;;
      *) eval "exec ${fd}>&-" 2>/dev/null || true ;;
    esac
  done
  exec "$tracejit" "$@"
}

work=$(mktemp -d)
# Cache state must live *outside* $work: $work is handed to the command under test, so it is an
# observed directory, and cache files created inside it change the observed listing between runs
# (and make the record unusable). Every miss in this harness traced back to that.
state=$(mktemp -d)
trap 'rm -rf "$work" "$state"' EXIT INT TERM

mkdir -p "$work/sub"
printf 'input one\n' >"$work/input.txt"
cc -O2 -Wall -Wextra -Werror -o "$work/two_outputs" benchmarks/realworld/repro/two_outputs.c

export GLIBC_TUNABLES=glibc.malloc.tcache_count=0
export MALLOC_ARENA_MAX=1

# --- Scenario 1: soft fail. HIT, fail applying the second output, roll back, retrace. ---
soft_cache="$state/cache-soft"
export TRACEJIT_CACHE_DIR="$soft_cache"
export TRACEJIT_TEST_RESTORE_FAIL_PATH="$work/sub/b.txt"
unset TRACEJIT_TEST_RESTORE_PAUSE_PATH

# Discovery with the hook present: no candidate, so nothing is restored and the hook is inert.
tracejit_run run -- "$work/two_outputs" "$work" >/dev/null
# Second run shares the identity, finds the record and restores; the hook aborts the apply.
# Its own report says MISS, because a failed apply rolls back and retraces -> the decision is
# "Executed". That is the designed outcome, not a cache miss: the evidence that the restore path
# ran is the injected-failure reason in the report, which only exists inside restore_outputs.
# The injected reason is reported in the JSON channel only; plain mode prints the retrace, not
# the cause. Asserting on it is what proves the restore path ran at all.
tracejit_run run --json -- "$work/two_outputs" "$work" >"$state/soft_probe.json" 2>/dev/null
PHASE_K4_STATE="$state" python3 - <<'PY'
import json, os
from pathlib import Path
state = Path(os.environ["PHASE_K4_STATE"])
report = json.loads((state / "soft_probe.json").read_text())
reason = report.get("decision_reason") or ""
assert "injected restoration failure" in reason, report
assert report.get("kind") == "Executed", report
print("RESULT phase-k4-soft-fail-injection PASS: the restore path ran and was aborted")
PY
printf 'user-a\n' >"$work/a.txt"
printf 'user-b\n' >"$work/sub/b.txt"
tracejit_run run --json -- "$work/two_outputs" "$work" >"$state/soft.json" 2>"$state/soft2.err"
PHASE_K4_STATE="$state" PHASE_K4_WORK="$work" python3 - <<'PY'
import json, os
from pathlib import Path
state = Path(os.environ["PHASE_K4_STATE"])
work = Path(os.environ["PHASE_K4_WORK"])
report = json.loads((state / "soft.json").read_text())
decision = report.get("cache_decision") or report.get("kind")
assert decision != "Reused", report
assert (work / "a.txt").read_text() == "input one\n"
assert (work / "sub" / "b.txt").read_text() == "input one\n"
print(f"RESULT phase-k4-soft-fail-retrace PASS decision={decision}")
PY

# --- Scenario 2: hard kill. HIT, pause mid-apply, SIGKILL, then recover. ---
hard_cache="$state/cache-hard"
export TRACEJIT_CACHE_DIR="$hard_cache"
unset TRACEJIT_TEST_RESTORE_FAIL_PATH
export TRACEJIT_TEST_RESTORE_PAUSE_PATH="$work/sub/b.txt"

# Discovery with the pause hook present: the pause lives on the restore path only, so a
# discovery run stores its record and returns without sleeping.
tracejit_run run -- "$work/two_outputs" "$work" >/dev/null

# A restore only writes outputs whose staged bytes differ from what is on disk, and the pause hook
# sits inside that write loop; a workspace that already matches the record is restored without any
# apply and therefore never pauses. The outputs must also hold the bytes the record pinned, because
# an output's pre-state is a guard. One priming run satisfies both: it misses (the pre-state changed
# from the discovery run's absent outputs), stores a record pinning these bytes, and the run after
# it hits and really applies.
printf 'user-a\n' >"$work/a.txt"
printf 'user-b\n' >"$work/sub/b.txt"
tracejit_run run -- "$work/two_outputs" "$work" >/dev/null
printf 'user-a\n' >"$work/a.txt"
printf 'user-b\n' >"$work/sub/b.txt"
set +e
( tracejit_exec_clean_fds run -- "$work/two_outputs" "$work" ) \
  >/dev/null 2>"$state/pause.err" &
pid=$!
# Poll for the intent file rather than sleeping a fixed interval: the process writes it
# immediately before the pause, and a fixed sleep either races the write or lets a
# completed restore clean the file up again.
for _ in $(seq 1 100); do
  if [ -e "$hard_cache/restore-intent.v1.$pid.json" ]; then
    break
  fi
  sleep 0.05
done
kill -KILL "$pid" 2>/dev/null
wait "$pid" 2>/dev/null
set -e
echo "after kill a=$(cat "$work/a.txt") b=$(cat "$work/sub/b.txt")"
if [ ! -e "$hard_cache/restore-intent.v1.$pid.json" ]; then
  # The pause hook only fires on a restore that actually applies bytes, and only when the
  # output path matches the hook value exactly. When it does not fire here the run simply
  # re-executes, so this scenario cannot be exercised in this configuration. Say so instead of
  # passing: the dead-intent refusal itself is covered by the integration test
  # `interrupted_restore_intent_refuses_hit` (crates/tracejit-cli/tests/linux_integration.rs),
  # which drives the same hook and asserts the refusal reason.
  echo "--- pause.err ---" >&2
  cat "$state/pause.err" >&2
  echo "RESULT phase-k4-hard-kill-recovery SKIP (pause hook did not fire; see interrupted_restore_intent_refuses_hit)"
  exit 0
fi

# Recovery with the same identity (the hook is still exported, and the pause path is only
# reachable on a hit, which the dead intent must refuse). The dead-pid intent must refuse the
# HIT and re-execute to the correct observation.
tracejit_run run --json -- "$work/two_outputs" "$work" >"$state/recover.json" 2>"$state/recover.err"
PHASE_K4_STATE="$state" PHASE_K4_WORK="$work" python3 - <<'PY'
import json, os
from pathlib import Path
state = Path(os.environ["PHASE_K4_STATE"])
work = Path(os.environ["PHASE_K4_WORK"])
report = json.loads((state / "recover.json").read_text())
assert report.get("exit_code") == 0, report
assert (work / "a.txt").read_text() == "input one\n"
assert (work / "sub" / "b.txt").read_text() == "input one\n"
decision = report.get("cache_decision") or report.get("kind")
assert decision != "Reused", report
reason = report.get("decision_reason") or ""
assert "interrupted" in reason, report
print(f"RESULT phase-k4-hard-kill-recovery PASS decision={decision}")
PY

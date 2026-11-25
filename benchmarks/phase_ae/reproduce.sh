#!/usr/bin/env bash
# Phase AE benchmark package: one entry point, two suites.
#
#   ./benchmarks/phase_ae/reproduce.sh quick   # ~2 minutes: accounting, integrity, TOCTOU,
#                                              # environment probe; no competitor needed
#   ./benchmarks/phase_ae/reproduce.sh full    # the competitive matrix and economics; needs a
#                                              # Firebuild build (see docs/FIREBUILD_CROSS_VERSION_RESULTS.md)
#
# Environment variables:
#   TRACEJIT=path/to/tracejit        (default: target/release/tracejit)
#   FIREBUILD=path/to/firebuild      (build-tree binary for >=0.8.6)
#   FIREBUILD_CONF=path/to/firebuild.conf
#   FIREBUILD_VERSION=0.8.6.2
#   FIREBUILD_LABEL=fb862            (prefix used for arm ids)
#
# Every suite writes raw JSON under benchmarks/results/phaseae/.  Expected capability skips are
# printed, never silently swallowed: no Landlock here means --enforce cannot reuse, and an
# unaudited libc means the allocator-entropy contract is unavailable.
set -u
cd "$(dirname "$0")/../.." || exit 1

TRACEJIT=${TRACEJIT:-target/release/tracejit}
SUITE=${1:-quick}
status=0
step() { printf '\n=== %s ===\n' "$1"; }
check() { if [ "$1" -ne 0 ]; then echo "FAILED: $2"; status=1; else echo "ok: $2"; fi; }

if [ ! -x "$TRACEJIT" ]; then
  echo "building $TRACEJIT"
  cargo build --release -p tracejit-cli >/dev/null 2>&1 || { echo "build failed"; exit 1; }
fi

step "harness accounting regressions"
python3 benchmarks/phase_ae/test_accounting.py >/dev/null 2>&1
check $? "test_accounting.py"

step "fresh-cache TraceJIT integrity probe (corrupted object must not be served)"
python3 benchmarks/phase_ae/tracejit_integrity_probe.py --tracejit "$TRACEJIT" >/dev/null 2>&1
check $? "tracejit_integrity_probe.py"

step "TOCTOU interleavings (deterministic hooks + concurrent writer)"
python3 benchmarks/phase_ae/toctou_race.py --tracejit "$TRACEJIT" >/dev/null 2>&1
check $? "toctou_race.py"

step "environment fingerprint and enforcement probe"
python3 benchmarks/phase_ae/environment_probe.py --tracejit "$TRACEJIT" \
  --output benchmarks/results/phaseae/environment-local.json >/dev/null 2>&1
check $? "environment_probe.py"

if [ "$SUITE" = "quick" ]; then
  echo
  echo "quick suite done; see docs/PHASE_AE_REPORT.md for interpretation"
  exit $status
fi

step "competitive matrix (needs Firebuild)"
if [ -z "${FIREBUILD:-}" ] || [ -z "${FIREBUILD_CONF:-}" ]; then
  echo "SKIP: FIREBUILD/FIREBUILD_CONF unset; see docs/FIREBUILD_CROSS_VERSION_RESULTS.md"
else
  python3 benchmarks/phase_ae/competitive_matrix.py \
    --tracejit "$TRACEJIT" \
    --arms native,tj-ae,tj-native \
    --workloads bzip2-file,gzip-file,gzip-stdout,sed-lines,sha256sum,gzip-mutating \
    --sizes 2,3,10,25 --modes cold,steady --repeats 5 \
    --firebuild-binary "$FIREBUILD" --firebuild-conf "$FIREBUILD_CONF" \
    --firebuild-version "${FIREBUILD_VERSION:-unknown}" \
    --firebuild-label "${FIREBUILD_LABEL:-fb}" --tuned
  check $? "competitive_matrix.py (${FIREBUILD_VERSION:-unknown})"
  python3 benchmarks/phase_ae/economics.py --markdown >/dev/null 2>&1
  check $? "economics.py"
  python3 benchmarks/phase_ae/firebuild_policy_probe.py \
    --firebuild "$FIREBUILD" --conf "$FIREBUILD_CONF" \
    --version "${FIREBUILD_VERSION:-unknown}" --label "${FIREBUILD_LABEL:-fb}-default"
  check $? "firebuild_policy_probe.py (${FIREBUILD_VERSION:-unknown})"
fi

step "verified replay profile and lower bounds"
python3 benchmarks/phase_ae/replay_profile.py --tracejit "$TRACEJIT" \
  --artifacts "${ARTIFACTS:-/tmp/artifacts}" >/dev/null 2>&1
check $? "replay_profile.py (skips missing artifacts)"

echo
echo "full suite done (status $status)"
exit $status

#!/bin/sh
# Clean-install verification for a packaged release archive.
#
# Usage: scripts/clean-install-verify.sh DIST_DIR
#
# Installs from the local archive exactly as a user would (checksum, layout and
# version are verified by install-release.sh), then runs the installed binary,
# never the development target. Prints RESULT lines and exits nonzero on any
# failed step.
set -eu

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "clean-install verification runs on Linux x86_64 only" >&2
  exit 1
fi

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
dist=$(CDPATH= cd -- "${1:?usage: scripts/clean-install-verify.sh DIST_DIR}" && pwd)
version=$(cat "$root/VERSION")
prefix=$(mktemp -d)
home_dir=$(mktemp -d)
cache_dir=$(mktemp -d)
cleanup() {
  rm -rf "$prefix" "$home_dir" "$cache_dir"
}
trap cleanup EXIT

fail() {
  echo "RESULT clean-install FAIL: $1" >&2
  exit 1
}

echo "=== install from archive ==="
TRACEJIT_RELEASE_DIR="$dist" TRACEJIT_INSTALL_PREFIX="$prefix" \
  "$root/scripts/install-release.sh"
test -x "$prefix/tracejit" || fail "installer did not produce an executable"
tracejit=$prefix/tracejit
echo "RESULT install PASS"

echo "=== checksum verification ==="
(cd "$dist" && sha256sum -c SHA256SUMS) || fail "checksum verification"
echo "RESULT checksum PASS"

echo "=== version ==="
reported=$("$tracejit" --version)
test "$reported" = "tracejit ${version}" || fail "version is '$reported'"
echo "RESULT version PASS ($reported)"

echo "=== help and doctor ==="
"$tracejit" --help >/dev/null || fail "--help"
doctor=$("$tracejit" doctor)
printf '%s\n' "$doctor"
printf '%s\n' "$doctor" | grep -q 'supported      yes' || fail "doctor unsupported"
printf '%s\n' "$doctor" | grep -q 'ptrace         yes' || fail "doctor ptrace"
echo "RESULT help PASS"
echo "RESULT doctor PASS"
if printf '%s\n' "$doctor" | grep -q 'landlock       yes'; then
  echo "RESULT proven-capability PASS"
else
  echo "RESULT proven-capability SKIP: Landlock is not enabled on this kernel"
fi

echo "=== cache initialization ==="
export TRACEJIT_CACHE_DIR="$cache_dir"
"$tracejit" cache stats >/dev/null || fail "cache stats"
test -d "$cache_dir" || fail "cache directory was not created"
echo "RESULT cache-init PASS"

echo "=== cold execution, warm hit, mutation deopt ==="
demo_log=$(mktemp)
TRACEJIT="$tracejit" "$root/scripts/demo.sh" >"$demo_log" 2>&1 || {
  cat "$demo_log" >&2
  fail "demo against the installed binary"
}
grep -q 'RESULT miss PASS' "$demo_log" || fail "cold execution"
grep -q 'RESULT hit PASS' "$demo_log" || fail "warm hit"
grep -q 'RESULT mutation DEOPT' "$demo_log" || fail "mutation deopt"
rm -f "$demo_log"
echo "RESULT cold-execution PASS"
echo "RESULT warm-hit PASS"
echo "RESULT mutation-deopt PASS"

echo "=== nondeterministic command is refused ==="
refusal_dir=$(mktemp -d)
refusal_cache=$(mktemp -d)
TRACEJIT_CACHE_DIR="$refusal_cache" "$tracejit" run -- \
  python3 -c 'import os; print(os.urandom(4).hex())' >"$refusal_dir/python.out" 2>"$refusal_dir/python.err" || true
if grep -q 'cache          HIT' "$refusal_dir/python.err"; then
  fail "nondeterministic command was reused"
fi
if ! grep -Eq 'classified     (UNKNOWN|NONDETERMINISTIC)' "$refusal_dir/python.err"; then
  cat "$refusal_dir/python.err" >&2
  fail "nondeterministic command was not classified as refused"
fi
echo "RESULT nondeterministic-refusal PASS"
rm -rf "$refusal_dir" "$refusal_cache"

echo "=== concurrent execution ==="
concurrent_cache=$(mktemp -d)
pids=""
for _ in 1 2 3 4; do
  TRACEJIT_CACHE_DIR="$concurrent_cache" "$tracejit" run -- /bin/true >/dev/null 2>&1 &
  pids="$pids $!"
done
for pid in $pids; do
  wait "$pid" || fail "concurrent run failed"
done
pids=""
for _ in 1 2 3 4; do
  TRACEJIT_CACHE_DIR="$concurrent_cache" "$tracejit" run -- /bin/true >/dev/null 2>&1 &
  pids="$pids $!"
done
for pid in $pids; do
  wait "$pid" || fail "concurrent warm run failed"
done
echo "RESULT concurrency PASS"
rm -rf "$concurrent_cache"

echo "=== uninstall and reinstall ==="
rm -f "$prefix/tracejit"
test ! -e "$prefix/tracejit" || fail "uninstall"
TRACEJIT_RELEASE_DIR="$dist" TRACEJIT_INSTALL_PREFIX="$prefix" \
  "$root/scripts/install-release.sh" >/dev/null
test "$("$prefix/tracejit" --version)" = "tracejit ${version}" || fail "reinstall version"
echo "RESULT uninstall-reinstall PASS"

echo "RESULT clean-install PASS"

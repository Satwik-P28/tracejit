#!/bin/sh
# Reproduces the multi-output partial-restoration defect, or shows it is fixed.
#
# usage: partial_restore.sh <path-to-tracejit>
#
# The workspace has two captured outputs in two directories. After a verified
# cache hit, the second output's directory is made read-only, which passes the
# per-output precondition check (the file itself is still writable) but makes
# staging a replacement in that directory fail. The question this script answers
# is whether the first output was already replaced when that failure happened.
#
# Exit status 0 when the failed restoration left the workspace untouched.
set -eu

tracejit=$1
if [ ! -x "$tracejit" ]; then
  echo "usage: partial_restore.sh <path-to-tracejit>" >&2
  exit 2
fi
command -v cc >/dev/null || { echo "cc is required" >&2; exit 2; }

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'chmod -R u+w "$work" 2>/dev/null; rm -rf "$work"' EXIT INT TERM

mkdir -p "$work/sub"
printf 'input one\n' > "$work/input.txt"
cc -O2 -Wall -Wextra -Werror -o "$work/two_outputs" "$here/two_outputs.c"

TRACEJIT_CACHE_DIR="$work/cache" \
GLIBC_TUNABLES=glibc.malloc.tcache_count=0 \
MALLOC_ARENA_MAX=1 \
  "$tracejit" run -- "$work/two_outputs" "$work" >/dev/null 2>&1

TRACEJIT_CACHE_DIR="$work/cache" \
GLIBC_TUNABLES=glibc.malloc.tcache_count=0 \
MALLOC_ARENA_MAX=1 \
  "$tracejit" run -- "$work/two_outputs" "$work" >/dev/null 2>"$work/second.err"
if ! grep -q 'cache          HIT' "$work/second.err"; then
  echo "FAIL: the second run did not reuse, so this host cannot reproduce the setup" >&2
  cat "$work/second.err" >&2
  exit 1
fi

printf 'user content\n' > "$work/a.txt"
printf 'user content\n' > "$work/sub/b.txt"
chmod 0555 "$work/sub"

set +e
TRACEJIT_CACHE_DIR="$work/cache" \
GLIBC_TUNABLES=glibc.malloc.tcache_count=0 \
MALLOC_ARENA_MAX=1 \
  "$tracejit" run -- "$work/two_outputs" "$work" >/dev/null 2>"$work/third.err"
status=$?
set -e

chmod 0755 "$work/sub"
first=$(cat "$work/a.txt")
second=$(cat "$work/sub/b.txt")

echo "third run exit status : $status"
grep '^tracejit:' "$work/third.err" >&2 || true
echo "a.txt                 : $first"
echo "sub/b.txt             : $second"

if [ "$status" -eq 0 ]; then
  echo "INCONCLUSIVE: the third run succeeded, so no restoration failure was induced" >&2
  exit 2
fi

if [ "$first" = "input one" ]; then
  echo "RESULT partial restoration: a.txt was replaced from the cache before the failure"
  exit 1
fi

echo "RESULT no partial mutation: a.txt still holds the caller's content"

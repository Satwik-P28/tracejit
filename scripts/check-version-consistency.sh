#!/bin/sh
# Fail when the version declarations disagree.
#
# Sources checked: ./VERSION, the Cargo workspace version, the built binary
# (when present), and stale version literals in release scripts and workflows.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

file_version=$(cat VERSION)
cargo_version=$(awk '
  /^\[workspace.package\]/ { in_section = 1; next }
  /^\[/ { in_section = 0 }
  in_section && /^version = "/ { gsub(/"/, "", $3); print $3; exit }
' Cargo.toml)

if [ "$file_version" != "$cargo_version" ]; then
  echo "VERSION ($file_version) != Cargo.toml workspace version ($cargo_version)" >&2
  exit 1
fi

binary=${TRACEJIT_BINARY:-$root/target/release/tracejit}
if [ -x "$binary" ]; then
  reported=$("$binary" --version | awk '{print $2}')
  if [ "$reported" != "$file_version" ]; then
    echo "binary reports $reported but VERSION is $file_version" >&2
    exit 1
  fi
fi

# A hardcoded previous version in the release path silently republishes the
# wrong archive. Research and historical documents are exempt.
if grep -rn --include='*.sh' --include='*.yml' --include='*.yaml' --include='*.py' \
  -e '0\.1\.1' scripts .github benchmarks/releases 2>/dev/null; then
  echo "a hardcoded previous version literal found in release scripts or workflows" >&2
  exit 1
fi

echo "version consistency PASS ($file_version)"

#!/bin/sh
# Build the Linux x86_64 release archive and its provenance manifest.
#
# Usage: scripts/package-release.sh [DIST_DIR]
#
# Environment:
#   TRACEJIT_RELEASE_VERSION  override VERSION (default: contents of ./VERSION)
#   TRACEJIT_BINARY           binary to package (default: target/release/tracejit)
#   TRACEJIT_ALLOW_DIRTY=1    package a dirty working tree (records dirty=true)
#   SOURCE_DATE_EPOCH         tar member timestamp (default: commit time)
#
# The archive is not claimed to be byte-for-byte reproducible. The manifest
# records the exact commit, toolchain, lockfile, target and artifact hashes so a
# rebuild can be compared by hand.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

target=x86_64-unknown-linux-gnu
version="${TRACEJIT_RELEASE_VERSION:-$(cat "$root/VERSION")}"
case "$version" in
  ''|*[!0-9A-Za-z.+-]*)
    echo "invalid release version: $version" >&2
    exit 1
    ;;
esac
name="tracejit-v${version}-${target}"
dist=${1:-"$root/dist"}
binary="${TRACEJIT_BINARY:-$root/target/release/tracejit}"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "the release archive is built on Linux x86_64 only" >&2
  exit 1
fi
if [ ! -x "$binary" ]; then
  echo "missing release binary: $binary (run cargo build --workspace --release)" >&2
  exit 1
fi

commit=$(git rev-parse HEAD)
dirty=false
if [ -n "$(git status --porcelain)" ]; then
  if [ "${TRACEJIT_ALLOW_DIRTY:-0}" != "1" ]; then
    echo "working tree is dirty; commit first or set TRACEJIT_ALLOW_DIRTY=1" >&2
    git status --short >&2
    exit 1
  fi
  dirty=true
fi

reported=$("$binary" --version | awk '{print $2}')
if [ "$reported" != "$version" ]; then
  echo "binary reports $reported but VERSION is $version" >&2
  exit 1
fi

epoch="${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct)}"
stage="$dist/$name"
rm -rf "$stage" "$dist/$name.tar.gz" "$dist/SHA256SUMS" "$dist/RELEASE_MANIFEST.json" "$dist/sbom.cdx.json"
mkdir -p "$stage/docs"

install -m 0755 "$binary" "$stage/tracejit"
install -m 0644 README.md LICENSE-APACHE LICENSE-MIT SECURITY.md SAFETY.md \
  ARCHITECTURE.md RELEASE_NOTES.md CHANGELOG.md VERSION "$stage/"
install -m 0644 docs/INSTALL.md docs/BENCHMARK_REPRODUCTION.md docs/LIMITATIONS.md "$stage/docs/"

# Provenance before hashing, so the manifest describes the archive contents.
python3 scripts/release_manifest.py \
  --version "$version" --commit "$commit" --dirty "$dirty" --target "$target" \
  --binary "$binary" --stage "$stage" --output "$stage/RELEASE_MANIFEST.json"
python3 scripts/release_sbom.py --output "$stage/sbom.cdx.json"

tar --sort=name --mtime="@${epoch}" --owner=0 --group=0 --numeric-owner \
  -C "$dist" -cf - "$name" | gzip -n -9 > "$dist/$name.tar.gz"
(cd "$dist" && sha256sum "$name.tar.gz" > SHA256SUMS)

cp "$stage/RELEASE_MANIFEST.json" "$dist/RELEASE_MANIFEST.json"
cp "$stage/sbom.cdx.json" "$dist/sbom.cdx.json"
(
  cd "$dist"
  sha256sum RELEASE_MANIFEST.json sbom.cdx.json >> SHA256SUMS
)

echo "packaged $dist/$name.tar.gz"
cat "$dist/SHA256SUMS"

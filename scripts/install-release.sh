#!/bin/sh
# Install the published Linux x86_64 release. Exits if v0.1.0 has not been published.
set -eu

version=0.1.0
name="tracejit-v${version}-x86_64-unknown-linux-gnu.tar.gz"
base="https://github.com/Satwik-P28/tracejit/releases/download/v${version}"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
cd "$workdir"

if ! curl -fsSL -o "$name" "${base}/${name}"; then
  echo "v${version} is not published. Use ./scripts/install-dev.sh from a checkout." >&2
  exit 1
fi
curl -fsSL -o SHA256SUMS "${base}/SHA256SUMS"
sha256sum -c SHA256SUMS
tar -xzf "$name"

dest="${HOME}/.local/bin"
mkdir -p "$dest"
install -m 755 "tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit" "${dest}/tracejit"
echo "installed ${dest}/tracejit"
echo "ensure ${dest} is on PATH, then run: tracejit doctor"

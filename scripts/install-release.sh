#!/bin/sh
# Install the published Linux x86_64 release. Exits if v0.1.1 has not been published.
# TRACEJIT_RELEASE_DIR skips the download and reads the archive plus SHA256SUMS from that directory.
# TRACEJIT_INSTALL_PREFIX selects the install directory. The default is ~/.local/bin.
set -eu

version=0.1.1
name="tracejit-v${version}-x86_64-unknown-linux-gnu.tar.gz"
base="${TRACEJIT_RELEASE_BASE:-https://github.com/Satwik-P28/tracejit/releases/download/v${version}}"
dest="${TRACEJIT_INSTALL_PREFIX:-${HOME}/.local/bin}"
if [ -n "${TRACEJIT_RELEASE_DIR:-}" ]; then
  TRACEJIT_RELEASE_DIR=$(CDPATH= cd -- "$TRACEJIT_RELEASE_DIR" && pwd)
fi
case "$dest" in
  /*) ;;
  *) dest=$(pwd)/$dest ;;
esac

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "TraceJIT v${version} requires Linux x86_64." >&2
  exit 1
fi

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
cd "$workdir"

if [ -n "${TRACEJIT_RELEASE_DIR:-}" ]; then
  if [ ! -f "${TRACEJIT_RELEASE_DIR}/${name}" ] || [ ! -f "${TRACEJIT_RELEASE_DIR}/SHA256SUMS" ]; then
    echo "v${version} is not published. Use ./scripts/install-dev.sh from a checkout." >&2
    exit 1
  fi
  cp "${TRACEJIT_RELEASE_DIR}/${name}" "${TRACEJIT_RELEASE_DIR}/SHA256SUMS" .
else
  if ! curl -fsSL -o "$name" "${base}/${name}"; then
    echo "v${version} is not published. Use ./scripts/install-dev.sh from a checkout." >&2
    exit 1
  fi
  if ! curl -fsSL -o SHA256SUMS "${base}/SHA256SUMS"; then
    echo "v${version} checksum file is missing. Refusing to install." >&2
    exit 1
  fi
fi

if ! sha256sum -c SHA256SUMS; then
  echo "checksum mismatch; refusing to install" >&2
  exit 1
fi
tar -xzf "$name"

mkdir -p "$dest"
install -m 755 "tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit" "${dest}/tracejit"
echo "installed ${dest}/tracejit"
echo "ensure ${dest} is on PATH, then run: tracejit doctor"

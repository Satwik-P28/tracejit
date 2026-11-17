#!/bin/sh
# Install the published Linux x86_64 release.
#
# Version resolution: TRACEJIT_RELEASE_VERSION, else ./VERSION next to this script.
#   TRACEJIT_RELEASE_DIR     read the archive and SHA256SUMS from a local directory
#   TRACEJIT_RELEASE_BASE    download base URL (default: the GitHub release tag)
#   TRACEJIT_INSTALL_PREFIX  install directory (default: ~/.local/bin)
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if [ -n "${TRACEJIT_RELEASE_VERSION:-}" ]; then
  version=$TRACEJIT_RELEASE_VERSION
elif [ -f "$root/VERSION" ]; then
  version=$(cat "$root/VERSION")
else
  echo "cannot determine the release version; set TRACEJIT_RELEASE_VERSION" >&2
  exit 1
fi

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

# SHA256SUMS also lists the manifest and SBOM, which this script does not
# download. Verify the archive entry and fail if it is absent.
if ! grep -q "  ${name}\$" SHA256SUMS; then
  echo "SHA256SUMS has no entry for ${name}; refusing to install" >&2
  exit 1
fi
if ! sha256sum -c --ignore-missing SHA256SUMS; then
  echo "checksum mismatch; refusing to install" >&2
  exit 1
fi
tar -xzf "$name"

extracted="tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit"
if [ ! -x "$extracted" ]; then
  echo "archive does not contain $extracted" >&2
  exit 1
fi
reported=$("$extracted" --version | awk '{print $2}')
if [ "$reported" != "$version" ]; then
  echo "archive binary reports $reported but the release is $version; refusing to install" >&2
  exit 1
fi

mkdir -p "$dest"
install -m 755 "$extracted" "${dest}/tracejit"
echo "installed ${dest}/tracejit"
echo "ensure ${dest} is on PATH, then run: tracejit doctor"

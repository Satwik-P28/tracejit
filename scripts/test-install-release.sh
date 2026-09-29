#!/bin/sh
# Exercise install-release.sh against a local archive. Does not contact GitHub.
set -eu

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "This installer test runs on Linux x86_64." >&2
  exit 1
fi

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
release_dir=${1:?usage: scripts/test-install-release.sh DIST_DIR}
name=tracejit-v0.1.0-x86_64-unknown-linux-gnu.tar.gz
archive="${release_dir}/${name}"
sums="${release_dir}/SHA256SUMS"
install_script="${root}/scripts/install-release.sh"

test -f "$archive"
test -f "$sums"
(cd "$release_dir" && sha256sum -c SHA256SUMS)

members=$(tar -tzf "$archive" | sort)
expected=$(printf '%s\n' \
  "tracejit-v0.1.0-x86_64-unknown-linux-gnu/" \
  "tracejit-v0.1.0-x86_64-unknown-linux-gnu/LICENSE-APACHE" \
  "tracejit-v0.1.0-x86_64-unknown-linux-gnu/LICENSE-MIT" \
  "tracejit-v0.1.0-x86_64-unknown-linux-gnu/README.md" \
  "tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit" | sort)
test "$members" = "$expected"
tar -tvzf "$archive" | grep '/tracejit$' | grep -q '^-r.x'
file "${release_dir}/tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit" | grep -q 'ELF 64-bit'
file "${release_dir}/tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit" | grep -q 'x86-64'
file "${release_dir}/tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit" | grep -q 'dynamically linked'
if ldd "${release_dir}/tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit" | grep -q 'not found'; then
  echo "release binary has an unresolved dynamic dependency" >&2
  ldd "${release_dir}/tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit" >&2
  exit 1
fi

prefix=$(mktemp -d)
trap 'rm -rf "$prefix"' EXIT
TRACEJIT_RELEASE_DIR="$release_dir" TRACEJIT_INSTALL_PREFIX="$prefix" "$install_script"
test -x "${prefix}/tracejit"
"${prefix}/tracejit" --version | grep -q 'tracejit 0.1.0'
doctor_out=$("${prefix}/tracejit" doctor)
printf '%s\n' "$doctor_out"
printf '%s\n' "$doctor_out" | grep -q 'supported      yes'
if printf '%s\n' "$doctor_out" | grep -q 'not writable'; then
  echo "doctor reported an unwritable cache on a normal home directory" >&2
  exit 1
fi

bad=$(mktemp -d)
cp "$archive" "$sums" "$bad/"
checksum_prefix=$(mktemp -d)
printf '%s\n' "0000000000000000000000000000000000000000000000000000000000000000  ${name}" > "$bad/SHA256SUMS"
set +e
checksum_out=$(TRACEJIT_RELEASE_DIR="$bad" TRACEJIT_INSTALL_PREFIX="$checksum_prefix" "$install_script" 2>&1)
checksum_status=$?
set -e
printf '%s\n' "$checksum_out"
test "$checksum_status" -ne 0
printf '%s\n' "$checksum_out" | grep -q 'checksum mismatch'
test ! -e "${checksum_prefix}/tracejit"
rm -rf "$bad" "$checksum_prefix"

empty=$(mktemp -d)
missing_prefix=$(mktemp -d)
set +e
missing_out=$(TRACEJIT_RELEASE_DIR="$empty" TRACEJIT_INSTALL_PREFIX="$missing_prefix" "$install_script" 2>&1)
missing_status=$?
set -e
printf '%s\n' "$missing_out"
test "$missing_status" -ne 0
printf '%s\n' "$missing_out" | grep -q 'not published'
test ! -e "${missing_prefix}/tracejit"
rm -rf "$empty" "$missing_prefix"

echo "installer test passed"

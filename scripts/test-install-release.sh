#!/bin/sh
# Exercise install-release.sh against a local dist directory. Does not contact GitHub.
#
# Usage: scripts/test-install-release.sh DIST_DIR
set -eu

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "This installer test runs on Linux x86_64." >&2
  exit 1
fi

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
release_dir=$(CDPATH= cd -- "${1:?usage: scripts/test-install-release.sh DIST_DIR}" && pwd)
version=$(cat "$root/VERSION")
prefix_name="tracejit-v${version}-x86_64-unknown-linux-gnu"
name="${prefix_name}.tar.gz"
archive="${release_dir}/${name}"
sums="${release_dir}/SHA256SUMS"
install_script="${root}/scripts/install-release.sh"

test -f "$archive"
test -f "$sums"
test -f "${release_dir}/RELEASE_MANIFEST.json"
test -f "${release_dir}/sbom.cdx.json"
(cd "$release_dir" && sha256sum -c SHA256SUMS)

members=$(tar -tzf "$archive" | sort)
expected=$(printf '%s\n' \
  "${prefix_name}/" \
  "${prefix_name}/ARCHITECTURE.md" \
  "${prefix_name}/CHANGELOG.md" \
  "${prefix_name}/LICENSE-APACHE" \
  "${prefix_name}/LICENSE-MIT" \
  "${prefix_name}/README.md" \
  "${prefix_name}/RELEASE_MANIFEST.json" \
  "${prefix_name}/RELEASE_NOTES.md" \
  "${prefix_name}/SAFETY.md" \
  "${prefix_name}/SECURITY.md" \
  "${prefix_name}/VERSION" \
  "${prefix_name}/docs/" \
  "${prefix_name}/docs/BENCHMARK_REPRODUCTION.md" \
  "${prefix_name}/docs/INSTALL.md" \
  "${prefix_name}/docs/LIMITATIONS.md" \
  "${prefix_name}/sbom.cdx.json" \
  "${prefix_name}/tracejit" | sort)
test "$members" = "$expected"
tar -tvzf "$archive" | grep '/tracejit$' | grep -q '^-r.x'
file "${release_dir}/${prefix_name}/tracejit" | grep -q 'ELF 64-bit'
file "${release_dir}/${prefix_name}/tracejit" | grep -q 'x86-64'
file "${release_dir}/${prefix_name}/tracejit" | grep -q 'dynamically linked'
if ldd "${release_dir}/${prefix_name}/tracejit" | grep -q 'not found'; then
  echo "release binary has an unresolved dynamic dependency" >&2
  ldd "${release_dir}/${prefix_name}/tracejit" >&2
  exit 1
fi

prefix=$(mktemp -d)
trap 'rm -rf "$prefix"' EXIT
TRACEJIT_RELEASE_DIR="$release_dir" TRACEJIT_INSTALL_PREFIX="$prefix" "$install_script"
test -x "${prefix}/tracejit"
test "$("${prefix}/tracejit" --version)" = "tracejit ${version}"
doctor_out=$("${prefix}/tracejit" doctor)
printf '%s\n' "$doctor_out"
printf '%s\n' "$doctor_out" | grep -q 'supported      yes'
if printf '%s\n' "$doctor_out" | grep -q 'not writable'; then
  echo "doctor reported an unwritable cache on a normal home directory" >&2
  exit 1
fi

# A checksum that does not match the archive must refuse installation.
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

# A truncated archive with a matching checksum must fail before the binary is installed.
corrupt=$(mktemp -d)
corrupt_prefix=$(mktemp -d)
head -c 4096 "$archive" > "$corrupt/${name}"
(cd "$corrupt" && sha256sum "${name}" > SHA256SUMS)
set +e
corrupt_out=$(TRACEJIT_RELEASE_DIR="$corrupt" TRACEJIT_INSTALL_PREFIX="$corrupt_prefix" "$install_script" 2>&1)
corrupt_status=$?
set -e
printf '%s\n' "$corrupt_out"
test "$corrupt_status" -ne 0
test ! -e "${corrupt_prefix}/tracejit"
rm -rf "$corrupt" "$corrupt_prefix"

# A missing archive must refuse installation.
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

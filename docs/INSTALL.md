# Install TraceJIT (Linux x86_64)

TraceJIT is a research prototype. It requires Linux x86_64, a kernel with
`ptrace`, and a filesystem that supports advisory locking. Other platforms are
refused, not emulated.

## From a release archive

```bash
version=$(curl -fsSL https://raw.githubusercontent.com/Satwik-P28/tracejit/main/VERSION)
base="https://github.com/Satwik-P28/tracejit/releases/download/v${version}"
name="tracejit-v${version}-x86_64-unknown-linux-gnu.tar.gz"

curl -fsSLO "${base}/${name}"
curl -fsSLO "${base}/SHA256SUMS"
sha256sum -c --ignore-missing SHA256SUMS
tar -xzf "$name"
install -m 755 "tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit" ~/.local/bin/tracejit
```

`~/.local/bin` must be on `PATH`. Verify the install:

```bash
tracejit --version
tracejit doctor
```

`doctor` must print `supported      yes` and `ptrace         yes`. With
`--enforce`, `seccomp` and `landlock` must also be `yes`; otherwise TraceJIT
stays `GUARDED` and never claims `PROVEN`.

The repository installer performs the same steps and refuses an archive whose
checksum, layout, or reported version does not match:

```bash
./scripts/install-release.sh            # version from ./VERSION
TRACEJIT_INSTALL_PREFIX=$HOME/bin ./scripts/install-release.sh
TRACEJIT_RELEASE_DIR=./dist ./scripts/test-install-release.sh ./dist
```

## From source

```bash
git clone https://github.com/Satwik-P28/tracejit
cd tracejit
cargo build --workspace --release     # Rust stable, 1.85 or newer
./scripts/demo.sh
```

## Uninstall

```bash
rm ~/.local/bin/tracejit
tracejit cache clear                  # optional: drops cached outputs and records
```

The cache lives in `~/.cache/tracejit` (or `TRACEJIT_CACHE_DIR`). Treat it as
sensitive as the commands you traced: it can contain command output and
environment values. It is not encrypted and not isolated between users.

## Verify an artifact

`RELEASE_MANIFEST.json` records the exact commit, Rust toolchain, lockfile hash,
target and per-file SHA-256. `sbom.cdx.json` is a CycloneDX 1.5 dependency
inventory generated from `Cargo.lock`. Both are listed in `SHA256SUMS`.

```bash
sha256sum -c --ignore-missing SHA256SUMS
python3 -c 'import json,sys; m=json.load(open("RELEASE_MANIFEST.json")); print(m["release"]["commit"], m["build"]["target"])'
```

Byte-for-byte rebuild equality is **not** claimed. See
[BENCHMARK_REPRODUCTION.md](BENCHMARK_REPRODUCTION.md) to rebuild and compare.

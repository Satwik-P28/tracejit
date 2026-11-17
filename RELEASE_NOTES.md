# TraceJIT v0.2.0-beta.1

First independently packaged public beta. Linux x86_64 only.

TraceJIT is a research-oriented prototype. It does not guarantee execution
equivalence, has not been peer reviewed, and has no production adoption. Read
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) before relying on a cache hit.

## What changed

- Version declarations now come from one `VERSION` file, checked against the
  Cargo workspace version and the binary by `scripts/check-version-consistency.sh`
  and by CI.
- The release archive is built by `scripts/package-release.sh` and contains the
  optimized binary, README, both licenses, `SECURITY.md`, `SAFETY.md`,
  `ARCHITECTURE.md`, install and benchmark-reproduction guides,
  `docs/LIMITATIONS.md`, a provenance manifest, and a CycloneDX SBOM.
- `SHA256SUMS` covers the archive, `RELEASE_MANIFEST.json` and `sbom.cdx.json`.
- The installer verifies the checksum, the archive layout, and the binary's
  reported version, and refuses corrupt, truncated, or mismatched artifacts.
- New release benchmark package under `benchmarks/releases/v0.2.0-beta.1/` with
  raw samples, medians, p95, bootstrap confidence intervals, environment details
  and retained negative results.
- No optimization research branch was merged. Phase Q, R and S were negative;
  newest-first candidate selection and strict hashing stay the defaults.

Product semantics are unchanged from v0.1.1: guarded whole-command reuse,
fail-closed classification, certificates that never assert full equivalence.

## Install

```bash
version=$(curl -fsSL https://raw.githubusercontent.com/Satwik-P28/tracejit/main/VERSION)
base="https://github.com/Satwik-P28/tracejit/releases/download/v${version}"
name="tracejit-v${version}-x86_64-unknown-linux-gnu.tar.gz"
curl -fsSLO "${base}/${name}" && curl -fsSLO "${base}/SHA256SUMS"
sha256sum -c --ignore-missing SHA256SUMS
tar -xzf "$name"
install -m 755 "tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit" ~/.local/bin/tracejit
tracejit doctor
```

## Verification

```bash
tracejit --version   # tracejit 0.2.0-beta.1
sha256sum -c --ignore-missing SHA256SUMS
python3 -c 'import json; m=json.load(open("RELEASE_MANIFEST.json")); print(m["release"]["commit"], m["build"]["binary_sha256"])'
```

Byte-for-byte reproducible builds are not claimed. Rebuild and compare the
recorded hashes with [docs/BENCHMARK_REPRODUCTION.md](docs/BENCHMARK_REPRODUCTION.md).

## Known limitations

Validate-to-restore TOCTOU remains. Multi-output restore is not crash-atomic
under hard kill; restore intent makes the next attempt retrace. Observation is
ptrace-level. Warm hits have a fixed cost that loses on short commands. Cache
eligibility under unmodified defaults is low. See
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) for the full list.

## License

Apache-2.0 OR MIT, at your option.

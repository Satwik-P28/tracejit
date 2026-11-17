# Packaged artifacts (v0.2.0-beta.1)

Built by `scripts/package-release.sh dist` from commit `0ed69c56` on the release
branch. The Rust sources are identical to the measured commit `cdb307b`; the
packaged binary SHA-256 (`5a1100c5fd92dd7f...`) is the binary those benchmarks
ran. Neither `dist/` nor these copies are published: no GitHub release, tag or
hosted asset exists for this candidate.

`SHA256SUMS` lists the archive, manifest and SBOM. Verify with:

```bash
sha256sum -c SHA256SUMS
```

# Changelog

## Unreleased (`development/v0.3`, Phase U)

Compatibility modelling and verification work on top of the published
`v0.2.0-beta.1`. No version bump, no release. Native reuse semantics are
unchanged; the additions only admit observations whose value is already
reproduced by existing guards.

- The null device is classified by device identity (character device 1:3,
  checked on the open descriptor) instead of being refused as an unhashable
  path, so `open("/dev/null")` reads and writes no longer block reuse.
- Create-only `epoll_create1` instances are process-internal; `epoll_ctl`,
  `epoll_wait`, reads from the descriptor and failed creation still refuse.
- `fcntl(F_SETFL)`/`ioctl(FIONBIO)` are admitted only when the sole changed
  bit is `O_NONBLOCK` on a regular file this process opened and before it has
  created a child. `O_APPEND`, pipe and inherited-descriptor rewrites refuse.
- Pure `prlimit64` queries for the four limits `RuntimeIdentity` already
  guards are no longer effects; installing a limit still is.
- `EBADF` on a negative descriptor and `ENOTTY` from `TCGETS` on an internal
  pipe are treated as the deterministic observations they are.
- New `benchmarks/realworld/census_v03.py`: a twenty-workload held-out corpus
  that imports the existing census harness. `docs/COMPATIBILITY_V03.md`
  records the measured blocker taxonomy, the accepted and rejected models, and
  the metadata-guard (`atime`) deopt it found.

## 0.2.0-beta.1

First independently packaged public beta. No optimization research branch was
merged: Phase Q, R and S all produced negative results, so newest-first
candidate selection and strict hashing remain the production defaults.

- Single-source version declaration in `VERSION`, with
  `scripts/check-version-consistency.sh` and CI enforcement.
- `scripts/package-release.sh` builds the archive with README, licenses,
  security/safety/architecture docs, install and benchmark guides, provenance
  manifest and CycloneDX SBOM; `SHA256SUMS` covers the archive, manifest and SBOM.
- `scripts/release_manifest.py` records commit, commit date, Rust toolchain,
  lockfile hash, target, and per-file hashes. Byte-for-byte reproducibility is
  not claimed.
- `scripts/install-release.sh` and `scripts/test-install-release.sh` are
  version-parameterized, verify the archive checksum, the archive layout, and
  the binary's reported version, and refuse corrupt or truncated archives.
- Release and public-install workflows derive the version instead of hardcoding
  it, and the public install check now verifies the current release.
- `benchmarks/releases/run_release.py` produces the committed release benchmark
  package: direct vs cold vs warm on CPU-heavy, short-command, compression, ETL
  session, 64 MiB restore, invalidation and concurrency scenarios, plus the
  real-world census and Make/Ninja comparison.
- New `docs/LIMITATIONS.md`, `docs/INSTALL.md` and
  `docs/BENCHMARK_REPRODUCTION.md`; README states the prototype status and the
  supported platform explicitly.

## Unreleased (final adversarial package on main@827b776)

Documentation and verification packaging for mandate §§1–18 (PRs #26–#30): live baseline/invariants; P0 process/TOCTOU/restore-intent; P1 census/e2e/admission/CEGAR/assurance/security/prior-art matrix; artifact evaluation and FINAL_ANSWER. Product semantics of #27–#28 remain as merged; no version bump. See `docs/final/FINAL_ANSWER.md`. Open `cargo audit` finding RUSTSEC-2026-0459 deferred.

## 0.1.1

- `tracejit explain` prints observed inputs, outputs, and guards without environment values.
- `tracejit doctor` names an unsupported OS and architecture, explains a ptrace denial, and separates `GUARDED` reuse from `PROVEN`.
- A file-backed `MAP_SHARED` mapping that is writable, or that `mprotect` makes writable, is `UNKNOWN`. `mremap` of a recorded file mapping is `UNKNOWN`. v0.1.0 ignored these syscalls.
- vDSO `clock_gettime`, `gettimeofday`, and `time` are redirected to real syscalls before the first userspace instruction. If that cannot be completed, the trace is `UNKNOWN` and is not reused.
- The 312.913 ms and 7.396 ms results stay attached to commits `e9684c1` and `63e3363`. They were not remeasured for 0.1.1.

## 0.1.0

Linux x86_64 release. The published measurements are the synthetic C transform at `e9684c1` (312.913 ms to 3.972 ms) and the short C ETL at `63e3363` (7.396 ms to 7.957 ms).

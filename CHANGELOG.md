# Changelog

## 0.3.0-alpha.1 (research prerelease, prepared, not published)

First research prerelease after `v0.2.0-beta.1`. It is labelled alpha because the
correctness contract now states an operating assumption it cannot enforce: no
external process may mutate an input during the reuse window
(`docs/FINAL_CORRECTNESS_CONTRACT.md` §11). It is a research artefact, not a
stable tool.

- **Enforcement is qualified on a capable host.** The complete lifecycle
  (discovery, candidate, policy installation, `PROVEN`, enforced reuse, mutation,
  re-execution) is measured and asserted end to end for read-only commands on a
  kernel with Landlock ABI 8. `benchmarks/phase_af/enforcement_lifecycle.py`,
  `benchmarks/results/phaseaf/enforcement_lifecycle.json`.
- **`PROVEN` is now visible on a hit.** The plain-mode report prints the record's
  class on the reuse path; previously a `PROVEN` record could be reused without
  the report saying the policy had been installed. The label means "policy
  installed", never equivalence, and the explanation is unchanged.
- **New negative regression.** `a_producer_that_replaces_an_existing_output_is_not_promoted`
  pins the fail-closed refusal that stops a timestamp-setting producer from being
  promoted to `PROVEN`.
- **Four new policy tests** in `tracejit-sandbox`: read/write separation, an
  undeclared neighbour of a declared path, a policy that cannot be installed, and
  a policy the mechanism cannot express.
- **Corrected headline arithmetic.** The `bzip2` applicability result is `5.22x`
  and `80.8%` less cumulative execution time against native, recomputed from the
  raw session rows; the earlier `5.6x` was arithmetic drift. Tables are generated
  from evidence by `benchmarks/phase_af/build_tables.py`, and
  `benchmarks/phase_af/test_tables.py` fails when a table disagrees with it.
- **Break-even is defined four ways** (equal cost, strictly positive saving,
  measured session, model estimate) and documents must say which one they use.
- **The verified-replay figure is a cost model, not a lower bound.** The estimate
  is a serial sum of measured components; overlapping implementations can beat it.
- **Documentation:** `docs/FINAL_CORRECTNESS_CONTRACT.md`, `docs/FINAL_RESEARCH_REPORT.md`,
  `docs/PAPER_REVIEW_AUDIT.md`, `docs/RELEASE_QUALIFICATION_V03.md`,
  `docs/REPRODUCTION_PACKAGE.md`, `paper/`. Phase AD/AE reports are marked
  superseded where they disagree with the contract.
- No product behaviour changed outside the report line and the new tests.

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

### Phase U1 (CI stabilisation)

- `fcntl` flag queries (`F_GETFL`, `F_GETFD`, `F_GETOWN`, `F_GETLEASE`,
  `F_GETPIPE_SZ`) are process-local only for descriptors this execution
  created. On an inherited descriptor the flags were chosen elsewhere and no
  guard records them, so the query now refuses instead of replaying the
  previous run's branch.
- Integration harness: `pipe2(O_CLOEXEC)` for test-created pipes, no
  descriptor is ever closed by the harness, `pre_exec` closures touch only
  descriptor 9, the two tests that install descriptor 9 run in their own
  re-executed process, and the timing lock recovers from poisoning. The
  inherited-descriptor enforcement itself is unchanged.
- Descriptors the test process inherited from its parent (for example the
  two GitHub Actions hands to the step) are dropped from every child. Phase
  U2 replaced the first process-wide marking with a per-spawn sweep; see
  below. Nothing is closed, so no component's descriptor becomes invalid; the
  assertion that used to fail the run on their presence is gone.
- `auto_admission_skips_short_commands_and_caches_expensive_ones` asserts
  the admission rule against the cost the measuring run reports, not
  against an assumption that the host runs `wc` inside the break-even
  window. `tracejit_core::HIT_COST_FLOOR_NS` is public for that test.
- New regression `an_inheritable_parent_descriptor_is_refused` proves a real
  parent-held descriptor is refused by number, cannot produce a HIT, falls
  back to a native run, and stops blocking reuse once closed.
- `docs/PHASE_U1_REPORT.md` records the root causes, the syscall-model audit,
  the warm-hit profile against `v0.2.0-beta.1`, and the `atime` analysis.

### Phase U2 (descriptor race elimination)

- The integration harness no longer modifies the descriptor table of the
  shared test process. Each spawn marks the descriptors it did not hand over
  `FD_CLOEXEC` in `pre_exec`, with one `close_range(3, …, CLOSE_RANGE_CLOEXEC)`
  call in the forked child. That child has one thread and a private copy of
  the table, so no unrelated test or thread can observe the change; nothing is
  closed; descriptors above 1023 are covered; and there is no
  `F_GETFD`/`F_SETFD` window. Older kernels fall back to a loop bounded by
  `RLIMIT_NOFILE`, race-free for the same reason.
- `invoke_inheriting` states explicitly when a spawn must keep the table, and
  is used only by the inherited-descriptor regressions.
- New regression
  `runner_inherited_descriptors_do_not_contaminate_runs_and_are_still_refused`
  re-executes the test binary with 142, 145 and 1500 open and inheritable,
  reproducing CI run `44235001207` across a real `exec`: ordinary runs reuse
  with no `EBADF`, handing the table over is refused by descriptor number
  (including above 1023) with native output and status, and closing restores
  reuse.
- Production code is untouched; `target/release/tracejit` is byte-identical
  before and after the change.

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

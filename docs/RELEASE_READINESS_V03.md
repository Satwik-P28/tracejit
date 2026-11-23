# v0.3 release readiness

Assessed at the end of Phase AA on `research/phase-aa` (commit `9abb10bb…`).
Evidence for every row is in `benchmarks/results/phaseaa/`.

## Verdict

**Not qualified for a v0.3 prerelease.** The *benchmark system* is qualified: it
measures what it says it measures, it fails closed on an incorrect hit, and its
results reproduce from a fresh checkout with one command. The *product* has two
hard blockers that are not benchmark problems — the version label would ship
post-beta code as `v0.2.0-beta.1`, and CI could not be verified at all — plus a
set of correctness risks that v0.3 would carry forward unchanged.

This is not a judgement that the work is bad. It is that "reproducible evidence"
and "shippable release" are different gates, and only the first is met.

## Gates that were run

| Gate | Command | Result |
| --- | --- | --- |
| Clean release build | `cargo build --workspace --release` | pass, 4 m 18 s, exit 0 |
| Formatting | `cargo fmt --all -- --check` | pass |
| Lints | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| Workspace tests | `cargo test --workspace` | **270 passed, 0 failed, 1 ignored** |
| Integration tests | `cargo test -p tracejit-cli --test linux_integration` (in the workspace run) | pass |
| State-machine model check | `scripts/modelcheck/check_state_machines.py` | pass, 0 violations, `restore_crash` 2 mixed-kill states recorded as a limitation |
| Packaging | `scripts/package-release.sh dist` | pass: archive, `RELEASE_MANIFEST.json`, `SHA256SUMS`, SBOM with 110 components |
| Installer | `scripts/test-install-release.sh dist` | pass, including the negative path that refuses an unpublished version |
| Version consistency | `scripts/check-version-consistency.sh` | pass (`0.2.0-beta.1`) |
| Real-world benchmark | `benchmarks/realworld_v2/run.sh` | pass, 177 rows, schema-validated, 0 incorrect hits |
| Adversarial | `adversarial.py --trials 12` | pass, W1 13/13, 0 incorrect hits, 0 stale race observations |
| Fresh checkout reproduction | clone + `AA_MODE=smoke run.sh` | pass — see [reproduction guide](BENCHMARK_REPRODUCTION.md#phase-aa-fresh-checkout-check) |
| CI on this head | GitHub Actions | **not run / not verifiable from the authoring environment** |

Not run, and why: hardware counters (`perf` absent), cold-page-cache runs (this VM
cannot establish one), and any comparison against ccache, sccache, ninja or
firebuild (no root, no prebuilt archives).

## Blockers

1. **The version label is wrong for anything shipped from `main`.** `VERSION`,
   `Cargo.toml` and the packaging script all say `0.2.0-beta.1`, but `main`
   contains a second audited contract (`compiler-runtime-v1`) and the 8.12
   allocator admission that the beta does not have. Running
   `scripts/package-release.sh` today produces
   `tracejit-v0.2.0-beta.1-x86_64-unknown-linux-gnu.tar.gz` containing post-beta
   code. Bump the version and re-run `check-version-consistency.sh` before any
   artifact is published. Nothing was published in Phase AA.
2. **CI status on the exact head is unknown.** No GitHub access from the
   authoring environment. The workflows are committed
   (`.github/workflows/ci.yml`, `.github/workflows/benchmark-v2.yml`) and the same
   commands pass locally, but "green on CI" is an unverified claim until somebody
   with repository access confirms it.
3. **The validate→restore TOCTOU window is unchanged.** Phase X documented it;
   Phase AA's race probe observed 0 stale results in 12 trials, which does not
   close it. A v0.3 release needs either a mitigation or a prominent, explicit
   statement in `SAFETY.md` that the window exists.
4. **Classification is not deterministic under load** for at least one workload:
   `gcc-cc-small-tu` under `compiler-runtime-v1` was `reused` in two full-suite
   runs and `refused` (`Nondeterministic`) in one, with an identical binary,
   identical corpus and 10/10 `Guarded` in a focused repeat. Users see a cache
   that sometimes declines for no reason they can see. Needs a deterministic test
   and a cause.
5. **Relocating `TRACEJIT_CACHE_DIR` invalidates every record**, because the
   environment — including that variable — is hashed into the identity. Copying or
   moving a cache, including into a container image, silently produces zero hits.
   Documented; not fixed.
6. **No competitive evidence for the one niche where TraceJIT wins.** The
   6.9–7.4× compiler result has no ccache or firebuild baseline. Claiming
   usefulness for compiler workloads without that comparison is not defensible in
   a release note.
7. **The product is slower than native for most real commands.** 8 of 13 timed
   workloads lose, some by 6–7×, and the 13–16 ms warm-hit floor excludes every
   cheap command. That is a documentation constraint (users must be told when *not*
   to use it), and `README.md` now carries the table, but a release note that
   omits it would mislead.

## Non-blocking, but should be stated in the release notes

- Landlock is unavailable on this image, so the enforced path and `proven` mode
  were not exercised here. That path needs a host that supports it before any
  "enforced" claim.
- `cargo audit` finding RUSTSEC-2026-0459 remains deferred (recorded in
  `CHANGELOG.md`); re-check at release time.
- The packaged archive is explicitly not byte-for-byte reproducible; the manifest
  records commit, toolchain, lockfile and artifact hashes so a rebuild can be
  compared by hand.
- Numeric results in this branch come from a 2-vCPU shared VM with no frequency
  control. They are reproducible in shape, not to the millisecond, elsewhere.

## What would clear the verdict

In order:

1. Bump `VERSION` to the intended `0.3.0-*` and re-run
   `check-version-consistency.sh`, packaging and the installer test.
2. Get CI green on the merged head of `research/phase-aa`, including the
   benchmark-v2 smoke job.
3. Resolve or clearly scope items 3–5 above in `SAFETY.md` and
   `docs/LIMITATIONS.md`, with the residual risk named rather than implied.
4. Add one real competitor baseline (ccache on the zlib translation units) or
   drop the competitive framing from the release notes.
5. Publish the "when not to use this" table alongside the wins.

Then a v0.3 prerelease can be cut honestly, with the claim set restricted to:
compute-bound repeated commands, and large translation units under the explicitly
declared `compiler-runtime-v1` contract.

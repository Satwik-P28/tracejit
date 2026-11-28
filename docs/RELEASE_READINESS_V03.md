<!-- Historical record. Superseded by docs/FINAL_CORRECTNESS_CONTRACT.md and
     docs/PHASE_AF_REPORT.md. Statements below about the absence of a Landlock-capable
     environment are host-specific and were true of the hosts named here; a later host in this
     project reports Landlock ABI 8 and the enforcement lifecycle was qualified there. -->

# v0.3 release readiness

Assessed at the end of Phase AA on `research/phase-aa` (commit `9abb10bb…`), and
re-audited in Phase AA1 at `1c87e02` (`docs/PHASE_AA1_AUDIT.md`). Evidence for
every row is in `benchmarks/results/phaseaa/` and, for the numbers AA1 corrected,
`benchmarks/results/phaseaa1/`.

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
| Real-world benchmark | `benchmarks/realworld_v2/run.sh` | pass: 177 declared cells, 162 attempted, 28 verified HITs, 20 timed rows, schema- and accounting-validated, 0 incorrect hits |
| Adversarial | `adversarial.py --trials 12` | pass, W1 13/13, 0 incorrect hits, 0 stale race observations. AA1 made the W1 audit re-runnable (it used a fixed `/tmp` root) and it now passes twice in a row |
| Fresh checkout reproduction | clean clone at `ae884c5`, empty `HOME`, fresh scratch and vendor, `AA_MODE=smoke run.sh` | pass: exit 0, schema OK, 42 declared cells, 9 reused, 0 incorrect hits, 13/13 counterexamples. This is the AA1 run; it also found the W1 fixed-`/tmp` defect above |
| Competitor baseline | `competitive_zlib.py` with ccache 4.10.2 | measured: ccache 4.54 ms vs TraceJIT 65.18 ms on the same zlib compile (108× vs 7.5×), all objects byte-identical |
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
4. **Classification is not deterministic under load.** AA1 quantified it: 94/100
   `Guarded` for `gcc-cc-small-tu`, 98/100 for `zlib-compile-deflate`, and
   `gcc-cc-heavy-tu` refused once during a loaded timing run despite 100/100 in a
   focused probe. The determinant is a `getrandom` in the gcc driver's startup,
   before `cc1`. The refusal is correct; the *rate* makes a 25-build session refuse
   roughly 40 % of the time at 2 %, so a user sees a cache that declines for no
   visible reason. This is a usability blocker, not a soundness one, and it is
   Phase AB priority 1.
5. **Relocating `TRACEJIT_CACHE_DIR` invalidates every record**, because the
   environment — including that variable — is hashed into the identity. Copying or
   moving a cache, including into a container image, silently produces zero hits.
   Documented; not fixed.
6. **The competitive baseline now exists, and it is unfavourable.** ccache 4.10.2
   hits in 4.54 ms where TraceJIT needs 65.18 ms on the same zlib compile (108× vs
   7.5×), verified byte-identical. A release note cannot present compiler speed as
   a reason to use TraceJIT. What remains defensible is output-integrity repair and
   coverage of commands a compiler cache cannot see, and neither is measured end to
   end yet.
7. **The product is slower than native for most real commands.** 9 of 13 timed
   workloads lose, the worst by 6.7× (`readelf-header`, 0.15×), and the 8–17 ms
   warm-hit floor excludes every cheap command. That is a documentation constraint
   (users must be told when *not* to use it), and `README.md` carries the table, but
   a release note that omits it would mislead.

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
4. ~~Add one real competitor baseline (ccache on the zlib translation units).~~
   Done in AA1; the result argues for dropping the compile-speed framing, not for
   keeping it.
5. Publish the "when not to use this" table alongside the wins.

Then a v0.3 prerelease can be cut honestly, with the claim set restricted to:
compute-bound repeated commands, and large translation units under the explicitly
declared `compiler-runtime-v1` contract.

## Phase AB re-assessment (`research/phase-ab`, from `fd6d004`)

Phase AB changed one product behaviour and produced evidence that changes the
*claim set*, not the gates.

| Gate | Phase AB result |
| --- | --- |
| Formatting, lints, workspace tests | pass |
| Linux integration tests (4 threads) | 85/85 (84 before; +1 adversarial entropy test) |
| `cargo audit` | pass, 110 crates, no advisory |
| Model check / fuzz seed 29 / fault injection / W1 oracle | PASS / PASS 0 incorrect / PASS / 13/13 |
| Frozen corpus smoke at this head | 42 declared cells, 40 attempted, 10 reused, 0 incorrect hits, 13/13 counterexamples |
| Whole-build experiment (32 TUs, 4 arms, 12 schedules) | no incorrect artifact in any arm that compiled |
| CI on this head | see the PR; still not verifiable from the authoring environment |

What improved: warm hits on commands with no workspace output got 1.9–2.5 ms
cheaper (paired, 95 % CI excludes 0), which puts `gzip -6` at parity with native
instead of a 0.77× loss. One intermittent-classification root cause is closed with
a measured rate (5.7 %, 1,000 trials) and a stated remedy (refusal retained).

What did not change: eligibility, admission, guards, identity, schema. The three
blockers from AA1 stand — the version label is still `0.2.0-beta.1` for post-beta
code, exact-head CI is unconfirmed from here, and the validate→restore TOCTOU
window is untouched.

New information a v0.3 note must carry:

* **Competitive position at build scale.** Warm 32-unit rebuild: ccache 0.19 s,
  TraceJIT 3.20 s, make 7.29 s. ccache is 17× faster than TraceJIT on the workload
  TraceJIT was designed for.
* **Restored outputs keep their recorded mtime**, so a timestamp-driven archive
  step can leave a stale member after a correct object restore
  (`OUTPUT_INTEGRITY_ECONOMICS.md` §3).
* **The integrity-repair framing should be dropped**: no cache repairs an artifact
  the build system does not rebuild, and ccache repairs the ones it is asked for
  as well.

The verdict is unchanged: **not qualified for a v0.3 prerelease**, and Phase AB
narrows the defensible claim to guarded, verified whole-command reuse for
repeated compute-bound commands, with the compiler case documented as a
controlled contract that loses to ccache.

## Phase AC review

The blocking benchmark failure is resolved and it was not a product defect: the
`tar-create` cold mismatch came from the harness preparing its two twins at
different wall-clock times, so `tar` serialised different member mtimes
(`docs/PHASE_AC_COLD_MISMATCH_AUDIT.md`). The harness now builds the traced twin
as a metadata-preserving clone and refuses to compare twins whose metadata
differs; 0/200 mismatches after the change, and the local mirror of the CI smoke
step passes with 0 cold mismatches and 0 incorrect hits.

Correctness work added: a deterministic prune-versus-restore matrix (5 new tests,
all fail-closed or verified), and an audited decision **not** to adopt
field-precise metadata guards, with a 9-mutation adversarial matrix showing the
conservative guard is load-bearing. Output restoration keeps timestamp-exact
semantics deliberately; the stale-archive consequence is now documented with a
tested workaround instead of being an unexplained benchmark finding.

What changed for a v0.3 note:

* **A measured non-compiler niche exists.** `bzip2 -9` on a 2 MiB artifact saves
  85 % of a 25-invocation session at break-even 1.5; `gzip -9` 65 %; `sed` on
  200k lines 51 %. `gzip -9 -n -c` reuses with no execution contract at all.
* **The hit floor is the limit, not eligibility.** Five of nine measured
  non-compiler configurations lose at every session length because a 15-50 ms hit
  exceeds a 2-5 ms command. Admission (`auto`) is the mitigation, not more caching.
* **Compatibility is still the blocker for release.** 28 of 177 frozen-corpus
  rows reuse; `xz`, `tar`, `sort`, `awk`, `perl` and every Python/Node workload
  refuse for structural reasons.

The release verdict is unchanged: **not qualified for a v0.3 prerelease**. The
defensible claim is narrower than "build accelerator": guarded, verified
whole-command reuse for repeated compute-bound commands (compression, large text
transforms, compiler steps under a declared contract), with a documented
mtime-driven build-system limitation and no general-compiler advantage over
ccache. Paper readiness: option **B**, a narrow paper on fail-closed whole-command
reuse, pending a measured comparison against Firebuild.

## Phase AD update (competitive validation, descriptors, admission)

New evidence, same verdict: **not qualified for v0.3**.

* **Competitive position measured.** Firebuild 0.8.2 (same host, pinned debs) cannot cache
  commands that preserve timestamps on their outputs — it re-executes `gzip -k`, `bzip2 -k` and
  `objcopy` every time — and it reuses clock-dependent commands by default (`date +%s` is
  replayed from cache). TraceJIT caches the former at 3–20× direct cost and refuses the latter.
  On cheap stdout filters with Firebuild's default config, TraceJIT is competitive (486 ms vs
  622 ms over 100 invocations) and loses when Firebuild is tuned to cache `sed` (1982 vs 2548 ms).
  See `docs/FIREBUILD_COMPARISON.md`.
* **Scale measured on authentic artifacts.** Linux 6.6.50 release archive, 1/10/100 MiB: hit
  costs 6.0/18.2/85.3 ms against native 46/565/5468 ms for compressible text; incompressible
  100 MiB is 362 ms against 2852 ms. Hash-only commands reverse below ~10 MiB. Integer
  break-even is 2 invocations for every compression workload, "never" for `sha256sum` at
  ≤10 MiB and 9 at 100 MiB. See `docs/ARTIFACT_BENCHMARKS.md`.
* **Admission audited, not changed.** A 24-step mixed session: `always` 1229/1240 ms, default
  `auto` 1285/1292 ms, `never` 1663/1745 ms, direct 1564/1639 ms, retrospective oracle
  653/631 ms. The default is 3–4 % behind `always` and protects one-shot work; no production
  change without a policy whose benefit is a lower bound. See `docs/ECONOMIC_ADMISSION.md`.
* **Descriptor compatibility did not improve.** The `F_GETFD`-on-inherited promotion is sound
  but changed 0/48 census cells; it was reverted. `tar` remains blocked by a realtime clock read
  and a socket control, `xz` by pipe status-flag toggles. See
  `docs/INHERITED_DESCRIPTOR_SEMANTICS.md`.
* **TOCTOU unchanged.** Second validation pass retained, window documented, no userspace-only
  close found, no cooperative lock added. `PROVEN` is untested because this host's LSMs are
  `capability,selinux` (no Landlock). See `docs/TOCTOU_MITIGATION_STUDY.md`.

Acceptance criteria for a v0.3 prerelease remain: (1) zero incorrect HITs across the frozen
corpus, adversarial suites, model checking and fault injection; (2) a second host and kernel
reproducing the gates; (3) a Landlock-capable environment for `PROVEN`; (4) the TOCTOU window
either closed by isolation or explicitly accepted in the release notes; (5) documented limits
for mutation-heavy, one-shot and sub-10 ms workloads; (6) `cargo audit` clean in CI.

## Phase AE review (competitive evidence audit, cross-environment, correctness boundary)

This section **supersedes the competitive and TOCTOU bullets of the Phase AD update above**.
Phase AE re-measured both, added Firebuild 0.8.6.2, and corrected claims the evidence does not
support. Nothing in the product changed.

**Withdrawn claims.**

* "Firebuild performs unvalidated reuse / the fingerprint is the lookup key" — **false**.
  Firebuild validates every recorded input at reuse time (`pio_matches_fs` →
  `HashCache::file_info_matches`, content hash included). The claim is removed from all
  documents.
* "TraceJIT wins the artifact-producing niche outright" — **false** with Firebuild 0.8.6.2,
  which caches `gzip -9 -n -k`. It is 1.67× faster than TraceJIT at that workload.
* "Every compression workload breaks even at the second invocation" — **false** for the 1 MiB
  incompressible gzip row, which needs 3 by the integer model and 10 by the measured cold
  session.
* "The warm path validates inputs twice / a second pass catches a mutation after validation" —
  **false**. One surviving pass; a mutation after it produces stale output (measured).

**Retained, measured position.**

* TraceJIT-only reuse: `bzip2 -9 -k` (Firebuild 0.8.2 and 0.8.6.2 both refuse:
  `Changing file timestamps is not supported`). n=25 cold session: native 2846.7 ms,
  TraceJIT 545.3 ms, Firebuild 3119.4 ms.
* TraceJIT's validated replay of large stdout is competitive: 6.56 ms vs 7.47 ms per invocation
  at 1.2 MiB; 79.8 ms for a 100 MiB text artifact in the phase profile.
* Contract differences: default Firebuild replays clock-dependent output (TraceJIT refuses);
  Firebuild's strict configuration refuses to cache those commands. Firebuild replays a
  corrupted cached blob; TraceJIT refuses the object and re-executes.
* Verified replay is within ~1.5× (compressible) and ~2.7× (incompressible) of a floor that
  already includes full input and output verification; no optimisation is promoted.

**Environment matrix.** Two userspaces on one kernel: Ubuntu 24.04/glibc 2.39 (guarded reuse
works) and Ubuntu 25.10/glibc 2.42 (correct execution, no reuse — the `allocator-entropy-v1`
contract is unavailable for an unaudited libc). No Landlock anywhere, so `--enforce` never
reuses and never labels a run `PROVEN`. A GitHub Actions workflow is prepared but its results
could not be read back and would not constitute independent reproduction.

**Gates run locally on the pushed tree**: fmt, clippy `-D warnings`, `cargo test --workspace`
(283 passed, 1 ignored), accounting regressions (17), state-machine model check, both restore
fault scenarios, benchmark harness self-tests, version consistency, fresh-checkout build + reuse
smoke, and `cargo audit --deny warnings` (0 vulnerabilities in 110 dependencies). Release
packaging and clean-install gates were not run here.

**Verdict: qualified as a research prerelease (0.3.0-alpha class), not as a stable beta.**
Blockers that require engineering or capability: (1) a Landlock-capable host to exercise
`PROVEN` end to end; (2) the residual validation-to-restore race, which must be disclosed as an
operating assumption; (3) documented unavailability of reuse on unaudited glibc; (4) a second
kernel and an independent operator; (5) the packaging/clean-install gate. The misleading
guarantees and invalid benchmark claims that would have blocked even a prerelease are corrected
by `docs/PHASE_AE_REPORT.md`, `docs/COMPETITIVE_EVIDENCE_AUDIT.md`,
`docs/FIREBUILD_CROSS_VERSION_RESULTS.md`, `docs/TOCTOU_CORRECTNESS_BOUNDARY.md`,
`docs/VALIDATED_REPLAY_PERFORMANCE.md` and `docs/PAPER_CLAIMS_LEDGER.md`.

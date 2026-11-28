# v0.3.0-alpha.1 release qualification

Proposed release: `0.3.0-alpha.1`, **research prerelease, prepared and qualified but not
published.** The published `v0.2.0-beta.1` tag and its evidence are untouched.

This file records what was actually executed, on what tree, with what result. Anything not
executed is listed as not executed. Nothing here is inferred from a previous phase.

| item | value |
| --- | --- |
| source commit the artifact was built from | `b81242d65e8a02bfe4459506a44b2eca566c5d89` (branch `research/phase-af`, base `68ba406`) |
| working tree at packaging time | **dirty** (`working_tree_dirty: true` in the manifest) — Phase AF changes were uncommitted |
| host | Ubuntu 24.04.5 LTS, kernel 7.0.0-38-generic, glibc 2.39-0ubuntu8.12, x86_64, 4 vCPU |
| toolchain | rustc 1.100.1 (20ddd0171 2026-11-25), cargo 1.100.1 |
| release profile | `--release`, workspace default |
| artifact | `tracejit-v0.3.0-alpha.1-x86_64-unknown-linux-gnu.tar.gz` |

Because the tree was dirty, the artifact's `commit` field names the last commit and the manifest
says `dirty: true`. **A published artifact must be rebuilt from a clean, tagged tree**; this
packaging run qualifies the pipeline, not the bytes.

## 1. Version sources

| source | value | check |
| --- | --- | --- |
| `VERSION` | `0.3.0-alpha.1` | authoritative |
| `Cargo.toml` `[workspace.package] version` | `0.3.0-alpha.1` | equal to `VERSION` |
| crate manifests | `version.workspace = true` | inherit |
| built binary `--version` | `tracejit 0.3.0-alpha.1` | matches |
| archive `VERSION` member | `0.3.0-alpha.1` | matches |
| `RELEASE_MANIFEST.json` `release.version` / `release.tag` | `0.3.0-alpha.1` / `v0.3.0-alpha.1` | matches |
| `scripts/check-version-consistency.sh` | PASS | see §5 |

`scripts/package-release.sh` takes the version from `VERSION`, so the packaging path and the CLI
cannot disagree.

## 2. Artifact contents and digests

```
eb24fdef8bc04f091b47a2fabac763e498a023bfae778157a74c8f32f98cae92  tracejit-v0.3.0-alpha.1-x86_64-unknown-linux-gnu.tar.gz
45e747c4e306684c3ff325229cb9de98b35165930e1b6ddc36049c3a4e85139e  tracejit (inside the archive)
72ad821d3d8d84a58728c1b2a2659403b3406bd0448b3a66d476af390d1e98ec  RELEASE_MANIFEST.json
6464cbc4c63799a2ddc81e838cb63e635d83a4550ef36233953073347de8573d  sbom.cdx.json
```

Archive members: `tracejit`, `VERSION`, `README.md`, `CHANGELOG.md`, `RELEASE_NOTES.md`,
`SAFETY.md`, `SECURITY.md`, `ARCHITECTURE.md`, `LICENSE-APACHE`, `LICENSE-MIT`,
`RELEASE_MANIFEST.json`, `sbom.cdx.json`, `docs/INSTALL.md`, `docs/LIMITATIONS.md`,
`docs/BENCHMARK_REPRODUCTION.md`.

* **SHA-256 generation**: `SHA256SUMS` covers the archive, the manifest and the SBOM; the three
  digests above are that file.
* **Manifest**: `scripts/release_manifest.py` records version, tag, commit, commit date, branch,
  dirty flag, toolchain (cargo, rustc, `rust-toolchain.toml` + digest), target, every member's
  digest and size, and the dependency list.
* **SBOM**: `scripts/release_sbom.py` emits CycloneDX with **110 components**.
* **Licenses**: both license files ship in the archive; the workspace declares
  `Apache-2.0 OR MIT`.
* **Reproducible binaries**: **not claimed.** The manifest exists so a second build can be
  compared by hand. An earlier Firebuild source build in this project produced different digests
  under a different compiler, which is the same caveat.

## 3. Installer and fresh-user path

`scripts/clean-install-verify.sh /tmp/dist` installs from the archive only (never the development
binary), into a temporary prefix and `HOME`:

```
RESULT install PASS
RESULT checksum PASS
RESULT version PASS (tracejit 0.3.0-alpha.1)
RESULT help PASS
RESULT doctor PASS
RESULT proven-capability PASS (landlock abi 8)
RESULT cache-init PASS
RESULT cold-execution PASS
RESULT warm-hit PASS
RESULT mutation-deopt PASS
RESULT nondeterministic-refusal PASS
RESULT concurrency PASS
RESULT uninstall-reinstall PASS
RESULT clean-install PASS
```

`scripts/test-install-release.sh /tmp/dist` exercises the failure paths:

* a tampered archive is rejected (`checksum mismatch; refusing to install`);
* a truncated archive is rejected (`gzip: unexpected end of file`, `tar: Unexpected EOF`);
* installing an unpublished version by version number is refused
  (`v0.3.0-alpha.1 is not published`);
* `installer test passed`.

The `proven-capability` check was fixed during this qualification. It previously grepped the
human-readable report for `landlock       yes`, a string `doctor` never prints, so it **skipped on
a host that can install the policy**. It now reads `doctor --json` and qualifies the capable path.

## 4. Unsupported-platform handling

`doctor` refuses non-Linux, non-x86_64 and missing `ptrace`, and the packaging script refuses to
build an archive off Linux x86_64. Not exercised here: no macOS/Windows/AArch64 host was available,
so the refusal text is covered by unit tests only, not by an execution on such a host.

## 5. Gates

All commands were run in this workspace on the qualified tree.

| gate | command | result |
| --- | --- | --- |
| formatting | `cargo fmt --all -- --check` | PASS (after `cargo fmt --all`; the first run failed on the new Rust code) |
| lints | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| workspace tests | `TRACEJIT_REQUIRE_PROVEN=1 cargo test --workspace` | PASS, 0 failed |
| Linux integration | `cargo test -p tracejit-cli --test linux_integration` | PASS, 86 tests |
| enforcement lifecycle | `python3 benchmarks/phase_af/enforcement_lifecycle.py --assert-capability` | PASS, 11/11 assertions |
| sandbox policy tests | `TRACEJIT_REQUIRE_PROVEN=1 cargo test -p tracejit-sandbox -- --nocapture` | PASS, 8 tests, none skipped |
| publication tables | `python3 benchmarks/phase_af/build_tables.py --check --emit paper/tables` | PASS, 8/8 tables, 0 problems |
| table integrity tests | `python3 benchmarks/phase_af/test_tables.py` | PASS, 10 tests |
| version consistency | `scripts/check-version-consistency.sh` | PASS (`0.3.0-alpha.1`) |
| packaging | `TRACEJIT_ALLOW_DIRTY=1 scripts/package-release.sh /tmp/dist` | PASS |
| clean install | `scripts/clean-install-verify.sh /tmp/dist` | PASS, all steps |
| installer failure paths | `scripts/test-install-release.sh /tmp/dist` | PASS |
| model check | `python3 scripts/modelcheck/check_state_machines.py` | PASS |
| restore fault injection, soft fail | `scripts/phase_k4_restore_fault.sh` | PASS — asserts the injected-failure reason, so it is proven to have reached `restore_outputs` |
| restore fault injection, hard kill | same script | **SKIP** — prints `RESULT … SKIP (pause hook did not fire)`; the dead-intent refusal is covered by `linux_integration::interrupted_restore_intent_refuses_hit`, which passes |

### Not executed, and therefore not claimed

| gate | reason |
| --- | --- |
| differential fuzzing | not run in this environment |
| `cargo audit` | `cargo-audit` is not installed here; the previous phase recorded a clean run on 110 dependencies, which is **not** re-claimed for this tree |
| Firebuild competitive re-measurement | no Firebuild on this host; Phase AE's numbers are cited as historical evidence with their own commit |
| TLA⁺ tool run | `tla2tools` is not installed; the Python state-machine checker ran instead |
| independent external reproduction | no third-party operator exists; not achievable from inside the project |
| GitHub Actions on the Phase AF head | only possible after a push; see §6 |

## 6. CI

The tree this phase started from, `b81242d`, has four successful workflows (CI push `45573894337`,
CI PR `45573903654`, benchmark v2 `45573903647`, environment `45573903708`).

The Phase AF head `7cdb0a6` was pushed to both `research/phase-af` and the PR branch
`research/phase-ad` (PR #45, still draft, `mergeable: true`):

| workflow | result on `7cdb0a6` |
| --- | --- |
| CI | **success** |
| Phase AE environment | **success** (guarded reuse plus the `PROVEN` classification on the runner) |
| Real-world benchmark v2 | **failure**, at `fetch_inputs.py --vendor`: the runner could not download the pinned `zlib-1.3.1.tar.gz` from `zlib.net` |
| benchmark `competitive` / `full` jobs | skipped by workflow design, so they are not a competitive qualification |

The benchmark failure is an input-fetch failure, not a code regression: the same command run in
this workspace fetches the archive and verifies the pinned SHA-256 (`9a93b2b7…`), and no file the
Phase AF commits touch is on that code path. It needs a workflow re-run, which requires repository
write permission that this environment does not have. Treat the real-world benchmark as **not
qualified on this head** until it is re-run.

## 7. Publication decision

Nothing was published, tagged, or uploaded. The release notes
(`docs/RELEASE_NOTES_V0.3.0-ALPHA.1.md`) and the archive are prepared for an explicit human
decision. Before publishing:

1. commit the Phase AF tree and rebuild the archive from a clean checkout (so `dirty` is `false`
   and `commit` names the released revision);
2. re-run §5 on that clean tree;
3. re-generate `SHA256SUMS`, `RELEASE_MANIFEST.json` and `sbom.cdx.json`;
4. publish the prerelease explicitly, and verify the post-publication install from the published
   URL rather than from `/tmp/dist`.

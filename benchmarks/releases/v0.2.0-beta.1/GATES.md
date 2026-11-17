# Release gate evidence: v0.2.0-beta.1

Commit: `cdb307be9160b93318603005373a0a9f69b84219`
Binary SHA-256: `5a1100c5fd92dd7f2593451932d1ba93a2bd1f83d8681bb18861a4bc246db990`
Host: Ubuntu 24.04.5, kernel 6.1.102, x86_64, 2 vCPU, ext4.

| Gate | Command | Result |
| --- | --- | --- |
| Formatting | `cargo fmt --all -- --check` | PASS |
| Clippy | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Unit + crate tests | `cargo test --workspace` | PASS, 217 tests, 0 failed |
| Linux integration | `cargo test -p tracejit-cli --test linux_integration -- --nocapture` | PASS, 62 tests, 2 SKIP |
| Release build | `cargo build --workspace --release` | PASS |
| Version consistency | `./scripts/check-version-consistency.sh` | PASS (0.2.0-beta.1) |
| Dependency audit | `cargo audit` | PASS, 110 locked crates, 0 advisories |
| Canonical demo | `./scripts/demo.sh` | PASS, HIT and DEOPT asserted |
| State machines | `python3 scripts/modelcheck/check_state_machines.py` | PASS, 0 violations |
| Restore fault injection | `./scripts/phase_k4_restore_fault.sh ./target/release/tracejit` | PASS, soft-fail retrace + hard-kill recovery |
| Independent oracle | `python3 benchmarks/oracle/independent_obs.py --seed {7,11,29}` | PASS, 0 incorrect hits, 0 regressions |
| Differential fuzz | `python3 benchmarks/differential/fuzz.py --seed {7,11}` | PASS |
| Certificate verification | certificate tests inside `cargo test --workspace` | PASS |
| Packaging | `./scripts/package-release.sh dist` | PASS |
| Installer (mismatch, truncated, missing) | `./scripts/test-install-release.sh dist` | PASS, all refusals asserted |
| Clean install | `./scripts/clean-install-verify.sh dist` | PASS, 12 steps |

## Environment limitations on this host

- Landlock is not enabled (`/sys/kernel/security/lsm` = `capability,selinux`).
  The integration tests `sandbox_declared_path_succeeds_and_other_effects_are_denied`
  and `enforced_execution_is_proven_reused_and_invalidated` therefore print
  `RESULT ... SKIP`, and `doctor` reports `landlock no`, so `PROVEN` cannot be
  exercised here. `GUARDED` reuse, which is the documented default path, is
  fully exercised. CI sets `TRACEJIT_REQUIRE_PROVEN=1` and fails if either test
  skips; that hosted run has not been observed for this commit.
- The host is a shared 2-vCPU VM, not a dedicated benchmark machine. Raw samples
  are published so the noise is visible.
- Artifact attestations require GitHub OIDC and were not produced locally.

## Clean-install steps exercised

install from archive, checksum verification, version, `--help`, `doctor`, cache
initialization, cold execution, warm HIT, input mutation and DEOPT,
nondeterministic command refusal, concurrent execution, uninstall and reinstall.
All used the installed binary, never `target/release/tracejit` except where the
demo recompiles its own workload.

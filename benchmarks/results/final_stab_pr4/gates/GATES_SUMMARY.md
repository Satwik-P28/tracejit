# PR4 mandatory gates

Tip: `7b9e7ca98143fc8e55e4927b21906aa361219b6a`

| Status | Command | Evidence |
| --- | --- | --- |
| passed | `cargo fmt --all -- --check` | `benchmarks/results/final_stab_pr4/gates/fmt.log` |
| passed | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | `benchmarks/results/final_stab_pr4/gates/clippy.log` |
| passed | `cargo test --workspace` | `benchmarks/results/final_stab_pr4/gates/cargo_test_workspace.log` |
| passed | `cargo test -p tracejit-cli --test linux_integration -- --nocapture` | `benchmarks/results/final_stab_pr4/gates/linux_integration.log` |
| passed | `cargo build --workspace --release` | `benchmarks/results/final_stab_pr4/gates/release_build.log` |
| passed | `cargo audit` | `benchmarks/results/final_stab_pr4/gates/cargo_audit.log` — clean on tip; no advisories reported |
| passed | `./scripts/demo.sh` | `benchmarks/results/final_stab_pr4/gates/demo.log` |
| passed | `python3 scripts/modelcheck/check_state_machines.py` | `benchmarks/results/final_stab_pr4/gates/modelcheck.log` |
| passed | `./scripts/phase_k4_restore_fault.sh ./target/release/tracejit` | `benchmarks/results/final_stab_pr4/gates/phase_k4_restore_fault.log` |
| passed | `cargo test -p tracejit-core --lib certificate` | `benchmarks/results/final_stab_pr4/gates/certificate_tests.log` |
| passed | `cargo test -p tracejit-effects --lib cegar` | `benchmarks/results/final_stab_pr4/gates/cegar_tests.log` |
| passed | `python3 benchmarks/oracle/independent_obs.py --seed 7` | `benchmarks/results/final_stab_pr4/gates/oracle_seed7.log` |
| passed | `python3 benchmarks/differential/fuzz.py --seed 7` | `benchmarks/results/final_stab_pr4/gates/differential/seed7.log` |
| passed | `python3 benchmarks/differential/fuzz.py --seed 11` | `benchmarks/results/final_stab_pr4/gates/differential/seed11.log` |
| passed | `python3 benchmarks/differential/fuzz.py --seed 29` | `benchmarks/results/final_stab_pr4/gates/differential/seed29.log` |
| passed | `python3 benchmarks/differential/phase_d.py --seed 7 --cases 40` | `benchmarks/results/final_stab_pr4/gates/phase_d_seed7.log` |
| passed | `python3 benchmarks/differential/phase_d.py --seed 11 --cases 40` | `benchmarks/results/final_stab_pr4/gates/phase_d_seed11.log` |
| passed | `./target/release/tracejit doctor` | `benchmarks/results/final_stab_pr4/gates/cli_doctor.log` |
| passed | `./target/release/tracejit --help` | `benchmarks/results/final_stab_pr4/gates/cli_help.log` |
| passed | `./target/release/tracejit refine --input docs/research/cegar/rename_exchange.json --json` | `benchmarks/results/final_stab_pr4/gates/refine_cli.log` |
| passed | `./scripts/test-install-release.sh DIST_DIR (v0.1.1 assets, extracted)` | `benchmarks/results/final_stab_pr4/gates/install_smoke.log` |
| not run | `dedicated metamorphic harness` | `benchmarks/results/final_stab_pr4/gates/metamorphic.log` — no metamorphic harness in repo; multi-seed differential/phase_d used instead |
| failed | `gh api .../branches/main/protection` | `benchmarks/results/final_stab_pr4/gates/branch_protection.log` — HTTP 403 Resource not accessible by integration |

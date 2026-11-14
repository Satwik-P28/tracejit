# Artifact evaluation

Tip under evaluation: `827b7763a73cddda4e3a99c9883fbae4b18d87d2` (origin/main after PR #30).  
Gate log: `benchmarks/results/final_release/gates-summary.json`  
Host (this run): Linux 6.12.113+ x86_64, 4 CPUs, ext4 (`benchmarks/results/final_release/provenance.txt`).

## One-command demos

```bash
git checkout 827b7763a73cddda4e3a99c9883fbae4b18d87d2
cargo build --workspace --release
./scripts/demo.sh
./target/release/tracejit doctor
```

Expected: demo ends with `RESULT mutation DEOPT`; doctor reports `supported yes`, `proven yes` when seccomp+Landlock ABI≥3 are available.

## Mandatory gates (§17)

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
python3 scripts/modelcheck/check_state_machines.py
./scripts/phase_k4_restore_fault.sh ./target/release/tracejit
python3 benchmarks/differential/fuzz.py --seed 29 --output /tmp/diff29
```

This host’s recorded RESULT: all PASS — see `benchmarks/results/final_release/gates-assurance.log` and `gates-summary.json`.

## Pinned raw evidence (do not invent)

| Claim class | Artifact | Measured tip |
| --- | --- | --- |
| E2E four objectives + counts | `benchmarks/results/final_p1/e2e.{json,md}` | `026e660` |
| Compatibility census ≥25 | `benchmarks/results/final_p1/census/` | `026e660` |
| Admission regret | `benchmarks/results/final_p1/admission-eval.txt` | `026e660` |
| CEGAR refine / audit / modelcheck | `benchmarks/results/final_p1_assurance/` | `bb4302f` lineage / `1d78029` |
| Release gates | `benchmarks/results/final_release/` | `827b776` |
| Competitive Make/Ninja | `benchmarks/results/phase_k8/` | `364331b` |

## Environment provisioning

- Linux x86_64 with ptrace permission.
- Rust toolchain matching `rust-version` in workspace `Cargo.toml`.
- Optional: Landlock ABI 3+ and seccomp for `PROVEN` (doctor reports availability).
- Optional tools for census (cc, gzip, …) — missing tools are recorded, not scored as refusals.

## Claim linking

Every ledger row in `docs/research/CLAIMS_LEDGER.md` must point at a test, audit, or raw JSON path. Status labels: implemented+verified / incomplete / experimental / rejected / deferred / blocked.

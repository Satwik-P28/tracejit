# TRA-28 / mandate §§11–14 — verified package

Base: `origin/main` `bb4302fccaf780d53287dde557f984adc2615870`  
Branch: `cursor/final-adversarial-p1-assurance-6ed7`

## Deliverables

| § | Doc | Raw / code |
| ---: | --- | --- |
| 11 | `P1_CEGAR.md` | `benchmarks/results/final_p1_assurance/refine-*.json`; `cegar.rs` |
| 12 | `P1_ASSURANCE.md` | `modelcheck.txt`; extended `scripts/modelcheck/check_state_machines.py`; differential seed 28 |
| 13 | `P1_SECURITY.md` | `cargo-audit.txt`; certificate tests |
| 14 | `PRIOR_ART_IMPLEMENTATION_MATRIX.md` | commit/file/license rows; no incompatible code import |

## Headline results

- CEGAR: 6 unit tests pass; 3 fixtures refine with **no auto-deploy** (`Blocked…` / `VerifiedOfflineNotDeployed`)
- Modelcheck: PASS including new `restore_intent` IntentRefuseHit correlation
- Differential fuzz seed 28: **120 ok, 0 incorrect hits**
- `cargo audit`: **1 vulnerability** (`libsqlite3-sys` RUSTSEC-2026-0459) + rustix warning — **deferred** bump

## Deferred

- rusqlite / libsqlite3-sys upgrade
- Loom / Miri / cargo-fuzz introduction
- Selective tracing; typed DAG implementation
- Any novelty claim beyond engineering attribution

## Reproduce

```bash
cargo test -p tracejit-effects --lib cegar
cargo test -p tracejit-core --lib certificate
cargo build -p tracejit-cli --release
./target/release/tracejit refine --input docs/research/cegar/rename_exchange.json --json
python3 scripts/modelcheck/check_state_machines.py
python3 benchmarks/differential/fuzz.py --seed 28 --output /tmp/diff28
cargo audit
```

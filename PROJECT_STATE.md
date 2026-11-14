# Project state

## Thesis

Infer observable dependencies of an unmodified Linux process and reuse computation only when safety is enforced. Fail closed. Correctness beats performance.

## Safety invariants

- Reuse only `PROVEN` and `GUARDED`. `UNKNOWN`, `NONDETERMINISTIC`, and `EMPIRICALLY_STABLE` never reuse in V1.
- `PROVEN` requires seccomp plus Landlock ABI 3+ actually installed.
- Every guard must pass before cached stdout, stderr, exit status, or files are exposed.
- Writable file-backed `MAP_SHARED` and anonymous `MAP_SHARED` are `UNKNOWN`. vDSO time is redirected or `UNKNOWN`.
- Path guards replay the pathname the process passed (no lexical `..` collapse). Uncertainty fails closed.

## Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`  
Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards.

## Current main

- Tip: `827b776` — final adversarial PRs #26–#30 (baseline → P0 → P1 → assurance).
- Release packaging: `docs/final/FINAL_ANSWER.md`, `ARTIFACT_EVALUATION.md`, `EXECUTIVE_SUMMARY.md`; gates `benchmarks/results/final_release/`.
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Final adversarial map

| PR | Scope |
| ---: | --- |
| #26 | Live baseline + INVARIANTS |
| #27 | P0 process refuses + TOCTOU recheck |
| #28 | P0 restore-intent durability |
| #29 | P1 tracing/census/e2e/admission |
| #30 | P1 CEGAR/assurance/security/prior-art |

## Known limitations

- Multi-output restore: single-path rename atomic; soft rollback verified; hard-kill not crash-atomic / not inode-preserving. Restore-intent refuses next HIT.
- Validate→restore TOCTOU residual after recheck remains.
- Short-command floor / short-ETL session losses (final_p1 e2e).
- Census eligibility 1/32 under native defaults; randomness/clock dominate.
- Selective tracing, typed DAG validator deferred; bandit admission rejected.
- `cargo audit` RUSTSEC-2026-0459 deferred; not claimed clean.
- Controlled-runtime / epoll research stay off main.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
python3 scripts/modelcheck/check_state_machines.py
./scripts/phase_k4_restore_fault.sh ./target/release/tracejit
```

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

- Tip: `325f8a8` — Phase C execution semantics (PR #12) on Phase B (`a32c191`).
- Prior: `29718cf` Phase 3H/3I descriptor P0 (PR #8).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Phase B / C (on main)

- Phase B (#11): post-`Cache::open` inherited-fd re-scan; cache-path CLOEXEC regression.
- Phase C (#12): anonymous `MAP_SHARED` / hardlink create `UNKNOWN`; deleted `/proc/fd` paths; hit-path typestate; `EXECUTION_EQUIVALENCE.md`.

## Phase D (branch `cursor/phase-d-verification-3119`)

- Differential harness `benchmarks/differential/phase_d.py`: native vs discover vs reuse; full observables; seeds 7/11/17.
- Adversarial + concurrency + recovery integration tests in `phase_d_verification`.
- `proptest` property tests: hash parsing, effect eligibility, artifact fail-closed, candidate decode.
- No durable multi-file restore journal claimed; mixed-workspace detectability covered.
- Store report: `docs/phase-d-verification.md`.

## Reconciliation snapshot (2026-11-14)

Keep on main: #4, #5, #8, #11. Reject merge of #6/#7/#9/#10. Store: `docs/reconciliation-report.md`, `docs/defect-register.md`.

## Benchmarks (do not invent)

- Committed short-command loss: `benchmarks/results/latest.md` at `63e33638709aacfaed896ab587435e64c0ecea62`.
- Known-good transform/sweep: `e9684c1c01a7bbbab4cae50e2389105596d613f1`.
- Native census remains refuse-heavy; do not quote research Python numbers as native equivalence.

## Known limitations

- Multi-output restore is pathname-visible under hard kill (not crash-atomic / not inode-preserving).
- seccomp+Landlock ≠ full execution equivalence (validate→restore TOCTOU remains).
- Stdin OFD aliases use device/inode/position when `kcmp` is unavailable (conservative).
- Bind-mount `/dev/null` substitution may be environment-blocked (`unshare -m` EPERM).

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
```

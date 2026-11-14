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

- Tip: `a32c191` — Phase B post-`Cache::open` inherited-fd re-scan (PR #11).
- Prior: `29718cf` Phase 3H/3I descriptor P0 (PR #8).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Phase B (landed on main via #11)

- Post-`Cache::open` inherited-descriptor re-scan; cache-path CLOEXEC regression.
- Removed unused workspace dependency `tracing`.
- Concise `PROJECT_STATE.md` reconciliation.

## Phase C (branch `cursor/phase-c-execution-semantics-1daa`)

- Formal contract: `docs/research/EXECUTION_EQUIVALENCE.md` (Exec/Trace/Reuse, Obs(E), class eligibility, assumptions).
- Anonymous `MAP_SHARED` refused; `link`/`linkat` explicit `UNKNOWN`; deleted `/proc/fd` pathnames not live paths.
- Hit-path typestate: guards → verified streams → expose only after restore.
- Regressions: `mmap_anon_shared`, `hardlink_create`, `negative_lookup`, hardlink path replacement.
- ADRs: `docs/research/ARCHITECTURE_DECISIONS.md` (ADR-C-001..003).
- Does **not** duplicate Phase B re-scan; rebased onto `a32c191`.

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

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

- Tip: `aa3a186` — Phase K6 certificate StrictCas (PR #23) on K5 (`f148228`).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Phases C–G (merged)

- **C** semantics: anon `MAP_SHARED`/`link` UNKNOWN; hit-path expose order; EXECUTION_EQUIVALENCE.md (#12).
- **D** verification: differential seeds 7/11/17, adversarial, proptest, concurrency (#13).
- **E** research: certificates, CEGAR workflow, admission-eval; bandit default rejected (#14).
- **F** performance: stream-hash CAS staging, single-fd guards, candidate LIMIT; large-file win; short ETL still loss (#15).
- **G** evaluation: competitive suite + sessions A/B; make incorrect on mtime/corrupt; ninja/ccache/sccache skipped (#16).

## Phases H–J (merged)

- Part XVIII technical report, README, claims ledger, FOCUS materials (#17).

## Phase K (in flight)

- Baseline: `docs/audits/PHASE_K_INDEPENDENT_BASELINE.md`.
- K1 (merged #18): `renameat2(RENAME_EXCHANGE)` false HIT fixed; related Obs refuses.
- K2 (merged #19): CLI-only Obs oracle — `benchmarks/oracle/independent_obs.py`.
- K3 (merged #20): hit-path + restore-crash modelcheck — `scripts/modelcheck/check_state_machines.py`.
- K4 (merged #21): restore fault injection — `scripts/phase_k4_restore_fault.sh`; soft rollback+retrace; hard-kill recovery (no journal).
- K5 (merged #22): input-driven CEGAR engine — `tracejit refine` (never auto-deploys).
- K6 (merged #23): certificate StrictCas — `verify_certificate_strict` / `--strict`.
- K7 (in flight): measured perf — staging `sync_data` + `prepare_cached`; see `benchmarks/results/phase_k7/`.

## Known limitations

- Multi-output restore pathname-visible under hard kill (not crash-atomic / not inode-preserving).
- Validate→restore TOCTOU remains; certificates are not full proofs.
- Short-command floor; large restore+hash can lose to direct copy.
- Controlled-runtime and epoll/retrieval research stay off main.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
```

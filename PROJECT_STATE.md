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

- Tip: `3779ca0` — merge of docs/gates PR [#36](https://github.com/Satwik-P28/tracejit/pull/36); product `crates/` unchanged since `ed3bd39`. Main CI: [43682852108](https://github.com/Satwik-P28/tracejit/actions/runs/43682852108) success.
- PR3 evidence: `benchmarks/results/final_stab_pr3/` (skip-rate negative result; phase breakdown; mandate §4).
- PR4 gates + release report: `benchmarks/results/final_stab_pr4/`, `docs/final/RELEASE_REPORT.md`.
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Beta release candidate: `v0.2.0-beta.1` on branch `release/v0.2.0-beta.1`,
  version from `VERSION`, packaged by `scripts/package-release.sh` with manifest
  + SBOM. Benchmarks and gates: `benchmarks/releases/v0.2.0-beta.1/`
  (`RESULTS.md`, `GATES.md`). Product semantics unchanged from v0.1.1.
- Not published: `gh` is unauthenticated in this workspace, so no tag, GitHub
  release or CI run exists for the candidate.
- Landlock is unavailable on the local host, so `PROVEN`/sandbox tests SKIP here;
  CI requires them and has not been observed.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).
- Branch protection: API **403** from this agent (cannot enable).

## Final adversarial + stabilization map

| PR | Scope |
| ---: | --- |
| #26–#32 | Adversarial baseline through merge-SHA packaging |
| #33 | CI fd9/starttime restore |
| #34 | Dependency audit (rusqlite/tempfile) |
| #35 | Warm-HIT profile; destination-match skip **withdrawn** |
| (PR4) | Docs, §3 gates, RELEASE_REPORT |

## Known limitations

- Multi-output restore: single-path rename atomic; soft rollback verified; hard-kill not crash-atomic / not inode-preserving. Restore-intent refuses next HIT.
- Validate→restore TOCTOU residual after recheck remains.
- Short-command floor / short-ETL session losses (mandate §4 / final_p1 e2e).
- Census eligibility 1/32 under native defaults; randomness/clock dominate.
- Destination-match restore skip withdrawn: 0% skip when outputs are consumed (`skip_rate_study.json`).
- Selective tracing, typed DAG validator deferred; bandit admission rejected.
- Controlled-runtime / epoll research stay off main.

## Validation

```bash
./scripts/check-version-consistency.sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
cargo audit
./scripts/demo.sh
python3 scripts/modelcheck/check_state_machines.py
./scripts/phase_k4_restore_fault.sh ./target/release/tracejit
```

Gate evidence: `benchmarks/results/final_stab_pr4/gates/GATES_SUMMARY.md`.

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

- Tip: `84b07c1` — Phase F performance (PR #15) on Phase E (`7801748`).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Phase F (merged)

- Stream-hash CAS staging, single-fd metadata+hash pairs, candidate `LIMIT`, precomputed runtime-identity JSON.
- Large-file warm hit improved on this host; short ETL remains a net loss.
- Raw: `benchmarks/results/phase_f/`.

## Phase G (branch `cursor/phase-g-evaluation-0f6f`)

- Competitive suite + held-out sessions A/B via `benchmarks/repos/phase_g_evaluation.py`.
- Wins: CPU transform (~11×), bzip2 compression, A/B/A reuse, multi-output restore, correct mtime/corrupt recovery vs make.
- Losses retained: short ETL overhead, large restore+hash vs direct, TraceJIT identical-rerun slower than make (and deopts on bzip2 output presence).
- Skips: ninja/ccache/sccache (not installed). Controlled-runtime not claimed.
- Ablations: candidate LIMIT cheap; lazy decode kept; Fast vs Strict ~1 ms guard; auto admission skips short ETL but caches transform; Phase F staging still helps large CAS vs Phase E tip.
- Store: `docs/phase-g-evaluation.md`. Raw: `benchmarks/results/phase_g/`.

## Known limitations

- Multi-output restore is pathname-visible under hard kill (not crash-atomic / not inode-preserving).
- seccomp+Landlock ≠ full execution equivalence (validate→restore TOCTOU remains).
- Certificate verification re-samples the same mutable filesystem as the hit path.
- Stdin OFD aliases use device/inode/position when `kcmp` is unavailable (conservative).
- Short-command floor remains; process_startup phase timer is coarse on this host.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
```

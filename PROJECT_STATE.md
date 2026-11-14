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

- Tip: `7801748` — Phase E research (PR #14) on Phase D (`48e9596`).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Phase F (branch `cursor/phase-f-performance-5cf6`)

- Profiled warm hit path with `TRACEJIT_PHASE_TIMING` (no `perf`/CPU PMU on this host).
- Ranked engine costs: CAS restore (large outputs), guard validation, SQLite query/decode.
- Shipped: stream-hash CAS staging, single-fd metadata+hash pairs, candidate `LIMIT`, precomputed runtime-identity bytes.
- Rejected: drop staging fsync, skip guard re-hash, sync=NORMAL, metadata hash cache, unchanged-output shortcut.
- Measured large_file warm hit 14.591 → 9.748 ms; cas_restore 9.980 → 5.947 ms. Short ETL still a net loss.
- Store: `docs/phase-f-performance.md`. Raw: `benchmarks/results/phase_f/`.

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

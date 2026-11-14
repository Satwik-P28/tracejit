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

- Tip: `48e9596` — Phase D verification (PR #13) on Phase C (`325f8a8`).
- Releases: `v0.1.0` (`cf0ddb2`), `v0.1.1` (`31c36d1`). Do not move tags.
- Research PRs #6/#7/#9/#10 stay isolated (not for main).

## Phase E (branch `cursor/phase-e-research-95c5`)

- Reuse certificates + independent structural verifier (`CheckedByVerifier` max).
- CEGAR-shaped refinement workflow + syscall registry; `getrusage` refinement rejected.
- Offline cost-sensitive admission comparison; production `auto` unchanged.
- Thin TLA+ hit-path model (not a full-system proof).
- Does not duplicate Phase D harnesses. Store: `docs/phase-e-research.md`.

## Known limitations

- Multi-output restore is pathname-visible under hard kill (not crash-atomic / not inode-preserving).
- seccomp+Landlock ≠ full execution equivalence (validate→restore TOCTOU remains).
- Certificate verification re-samples the same mutable filesystem as the hit path.
- Stdin OFD aliases use device/inode/position when `kcmp` is unavailable (conservative).

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
```

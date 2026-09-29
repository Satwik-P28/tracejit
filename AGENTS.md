# Agent guide

Read this file, then `PROJECT_STATE.md`, then `git log -5` and `git status`. Open only the files needed for the current task.

## Thesis

TraceJIT infers observable dependencies of an unmodified Linux process and reuses computation only when safety is enforced. Fail closed. Correctness beats performance. Never invent benchmark numbers. Never weaken safety to improve a benchmark.

## Safety

Reuse only `PROVEN` and `GUARDED`. `PROVEN` requires seccomp and Landlock actually installed. `UNKNOWN`, `NONDETERMINISTIC`, and `EMPIRICALLY_STABLE` never reuse in V1. Every guard must pass before cached stdout, stderr, exit status, or files are exposed.

Do not ignore `getrandom`, clocks, process identity, or mutable system information. Workload environment such as `PYTHONHASHSEED` may be set explicitly. That is not a classifier exception.

## Architecture

Keep the crate boundaries: `tracejit-effects`, `tracejit-guards`, `tracejit-cache`, `tracejit-trace`, `tracejit-sandbox`, `tracejit-core`, `tracejit-cli`. V1 is Linux x86_64, ptrace, BLAKE3, SQLite, whole-command reuse, strict hashing, synchronous guards.

## Workflow

- Focused commits. Do not force-push. Do not leave `main` broken.
- Do not publish releases, crates, or posts without explicit user approval.
- Do not regenerate `SPEC.md`, `ARCHITECTURE.md`, or `SAFETY.md` unless a change makes them false.
- Update `PROJECT_STATE.md` after meaningful work. Keep it under about 150 lines.
- Validate before pushing:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
```

The integration test runs only on Linux x86_64. Benchmarks run on native Linux x86_64 via `./scripts/benchmark.sh`. Commit `benchmarks/results/latest.json` and `latest.md` only when that harness produced them.

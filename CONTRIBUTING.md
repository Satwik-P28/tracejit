# Contributing

TraceJIT accepts changes that preserve conservative classification and auditability.

Before submitting:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Linux tracing changes must also run:

```bash
cargo test -p tracejit-cli --test linux_integration -- --nocapture
```

Development setup is Rust stable, as pinned by `rust-toolchain.toml` when that file is present, plus a C compiler on Linux for the fixtures and the demo. `./scripts/install-dev.sh` installs the CLI from this checkout. `tracejit doctor` is the first command to run. On macOS it is expected to fail.

Read [ARCHITECTURE.md](ARCHITECTURE.md) and [SAFETY.md](SAFETY.md) before changing classification, guards, or the sandbox. [docs/ADVERSARIAL.md](docs/ADVERSARIAL.md) describes the fixtures. [SECURITY.md](SECURITY.md) says where a suspected unsafe reuse should go. [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) is the discussion policy.

## Break TraceJIT

This is the main contribution. Use the Break TraceJIT issue template. A report needs a reproduction, the expected behavior, the actual behavior, the environment, the TraceJIT commit, and a minimal testcase.

Accepted safety bugs become named fixtures in `tests/fixtures/cases.json`. Other useful work, one change at a time:

- syscall and effect coverage, each with an adversarial test
- the shell and `cc` refusals, only with a fail-closed model
- guard cost, with a measured before and after on a hot path
- a workload that shows a loss as well as a win
- documentation that makes a claim match the code

Suggested labels, once the maintainer creates them: `good first issue`, `help wanted`, `break-tracejit`, `compatibility`, `performance`, `syscall-coverage`, `safety`, `docs`, `benchmark`.

A valid report is handled in this order:

1. reproduce the behavior
2. fix the classifier, tracer, guard, cache, or sandbox boundary
3. add a permanent fixture to tests/fixtures/cases.json and the fixture driver
4. credit the contributor in fixture metadata or the changelog

Do not weaken an expected classification merely to make the table green.

## Design constraints

Keep the seven existing crate boundaries unless a concrete dependency cycle requires another. Expected runtime failures return typed errors. Unavoidable unsafe code belongs next to raw syscall interfaces with its invariant documented.

No benchmark number belongs in documentation unless `scripts/benchmark.sh` or `benchmarks/harness/break_even.py` generated it for the stated commit and environment.

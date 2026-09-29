# Contributing

TraceJIT accepts changes that preserve conservative classification and auditability.

Before submitting:

~~~bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
~~~

Linux tracing changes must also run the generated adversarial table:

~~~bash
cargo test -p tracejit-cli --test linux_integration -- --nocapture
~~~

## Break TraceJIT

This is the main contribution. Use the Break TraceJIT issue template. A report needs a reproduction, the expected behavior, the actual behavior, the environment, the TraceJIT commit, and a minimal testcase.

Accepted safety bugs become named fixtures in `tests/fixtures/cases.json`. Other useful work, one change at a time:

- workload compatibility: shell, compilers, Python, Node, Make, pytest, and other build tools
- syscall and effect coverage, each with an adversarial test
- performance, with a measured before and after on a hot path

Issue labels: `good first issue`, `break-tracejit`, `compatibility`, `performance`, `syscall-coverage`, `safety`, `docs`, `benchmark`.

A valid report is handled in this order:

1. reproduce the behavior
2. fix the classifier, tracer, guard, cache, or sandbox boundary
3. add a permanent fixture to tests/fixtures/cases.json and the fixture driver
4. credit the contributor in fixture metadata or the changelog

Do not weaken an expected classification merely to make the table green.

## Design constraints

Keep the seven existing crate boundaries unless a concrete dependency cycle
requires another. Expected runtime failures return typed errors. Unavoidable unsafe
code belongs next to raw syscall interfaces with its invariant documented.

No benchmark number belongs in documentation unless scripts/benchmark.sh generated
it for the stated commit and environment.


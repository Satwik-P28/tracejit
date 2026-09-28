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

Use the Break TraceJIT issue template for a safety discrepancy. Include:

- a minimal program
- the expected effect
- actual TraceJIT behavior
- kernel, architecture, filesystem, and TraceJIT commit

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


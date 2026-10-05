## What changed

## Why

## Safety

- [ ] `UNKNOWN` and `NONDETERMINISTIC` still do not reuse
- [ ] A new syscall or effect has a fixture in `tests/fixtures/cases.json`, or this change does not affect classification
- [ ] No benchmark number was added unless `./scripts/benchmark.sh` or `benchmarks/harness/break_even.py` wrote it for the stated commit

## Tests

- [ ] `cargo fmt --all -- --check`
- [ ] `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --workspace`
- [ ] Linux x86_64: `cargo test -p tracejit-cli --test linux_integration -- --nocapture`

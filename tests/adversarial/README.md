# Adversarial suite

The executable fixture driver and generated expectation manifest live in
`../fixtures`. The runnable Linux test is
`crates/tracejit-cli/tests/linux_integration.rs` because Cargo exposes the built
`tracejit` binary to that package's integration tests.

Run it with:

~~~bash
cargo test -p tracejit-cli --test linux_integration -- --nocapture
~~~


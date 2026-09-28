# Integration tests

Linux end-to-end tests live beside the CLI package at
`crates/tracejit-cli/tests/linux_integration.rs`. They cover subprocess tracing,
descendants, deoptimization, hits, output restoration, stdout and stderr replay,
environment misses, nondeterministic and unknown-effect refusal, plus conditional
sandbox checks.

Keeping the executable test beside `tracejit-cli` allows Cargo to provide the
exact built binary path without installing the program globally.


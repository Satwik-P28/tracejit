# Project state

## Thesis

Automatically infer enough observable dependencies of an unmodified Linux process to reuse computation safely, and enforce that safety.

## Safety invariants

- `UNKNOWN` and `NONDETERMINISTIC` never reuse.
- `EMPIRICALLY_STABLE` does not reuse in V1.
- `PROVEN` requires seccomp plus Landlock ABI 3+.
- Guards finish before cached output is exposed.
- Uncertainty fails closed.

## Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`

Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards. Deoptimize and retrace after invalidation.

## Validated capabilities

- CI on `main` formats, clippy, and tests the workspace.
- Adversarial fixture table classifies file, metadata, symlink, environment, clock, randomness, procfs, network, and ioctl cases.
- Guarded hit, restore, replay, and deopt are covered by `linux_integration`.
- `tracejit doctor` reports OS, arch, ptrace, seccomp, Landlock, PROVEN readiness, and cache path.
- Refusals name the observed syscall, for example `process read randomness via getrandom`.

## Benchmark status

Harness result for `63e33638709aacfaed896ab587435e64c0ecea62` is in `benchmarks/results/latest.json`. Ubuntu 24.04.5, kernel `6.17.0-1022-azure`, 5 warmups, 30 runs. C ETL medians: baseline 7.396 ms, traced cold 21.024 ms (184% overhead), guard check 1.113 ms, cached end-to-end 7.957 ms (0.93x, 0.561 ms slower). Equivalence and deopt passed. Python ETL stayed `NONDETERMINISTIC` because of `getrandom` and `gettid`.

## Blockers

- Guarded reuse loses on this short workload. The next performance question is TraceJIT startup plus guard cost, measured separately from tracer overhead.
- CPython cannot be reused while `gettid` and `getrandom` are observed. That refusal is intentional.
- No GitHub Release binaries. Installation is `cargo install --path crates/tracejit-cli`.
- GitHub detects the license as Apache-2.0. `LICENSE-MIT` is present and `Cargo.toml` says `Apache-2.0 OR MIT`.

## Next tasks

1. Ask before cutting a v0.1.0 release or publishing binaries.
2. Profile startup and guard cost on the measured C workload before changing hot paths.
3. Record a compatibility matrix for pytest, shell, Make, a small Rust build, and Node. Expect Python refusals until thread-id and RNG startup are modeled without weakening safety.
4. Capture a real `tracejit run` transcript on Linux before putting terminal output in the README.
5. Keep `main` green.

## Known-good commit

`63e33638709aacfaed896ab587435e64c0ecea62` passed CI and the native benchmark.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
./scripts/benchmark.sh --runs 30 --warmups 5
```

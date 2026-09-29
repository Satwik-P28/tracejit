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

No published numbers yet. The last native run on `93f92e2` classified the Python ETL workload `NONDETERMINISTIC` because of `getrandom` and two unguarded kernel-state reads. The harness now avoids hashlib and sets `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`, and `MALLOC_ARENA_MAX=1`. Results still have to be produced by `./scripts/benchmark.sh` on Linux x86_64.

## Blockers

- Native benchmark has not yet produced `benchmarks/results/latest.json` for the current commit.
- No GitHub Release binaries, so installation is still `cargo install --path crates/tracejit-cli`.
- Root `LICENSE` was removed so the repository matches the Rust dual-license layout (`LICENSE-APACHE` and `LICENSE-MIT`). `Cargo.toml` remains `Apache-2.0 OR MIT`. GitHub may still display one of the two licenses.

## Next tasks

1. Produce and commit a real native benchmark for baseline, traced cold, guarded hit, and deopt.
2. Put the measured demo and numbers in the README only after that artifact exists.
3. Prepare a checksummed Linux x86_64 release for approval. Do not publish it unprompted.
4. Build a compatibility matrix from real Python, pytest, shell, Make, small Rust, and Node runs.
5. Profile tracer overhead only after a measured baseline exists.

## Known-good commit

`93f92e2` passed CI. This file is updated again after the next green push.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
./scripts/benchmark.sh --runs 30 --warmups 5
```

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

Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards. Deoptimize and retrace after invalidation. No daemon. `TRACEJIT_PHASE_TIMING=1` writes phase JSON to `TRACEJIT_PHASE_TIMING_PATH`.

## Validated capabilities

- CI formats, clippy-checks, and tests the workspace.
- Adversarial fixtures and `linux_integration` cover guarded hit, restore, replay, and deopt.
- `tracejit doctor` and named refusal reasons.
- Steady-state guarded hits skip rewriting a record whose decision is already `Reused`.

## Benchmark status

Kept loss, commit `63e33638709aacfaed896ab587435e64c0ecea62`: C ETL baseline 7.396 ms, cache hit 7.957 ms (0.93x). See `benchmarks/results/latest.md`.

Before the rewrite skip, commit `25d7c24e25b64382050d6d0ce126560e461855a4`: decision persist 3.136 ms, record decode 0.750 ms. Slowest measured loss 4.952 ms, fastest measured win 9.226 ms. See `benchmarks/results/overhead-before.md`.

After, commit `e9684c1c01a7bbbab4cae50e2389105596d613f1`: hit floor about 4 ms. Slowest measured loss 1.796 ms, fastest measured win 5.274 ms. `c-transform` baseline 312.913 ms, hit 3.972 ms, 78.780x. Shell and `cc -c` stayed `UNKNOWN`. Python stayed `NONDETERMINISTIC` (`getrandom`, `gettid`). No daemon. See `benchmarks/results/break-even.md`.

## Blockers

- Shell and compiler invocations are refused because of unmodeled syscalls and access checks. That is fail-closed.
- CPython `gettid` is observable via `threading.get_native_id()`, and `PYTHONHASHSEED=0` does not remove the remaining `getrandom`. No whitelist.
- No GitHub Release binaries.

## Next tasks

1. Ask before a release or published binaries.
2. Model the shell and `cc` refusals only with a fail-closed argument and regression tests.
3. Capture a real `tracejit run` transcript on Linux before putting terminal output in the README.
4. Keep `main` green.

## Known-good commit

`e9684c1c01a7bbbab4cae50e2389105596d613f1` passed CI and the break-even workflow.

## Validation

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
python3 benchmarks/harness/break_even.py --runs 30 --warmups 5
```

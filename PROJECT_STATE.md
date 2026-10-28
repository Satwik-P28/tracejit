# Project state

## Thesis

Automatically infer enough observable dependencies of an unmodified Linux process to reuse computation safely, and enforce that safety when enforcement is available. Fail closed.

## Safety invariants

- `UNKNOWN` and `NONDETERMINISTIC` never reuse.
- `EMPIRICALLY_STABLE` does not reuse in V1.
- `PROVEN` requires seccomp plus Landlock ABI 3+ actually installed. Observation alone is not `PROVEN`.
- Guards finish before cached output is exposed.
- Writable file-backed `MAP_SHARED` mappings are `UNKNOWN`. vDSO `clock_gettime`, `gettimeofday`, and `time` are redirected to syscalls, or the trace is `UNKNOWN`.
- `Guard::NoUnexpectedEffects` always passes. Classification is the real rejection.
- Uncertainty fails closed.

## Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`

Linux x86_64. ptrace. BLAKE3 CAS. SQLite. Whole-command reuse. Strict hashing. Synchronous guards. Deoptimize and retrace after invalidation. No daemon.

## Validated capabilities

- Linux x86_64 CI on `31c36d1` formatted, clippy-checked, and tested the workspace, including `linux_integration` and `./scripts/demo.sh`.
- `vdso_clock` calls libc `clock_gettime`, `gettimeofday`, and `time` and is `NONDETERMINISTIC`. Shared writable mmap fixtures are `UNKNOWN`.
- v0.1.1 is the published release at that commit. v0.1.0 remains the older release and does not contain this `explain` summary, these `doctor` sentences, the shared-mmap refusal, or the vDSO redirect.

## Phase 1 status

Branch `freebuff/c4bae51ae7d50b70f5bd4fc1`, branched from `f90b4db`. Audited, reproduced and
fixed five reliability defects (partial multi-output restoration, unrecoverable corrupt CAS object,
permanently fatal malformed record, deleted-output precondition, benchmark methodology) and one
execution-equivalence defect: `resolve_executable` canonicalized symlinks, so `tracejit run` exec'd
the canonical target with a rewritten `argv[0]` and CPython resolved a different installation
(`sys.prefix=/usr`) than a direct run (`/opt/freestyle/python`). Fixed by restoring the caller's
`argv[0`]; regression test `traced_execution_preserves_the_caller_supplied_argv0`.

Real-world census (`benchmarks/realworld/census.py`, 9 workloads, commit `6358522` plus the fixes):
**0 of 9 reusable**, 9 refused, 0 execution failures, output equivalence PASS on all 9. Ranked
blockers: unguardable `access()` checks (4 workloads, 28 occurrences), unclassified descriptors (4),
interpreter startup clock/pid/getrandom (3), then `pipe2` (5), `epoll_create1`, `fstat`, `/dev/null`,
failed `close(-1)`, `getrusage`. Reports: `docs/audits/PHASE1_COMPATIBILITY_REPORT.md`,
`docs/audits/PHASE1_CORRECTNESS_MATRIX.md`, `docs/audits/PHASE1_RELIABILITY_AUDIT.md`,
`docs/audits/PHASE1_PHASE2_HANDOFF.md`.

Raw data for this phase is in `benchmarks/results/phase1/` (census and native timing samples).

## Benchmark status

Do not replace these with local guesses.

Kept loss, commit `63e33638709aacfaed896ab587435e64c0ecea62`: C ETL baseline 7.396 ms, cache hit 7.957 ms (0.929468x). See `benchmarks/results/latest.md`.

After the hit-path change, commit `e9684c1c01a7bbbab4cae50e2389105596d613f1`: `c-transform` baseline 312.913 ms, hit 3.972 ms, 78.780x. That workload is synthetic (`EXTRA_ROUNDS` is 250000000). Slowest measured loss 1.796 ms, fastest measured win 5.274 ms. Shell and `cc -c` stayed `UNKNOWN`. Python stayed `NONDETERMINISTIC` (`getrandom`, `gettid`). See `benchmarks/results/break-even.md`.

## Release

v0.1.0 stays at its existing tag. v0.1.1 is published from `31c36d1`. Do not move either tag.

## Blockers before a public announcement of this tree

- Social preview upload is a GitHub settings action. The 1280×640 PNG is `docs/assets/social-preview.png`.
- Shell, `cc`, and CPython remain refused, and the Phase 1 census confirms it on 9 real workloads. That is correct until a fixture says otherwise.

## Known-good benchmark commits

`e9684c1c01a7bbbab4cae50e2389105596d613f1` for the transform and the sweep. `63e33638709aacfaed896ab587435e64c0ecea62` for the published short-command loss.

## Validation still required on Linux

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
```

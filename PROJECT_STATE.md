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

## Phase 1.5 verification (branch `verify/phase1-5`)

Independent verification of Phase 1 ran on Ubuntu 24.04.5 / kernel 6.1.102, 2 vCPU. All seven Phase 1
defects were re-tested: D6, D7, D1-D4 all hold, D2/D3 recovered end to end. Four new defects were
found and fixed with regression tests: D8 (a refused cached replacement aborted a command that
succeeds when re-run), D9 (a traced script saw a canonical `$0` instead of the caller's path), D10
(benchmarks recorded every run as dirty) and D11 (the seccomp capability probe tested `prctl`
instead of the filter interface). The seccomp filter is now verified on its own, so enforcement has
real coverage even without Landlock.

`PROVEN` still has never been exercised: this kernel has no Landlock (`ENOSYS`, LSM list
`capability,selinux`), so those probes report SKIP. CI already fails on `RESULT sandbox SKIP`; that
gate cannot run here without a push. Two clean benchmark sessions: baseline 8.3414/8.3508 ms, cold
19.0236/18.5066 ms, hit 3.9715/3.9912 ms, speedup 2.1003x/2.0923x, 2.33-2.44 hits to recover a cold
trace. The break-even sweep did not finish and is reported as BLOCKED, not estimated.

See `docs/audits/PHASE1_5_*.md` and `benchmarks/results/phase1_5/`.

## Phase 2 (branch `verify/phase1-5`, commit `2edbf0d`)

Phase 2B.2 landed: `access`/`faccessat`/`faccessat2` are now recorded verbatim (path, mode, flags and
the exact errno) and replayed as a predicate at validation time, instead of being refused. This was
the census's most frequent blocker (4 of 9 workloads, 28 occurrences) and it is now absent from the
ranking. Phase 2A.1 landed too: the tracer re-hashes the executable immediately before exec and
refuses to trace on a mismatch, so a replaced path cannot file a profile under an identity that did
not produce it; the final window between the check and `execve` remains open and is documented.

Eligibility is still **0 of 9**: the remaining blockers are `unclassified_descriptor` (4 workloads,
11 occurrences), `pipe2` (5), `getrusage` (2), `epoll_create1` (1) and `fstat` (1). Output
equivalence stayed 9/9. `PROVEN` is still unexercised (no Landlock on this host).

Tests: 77 passing. Benchmarks have **not** been re-run at `2edbf0d`; do not quote Phase 1.5 numbers
for this commit. See `docs/PROJECT_EXECUTION_STATE.md`, `docs/audits/PHASE2_ACCESS_PREDICATES.md`,
`docs/audits/PHASE2_EXEC_IDENTITY.md`, `docs/audits/PHASE2_CENSUS_DELTA.md`, and
`benchmarks/results/phase2/census-2edbf0d/`.

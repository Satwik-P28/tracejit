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

## Phase 2B (branch `verify/phase1-5`, commit `b57bc7f`)

Soundness audit of the access mechanism found three high-severity defects, all fixed with regression
tests. (A1) The replay ran as the validating process, so a check recorded by a privilege-dropped
child was re-answered as root: root bypasses discretionary checks, so a revoked ACL still looked
permitted. Each check now records a digest of the uid/gid quadruple, supplementary groups and
capability sets, and the guard refuses when the replaying process does not hold that identity. (A2)
`AT_EMPTY_PATH` was answered about a path instead of a descriptor; now refused. (A3) `normalize()`
collapsed `..` lexically, so `a/link/../b` was recorded as `a/b` and the guard hashed a different
file than the one that was read; `..` is now preserved and resolved by the kernel.

Internal pipes are modelled by pipe identity (`FdState::InternalPipe`) across `dup`, fork and exec,
so `pipe2` and `unclassified_descriptor` have disappeared from the census ranking entirely. Reuse of
pipe traffic requires one writing process, no short read followed by more data, and no partial or
untracked transfer; each violation is recorded with the observation that triggered it.

Eligibility is **still 0 of 9**, now blocked by `clock`/`randomness`/`process_identity` (interpreter
startup), pipe short-read-then-more (3 workloads), `fstat` on a pipe (2), `getrusage` (2) and
`epoll_create1` (1). Output equivalence stayed 9/9. Tests: 86 passing. Benchmarks have **not** been
re-run at this commit. See `docs/audits/PHASE2B_*.md` and
`benchmarks/results/phase2b/census-b57bc7f/`.

## Phase 2C (branch `verify/phase1-5`, commit `bd59a0e`)

**First real-world cache hit.** `gzip -9 -c <18 MB text>` classifies `GUARDED` with 9 dependencies
and one process; the second run reports `Reused` and returns bytes identical to a direct run, 20/20
consecutive runs hit, and the measured speedup is **23.84x** (259.41 ms direct vs 10.88 ms cached,
p95 272.03 / 14.05), with two repeated uses repaying the cold trace. A content change deoptimizes and
returns the new bytes; an mtime-only change deoptimizes because gzip stores the timestamp; a changed
environment is not reused; a symlink repointed at another program is never replayed. The regression
test is `real_gzip_workload_is_reused_and_invalidated`.

`getrusage` was investigated and **not** admitted. It is called once by `as` (not `cc1`, not for
`-ftime-report`, `RUSAGE_SELF`); overriding the value with zeros or absurd numbers, or failing the
call outright, leaves the object file byte-identical, and `as --statistics` prints `0.000000` under
either extreme, so the value reaches no observable output — for these inputs. It stays
`NONDETERMINISTIC` because per-run consumption cannot be guarded.

Census unchanged at **0 of 9**. Two findings explain most of it: the census invokes workloads through
`sh -c`, so the shell's own `/dev/tty`, `getpeername` and `statfs` are part of what is measured; and
`sort`/`base64`/`md5sum`/`tr`/`wc`/`head` read `getrandom` at startup, so they are nondeterministic
regardless of modelling. Pipe reuse is limited by the packetisation argument, not by a missing
syscall. Tests: 87 passing. See `docs/audits/PHASE2C_*.md` and
`benchmarks/results/phase2c/direct-suite/`.

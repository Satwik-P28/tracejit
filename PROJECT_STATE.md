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

## Phase 2I (branch `freebuff/phase2f`, base `9b777ee`)

The allocator-key question is resolved by decision, not by a new key: the fixed controlled value is
retained because glibc's `tcache_key` is an integrity value checked by list membership, a derived
key cannot keep a secret the child can read, and fresh OS randomness would make reuse impossible. It
stays opt-in, build-ID/offset/signature checked, and outside any `PROVEN` claim.

Admission now records deoptimisations and uses a Laplace-smoothed, three-invocation cumulative
benefit estimate with a 30-day sample TTL; `--admission auto-v1` preserves the Phase 2H policy for
comparison. The policy does not beat `auto-v1` on the 20-invocation matrix (3.54x/2.73x vs
3.55x/2.84x) and `always` wins that stable matrix (4.03x/3.19x), but on a real zlib v1.3.1 session
`auto` saves **1.20x/1.07x** net while `always` is **1.71x/1.82x slower**, because it refuses to
trace `make` and caches repeated `./minigzip` compressions (24-28 ms vs ~380 ms). Decompression stays
ineligible on `lseek` of inherited fd 0. Coverage is unchanged: 1/16 native, 7/16 controlled, 0/9
census, 16/16 and 9/9 output equivalence. The differential fuzzer is 45 cases x seeds 7 and 11 with
0 incorrect hits. A genuine concurrency defect (`database is locked` during concurrent cache open)
was found and fixed with a busy timeout plus bounded retry. Tests: 109 passing, three consecutive
runs. See `docs/audits/PHASE2I_*.md` and `benchmarks/results/phase2i/`.

## Phase 2J (base `4ecb804`)

Inherited stdin now has an offset model instead of a blanket `lseek` refusal. `SEEK_SET`,
`SEEK_CUR` and `SEEK_END` on fd 0 itself update a model position; the guard still requires the
recorded start offset and content hash, and a hit seeks the shared description to the recorded
final offset. `pread64` no longer counts as consuming bytes. Aliases (`dup` of stdin), directory
fds and `SEEK_DATA`/`SEEK_HOLE` are refused. This unlocks `./minigzip -d`: first run `Guarded`,
second `Reused`, byte-identical output. `tests/fixtures/stdin_seek.c` covers seek-before/after-read,
`SEEK_END`, `pread`, failed seeks, aliases, `SEEK_DATA`, changed initial offset and content
mutation, checking both bytes and the caller's file position.

Admission was simplified after an ablation: the Phase 2I smoothed probability and 3-invocation
horizon did not beat the Phase 2H threshold, so `auto` is now `direct >= 2 x max(hit, 6 ms)` and
`hits + 1 > deopts`, with `auto-v1` retained. Real sessions: zlib **1.099x/1.228x** net with both
compression and decompression reused (`always` 0.268x/0.356x); libpng's 1.1x in session A is
noise because `pngtest` is 7 ms and is correctly declined, and `always` makes its configure exit 1;
lz4 is `NONDETERMINISTIC` because its CLI reads the monotonic clock (one valid session, 0.969x).
The differential fuzzer is 120 cases x seeds 7/11/17 (360 comparisons, 0 incorrect hits). The
intermittent `ETXTBSY` was the test's direct exec racing a parallel fork that inherited the
script's write descriptor; reproduced with `bash -c 'exec 9>prog; prog'` and fixed in the test
only with a bounded retry. Tests: **110 passing**; fmt and clippy clean; `PROVEN` still blocked
(`landlock no`). See `docs/audits/PHASE2J_*.md` and `benchmarks/results/phase2j/`.

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

## Phase 2D (branch `verify/phase1-5`)

A fixed **direct-execution suite** of 16 real commands (no shell, own working directory, denominator
fixed with refusals in it) replaces guesswork about what is reusable: **1 of 16 reused** (`gzip`),
**16 of 16** traced output identical to a direct run, in two independent sessions. `getrandom` at
startup refuses nine of them; `statfs` refuses `tar` and `sed`; `/proc/self/maps` refuses `grep`; an
inherited descriptor read refuses `tr`; `getrusage` refuses `gcc` and `as`. `zstd`, `clang`, `pandoc`,
`convert` and `ffmpeg` are absent, so image and documentation conversion are BLOCKED, not refused.

The Phase 2C claim that a future-dated input `mtime` caused repeated deoptimization was **wrong**,
and the atime hypothesis with it. `explain` shows the failing guard is a `FileMetadata` dependency on
the **parent directory** of the opened path; its `mtime`/`ctime` change when anything is created or
removed in that directory, including the command's own output, and directories have no content hash
to fall back on. `atime` was byte-identical in the failing comparison. The scoped fix (identity-only
comparison for resolution-time directory snapshots, keeping full fingerprints for genuine `stat`)
would be sound, but the recording site was not located, and a guard-level shortcut would also stop
noticing a real directory `stat` — so it is documented as open, not patched. Consequence: the 7x
below holds only while that directory is unchanged.

Two benchmark sessions, 480 KB input: direct 28.84/28.78 ms, cached 4.03/4.18 ms, cold
46.26/47.10 ms, **7.16x/6.89x**, **0.70/0.74 hits to repay**. Only `gzip` is timed (the others never
reused). No competitive comparison is possible here.

Certified effect noninterference was surveyed, not built: Rattle ignores nondeterminism by assumption
and substitutes observed values, Firebuild refuses by contract, `rr` proves path identity (the
opposite direction), and only self-adjusting computation has a machine-checked equivalence theorem —
for an instrumented language, not a shipped binary. No system in that literature certifies a specific
dynamic read as dead. The hypothesis put forward (perturbation-coverage certificates stored in the
record) is untested, so no research contribution is claimed. Tests: 87 passing. See
`docs/audits/PHASE2D_*.md` and `benchmarks/results/phase2d/`.

## Phase 2E (branch `verify/phase1-5`)

The Phase 2D explanation of the directory invalidation was wrong in both of its parts. The dependency
is created by a real `openat(AT_FDCWD, "<dir>", O_RDONLY|O_DIRECTORY)` that `gzip` issues to obtain a
name-resolution base for the input, which the tracer recorded as a metadata read because a directory
has no content hash. There is no `stat` and no path-resolution snapshot: `strace` and the new
`TRACEJIT_DIAG_DEPS=1` events show only the open, then `openat(dirfd, "in.txt")`.

That dependency is now its own kind, end to end: `ReadEffect::DirectoryOpened` →
`InputDependency::DirectoryOpened` → `Guard::DirectoryOpened`, which compares `device`, `inode`,
`mode`, `uid` and `gid`, requires the path to still be a directory, and replays a probe open. `stat`,
`fstat` and `newfstatat` still produce `Metadata` and still compare every timestamp; a program that
enumerates a directory is now refused, because `getdents64` had been silently ignored and entries were
never guarded.

Ordinary output placement now costs nothing: with the output and unrelated siblings written beside the
input, 15/15 runs reuse and 0% invalidate in all eight cells of two sessions (5.86–12.04 ms warm versus
112–1494 ms direct, one hit repaying the trace). The `0ccf181` baseline for the same sequence was 1/6
hits, 83% invalidation, and 0.82x–0.96x, i.e. slower than not caching. The added guard is below this
VM's measurement floor (6.02/10.41 ms versus 9.46/14.30 ms baseline, p95 spread wider than the
difference). The direct suite is unchanged at 1 of 16 reused (gzip) with 16/16 output equivalence, and
the nine-workload census at 0 of 9: no new category was obtained. Tests: 95 passing. See
`docs/audits/PHASE2E_DIRECTORY_DEPENDENCY.md` and `benchmarks/results/phase2e/`.

## Phase 2F (branch `verify/phase1-5`, commits `5db741f`, `be94f38`)

The `DirectoryOpened` audit found two soundness defects — the probe open ran under the validator's
credentials instead of the recorded child's, and it replayed an `O_PATH` open as a read open — both
fixed by recording the credential digest and the original access mode. It also found a
pre-existing path defect: `..` was normalised lexically, so `/a/link/../b` was guarded as `/b` while
the kernel resolved it through the symlink; `be94f38` canonicalises paths containing `..`.

Three dependency models landed: `statfs`/`fstatfs` (all 120 returned bytes, same call shape, mount
namespace and credentials bound, cached errno replayable), `getdents64` (the exact per-call byte
stream, preserving order, cookies, `d_type` and partial reads) and inherited regular-file stdin
(content hash, descriptor identity, start offset; the hit path advances to the recorded end offset).
Pipes, sockets, terminals, anonymous and unknown descriptors still refuse.

The blockers those models targeted are gone: `sed` and `tar` now stop at `getrandom`, `tr` stops at
`getrandom` after its stdin read, and `nm` enumerates its plugin directory successfully. **The
two-additional-category target is unmet**: every surveyed glibc-linked tool (about 50, including
`sed`, `tar`, `tr`, `nm`, `ar`, `grep`, `sort`, `perl`, `make`, `zip`, `gcc`) calls `getrandom` from
inside `malloc`/`setlocale`, and `GLIBC_TUNABLES` tcache disabling does not remove it. Ignoring it
would be the forbidden global whitelist. Compatibility is unchanged: **1 of 16** direct workloads
reused (gzip, 16/16 output equivalent) and **0 of 9** census workloads, in two clean-tree sessions
each at `be94f38`. gzip: 28.89/29.00 ms direct, 4.33/4.06 ms warm, 6.67x/7.14x, 0.48/0.54 hits to
repay. Tests: **100 passing**; fmt and clippy clean. `PROVEN` remains BLOCKED (no Landlock on this
host). See `docs/audits/PHASE2F_*.md` and `benchmarks/results/phase2f/`.

## Phase 2G (branch `verify/phase1-5`, from `6941443`)

The path audit confirmed a **false cache hit** in `be94f38`: canonicalising `..` replaced the path
question with a file, so repointing a symlink before `..` still passed every guard (93/93) and
returned stale bytes. Two regression tests failed that way first, then passed after `normalize`
stopped collapsing `..`; the guard now replays the exact pathname. No false hit was found in the
remaining tested scenarios; mount changes are BLOCKED (`unshare -m` EPERM).

The allocator `getrandom` was forensically identified: glibc 2.39 `tcache_key_initialize`, called
from `ptmalloc_init` via `libselinux`→`strdup`→`malloc`, destination in libc's `.bss`, build ID
`a4a7992a8e66555c8141ab2a08a8465ff6e0ea65`. `tcache_count=0` does not remove it, no
`glibc.malloc.tcache_key` tunable exists, and static glibc still calls it; musl is untested (BLOCKED).

A second, opt-in contract `tracejit.allocator-entropy.v1` admits only a `getrandom(8,
GRND_NONBLOCK)` whose caller is a shared library and whose destination lies in that library's own
`PF_W` `PT_LOAD`, returning a fixed value; library hash, call shape, value and contract id are
recorded and guarded, and native and controlled entries cannot mix. It is **not** a sandbox and not
general determinism.

Measured, two sessions, fixed denominators: native **1/16** direct and **0/9** census unchanged;
controlled **7/16** and **6/16** direct (the difference is `tr`'s stdin atime changing the identity)
and **0/9** census, with 16/16 and 9/9 output equivalence throughout. `gzip` 7.39x, `bzip2` 4.10x;
sub-6 ms filters are slower cached (0.21–0.69x) because a hit costs 4–6 ms. A four-command
developer workflow on 5.4 MB saves **14.74x** (645.62 → 43.80 ms). Contract checks pass 4/4.

Tests: **105 passing**; fmt and clippy clean. `PROVEN`/Landlock remain unverified. Nothing was
pushed or released. See `docs/audits/PHASE2G_*.md` and `benchmarks/results/phase2g/`.

## Phase 2H (branch `verify/phase1-5`, from `45bd1c3`)

The contract no longer trusts a shared-library *pattern*. Admission is now an audited call-site
profile: GNU build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65`, resume offset `0xa9e89`,
destination offset `0x20b178`, and the bytes `0f 05 48 8d 5d d0 48 83 f8 08`. Any other build,
offset, destination or signature is refused, and records written under the old rule (empty build
ID) are refused rather than reinterpreted. The guard repeats every check against the current
library. A compiled double-free program still aborts with glibc's diagnostic under the contract, so
the injected key does not disable detection; the fixed key does remove per-process secrecy, which
is documented as an opt-in, heap-corruption-only weakening, with a per-identity derived key named
as the safer alternative.

`atime` was removed from the inherited-stdin runtime identity (the reference to the `tr` miss). `tr`
now reuses in both sessions, with content changes still invalidating. A new `--admission
always|auto|never` policy measures a command's direct runtime before paying for a trace, and stops
tracing identities already recorded as ineligible.

Two sessions: native **1/16** direct, controlled **7/16** (both sessions), census **0/9** in both
modes and both sessions with 9/9 equivalence. Auto shows 0/16 on the suite's second run by design
(it measures first, traces second, hits third). Workflow (5.4 MB, four commands): 8.95x/9.64x with
always, 10.36x/10.27x with auto, both sessions. Developer loops: always 1.52x/1.59x (slower than
direct), auto 1.08x/1.08x; refused workloads stop paying repeatedly under auto. Differential fuzzer:
32 mutation cases, **0 incorrect hits**. Tests: **108 passing**; fmt and clippy clean. `PROVEN` still
BLOCKED (LSM list `capability,selinux`; Landlock unavailable). Nothing pushed or released. See
`docs/audits/PHASE2H_*.md` and `benchmarks/results/phase2h/`.

## Phase 2K (base `f3bd191`)

The Phase 2J libpng diagnosis was wrong: traced `configure` exited 0; `make -j4` failed with
`missing process state`, because a vfork child's first stop can be reported before the parent's
`PTRACE_EVENT_VFORK`. Children are now adopted idempotently from `/proc` before their stop is
decoded, with a parallel-vfork regression that fails on the old tree and passes now. libpng builds
under every policy; `always` costs 0.311x/0.283x but no longer fails.

Inherited descriptors: every fd is classified at exec, an inherited regular file on fd 3 is refused
rather than read as ordinary content, stdin aliases (same device/inode/position, since `kcmp` is
`ENOSYS`) refuse the stream, a child's seek on shared stdin is refused, and the real fd position is
checked after each read/seek and before `exit_group`. zlib still reuses compression and
decompression, byte-identically.

The session harness now spells out `--admission`, invalidates a policy whose phases failed or whose
tool artifacts differ, and records commit/workload/host metadata. Two sessions: zlib auto
**1.033x/1.164x** (decompression and compression both `Reused`); libpng valid at 1.055x/0.929x
(noise, `pngtest` declined) and `always` 0.311x/0.283x; lz4 valid but no reuse (monotonic clock),
0.925x/1.056x. New execution-fidelity suite: 9/9 accounted, 0 failures (1 autoconf `Unavailable`,
7 safely executed without reuse, 1 reused). Fuzzing seeds 7/11: 240 comparisons, 0 incorrect hits.
8 concurrent cold runs: all correct, no lock error. **112 tests**; fmt/clippy clean. `PROVEN` still
BLOCKED (`landlock no`). See `docs/audits/PHASE2K_EXECUTION_FIDELITY.md` and
`benchmarks/results/phase2k/`.

## Phase 2L (base `53aef79`)

Process-tree audit closed two remaining repair defects: no state is installed for a child reaped
before its fork event (which could stall the wait loop), and a process with no tracked `/proc`
parent is reconstructed conservatively and marked unknown instead of aborting the command. Timed
parallel vfork storms cover both. The inherited-descriptor contract and its boundary (kcmp absent,
external mutation after the last operation) are documented, and zlib reuse is unchanged.

The execution-fidelity matrix is **14/14 accounted, 0 failures**: 3 safely reused, 10 executed
without reuse, 1 autoconf `Unavailable`. Clean-commit sessions at binary `b6a96117...`: zlib auto
**1.096x/1.125x**; bzip2 reuses compression and decompression but nets 0.983x/1.039x because its
build dominates. `always` is 0.44-0.69x. libpng/lz4 were not rerun clean in this phase.

Subprocess-level reuse was studied and **not built**: it adds pipe, signal, shared-descriptor and
parallel-ordering hazards, and every `cc`/`make` child is already refused for the same clocks and
entropy as its parent, so no measured advantage exists yet. Developer-preview gate: not ready as a
general accelerator; `PROVEN` still BLOCKED (`landlock no`). See
`docs/audits/PHASE2L_*.md` and `benchmarks/results/phase2l/`.

## Phase 2M (base `c7f2c68`)

CI run 42319563118 failed because the standalone seccomp test installed
`SECCOMP_MODE_FILTER` without `PR_SET_NO_NEW_PRIVS`. `apply` inherited the flag from the Landlock
step, but this shell already has `NoNewPrivs: 1`, so only an unprivileged runner saw `EACCES` and
exit 125. `apply_seccomp` now sets the precondition itself, the probe reports the errno, and the
child asserts the flag. 113 tests pass; the CI rerun needs an authorized push.

The four-repository matrix ran three sessions at binary `b0576fb1...`. Session B is contaminated
(`never` bzip2 build 3748 ms vs 1274 ms for `direct`) and retained as evidence of the noise ceiling.
Sessions A/C: zlib `auto` **1.145x/1.173x**; bzip2 reuses both directions but nets 0.976-0.980x
because the build dominates; libpng 0.92-1.00x (pngtest is 7 ms and declined); lz4 0.94-1.00x and
still `NONDETERMINISTIC`. `always` is 0.23-0.77x. All 60 policy runs produced correct artifacts.

Subprocess wrapping (`benchmarks/repos/subprocess_wrap.py`, two sessions, real zlib tree, standard
per-file compression rule): wrapped child **1.148x/1.175x**, whole-command `make` 0.842-0.860x,
5/5 cache hits on the cached repeat (52/40 ms vs 226-232 ms), ~12 ms net saved per child, no cache
lock under `-j4`, correct invalidation, environment and exit-status propagation. The advantage is
too small to justify transparent interception: a real build's time is in refused `cc`/`make`
children. No specialist gzip cache exists, so arm D is not applicable. `PROVEN` stays BLOCKED
(`landlock no`); preview remains not ready as a general accelerator. See
`docs/audits/PHASE2M_*.md` and `benchmarks/results/phase2m/`.

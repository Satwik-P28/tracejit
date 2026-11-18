# Phase U1 — CI stabilisation, descriptor audit, and measurement

Branch `development/v0.3`, base `e0dcc8c`. Everything below was produced on this host
(8 CPUs, Linux x86_64) by the commands quoted. Nothing here changes `v0.2.0-beta.1`.

## 1. Root causes of the failing CI run

The three integration tests refused with `inherited descriptor 142` because the *harness*
put that descriptor there. Three independent harness defects compounded:

1. **Leaked pipe.** `pipe_with_data()` used `libc::pipe()`, so both ends were inheritable in
   the shared test process. Any concurrently spawned `tracejit` child inherited one of them
   and correctly refused reuse for a descriptor number the failing test never created.
2. **`pre_exec` scrub closed live descriptors.** `close_descriptors_above_stderr()` ran in
   `pre_exec`, before `std::process` installs the child's stdio, and later once per process
   over slots `3..1024`. Closing descriptors the harness does not own broke spawning
   (`EBADF` from `Command::output`) and, in the once-per-process form, raced with live use by
   other threads: `TempDir` drop failed in `closedir` with `EBADF`.
3. **Shared slot 9.** `cloexec_source_already_on_fd9_still_reaches_the_child` called
   `dup2(_, 9)` and `close(9)` in the shared process. `dup2` onto a slot silently closes
   whatever another thread held there, which surfaced as `EBADF` in unrelated spawns and,
   once, as a closed stdout. The C-compiler timing lock also poisoned on the first panic,
   cascading one failure into six `PoisonError` panics.

Production enforcement was never at fault and is unchanged: the tracer still refuses any
non-CLOEXEC descriptor above stderr, still rescans after `Cache::open`, and still fails closed.

### Repairs (test harness only)

- Pipes are created with `pipe2(O_CLOEXEC)`; the child still receives the bytes because
  `run_with_fd9` installs descriptor 9 itself in `pre_exec`.
- No harness code closes a descriptor it does not own, and the shared test process's descriptor
  table is not modified at all. Each spawn marks its *own forked child's* descriptors
  `FD_CLOEXEC` in `pre_exec` (`close_range`, Phase U2 below), so anything the harness did not
  hand that child is dropped at `exec` without any other test or thread observing the change.
- `pre_exec` closures touch only descriptor 9.
- The two tests that deliberately manipulate descriptor 9 run in a re-executed copy of the
  test binary (`--exact`, `--test-threads=1`, guarded by `TRACEJIT_ISOLATED_TEST_CHILD`).
- The timing lock recovers from poisoning; per-test assertions are unchanged.

### New regression: `an_inheritable_parent_descriptor_is_refused`

Isolated process; (1) baseline is eligible and genuinely reuses, (2) a real parent-held
descriptor is cleared of `FD_CLOEXEC`, (3) the child inherits it and reuse is refused with
`inherited descriptor <fd>` while `eligible_for_reuse` is false, (4) repeating cannot produce a
HIT and the fallback run matches a native run's exit status and stdout, (5) closing the
descriptor restores reuse.

### Concurrency evidence

| configuration | result |
| --- | --- |
| `--test-threads=1` | 69/69 (25.6 s) |
| `--test-threads=2` | 69/69 (11.2 s) |
| `--test-threads=4` | 69/69 (6.4 s) |
| `--test-threads=8` | 69/69 (4.2 s) |
| `--test-threads=16` (2× oversubscribed) | 69/69 (3.9 s) |
| default parallelism, 10 consecutive runs | 69/69 each |
| default parallelism, `142` and `145` held non-CLOEXEC (the CI condition), 10 consecutive runs | 69/69 each |

### Hotfix: descriptors inherited from the CI runner (run `44235001207`)

`assert_no_inheritable_harness_descriptors` failed on GitHub Actions with `[142, 145]`. Those
descriptors were present before the first spawn: `Fixture::new` is the first thing any test does,
and run `44235001207` panicked in `a_corrupted_cached_output_fails_closed` at the assertion, not
in a test that had created anything. They are inherited from the runner process, not created by
any test, and nothing in the harness owns them.

The assertion was the wrong instrument: it cannot be race-free (it observes whatever the shape of
the process happens to be) and it made the run red without fixing the consequence, which is that
the traced child inherits those descriptors too and must refuse. Reproduced locally with
`bash -c 'exec 142>…; exec 145>…; cargo test …'`: before the change the run failed, after it the
suite was green with no `inherited descriptor` refusal anywhere.

### Phase U2: the sweep belongs to the child

The first repair marked those descriptors `FD_CLOEXEC` once per test process from a `Once`. That
is still a process-wide mutation during parallel execution, and it has real defects: another
thread's live descriptor can be flag-flipped, another test's intended child inheritance can
change, the scan stops at descriptor 1023, and a slot can be closed and reused between
`F_GETFD` and `F_SETFD`. Moving the same call into the shared process would not fix the ownership
problem, so the placement changed rather than the syscall.

Each spawn now sweeps its own fork. `pre_exec` calls
`close_range(3, UINT_MAX, CLOSE_RANGE_CLOEXEC)`: one kernel call, after `fork` and before `exec`,
in a process with exactly one thread and a private copy of the descriptor table. It closes
nothing (every descriptor stays valid for its owner and is merely dropped from the `exec`),
reaches every descriptor the process can own, and is invisible to the parent and to every other
test — no lock, and no cooperation from `std::process`, is required. `Command`'s spawn-error and
stdio pipes are already close-on-exec and are installed with `dup2`, which clears the flag on the
new 0/1/2, so marking them is a no-op. Kernels before 5.11 fall back to an `F_GETFD`/`F_SETFD`
loop bounded by `RLIMIT_NOFILE` (read in the parent, because `/proc` is not async-signal-safe);
the loop is race-free for the same reason, since it also runs in a single-threaded forked child.

Spawning with the table left alone is now explicit: `invoke_inheriting` is used only by the
regressions that must present TraceJIT with a descriptor the hash does not model.

`runner_inherited_descriptors_do_not_contaminate_runs_and_are_still_refused` reproduces the runner
across a real `exec`: the parent re-executes the test binary with 142, 145 and 1500 open and
inheritable, and the child asserts that they arrived inheritable; that an ordinary spawn reuses
with no `EBADF`; that handing the table over is refused with `eligible_for_reuse: false` and an
`inherited descriptor <fd>` reason; that the fallback's exit status and stdout match a native run;
that leaving only 1500 open is still refused by that number; and that closing it restores reuse.

The isolation policy is unchanged: the tests that deliberately create a non-CLOEXEC descriptor
(`an_inheritable_parent_descriptor_is_refused`, `cloexec_source_already_on_fd9_still_reaches_the_child`)
still run in their own re-executed process, and `run_with_fd9` still installs descriptor 9 in
`pre_exec`. The regression still shows baseline reuse, refusal by descriptor number, no HIT on
repetition, a native-identical fallback, and reuse restored after the descriptor is closed.

### Scheduling-sensitive wall-clock assertions

`auto_admission_skips_short_commands_and_caches_expensive_ones` is the only test whose assertion
depended on how fast the host is. Run 1 always measures (`Skipped`); run 2 applies
`admission_is_worth_tracing`, which pays for a trace when the measured direct cost reaches twice
the 6 ms hit-cost floor. Under 68-way parallel execution `wc -c` measured 11–25 ms, so paying for
the trace was the correct decision and the old fixed `Skipped` expectation was wrong, not the
policy. The test now asserts the policy against the cost the measuring run itself reports
(`tracejit_core::HIT_COST_FLOOR_NS`), asserting both directions rather than assuming an idle
machine; on the strict `--test-threads=1` CI job the sub-threshold branch is the one that runs.
The poisoned-lock recovery is kept and justified: the guarded value is `()`, so no data can be
inconsistent, and propagating the poison would bury the one real panic under six `PoisonError`s.

## 2. Descriptor and syscall-model audit

| admission | verdict | basis |
| --- | --- | --- |
| `/dev/null` identity | keep | `is_null_device_fd` checks device identity on the *opened* descriptor, so a bind mount or regular file at `/dev/null` takes the ordinary path. Reads reach EOF, writes are discarded, `fstat` is guarded through the node fingerprint, `TCGETS` deterministically fails `ENOTTY`. |
| `epoll_create1` | keep | A create-only instance has no observable content until a descriptor is registered; the fd number is a function of the program's own traced opens with the inherited table guarded. `epoll_ctl`/`epoll_wait`/reads still refuse (pinned by `epoll_registration_is_refused`). |
| `fcntl(F_SETFL)`/`FIONBIO` | keep | Only `O_NONBLOCK` may differ, only on a regular file this process opened, and only before it created a child (so no other process shares the open file description). Every other bit and every inherited/pipe descriptor refuses. |
| `prlimit64` query | keep | Admitted only for `pid == 0`, no new limit, and the four limits (`RLIMIT_STACK/NOFILE/AS/RSS`) that `RuntimeIdentity` records and rechecks on every hit. |
| deterministic `EBADF` | keep | A negative descriptor exists in no table, so the answer is fixed by the argument. |
| deterministic `ENOTTY` | keep | Failed `TCGETS` on a pipe or the null device is reported by the completion arm; a *successful* terminal query still refuses. |

One gap was found and closed: `fcntl` flag queries (`F_GETFL`, `F_GETFD`, `F_GETOWN`,
`F_GETLEASE`, `F_GETPIPE_SZ`) were treated as process-local for **every** descriptor. For an
inherited description the flags were chosen by whoever created it and no guard records them, so
a program branching on `O_NONBLOCK`/`O_APPEND` on stdin could have replayed the previous run's
branch. Queries are now admitted only for descriptors this execution created, with a unit
regression covering the inherited, owned and unknown cases. No admission was reverted; none
failed review.

This follows the rule the code already applies to `DirectoryOpened` and to stdin's atime:
guard exactly the fields the program could have observed.

## 3. Warm-hit profile

`scripts/phase_k7_perf_micro.py`, 5 warmups + 30 runs, medians, same host, published beta
(`5a1100c5…`) against this candidate (`c5f9151b…`):

| shape | phase | candidate | v0.2.0-beta.1 |
| --- | --- | --- | --- |
| c-etl | warm wall | 8.94 ms | 8.74 ms |
| c-etl | SQLite query | 0.27 ms | 0.28 ms |
| c-etl | record decode | 0.19 ms | 0.21 ms |
| c-etl | guard validation | 0.80 ms | 0.90 ms |
| c-etl | CAS restore | 2.53 ms | 2.31 ms |
| plain read | warm wall | 8.79 ms | 8.86 ms |
| plain read | SQLite / decode / guards / restore | 0.28 / 0.19 / 0.91 / 2.23 ms | 0.27 / 0.19 / 0.91 / 2.22 ms |

The reported fixed warm-hit overhead is therefore **unchanged from the published beta** and is
not a Phase U cost. Of the ~8.8 ms, ~3.6 ms is instrumented (CAS restore dominates at ~2.2 ms,
guard validation ~0.9 ms, SQLite ~0.27 ms, decode ~0.19 ms); the remaining ~5 ms is process
startup, cache open and output emission, which the phase timer does not cover. Dependency
hashing is inside guard validation and is not separately instrumented.

A second harness (5 cold + 30 warm runs of the same ETL workload) produced candidate 29.95 ms
cold / 7.28 ms warm against beta 41.84 ms / 9.19 ms, which shows how much this shared host
varies between batches; the direction is not a regression and the median differences are not
distinguishable from run-order noise.

Rejected on measurement: parallel guard checking (0.9 ms total, less than the scheduling cost),
a separate fast lookup path (SQLite is 3 % of warm wall), and connection reuse (one command per
process). No optimisation was accepted; correctness paths were not touched.

## 4. Metadata-guard precision (`atime`)

Measured today with `strip` under `--contract allocator-entropy-v1`:

```
run 1  Executed
run 2  Deoptimized  FileMetadata /tmp/…/a.o
        expected accessed_ns 1794974702722778519
        actual   accessed_ns 1794974702746778519
        size, blocks, inode, mode, mtime and ctime identical
        reason: "metadata changed; no content hash was recorded"
```

The tool's own read advances atime (relatime), so its input guard is stale the moment it
finishes and every later run deopts. The same fingerprint includes `accessed_ns` on output
pre-state guards.

Why the field cannot simply be dropped: `stat`/`fstat` report `st_atime`, so a program that
prints it must deopt when atime moves. The code already states the sound rule elsewhere —
`DirectoryOpened` compares identity but not timestamps because an `open` cannot report them,
and stdin's fingerprint zeroes `accessed_ns` for the same reason.

The sound narrowing is therefore: zero `accessed_ns` in fingerprints attached by
`open`/`openat`/`openat2` (an open returns no timestamps), and keep comparing it in
fingerprints attached by the `stat` family, which the tracer records separately. That requires
touching the effect sites at `linux.rs` ~2276/2309/2332 (~3017/3066 are the stat path), the
record semantics and therefore the cache-format validation, plus new mutation, symlink,
hard-link, concurrent-access and mount-difference regressions. It was **not** implemented in
this phase: shipping a record-semantics change without that full revalidation is the larger
risk. Guards stay as they are, and the limitation is recorded.

## 5. Verification

| check | result |
| --- | --- |
| `cargo fmt --all -- --check` | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 warnings |
| `cargo test --workspace --no-fail-fast` | 224 tests, 0 failed (includes `execution_fidelity`, `phase_d_verification`, `phase_k_modelcheck`, `phase_k_crash_recovery`) |
| `cargo build --workspace --release` | ok, `target/release/tracejit` = `31898b97…`, byte-identical to `f41c3b1`, so Phase U2 changed no production semantics |
| `cargo audit` | 0 vulnerabilities (1527 advisories) |
| `scripts/modelcheck/check_state_machines.py` | `RESULT phase-k3-modelcheck PASS`, 0 legal-state violations |
| `scripts/demo.sh` | direct / miss / HIT / explain / mutation-DEOPT all PASS |
| `scripts/phase_k4_restore_fault.sh` | soft fail-and-retrace and hard-kill recovery PASS |
| integration matrix | 69/69, see §1 |
| both compatibility corpora | see below |

Corpora (candidate, commit `5e2ca1d`):

| corpus | attempted | reused | rate | Phase U |
| --- | --- | --- | --- | --- |
| original census, native | 30 | 1 (`clang`) | 0.033 | 1/31 |
| original census, `--contract allocator-entropy-v1` | 30 | 7 | 0.233 | 7/31 |
| held-out 20, native | 20 | 0 | 0.000 | 0/20 |
| held-out 20, contract | 20 | 8 | 0.400 | 8/20 |

The one-workload difference is a tool missing on this host (2 blocked instead of 1). No
eligibility was inflated and the `fcntl` tightening changed no census outcome. Raw JSON and
rendered tables are in `benchmarks/results/phaseu1/`.

Not run: Landlock-dependent `PROVEN`/sandbox tests (this host's LSMs are
`capability,selinux`, so they skip), and the GitHub Actions run itself — see §6.

## 6. Repository operations

- `d2c1725` harness repair + `an_inheritable_parent_descriptor_is_refused`
- `5e2ca1d` refuse descriptor-flag queries on inherited descriptors + unit regression
- `5071037` Phase U1 evidence and report
- `f41c3b1` stop failing CI on runner-held descriptors
- `c686d27` child-local `close_range` sweep + runner-descriptor regression

Both are pushed to `origin/development/v0.3`. `main` and tag `v0.2.0-beta.1` are untouched;
no v0.3 tag or release was created.

**Blocked:** `gh` is not authenticated in this environment (`You are not logged into any GitHub
hosts`), so the PR against `main` could not be opened and CI run
`https://github.com/Satwik-P28/tracejit/actions/runs/44230006078` (and the run for `5e2ca1d`)
cannot be read from here. Opening the PR and confirming CI on `5e2ca1d` are the remaining
steps and need an authenticated client or the repository owner.

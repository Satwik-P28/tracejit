# TraceJIT Experiment Register

All results are tied to the local workspace and binary hashes below. They are not hosted-CI results.

## Environment

- Linux x86_64, kernel 6.1.102, 8 vCPU.
- Rust stable toolchain from `rust-toolchain.toml`.
- No Landlock; seccomp available. `PROVEN` is therefore unavailable locally.

## E-3A-01 — A/B/A alternate-candidate reuse

**Question:** Does retaining more than one guarded record let a return to an earlier input reuse without
retracing?

**Fixture:** `tests/fixtures/fixture_driver.c`, mode `plain_file_read`. It copies `input.txt` to
`output.txt`; the path and content are guards, not part of the lookup key.

**Sequence:** input one -> input two -> input one, in a fresh workspace and cache per session.

**Arms:**

- Current release: `79ee6501d7b09e8e0f4c02cb4cc32e0f4243b7525377f596e40c550cfafc084c`
- Pre-change release from `a11ae4b`: `3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`

**Command:**

```bash
python3 benchmarks/repos/candidate_reuse.py \
  --binary target/release/tracejit \
  --baseline .baseline/target/release/tracejit \
  --sessions 5 \
  --output benchmarks/results/phase3a/candidate-reuse.json
```

**Result (5 sessions):**

| Arm | Third-run decision | Median wall | Median report runtime | Correct bytes |
| --- | --- | ---: | ---: | --- |
| Current | `Reused` 5/5 | 13.841662 ms | 3,854,780 ns | yes |
| Pre-change | `Executed` 5/5 | 20.572657 ms | 5,258,884 ns | yes |

**Interpretation:** The candidate index changes the decision on this specific sequence and avoids a
retrace. The wall-time difference is a single small-command measurement, not a general speedup claim.

**Raw:** `benchmarks/results/phase3a/candidate-reuse.json`.

## E-3A-02 — Schema migration

**Question:** Can a v1 cache with `lookup_key` as a primary key be migrated without dropping its record?

**Test:** `crates/tracejit-cache/src/lib.rs::tests::v1_cache_is_migrated_without_losing_its_record`.

**Result:** `user_version` becomes 2; the legacy row survives; two rows with the same lookup key can be
inserted afterwards. Pass.

## E-3A-03 — Workspace and Linux integration gates

**Commands:**

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture --test-threads=1
```

**Result:** fmt pass; Clippy pass; 128 workspace tests pass; 42 Linux integration tests pass. The
`proven-reuse` integration test reports `SKIP` because Landlock is unavailable.

## E-3A-04 — Candidate bound

**Question:** Is eight the right retention bound?

**Status:** not measured. Eight is a conservative implementation bound, not an optimum. The next
experiment should measure lookup, decode, and guard-validation cost for 1, 2, 4, 8, and 16 candidates.

## E-3A-05 — Corrupt stream before output mutation

**Question:** Can a corrupt stdout/stderr object be detected before any workspace mutation?

**Status:** implemented ordering, but not isolated by a dedicated transient-state test. Existing
corruption tests prove that corrupt objects are not served and the command retraces; a new regression
should use a workspace state that would expose the old restore-then-fail order.

## Retained negative result — Phase 2T incremental comparison

The prior comparison remains authoritative for the claim boundary. Three sessions, 2.8 MB × 3 assets:

| Scenario | TraceJIT | Make | Ninja | Content cache |
| --- | ---: | ---: | ---: | ---: |
| Identical rerun | 678.59 ms | 2.63 ms | 2.82 ms | 60.22 ms |
| Five sessions | 2445.11 ms | 800.41 ms | 835.88 ms | 1071.34 ms |

Raw: `benchmarks/results/phase2t/incremental.json`. The result is a valid negative for whole-workflow
speed. Do not overwrite it with a more favorable definition.

## E-3B-01 — bzip2 transition and stable rerun

**Question:** Why did all three Phase 2T commands deoptimize on the identical rerun?

**Fixture:** three 2.8 MB assets compressed with `bzip2 -9 -k -f`; absent-output build, present-output
transition, stable third run, deleted outputs, edited input.

**Arms:** current `5c829977a78bff07b4905a7c575e16b9c805c3d0e97041991717f5f0422c2db4`; pre-Phase-3A
`3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`.

**Result:** transition is a `FileMetadata` failure on the command's own `.bz2` output. Current
833.464 / 793.821 / 231.120 / 261.146 / 474.566 ms; old 809.446 / 811.263 / 242.411 / 807.075 /
831.204 ms. The invalidation is necessary; stable reruns reuse.

**Raw:** `benchmarks/results/phase3b/identical-rerun-current.json`, `...-old.json`.

## E-3B-02 — candidate scaling

**Question:** What does retaining 1–32 candidates cost, and does newest-first remain viable?

**Result:** 1 candidate 9.133 ms, 8 17.726 ms, 32 41.087 ms for the oldest target; worst-case miss
13.943–41.655 ms; SQLite query 0.24–2.07 ms; decode 0.22–4.87 ms; guard validation ~0.94–1.07 ms.
Eviction with 16 states and bound 8 retained 8. Eight concurrent read-only readers all reused.
The default stays 8; no unsound ranking shortcut was added.

**Raw:** `benchmarks/results/phase3b/candidate-scaling.json`.

## E-3B-03 — corrupt stream before output mutation

**Question:** Can a corrupt stream object be rejected before any output restoration?

**Result:** `corrupt_stream_is_rejected_before_output_restoration` passes for both stdout and stderr
using fixtures that branch on output presence. The output remains `ABSENT\n` after the corrupt hit
and the retrace emits the correct stream.

## E-3B-04 — strict dependency hashing

**Result:** guard validation 1.130 ms at 1 KiB, 9.886 ms at 16 MiB, 99.400 ms at 256 MiB; about
2575 MiB/s at the largest size. No fs-verity or fanotify implementation was added.

**Raw:** `benchmarks/results/phase3b/hash-profile.json`.

## E-3B-05 — native compatibility census

**Result:** 9 attempted, 0 reused, 9 refused; `clock` and `randomness` each block 2; `lseek` blocks
3 and is the narrowest next candidate. Raw: `benchmarks/results/phase3b/census-native/`.

## E-3B-06 — old/current Phase 2T one-session check

**Result:** current 643.52 / 603.29 / 54.87 / 2171.11 ms for cold, transition, deleted outputs and
five sessions; old 611.64 / 615.12 / 610.16 / 2470.50 ms. One session, not a replacement for the
three-session historical table. Raw: `benchmarks/results/phase3b/phase2t-current-1session.json` and
`...-old-1session.json`.


## E-3C-01 — stable-workflow latency attribution

**Question:** What is actually spent in the three-asset bzip2 stable rerun?

**Result:** the Phase 3B 231 ms figure included 165-215 ms of post-command bzip2 output
decompression. The replay command loop is in the tens of milliseconds: 46.5-106.8 ms across two
sessions, with 15.4-31.6 ms per command. Dominant phases are process startup (6.3-6.9 ms), guard
validation (5.9-6.2 ms), and CAS restore (3.4-21.9 ms, writeback dependent). Shell-batch workflow
was 45.0-57.7 ms; there is no in-process batch mode.

**Raw:** `benchmarks/results/phase3c/latency.json`.

## E-3C-02 — repeated 1-64 candidate scaling and lazy decode

**Result:** three fresh-cache sessions per bound. Newest-hit medians were 11.5, 12.6, 11.3, 12.2,
12.3, 13.5 and 14.5 ms for 1, 2, 4, 8, 16, 32 and 64 candidates. Oldest-target medians were 6.3,
12.2, 14.6, 21.0, 25.1, 42.3 and 82.2 ms; misses were 16.8-77.2 ms. At 64, an oldest hit is more
expensive than a miss. Lazy `CandidateBytes` decoding is used in the `always` path; full guards
remain mandatory and non-always admission still decodes the full set.

**Raw:** `benchmarks/results/phase3c/candidate-scaling.json`.

## E-3C-03 — `/dev/null` inherited seek

**Result:** exact-path `/dev/null` `lseek` is constant-zero and now admitted; arbitrary inherited
character devices and directory seeks remain refused. `dev_null_seek_is_reusable` passes. Census
remains 9 attempted, 0 reused, 9 refused; `lseek` is no longer in the unmodeled ranking.

**Raw:** `benchmarks/results/phase3c/census-native/`.

## E-3C-04 — output restoration unchanged-file branch

**Result:** not implemented. Restore is 3.4 ms in the clean session and 21.9 ms under a writeback
tail. Skipping a matching output would change inode/ctime/ownership and hard-link semantics; a
managed contract and crash journal are prerequisites.

## E-3F-01 — inherited `/dev/null` read identity

**Question:** Did the read path admit `/dev/null` by pathname without proving the open object?

**Result:** yes. `read`, `pread64` and `readv` now require `is_null_device_fd(pid, fd)`; otherwise the
regular-file offset-stream model applies or reuse is refused. Commit `bb29414`; tests cover actual
null reads, `dup2` alias, regular stdin, changed identity and an uninspectable descriptor. Local gates:
135 workspace tests, 48 Linux integration tests, fmt, Clippy, release. Bind mount unavailable.

## E-3F-02 — exact CPython build and call-site inventory

**Build:** CPython 3.12.3, `/usr/bin/python3.12`, ELF build ID
`337d65cf00021797985cc9f77c0cc334a9fbeb38`, SHA-256
`e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f`.

**Observed:** one process; `getpid`/`getppid` during libc startup; three `getrandom` calls (8, 8 and
24 bytes; the 24-byte call at `Py_InitializeFromConfig+0x198`); `gettid` at
`_PyThreadState_Bind`; no visible `clock_gettime` syscalls because CPython uses the vDSO. No
controlled contract was enabled; three competing hypotheses and their counterexamples are recorded in
the Phase 3F audit.

## E-3F-03 — Phase 3F native census

**Result:** 9 attempted, 0 reused, 9 refused, 0 workload failures, 0 missing tools; every output
equivalence check passed. Blockers: clock 4 workloads, randomness 4, process identity 3,
`getrusage` 2, scheduling-dependent pipe reads 2, `ioctl`/failed fd 1, unmodeled `epoll_create1` 1,
unrestorable `/dev/null` output 1. Raw: `benchmarks/results/phase3f/census-native/`.


## E-3G-01 — independently inherited descriptor cache hit

**Question:** Can an fd above stderr change identity between recording and replay without changing
the lookup key?

**Result:** yes. With fd 9 inherited from `/dev/null`, the first run was `Executed`/`Guarded`; with
the identical command and fd 9 from `/dev/zero`, a regular file or a pipe, the second run was
`Reused` with cached `EOF`. A closed fd 9 also reused `EOF` instead of the direct `ERR`/exit 3.
The child was confirmed to inherit fd 9 and it was not `CLOEXEC`-closed. Fixture:
`tests/fixtures/fixture_driver.c::inherited_fd9_read`.

## E-3G-02 — inherited-descriptor preflight hotfix

**Result:** any surviving descriptor above stderr is captured before `Cache::open`; the cache is then
initialized, and the invocation is sent to the direct path before candidate lookup with the reason
`inherited descriptor N beyond stdin is not modelled; reuse refused`. `FD_CLOEXEC` descriptors are
skipped. No candidate is decoded and no reusable record is written. Trace retains an `Unknown` effect for the
same descriptors. Regressions cover `/dev/zero`, regular file, pipe, closed fd, two concurrent
replacements, a close-on-exec fd that must not block reuse, and the existing stdin-seek model (where
an externally inherited fd-3 alias is now refused). Local gates: **138 workspace tests**, **51 Linux
integration tests**, fmt, Clippy, release SHA-256
`cd51fe6e903adc8b6f85cbcf7917b3d915edadbd9018bbf89febaa0c22045402`.

**Hosted CI:** run `43301867797` failed in Tests before the test-harness descriptor cleanup; run
`43302318004` passed Tests, Clippy, Linux integration and release build but failed Demo because the
preflight counted the shell's close-on-exec script descriptor. Commit `ee32d6e` skips `FD_CLOEXEC`
descriptors. The demo also needed a clean environment identity (`b78726b`): its `_` variable changed
between the two runs. Hosted run `43304278963` passed every step at `b78726b`, and `main` was
fast-forwarded to it.

## E-3G-03 — CPython `PYTHONHASHSEED` differential

**Build:** CPython 3.12.3, ELF build ID `337d65cf00021797985cc9f77c0cc334a9fbeb38`, SHA-256
`e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f`.

**Result:** `python-csv-json` with `PYTHONHASHSEED` unset, `0`, or `1` was `Nondeterministic` and
`Ineligible` on both runs. Direct and traced outputs were byte-identical
(`28bc8fa9e7c25a10aa121654b5df07381a78fd5d45873ef077c4132cf51054e8`). Unset traces had two
`getrandom` calls (8 and 24 bytes); `PYTHONHASHSEED=0` had only the 8-byte call. Clocks and `gettid`
remained in all arms. Raw: `benchmarks/results/phase3g/python-differential.json` and
`python-strace-*.strace`.

## E-3G-04 — allocator contract plus fixed Python hash seed

**Result:** with `--contract allocator-entropy-v1`, the 8-byte glibc probe is controlled. With
`PYTHONHASHSEED=0`, the controlled report no longer lists randomness; monotonic clock, realtime clock
and `gettid` remain and the workload is still `Nondeterministic`/`Ineligible`. With `PYTHONHASHSEED`
unset, the uncontrolled 24-byte hash-secret call leaves a randomness blocker. No reuse occurred.
Raw: `benchmarks/results/phase3g/python-controlled-differential.json`.

## E-3G-05 — CPython 3.12.3 call-site study

**Result:** `Python/bootstrap_hash.c::_Py_HashRandomization_Init` requests the 24-byte
`_Py_HashSecret_t` from `pyurandom` when `use_hash_seed == 0`; `Python/initconfig.c` parses
`PYTHONHASHSEED` and maps `0` to a zeroed secret. `Python/pystate.c::bind_tstate` calls
`PyThread_get_thread_native_id`, implemented as `syscall(SYS_gettid)` in
`Python/thread_pthread.h`. `Python/pytime.c` implements the system and monotonic clocks through
`clock_gettime`/`gettimeofday`; TraceJIT sees them only after disarming the vDSO. The Phase 3F
attribution of the 24-byte call to `_PyTime_AsNanoseconds` is corrected.

## E-3G-06 — PR retention decision

**Result:** do not merge PR #6 (Phase 3D retrieval) or PR #7 (stacked epoll prototype). Preserve
`phase3d/compatibility-retrieval` and `phase3e/epoll-and-effect-frontier` plus their audit evidence.
Lift only the independent SQLite error-propagation fix if desired. Recommend closing both PRs; no
authenticated PR API session is available here.

## E-3H-01 — `/proc/self/fd` enumeration failure paths

**Question:** Can `readdir()` failure be mistaken for an empty inherited-descriptor table?

**Result:** yes in the old loop, which treated every `NULL` as EOF without checking `errno`. The
guard now returns `Result<Option<i32>, GuardError>` and fails closed for `opendir`, `dirfd`,
`readdir`, `fcntl(F_GETFD)` and `closedir`. Seven unit tests cover first-entry, after-entry,
`fcntl`, `dirfd`, `closedir`, CLOEXEC and complete scans. The Linux integration test
`descriptor_enumeration_failure_is_fail_closed` uses an `LD_PRELOAD` shim to fail the real
`/proc/self/fd` `readdir` before and after one entry; the invocation is non-successful and reports no
`HIT` or `MISS`. The preflight-to-`exec` race remains open and is documented, not claimed fixed.

**Raw:** `crates/tracejit-guards/src/lib.rs`, `crates/tracejit-cli/tests/linux_integration.rs`.

## E-3H-02 — descriptor-number reuse during directory enumeration

**Question:** Does closing a directory and reusing its descriptor number append a second stream to
the first enumeration record?

**Result:** yes. `ProcessState.enumerations` was keyed by fd and was not cleared on `close`, `dup`,
`open`, `pipe` or socket creation, so a guard could replay a concatenation that no single open file
description produced. A `forget_descriptor` helper now clears the fd state, CLOEXEC bit and
enumeration record together; unit test
`reusing_a_descriptor_forgets_its_directory_enumeration` covers it. This was found by the controlled
Python run, whose target then exposed a separate byte-padding difference (E-3H-03).

**Raw:** `crates/tracejit-trace/src/linux.rs`.

## E-3H-03 — controlled CPython target rejection

**Question:** Does the experimental Python-runtime watchpoint produce a `python-csv-json` hit?

**Result:** no. With exact CPython 3.12.3, `PYTHONHASHSEED=0` and
`tracejit.python-runtime.v1`, the first run is `Guarded`/`Executed` and the second is
`Guarded`/`Deoptimized`. The failing guard is `DirectoryEnumerated`: recorded `linux_dirent64`
padding after `.` was `sl.` and the fresh replay returned zeroes. Names, order, inode and offsets
were equal. The target output remained byte-identical
(`28bc8fa9...`). Canonicalising padding was rejected because a program can read the whole returned
buffer; a reader call-site proof is required first. Native census remains 9 attempted, 0 reused,
9 refused.

**Raw:** `benchmarks/results/phase3h/python-observations.json`.

## E-3H-04 — CPython clock and `gettid` call-site provenance

**Question:** Can a startup-only clock or identity exemption be justified from syscall class alone?

**Result:** no. `Python/pytime.c::py_get_system_clock` (line 919) and
`py_get_monotonic_clock` (1150) use `clock_gettime`; the application APIs in
`Modules/timemodule.c` (151, 168, 1179, 1194) reach the same effects. Plain `strace` sees no clock
syscalls because CPython uses the vDSO, while TraceJIT records both classes after disarming it.
`Python/pystate.c::bind_tstate` (241) stores `PyThread_get_thread_native_id` (257), implemented as
`syscall(SYS_gettid)` in `Python/thread_pthread.h` (328/337). The syscall is application-visible via
`threading.get_native_id`. The `LD_PRELOAD` prototype can replace symbol clocks and `getpid`, but not
`gettid`, so symbol-level identity virtualisation is insufficient.

**Raw:** `benchmarks/results/phase3h/strace/`.

## E-3H-05 — controlled Python smoke and invalidation

**Question:** Do the experimental watchpoints work when the program does not enumerate a directory or
print nondeterministic values?

**Result:** yes for the smoke mechanism, but it is not a target-workload or performance claim.
`python -S smoke.py` is `Reused` 10/10 after a cold `Executed`; cached stdout equals direct stdout.
Changing the script deoptimizes and the traced output equals the new direct stdout. Measured wall:
direct roughly 11-16 ms, cold 88-105 ms, warm 32-35 ms; the controlled path is slower on this tiny
script. The target workload has no hit.

**Raw:** `benchmarks/results/phase3h/contract-smoke.json`.

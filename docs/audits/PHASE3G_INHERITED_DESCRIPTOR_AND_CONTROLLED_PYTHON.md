# Phase 3G — independent inherited descriptors and the controlled CPython frontier

Date: 12 November 2026

Status: P0 fixed on `hotfix/inherited-descriptors`; P1 PRs remain open and are recommended for
closure; P2 has controlled differential evidence but no reusable Python execution; native census
remains **9 attempted, 0 reused, 9 refused** and is not changed by this phase.

## 1. P0 — inherited descriptor beyond stdin

### 1.1 Confirmed defect

`current_runtime_identity()` identified stdin (fd 0) but did not identify independently inherited
descriptors above stderr. `initial_descriptor_table()` did discover those descriptors, and the read
path could treat a verified `/dev/null` read as process-internal. The cache lookup key therefore did
not distinguish these executions:

| Command state | Direct child behavior | TraceJIT before the fix |
| --- | --- | --- |
| fd 9 inherited from `/dev/null` | read returns EOF | first run `Executed` / `Guarded` |
| fd 9 inherited from `/dev/zero` | read returns data | second run `Reused` with cached `EOF` |
| fd 9 inherited from a regular file | read returns file data | `Reused` with cached `EOF` |
| fd 9 inherited from a pipe | read returns pipe bytes | `Reused` with cached `EOF` |
| fd 9 closed | read fails with `EBADF`; fixture prints `ERR` and exits 3 | `Reused` with cached `EOF` and exit 0 |

The probe fixture is `tests/fixtures/fixture_driver.c::inherited_fd9_read`. It performs only
`read(9, ...)` and reports `EOF`, `DATA` or `ERR`. A direct child execution confirmed that fd 9 was
really inherited and readable; it was not closed by `CLOEXEC`. The `Reused` report was therefore an
incorrect cache hit, not a display-only problem.

The defect is broader than `/dev/null`: the runtime identity had no representation of the inherited
descriptor number, object identity, offset, flags, or shared open-description state for any fd above
2. The child can observe all of them.

### 1.2 Attempted identity field was too broad

The first patch added `inherited_descriptor_beyond_stdin: bool` to `RuntimeIdentity` and pushed an
`Unknown` effect for every fd above 2. It failed **32 of 49** Linux integration tests: ordinary
TraceJIT invocations inherited descriptors opened by the test harness or cache, so every recorded
identity said `true` while a fresh expectation said `false`. The field also made the identity a
function of internal TraceJIT descriptors, which is not a stable lookup property. That patch was not
committed.

This demonstrated the central design constraint: a boolean over the process descriptor table is
both over-broad and unstable. A correct identity would need a stable representation of every
external descriptor plus its offset and shared-description state, and would have to distinguish
parent-inherited descriptors from internal aliases.

### 1.3 Chosen correction: entry preflight refusal

`PreparedExecution::new` captures the first descriptor above stderr before `Cache::open` and before
any cache lookup. `run` checks that captured value immediately after constructing the lookup key:

```rust
if let Some(fd) = prepared.inherited_descriptor {
    let reason = format!(
        "inherited descriptor {fd} beyond stdin is not modelled; reuse refused"
    );
    return run_direct(&prepared, &cache, lookup_key, &reason, options.contract);
}
```

`run_direct` performs ordinary execution, passes through streams and status, and does not use or
write a reusable record. No cache candidate is decoded and no trace record is produced for that
invocation. The trace layer still pushes an `Unknown` effect for every inherited fd above 2 as a
second line of defence if another trace path reaches it.

The descriptor detector enumerates `/proc/self/fd`, excludes the `opendir` handle through `dirfd`,
and returns the first fd greater than 2. Enumeration failure returns `-1`, which the caller treats as
unmodelled and refuses. A `CLOEXEC` descriptor that cannot reach the child also causes a refusal;
that is conservative but loses a valid reuse opportunity. No unsafe or unstable descriptor metadata
was added to the cache identity.

### 1.4 Comprehensive identity model versus refusal

| Obligation | Full descriptor-identity model | Entry refusal (chosen) |
| --- | --- | --- |
| Identity of each inherited fd | Must record type, device/inode, path, flags, descriptor number | Not needed; any fd > 2 is refused |
| Offset and shared open description | Must record and guard current position, aliases and fork/exec sharing | Not needed; execution is not cached |
| Concurrent replacement | Must re-check identity immediately before every read and at replay | No cached result exists |
| Stable lookup key | Gains a potentially large, process-specific table | Unchanged; no extra key data |
| Valid reuse of externally supplied descriptors | Possible in principle | Lost; conservative |
| Smallest sound change | Large model, new guards, new tests | One preflight and one direct-execution path |

The project deliberately chose refusal for Phase 3G. A full model is a separate design with its own
fork/exec, `SCM_RIGHTS`, `fcntl` duplication, offset-sharing and concurrency obligations. Refusing
unmodelled descriptors is the smallest correction that makes the demonstrated exploit unreachable.

Internal `dup2` aliases created **inside** the traced process are unaffected: the preflight only
inspects descriptors inherited by the TraceJIT process before the target starts. The existing
inherited-stdin alias model remains guarded. An alias deliberately inherited across `exec` (the test
shell creates fd 3 from fd 0) is now refused at entry rather than analysed as an internal alias.

### 1.5 Regressions

- `inherited_descriptor_beyond_stdin_is_never_reused`: baseline fd 9 `/dev/null` twice; then
  `/dev/zero`, a regular file, a pipe, and a closed descriptor. Each traced run must be non-`Reused`,
  name descriptor 9 in the refusal reason, and match direct stdout and exit status.
- `concurrent_inherited_descriptor_replacements_are_refused`: two independent fixtures run fd 9
  `/dev/null` and `/dev/zero` concurrently; both produce their native bytes and neither reuses.
- `inherited_stdin_seek_model_reproduces_offsets_and_refuses_unsound_cases`: updated so an
  externally inherited fd-3 alias is expected to be refused at entry, while the fd-0 seek model
  remains tested.
- `dev_null_read_family_is_reusable`, regular-stdin and existing null-read tests remain green.

The test harness now closes descriptors above stderr before every TraceJIT launch, keeps the
stdin source descriptor with `CLOEXEC`, and keeps the fd-9 source only until `dup2`. This makes the
integration suite exercise the product, not descriptors opened by the local or hosted test runner.

### 1.6 Gates

Local, at hotfix commits `e099abd` plus the test-harness cleanup `b3c5e1f`:

- `cargo fmt --all -- --check`: pass
- `cargo clippy --workspace --all-targets -- -D warnings`: pass
- `cargo test --workspace`: **137 passed**, including **50 Linux integration tests**
- `cargo build --release --workspace`: pass; release SHA-256
  `00acc5e24e24b8a4b787eaff4425069fda05de0932c61647ab5c5237790b0f16`
- `PROVEN` remains a local SKIP because this host has no Landlock; hosted CI is the enforcement
  evidence.

Hosted CI run `43301867797` on `e099abd` failed in the Tests step. Unauthenticated GitHub API access
cannot download job logs; the local suite passed at the same commit, and the likely difference was
runner-opened descriptors. The test-harness cleanup commit `b3c5e1f` closes that gap. Its run
`43302318004` is the authoritative hosted gate; do not fast-forward `main` until it succeeds.

## 2. P1 — PR review

PR #6 (`phase3d/compatibility-retrieval`) and PR #7 (`phase3e/epoll-and-effect-frontier`) are still
open drafts and were not merged. Their branches and evidence are preserved.

- **PR #6:** do not merge. The retrieval prototype adds SQLite round trips and candidate-fetch
  machinery for a narrow newest-hit improvement; the oldest target worsened at four of seven
  bounds. The independently useful part is the SQLite error-propagation fix (do not suppress errors
  with `.ok()`), which can be lifted without the retrieval design. Phase 3D's extra round trips are
  not retained merely to preserve the experiment.
- **PR #7:** do not merge while stacked on PR #6. The create/dup/close subset passes, but the PR has
  no fork/exec inheritance, `CLOEXEC` and non-`CLOEXEC`, `RLIMIT_NOFILE`/`EMFILE`, `fcntl` or
  `SCM_RIGHTS` transfer, stale descriptor-number, or error-path regressions. Recreate a clean epoll
  change on `main` only after those tests exist.
- The Phase 3D and 3E findings are archived in `docs/audits/PHASE3F_CORRECTNESS_AND_CONTROLLED_PYTHON.md`
  and remain in the branches. There is no authenticated GitHub PR API session in this workspace, so
  this document recommends closure but cannot perform it.

## 3. P2 — controlled CPython research

### 3.1 Exact interpreter identity

| Property | Value |
| --- | --- |
| Interpreter | CPython 3.12.3, built 31 August 2026 with GCC 13.3.0 |
| Executable | `/usr/bin/python3.12` |
| ELF build ID | `337d65cf00021797985cc9f77c0cc334a9fbeb38` |
| SHA-256 | `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f` |
| Host libc | glibc 2.39, build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` |
| Host | Linux 6.1.102 x86_64 |

The launcher `/usr/local/bin/python3` is a shell script; all identities below are for the resolved
ELF, not the launcher.

### 3.2 Observed call sites and source attribution

Direct `strace -f -k` on `benchmarks/realworld/workloads/etl.py`:

| Observation | Unset `PYTHONHASHSEED` | `PYTHONHASHSEED=0` | Source evidence |
| --- | --- | --- | --- |
| `getrandom(8, GRND_NONBLOCK)` | one | one | libc `malloc` while `PyThread_allocate_lock` initializes runtime locks; glibc allocator/guard entropy, not CPython application entropy |
| `getrandom(24, GRND_NONBLOCK)` | one | **absent** | `Python/bootstrap_hash.c::_Py_HashRandomization_Init` requests `sizeof(_Py_HashSecret_t)` bytes when `use_hash_seed == 0` |
| `gettid` | one | one | `Python/pystate.c::bind_tstate` calls `PyThread_get_thread_native_id`; `Python/thread_pthread.h` uses `syscall(SYS_gettid)` on Linux |
| `clock_gettime` | no visible syscall | no visible syscall | `Python/pytime.c::_PyTime_GetSystemClock` and `_PyTime_GetMonotonicClock` use `clock_gettime`; TraceJIT disarms the vDSO and reports both clocks, while plain `strace` sees none |
| `getpid`/`getppid` | not observed in this direct run | not observed | Phase 3F saw libc startup calls with a different invocation; not relied on here |

**Correction to Phase 3F:** the earlier audit attributed the 24-byte `getrandom` to
`_PyTime_AsNanoseconds`/`Py_InitializeFromConfig+0x198`. The 3.12.3 source shows
`_PyTime_AsNanoseconds` is a pure integer conversion and makes no entropy call. The 24-byte size and
the disappearance under `PYTHONHASHSEED=0` identify the hash secret in
`_Py_HashRandomization_Init`; the earlier stack attribution was unreliable, likely because the
stripped build and unwinder mislabeled the frame. Treat the size plus the controlled experiment as
stronger evidence than the single unwound symbol.

### 3.3 Differential results

Raw: [`python-differential.json`](../../benchmarks/results/phase3g/python-differential.json),
[`python-controlled-differential.json`](../../benchmarks/results/phase3g/python-controlled-differential.json),
and the two `python-strace-*.strace` files.

The workload is `python-csv-json` (400 sales rows, 12 customers, standard library only). Direct and
traced outputs were byte-identical in every arm; direct output SHA-256 was
`28bc8fa9e7c25a10aa121654b5df07381a78fd5d45873ef077c4132cf51054e8`.

| Environment | Contract | First run | Second run | Reported blockers |
| --- | --- | --- | --- | --- |
| unset | none | `Nondeterministic`, `Ineligible` | `Nondeterministic`, `Ineligible` | randomness, monotonic clock, `gettid`, realtime clock |
| `PYTHONHASHSEED=0` | none | same | same | randomness, monotonic clock, `gettid`, realtime clock |
| `PYTHONHASHSEED=1` | none | same | same | same |
| unset | `allocator-entropy-v1` | same, 183 dependencies | same | randomness, monotonic clock, `gettid`, realtime clock, contract note |
| `PYTHONHASHSEED=0` | `allocator-entropy-v1` | same, 183 dependencies | same | **randomness absent**; monotonic clock, `gettid`, realtime clock remain |

The controlled contract fixes the audited 8-byte glibc allocator probe. With the hash secret also
fixed by `PYTHONHASHSEED=0`, no randomness reason remains, but the workload still cannot reuse
because clocks and process identity are ordinary effects. With `PYTHONHASHSEED` unset, the 24-byte
hash-secret call is uncontrolled even under the allocator contract, so randomness remains.

`PYTHONHASHSEED=0` changes Python's hash randomization semantics. It happened not to change this
workload's bytes because the workload sorts its output and does not expose set/dict iteration order.
That is an observation about this script, not a proof of application-visible equivalence. A workload
that emits a set or dict ordering can change output under a fixed seed.

### 3.4 Ten-part research graph

1. **CPython startup randomness:** the 24-byte hash secret is process-startup state; `PYTHONHASHSEED=0`
   replaces it with zero bytes and removes the call.
2. **Hash-seed initialization:** `config_init_hash_seed` parses the environment in
   `Python/initconfig.c`; `_Py_HashRandomization_Init` either memsets, uses an LCG, or asks the OS
   for 24 bytes.
3. **Glibc allocator entropy:** the 8-byte nonblocking probe comes from libc's allocator/runtime
   initialization, remains under `PYTHONHASHSEED=0`, and is the exact site audited by
   `allocator-entropy-v1`.
4. **Realtime and monotonic clocks:** CPython uses `_PyTime_GetSystemClock` and
   `_PyTime_GetMonotonicClock`; both are observed after TraceJIT redirects vDSO reads.
5. **vDSO time access:** a normal `strace` sees no clock syscall, so syscall-only accounting is
   incomplete. TraceJIT's vDSO disarming is what makes the observation visible; failure to disarm
   refuses reuse.
6. **Process and thread identity:** `bind_tstate` stores `PyThread_get_thread_native_id`, which is
   `gettid` on Linux. `getpid`/`getppid` can also appear during libc startup depending on the launch.
7. **Runtime call-site provenance:** the current allocator profile binds the exact glibc build ID,
   instruction offset, destination offset and instruction signature. No equivalent CPython profile
   exists for the 24-byte hash-secret site.
8. **Application-visible nondeterminism:** hash seed, clock reads and pid/tid can steer branch or
   output decisions. Repeated identical output across a few runs is not causal noninterference.
9. **Explicit controlled execution contracts:** a CPython contract would have to bind exact
   interpreter and shared-library identities, enumerate admitted call sites, and state the semantic
   changes (fixed hash seed, virtual clocks, virtual pid/tid).
10. **Complete effect verification:** clocks, `gettid`, hash secret, allocator entropy, filesystem,
    descriptors, output and process effects must all be captured or refused. This phase satisfies
    none of the complete-effect gates for a Python hit.

### 3.5 Competing branches

**A. Audited runtime initialization.** The existing contract machinery can identify the exact
8-byte glibc call site and fix it. It cannot identify the 24-byte CPython site because there is no
CPython `AllocatorEntropyProfile`; adding one would be version-specific and would still leave clocks
and `gettid`. Status: **partial evidence, no CPython contract enabled**.

**B. Fixed Python hash-seed configuration.** `PYTHONHASHSEED=0` removes the 24-byte observation and
does not alter this workload's bytes. It does not remove the allocator probe, clock reads or
`gettid`, and it deliberately changes hash randomization for every Python object. Status:
**measured, unsound as a general cache contract without an explicit versioned contract and output
equivalence argument**.

**C. Virtualized clocks and process identity.** A single-process opt-in contract could return
monotonic values that advance consistently with sleeps/timeouts and a fixed pid/tid. It must cover
`time`, `monotonic`, `perf_counter`, `process_time`, `clock_gettime`, `gettimeofday`, vDSO entry
points, `os.getpid`, `os.getppid`, `threading.get_native_id`, signals, subprocesses and extension
modules. None of that is implemented. A fake clock that does not advance can change liveness; a
fixed pid can change lock-file or cache naming. Status: **design obligation only**.

**D. Causal noninterference.** The claim would be that an observed clock or pid cannot affect the
final externally visible effects. Repeated identical output does not prove it: a program can read a
clock only on a rare branch, read a pid into a file name, or use a timeout whose outcome depends on
scheduling. A proof needs a complete effect and control-flow argument. Status: **rejected as a
shortcut; retained as a research question**.

No combination of these branches meets the Phase 3G acceptance criteria. The controlled experiment
is a milestone in **observability**, not a controlled cache hit.

### 3.6 Acceptance checklist

| Criterion | Status |
| --- | --- |
| Pin exact interpreter and shared-library identities | Partial: CPython and glibc hashes/build IDs recorded |
| Audit every intercepted observation and admitted call-site class | Partial: allocator site audited; hash-secret and clocks are not admitted |
| Verify complete filesystem, descriptor, output and process effects | Not established for Python |
| Refuse unsupported threads, subprocesses, extensions, syscalls, hardware observations | Current native refusal is conservative; no Python contract |
| Keep native and controlled namespaces separate | Contract ID is in the lookup key; no Python controlled records exist |
| Multiple independent controlled cold executions | Two per arm, but no reusable record |
| Counterexample and fault-injection tests | Not written for Python |
| Second controlled execution reuses without incorrect effects | Not achieved |
| Complete-session runtime compared with direct execution | Not measured; no hit |

## 4. Outcome and next actions

1. Wait for and report hosted CI run `43302318004`; fast-forward `main` only if it succeeds. Do not
   merge PR #6 or PR #7; archive their findings and recommend closure.
2. Keep entry refusal for inherited descriptors above stderr. Revisit a full descriptor identity
   only with explicit offset/shared-description/fork/exec and concurrent-replacement tests.
3. Do not add a CPython hash-secret exception on the strength of `PYTHONHASHSEED=0` alone. Any
   versioned CPython contract must bind the exact ELF and call site, pass multiple cold runs, and
   refuse application-visible hash ordering unless the contract states the semantic change.
4. Clocks and `gettid` remain the next causal blockers for `python-csv-json`; they need a real
   controlled execution model, not another syscall allowlist entry.
5. Keep the native nine-workload census unchanged and report native and controlled reuse separately.

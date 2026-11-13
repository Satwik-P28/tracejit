# Phase 3H — descriptor preflight hardening and controlled CPython

Date: 13 November 2026

Status: P0 descriptor failure paths are fail-closed and tested; a descriptor-number reuse defect in
directory enumeration was found and fixed. The experimental `tracejit.python-runtime.v1` contract
reuses a controlled smoke script but **does not** reuse `python-csv-json`: the target deoptimizes on
a directory-entry stream difference. Experimental Python-runtime code is on a review branch and is
not merged. The native nine-workload census is unchanged and reported separately.

Base: `e474b544c7351278be55a180479c67b02bc4ea70` (`main`). P0 fail-closed fix: `fc7feef`;
P0 descriptor-lifecycle follow-up: `e2a2f60` on `hotfix/descriptor-enumeration-p0`. Experimental
contract code: `c81fa1e`; research evidence/docs on `research/phase3h`; the evidence commit is `44a1936` and the contract commit is `c81fa1e`.

## 1. P0 — can an incomplete `/proc/self/fd` enumeration look empty?

### 1.1 Defect

`inherited_descriptor_beyond_stdin()` used the usual `readdir()` loop:

```text
while (entry = readdir(directory)) != NULL:
    inspect entry
# treat NULL as end of directory
```

POSIX and Linux allow `readdir()` to return `NULL` both at end-of-directory and on error, with
`errno` distinguishing them. The old loop did not clear or inspect `errno`. An `EINTR`, `EIO` or
allocation failure in libc could therefore make an incomplete table look empty, which would let an
execution with an inherited descriptor proceed to cache lookup. That is a fail-open path, although no
exploit was demonstrated: the fault injection below shows the old behavior only through a shim, and
the remaining preflight-to-`exec` race is still open.

### 1.2 Smallest sound correction

The guard now returns an explicit result:

```rust
pub fn inherited_descriptor_beyond_stdin() -> Result<Option<i32>, GuardError>
```

`GuardError::DescriptorEnumeration` carries the operation, path and OS error. The scan:

- sets `errno = 0` before every `readdir()`;
- distinguishes `NULL` with `errno == 0` (complete end) from `NULL` with a nonzero errno (failure);
- treats `opendir`, `dirfd`, `readdir`, `fcntl(F_GETFD)` and `closedir` failures as errors;
- closes the directory on every exit path, including failures;
- skips `FD_CLOEXEC` descriptors rather than refusing them; the kernel closes those before the
  target executes.

`tracejit-core` propagates the error with `?`. A refusal occurs after cache initialization but
**before** candidate lookup or record write. The descriptor scan itself occurs before `Cache::open`.
This corrects the Phase 3G wording: CLOEXEC is skipped, not refused, and cache initialization does
precede the refusal.

The trace layer's `initial_descriptor_table()` also changed from silently modelling only stdio to
`io::Result<HashMap<i32, FdState>>`; an entry error or failed `/proc` inspection now fails the trace
instead of producing a partial table.

### 1.3 Fault injection

`crates/tracejit-guards/src/lib.rs` has a `DescriptorDirectory` abstraction so the scan can be
tested without a real failing `/proc`. `LinuxDescriptorDirectory` is the production implementation.
Seven unit tests cover:

- failure before the first entry;
- failure after one entry;
- `fcntl(F_GETFD)` failure;
- `closedir` failure;
- `dirfd` failure;
- CLOEXEC filtering;
- a complete scan.

The Linux integration test `descriptor_enumeration_failure_is_fail_closed` uses an `LD_PRELOAD`
shim that intercepts the real `/proc/self/fd` `readdir()` and fails before, or after, one entry. It
asserts that the invocation is not successful and that no `HIT` or `MISS` is reported. This is a
controlled library fault, not a kernel or exploit reproduction.

### 1.4 Remaining preflight-to-exec race

The preflight captures one value, not a stable descriptor table. Between the scan and `execve`, the
parent or another process can close an already-inherited descriptor or arrange a new one. The child
that finally executes can therefore differ from the table the preflight observed. Closing that
window needs an atomic handoff: for example, a helper that performs the scan and `execve` without an
intervening user-space window, or a parent-side invariant that no thread can mutate the table.
Neither is implemented.

The risk is not reachable by the target program alone, because it has not run yet. It is a real
TOCTOU window against a concurrent parent and is a limitation of the refusal, not evidence that the
fault-injection fix is incomplete. No exploit is claimed.

### 1.5 Second defect found by the CPython experiment: descriptor-number reuse

The controlled Python trace exposed a directory-enumeration model bug. `ProcessState.enumerations`
was keyed by descriptor number and was removed on neither `close` nor descriptor reuse. If a program
closed a directory and the kernel reused that number for another directory, the second stream was
appended to the first effect record. The guard then replayed a concatenation that no single open
file description had produced. In the Python experiment this appeared as:

```text
directory entry stream changed
expected call 0: 48 bytes ...
actual        48 bytes ...
```

The raw bytes differed only in the padding after the NUL terminator of `.` (`sl.` versus zeroes).
That padding is **not** the lifecycle defect; it is a second, independent reason the target cannot
be reused soundly (Section 3.4). The lifecycle defect is still real and was fixed by a single
`forget_descriptor` helper used on `close`, `dup`, `dup2`, `open`, `pipe` and socket creation. It
clears the fd, CLOEXEC bit and enumeration record together. Unit test
`reusing_a_descriptor_forgets_its_directory_enumeration` checks all three.

## 2. P1 — CPython observations, one class at a time

### 2.1 Pinned identities

| Property | Value |
| --- | --- |
| Interpreter | CPython 3.12.3, `/usr/bin/python3.12` |
| ELF build ID | `337d65cf00021797985cc9f77c0cc334a9fbeb38` |
| SHA-256 | `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f` |
| glibc | 2.39, build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` |
| Host | Linux 6.1.102, x86_64 |

`/usr/local/bin/python3.12` is a launcher and is not the audited ELF. The harness records both
identity values in `benchmarks/results/phase3h/python-observations.json`.

### 2.2 Experiment A — audited startup clock reads

Source path:

| API | Caller | Actual clock operation | Destination | TraceJIT effect |
| --- | --- | --- | --- | --- |
| `time.time()` / `time.time_ns()` | `Modules/timemodule.c::time_time` (151), `time_time_ns` (168) | `get_system_time` → `_PyTime_GetSystemClockWithInfo` → `Python/pytime.c::py_get_system_clock`; `clock_gettime(CLOCK_REALTIME, &ts)` at 919 | stack `struct timespec ts`, then `_PyTime_t t`; Python float/int | `Clock(Realtime)` |
| `time.monotonic()` / `time.monotonic_ns()` | `timemodule.c::time_monotonic` (1179), `time_monotonic_ns` (1194) | `get_monotonic` → `_PyTime_GetMonotonicClockWithInfo` → `pytime.c::py_get_monotonic_clock`; `clock_gettime(CLOCK_MONOTONIC, &ts)` at 1150 | stack `struct timespec ts`, then `_PyTime_t` | `Clock(Monotonic)` |
| `time.perf_counter()` | `pytime.c` monotonic path | same `CLOCK_MONOTONIC` | stack / return value | `Clock(Monotonic)` |

The application call sites and the runtime startup call sites compile to the same syscall. Plain
`strace` sees **no** clock syscalls because CPython uses the vDSO. TraceJIT disarms the vDSO and
records 1 realtime and 13 monotonic observations in the target trace. The trace does not retain an
instruction pointer or caller for ordinary `Clock` effects, so it cannot tell a startup read from an
application read. Experiment A therefore has a negative result: **a startup-only clock whitelist
cannot be implemented from the current observation class**. It needs a call-site/instruction
signature, not a syscall whitelist. Counterexample: the same `Clock(Realtime)` effect is produced by
`time.time()` in `benchmarks/phase3h/probes.py clocks`, whose printed value changes on every run.

### 2.3 Experiment B — Python thread-state initialization and `gettid`

`Python/pystate.c::bind_tstate` (241) does:

```c
tstate->thread_id = PyThread_get_thread_ident();
#ifdef PY_HAVE_THREAD_NATIVE_ID
    tstate->native_thread_id = PyThread_get_thread_native_id();
#endif
```

`Python/thread_pthread.h::PyThread_get_thread_native_id` (328) uses
`native_id = syscall(SYS_gettid)` (337) on Linux. The syscall result is stored in the local
`pid_t native_id` and then in `tstate->native_thread_id` (257). `threading.get_native_id()` exposes
the same value to Python code, so it is application-visible, not merely an interpreter diagnostic.
The strace call-site evidence is in `benchmarks/results/phase3h/strace/identity.strace`; the stack
shows `PyThread_get_thread_native_id` below `_PyThreadState_Bind`/`PyInit__thread`.

`gettid` is not a libc symbol that `LD_PRELOAD` can replace in this code path: CPython invokes the
syscall instruction directly. The research prototype in `benchmarks/phase3h/virtualize.c` can
replace `clock_gettime`, `gettimeofday`, `time`, `getpid` and `getppid`, but `threading.get_native_id`
still reports the real tid in every mode:

```text
PHASE3H_VIRTUALIZE=clocks   time 1700000000392000000  pid <real>  tid <real>
PHASE3H_VIRTUALIZE=identity time <real>                pid 4242    tid <real>
PHASE3H_VIRTUALIZE=both     time 1700000000392000000  pid 4242    tid <real>
```

That is the counterexample to a symbol-level "fixed identity" claim. A sound contract must work at
the syscall boundary (the tracer's `PendingSyscall` path) or refuse.

### 2.4 Experiment C — a virtualized single-process clock/identity contract

The prototype fixes:

- `CLOCK_REALTIME`, `CLOCK_REALTIME_COARSE`, `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_COARSE` and
  `CLOCK_BOOTTIME` to a base value advanced by 1 ms per read;
- `gettimeofday` and `time` consistently with realtime;
- `getpid` to 4242 and `getppid` to 1.

It cannot fix `gettid`, `os.urandom`, or CPython's application-level `time.time()` consequences. A
program that writes the returned time, uses it as a lock/file name, or loops until a deadline can
change its output or liveness. The prototype is therefore **not** a contract: it is a way to show
which observations are symbol-replaceable and which are not. Raw outputs are in
`benchmarks/results/phase3h/python-observations.json` under `prototypes`.

### 2.5 What a program may not be assumed to ignore

The following are explicitly rejected as equivalence assumptions:

- `time.time()` / `time.time_ns()`: output, filenames, cache keys, branch selection, expiry;
- `time.monotonic()` / `time.monotonic_ns()` / `time.perf_counter()`: timeouts, polling, liveness;
- `threading.get_native_id()`: per-thread naming, logs, locks, hash tables;
- `os.getpid()` / `os.getppid()`: file names, locks, process-tree checks, output;
- `os.urandom()`: keys, nonces, salts, sampling, output bytes.

Repeated identical output across two native runs is not evidence that these values are dead. A rare
branch, a different clock boundary or a PID used only in an error path is a valid counterexample.

## 3. P2 — a versioned controlled contract, and its proof obligations

### 3.1 Implemented experimental watchpoints

A review-branch-only `tracejit.python-runtime.v1` contract was implemented for the pinned ELF. It:

- accepts only `/usr/bin/python3.12` with build ID `337d65cf...`;
- controls `clock_gettime(CLOCK_REALTIME|CLOCK_MONOTONIC)`, `gettimeofday`, the seconds-resolution
  `time()` syscall, `getpid`, `getppid` and `gettid` as explicit `ControlledRuntime` effects;
- records the executable hash and build ID in each effect and guard;
- rejects `clone`, `clone3`, `fork` and `vfork` as `Unknown` under the contract;
- leaves all other syscalls and effects on the ordinary path, so an unmodelled subprocess, signal,
  descriptor, extension or scheduler observation still makes the execution ineligible;
- keeps contract id `tracejit.python-runtime.v1` in the cache identity, so native and controlled
  records cannot mix.

The contract does **not** claim native equivalence. It returns fixed clock and identity values, and
those values can be observed by an application. The smoke script only prints a constant, so it is a
valid use of the watchpoints for that script, not a general Python contract.

### 3.2 Obligations status

| Obligation | Status |
| --- | --- |
| Exact executable and shared-library identity | Executable path, BLAKE3 hash and ELF build ID are recorded and guarded. The glibc allocator probe is guarded by the existing allocator call-site profile; the Python contract does not invent a second allocator rule. |
| Verified call-site and instruction signatures | **Not met** for ordinary clocks and `gettid`: effects carry no instruction pointer or caller. Source attribution exists, but per-instance signatures do not. |
| Consistent clock progression and ordering | **Not met**: fixed realtime/monotonic values do not advance. This is why the contract is labelled experimental and not merged. |
| Thread/process identity semantics | **Partial**: single-process/single-thread is enforced by refusing clone/fork; fixed pid/ppid/tid are not native values. |
| No unsupported subprocess, extension, signal, descriptor or scheduler effects | Partial: clone/fork are refused; ordinary unknown effects still reject the trace. No exhaustive proof. |
| Complete output and filesystem-effect comparison | **Partial**: the smoke test compares stdout, and the target output hash matches a direct run in every arm; no differential filesystem-effect suite yet. |
| Multiple independent controlled cold executions | One cold smoke run and the target first run; not yet a repeated cold campaign. |
| Explicit rejection of mismatched effect sequences | Directory-stream and other guard mismatches deoptimize; the target does exactly that. |
| Differential tests exposing time, randomness and PID values | Probes and prototype outputs do; the target workload does not print them. |

The contract is **not** eligible for a general cache-reuse claim until the unmet obligations are
satisfied. The target workload result below is a rejection, not a hit.

### 3.3 Target workload: `python-csv-json`

Raw: `benchmarks/results/phase3h/python-observations.json`. The workload is the original
`benchmarks/realworld/workloads/etl.py` with 400 sales rows and 12 customers, not a new simplified
benchmark. Direct output SHA-256 is
`28bc8fa9e7c25a10aa121654b5df07381a78fd5d45873ef077c4132cf51054e8` in all arms.

| Environment | Contract | First run | Second run | Target result |
| --- | --- | --- | --- | --- |
| `PYTHONHASHSEED` unset | none | `Nondeterministic` / `Ineligible` | same | refused; randomness, clocks, `gettid` |
| `PYTHONHASHSEED=0` | none | `Nondeterministic` / `Ineligible` | same | refused; clocks, `gettid` |
| `PYTHONHASHSEED=0` | `allocator-entropy-v1` | `Nondeterministic` / `Ineligible` | same | randomness gone; clocks and `gettid` remain |
| `PYTHONHASHSEED=0` | `python-runtime-v1` | `Guarded` / `Executed` | `Guarded` / **`Deoptimized`** | **no hit**; directory entry stream changed |

The Python contract removes the clock, `gettid` and randomness reasons. The second run matches the
candidate and then fails the `DirectoryEnumerated` guard. The difference is not an entry name or
order change: it is unspecified padding inside `linux_dirent64` records. One recorded record ends
with `.\\0sl.`; the fresh replay returns `.\\0\\0\\0\\0`. The kernel does not promise those padding
bytes, and a program can observe the whole returned buffer if it chooses. TraceJIT's byte-exact
directory model therefore fails closed. Canonicalising padding would turn a native-observable byte
difference into an assumed non-effect; that is not sound without a call-site proof that the reader
never examines padding. It was not done.

This is a **negative target result**. No `Reused` row exists for `python-csv-json`.

### 3.4 Controlled smoke hit, reported separately

`benchmarks/phase3h/contract_smoke.py` runs `python -S smoke.py` with a constant print. It exercises
the watchpoints without directory enumeration. Raw: `benchmarks/results/phase3h/contract-smoke.json`.

| Arm | Result |
| --- | --- |
| Direct (10 runs) | median 15.7 ms wall |
| Controlled cold | `Executed`; 104.8 ms wall |
| Controlled warm (10 runs) | 10/10 `Reused`; median 35.2 ms wall |
| Changed script | `Deoptimized`; traced stdout equals direct v2 stdout |

Cached stdout equals direct stdout (`dc5020c7...`) in the warm arm, and the changed script's traced
stdout equals its direct stdout (`c94a2569...`). This is a mechanism check only. It is slower than
direct execution on this tiny script, so it is not a performance claim. The target `python-csv-json`
has no hit.

## 4. P3 — native census and research

The original nine-workload native census was not replaced. The Phase 3H rerun in
`benchmarks/results/phase3h/census-native/` is **9 attempted, 0 reused, 9 refused**, 0 missing tools,
0 workload failures, with output equivalence on all nine. The blockers remain clock (4), randomness
(4), process identity (3), system information (1), shell/groff pipe scheduling and Pillow's
`epoll_create1`. The Phase 3H changes do
not add native eligibility; P0 refuses more explicitly, and the Python contract is not native.

No controlled target-workload hit exists, so no cold/warm/invalidated/full-session timing is reported
for `python-csv-json`. The smoke timing above is the only controlled timing and is explicitly
separate. The default path was not compared because there is no target hit to compare.

Research conclusions:

- CLOEXEC skipping and cache-before-refusal are now stated correctly; the descriptor preflight is
  fail-closed on enumeration errors.
- A syscall class is not a call-site identity. Startup clocks and application clocks share
  `Clock(Realtime)`/`Clock(Monotonic)` effects. `gettid` is a direct syscall in CPython, so
  `LD_PRELOAD` cannot reach it.
- Directory enumeration is a byte stream, not a list of names. Its ABI padding is observable to a
  program that reads the buffer, so byte-exact guarding deoptimizes when padding differs. A contract
  needs either a reader call-site proof or a narrower enumeration effect.
- The experimental contract is useful as a watchpoint prototype, but it does not satisfy the
  clock-progression, call-site and repeated-cold obligations. It remains unmerged.

## 5. Gates and reproduction

Local gates for the P0 commit and the follow-up descriptor-lifecycle fix are recorded after the final
run in `PROJECT_STATE.md`; the numbers in the initial commit are not reused as evidence for later
edits. Reproduce the controlled study with:

```bash
cargo build --release -p tracejit-cli
python3 benchmarks/phase3h/run.py
python3 benchmarks/phase3h/contract_smoke.py
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
```

`python-observations.json` contains direct/traced output hashes, report reasons, fault-injection
strace files and prototype outputs. `contract-smoke.json` contains the separate smoke timing and
invalidation. Neither file is a native census.

## 6. Unresolved

1. Close or bound the preflight-to-`exec` descriptor race.
2. Add per-instance call-site/instruction identity before any startup-only clock admission.
3. Decide whether directory-entry padding can be normalised soundly for an audited reader; until
   then, keep byte-exact refusal.
4. Run repeated independent controlled cold executions and a filesystem-effect differential before
   promoting any Python contract.
5. Do not merge the experimental Python-runtime branch merely because the smoke script hits.

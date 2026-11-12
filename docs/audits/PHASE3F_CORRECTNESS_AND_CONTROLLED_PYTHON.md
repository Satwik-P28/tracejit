# Phase 3F — null-read identity, PR review, and controlled CPython frontier

Date: 12 November 2026

Status: P0 fixed and locally verified on `hotfix/dev-null-read`; PR #6 and PR #7 reviewed but not
merged; no controlled CPython contract enabled; native census remains 0/9.

## 1. P0 — inherited `/dev/null` reads

### Defect

`crates/tracejit-trace/src/linux.rs` decoded `read`, `pread64`, and `readv` into the same
`PendingSyscall::Read` path. The inherited-descriptor branch admitted:

```rust
Some(FdState::InheritedFile(path)) if path == Path::new("/dev/null") => {}
```

The pathname is an observation made when the descriptor was classified, not proof that the open file
description still refers to Linux character device 1:3. A descriptor recorded as `/dev/null` could be
substituted before the read, or another object could be opened under that path. Treating a successful
read as process-internal then hides a real input effect and can produce a stale reuse.

### Fix

The read branch now requires `is_null_device_fd(pid, fd)`, the same `fstat` character-device check
already used by the inherited `lseek` path:

```rust
Some(FdState::InheritedFile(path))
    if path == Path::new("/dev/null") && is_null_device_fd(pid, fd) => {}
```

If the check fails, the branch falls through. A tracked regular stdin is still handled by the existing
guarded offset-stream model; any other inherited descriptor remains refused. There is no zero-length
read whitelist and no pathname-only exemption.

Commit: `bb294149cae8043aa19fad57de9e6b0c4c8392c3` on `hotfix/dev-null-read`, based directly on
`main` (`62425a9`), independent of the Phase 3D retrieval and Phase 3E epoll experiments.

### Regressions

Added fixture modes and Linux integration tests:

- `dev_null_read_family_is_reusable`: ordinary `read`, then `pread64` and `readv`, all against an
  explicitly opened `/dev/null`; both runs succeed and the second is a verified `Reused`.
- `dev_null_alias_read`: `dup2(0, 9)` then a read and close on descriptor 9; reuse is verified.
- `regular_file_stdin_read_uses_the_offset_stream_model`: a regular file on stdin takes the guarded
  offset-stream path and reuses.
- `changing_stdin_from_null_to_regular_is_not_reused`: the same cache key is not reused when the
  descriptor changes from `/dev/null` to a regular file.
- `null_device_identity_is_not_path_only`: an uninspectable descriptor number fails closed.

Attempted bind-mount substitution with `unshare -m`; this host returns `Operation not permitted`, so
there is no true mount-namespace replacement test. The changed-identity test is the available
adversarial substitute, not equivalent evidence.

### Gates

- `cargo fmt --all -- --check`: pass
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: pass
- `cargo test --workspace`: **135 tests**, all pass
- `cargo test -p tracejit-cli --test linux_integration -- --test-threads=1`: **48 tests**, all pass
- `cargo build --release --workspace`: pass; local release SHA-256
  `f82d8dde69eba77cd0e13bfd27304f73697b47551d0ff8bdbcdaeca896dbd3e8`
- Hosted CI run `43293187715`, job `131444490103`, succeeded in 2m38s on `bb29414`; one
  non-blocking warning remains in the check summary. `PROVEN` remains a local SKIP because this host
  has no Landlock; hosted CI is the enforcement evidence.

## 2. P1 — PR decisions

### PR #6 — Phase 3D incremental retrieval

Do **not** merge. Keep the branch as an experimental negative prototype.

The retrieval prototype adds SQLite round trips and candidate-fetch machinery, but the measured
benefit is narrow and not general: newest hits improved by roughly 0.6–3.4 ms, while the oldest target
got worse at four of seven candidate bounds; at 64 candidates the prototype was about 80.4 ms versus
82.2 ms. That is not enough to justify the extra query and cache surface in a correctness-first tree.
The review did find and fix a real error: automatic admission no longer uses `.ok()` to suppress
SQLite errors, pruned rows are misses, malformed records are skipped, and full guards still run.
That error-propagation fix is worth lifting independently; the retrieval design is not.

### PR #7 — Phase 3E epoll lifecycle

Do **not** merge while it is stacked on PR #6. The epoll change itself is deliberately narrow:
`epoll_create1` creates an `FdState::Epoll`, `CLOEXEC` is recorded, duplication and close are
process-internal, a failed create is refused, and reads from the instance are refused. `epoll_ctl`,
`epoll_wait`, registration, and readiness are not modeled and remain refused.

Review obligations still open:

- no fork-inheritance test, including `CLOEXEC` and non-`CLOEXEC` descriptors;
- no exec test proving close-on-exec behavior and no inherited-instance escape analysis;
- no `RLIMIT_NOFILE`/`EMFILE` test for failed creation;
- no test for descriptor transfer outside `dup`/`dup2` (for example `SCM_RIGHTS`) or `fcntl`-based
  duplication/flags;
- no test that a closed instance cannot be reused through a stale descriptor number;
- the PR still contains the Phase 3D retrieval base, so its diff is not reviewable as an independent
  epoll change until rebased onto `main`.

The create/dup/close tests that exist pass (`epoll_create1(EPOLL_CLOEXEC) = 3; close(3) = 0` for the
Pillow probe; `epoll_ctl` is correctly refused). That is evidence for the covered subset only. PR #7
cannot be retargeted to `main` until PR #6 is either integrated or abandoned; if PR #6 is abandoned,
the epoll commit should be recreated on a clean `main` branch rather than merged through the retrieval
stack.

## 3. P2 — exact CPython build and call-site inventory

### Exact build

| Property | Value |
| --- | --- |
| Interpreter | CPython 3.12.3, built 31 August 2026 with GCC 13.3.0 |
| Executable | `/usr/bin/python3.12` (`/opt/freestyle/python/bin/python3` is a symlink) |
| ELF build ID | `337d65cf00021797985cc9f77c0cc334a9fbeb38` |
| SHA-256 | `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f` |
| Host | Linux 6.1.102 x86_64, glibc 2.39 |
| Stripped | yes; dynamic symbols include `getrandom` and `clock_gettime` |

The launcher `/usr/local/bin/python3` is a 54-byte shell script that execs
`/opt/freestyle/python/bin/python3`; it is not the interpreter identity. Any controlled contract must
bind the resolved ELF build ID and hash above, not the launcher path.

### Observed call sites

`strace -f -k` on `benchmarks/realworld/workloads/etl.py` (one process) recorded:

| Observation | Count/shape | Caller evidence |
| --- | --- | --- |
| `getpid` | one | libc `__getpid+0xb` from `__libc_init_first+0x8a`, before Python initialization |
| `getppid` | one | libc `getppid+0xb` from libc startup |
| `getrandom` | 8 bytes, twice | libc `getrandom`/`malloc` paths during startup; not yet attributed to an application call |
| `getrandom` | 24 bytes | `_PyTime_AsNanoseconds+0xc4` → `Py_InitializeFromConfig+0x198`; runtime initialization |
| `gettid` | one | `PyThread_get_thread_native_id+0x21` → `_PyThreadState_Bind` → `Py_InitializeFromConfig+0x28b` |
| `clock_gettime` | zero syscalls visible | `strace` records no clock syscall for `time.time()`/`time.monotonic()`; CPython uses the vDSO |

The executable imports `clock_gettime` (GLIBC 2.17) and `getrandom` (GLIBC 2.25) dynamically. A
syscall-only audit is therefore incomplete: vDSO time reads are invisible unless the tracer forces
them through a real syscall (the existing mitigation) and the resulting call sites are audited too.

### Hypotheses

| Hypothesis | Smallest counterexample | Correctness obligation |
| --- | --- | --- |
| H-A: audited runtime-internal observations under a restricted contract | A script calls `time.time()` or `os.getpid()` after initialization and uses the value to choose its output | Bind exact ELF hash/build ID, audit every admitted call site, distinguish pre-`Py_Initialize` from application call sites, reject altered/interposed builds, and prove equivalent complete effects across multiple cold runs |
| H-B: virtualized single-process Python | A workload uses `time.monotonic()` for a timeout/sleep, or `os.urandom()` for a business decision; a fake clock changes liveness or bytes | Virtualize every clock, randomness source, pid/tid source, vDSO path, thread, signal, and C-extension direct syscall; preserve application-visible semantics, not just startup determinism |
| H-C: process-level causal dependency, conservatively refuse unverified observations | The current ETL workload: even with an audited seed, clock and `gettid` remain unverified | Complete observation and a proof that every effect is guarded; absent that, keep the command `NONDETERMINISTIC` and rerun it |

The smallest starting class is the initialization-only 24-byte `getrandom` at
`Py_InitializeFromConfig+0x198`, not all of CPython. Even if that class were admitted, the observed
ETL workload would still be refused for realtime/monotonic clock and `gettid`. No contract was enabled
in this phase: there is no audited inventory of application-level call sites, no multiple equivalent
controlled cold runs, and no real-workload hit.

### Approach comparison

| Approach | What it could establish | Why it is not enough here |
| --- | --- | --- |
| Hermit-style controlled runtime | Replaces selected nondeterministic interfaces inside an isolated execution | Produces a controlled identity, not a native record; the exact CPython build and call-site audit is still required |
| rr record/replay | Records syscall results and replays a single execution, including threads and signals | Replay is not reusable memoization; it does not decide which later executions have equivalent effects |
| Syscall virtualization (`ptrace`/seccomp/user notification) | Can substitute values at the kernel boundary and observe the caller | vDSO calls bypass the boundary; faking clocks/randomness can change application semantics |
| Runtime instrumentation | Can label CPython-internal call sites and separate startup from application use | Build-specific and invasive; stripped/alternate builds and C extensions can bypass it |

Native and controlled identities must remain separate. A controlled Python record cannot validate
against an unmodified native run.

## 4. P3 — Phase 3F native census

Command:

```bash
python3 benchmarks/realworld/census.py \
  --tracejit target/release/tracejit \
  --output-dir benchmarks/results/phase3f/census-native \
  --runs 2 --warmups 1
```

Result: **9 attempted, 0 reused, 9 refused, 0 failures, 0 missing tools**. Every workload's direct and
traced output equivalence passed. Raw: `benchmarks/results/phase3f/census-native/`.

| Workload | Class | Dependency count | Primary blocker |
| --- | --- | ---: | --- |
| `cc-compile-fixture` | Unknown | 1256 | unmodeled `getrusage` (98) |
| `cc-compile-large` | Unknown | 248 | unmodeled `getrusage` (98) |
| `shell-pipeline` | Unknown | 78 | failed fd operation, `ioctl(TCGETS)`, scheduling-dependent pipe `fstat`/short reads |
| `python-csv-json` | Nondeterministic | 190 | `getrandom`, monotonic/realtime clock, `gettid` |
| `python-csv-json-seeded` | Nondeterministic | 190 | `getrandom`, monotonic/realtime clock, `gettid` (seed does not remove them) |
| `awk-codegen` | Nondeterministic | 31 | `getpid`, `getppid`, `getrandom`, realtime clock |
| `groff-manpage-html` | Unknown | 115 | scheduling-dependent pipe `fstat` and short read |
| `pil-image-transform` | Unknown | 430 | unmodeled `epoll_create1` (291) |
| `cc-syntax-only-lint` | Unknown | 1167 | `getrandom`, `prlimit64`/`sysinfo`, realtime clock, unrestorable `/dev/null` output |

This is a negative compatibility result, not a regression: no guard was weakened to obtain a hit. The
`/dev/null` output in the lint workload is a separate output-restoration limitation, not a read-path
admission. The hotfix changes classification soundness, not the remaining barrier set.

## 5. Next actions

1. Obtain hosted CI for `bb29414`; fast-forward `main` only after it passes.
2. Keep PR #6 closed to merge; lift only its SQLite error-propagation fix if desired.
3. Recreate the epoll change on `main` and add the fork/exec/`RLIMIT_NOFILE`/transfer regressions
   before proposing it. Do not merge the stacked PR #7.
4. For CPython, audit application-level call sites for the exact build, starting with
   `Py_InitializeFromConfig+0x198`; do not enable a contract until multiple cold runs have equivalent
   complete effects.
5. Re-run the nine-workload census only after a real model change; require an actual verified hit
   before claiming compatibility progress.

# Phase 2B.2 — Permission checks as replayed predicates

Commit: `2edbf0d`. Kernel 6.1.102, Ubuntu 24.04.5, x86_64.

## The blocker this addresses

`access`, `faccessat` and `faccessat2` were refused unconditionally before this change:

```rust
// crates/tracejit-trace/src/linux.rs, before 2edbf0d
PendingSyscall::Access { path } => collector.push(pid, Effect::Unknown(UnknownEffect {
    detail: format!("successful access check cannot be guarded exactly: {}", path.display()),
    .. })),
```

A single `Unknown` effect makes the whole execution `UNKNOWN`, which is ineligible. In the Phase 1
census this was the **most frequent blocker: 4 of 9 workloads, 28 occurrences**. [VERIFIED]

## Why no fingerprint substitutes for it

The answer to `access(path, mode)` is a function of state that TraceJIT does not otherwise record:

- real credentials for `access`/`faccessat`, effective credentials under `AT_EACCESS`;
- execute permission on **every** ancestor directory on the path;
- POSIX ACLs, which are not in `stat(2)` output;
- mount options (a read-only mount answers `EROFS`), and immutable/append-only inode flags;
- path-resolution details, including whether the final component is a symlink.

Hashing the file captures none of these, and recording `mode`/`uid`/`gid` captures only part of
the first. A guard built on `FileFingerprint` would be an approximation presented as exactness,
which is exactly the class of mistake this project refuses.

## The mechanism

The call is recorded verbatim and **replayed**:

```rust
pub struct AccessCheck { pub path: PathBuf, pub mode: i32, pub flags: i32, pub errno: Option<i32> }
```

- `errno: None` — the check succeeded.
- `errno: Some(e)` — the exact `errno` the program observed, so `EACCES`, `EPERM`, `ENOENT`,
  `ENOTDIR`, `ELOOP` and friends stay distinguishable. A program may branch on `errno`, not just on
  the boolean, so the value is part of the observation.
- `flags` preserves `AT_EACCESS` and `AT_SYMLINK_NOFOLLOW`, which change the semantics.

Validation re-asks the kernel:

```rust
libc::syscall(libc::SYS_faccessat2, libc::AT_FDCWD, path, mode, flags)
```

On kernels older than 5.8 (`ENOSYS`) and only when `flags == 0`, it falls back to `access(2)`,
which has identical real-credential semantics. Any other flag combination on such a kernel fails
the guard, which deoptimizes rather than guessing.

`ENOENT` and `ENOTDIR` never reach this path: the tracer's existing absence arm turns them into an
`InputDependency::Metadata` with an absent fingerprint. That is stricter (the path must stay
absent) and cheaper (one `stat`, not a decision the kernel has to recompute).

## Why re-evaluation is a guard and not a second execution

`access(2)` has no side effects: it writes nothing and does not update `atime`. Its entire
observable output is the pair (return value, `errno`). Asking the kernel the same question again
therefore yields exactly the value the program would observe if it performed the check now. If the
answer is identical, the recorded dependency still holds; if it differs, the cache entry is
definitely stale. There is no third case, and no approximation.

The credentials used at validation time are TraceJIT's own, which are the credentials a
re-execution of the command would also run under, and `uid`/`euid`/`gid`/`egid` are additionally
part of `RuntimeIdentity` in the lookup key. Reuse remains whole-command reuse: TraceJIT does not
claim to model a program that changes its own credentials mid-run.

## Residual risks — none of these are closed

| Risk | Status |
| --- | --- |
| TOCTOU between validation and output restoration | **Unclosed**, shared with every guard in the system |
| The path is normalised at trace time, so a rename of the probed path is a miss | Conservative by construction; not a false hit |
| LSM (AppArmor/SELinux) path rules influencing the answer | Re-asked, so covered by construction; no test exercises an LSM denial — **UNVERIFIED** |
| A probe whose answer depends on a mount table changed between validation and restore | **Unclosed** TOCTOU class |
| Concurrent mutation of a probed path after the re-check | **Unclosed** TOCTOU class |

Nothing here claims atomicity or race freedom.

## Cost

One syscall per recorded check at validation time and no additional hashing. A workload that makes
no permission checks pays nothing.

## Evidence

| Check | Result |
| --- | --- |
| `access_guard_replays_the_kernel_answer` (unit) | PASS — recorded success becomes a failure when the path is removed |
| `access_guard_keeps_a_recorded_denial_that_still_holds` (unit) | PASS — a recorded `ENOENT` verifies while the path stays absent |
| `access_check_is_replayed_as_a_predicate` (integration) | PASS — run 1 executes, run 2 is `HIT`, creating the probed file makes run 3 `DEOPT` with exit `2`, matching a direct run |
| `cases.json` classification table | PASS — `access_check` and `faccessat_check` classify `Guarded`, eligible |
| Census at `2edbf0d` | `access_check_not_guardable` **absent** from the blocker ranking; 28 refusal occurrences eliminated |

## What it did not achieve

Real-world eligibility is **still 0 of 9**. Removing the top blocker exposed the next ones; the
workloads that were blocked by `access` are now blocked by `unclassified_descriptor` (4 workloads,
11 occurrences), `pipe2` (5), `getrusage` (2), `epoll_create1` (1) and `fstat` (1). The Phase 2B
acceptance target of three reusable workload categories is **not met** and is recorded as a failure
in `PHASE2_CENSUS_DELTA.md`.

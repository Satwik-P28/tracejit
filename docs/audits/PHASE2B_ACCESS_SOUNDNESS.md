# Priority 0 — soundness audit of replayed permission checks

Commit audited: `2edbf0d` (mechanism as introduced) and `b57bc7f` (fixes below).
Status legend: **[VERIFIED]** observed by execution or direct code reading, **[INFERENCE]** follows from
the model but was not executed, **[UNVERIFIED]** hypothesis, **[BLOCKED]** could not be tested here.

## What the mechanism does

`access`, `faccessat` and `faccessat2` are recorded verbatim — path, `mode`, `flags`, and either
success or the exact `errno` — and re-evaluated at validation time instead of being approximated by
a content or metadata fingerprint. `faccessat2(AT_FDCWD, path, mode, flags)` is the replay call;
plain `access(2)` is used only when the kernel lacks `faccessat2` **and** `flags == 0`, where the two
have identical real-credential semantics.

The premise that makes re-evaluation a guard rather than a second execution: these calls have no
side effects and do not update `atime`; their entire output is the `(return, errno)` pair.

## Defects found in the mechanism as first written

### A1 — the replay asked the question as the wrong principal. Severity: high. **[VERIFIED, FIXED]**

The guard ran in the validating process. The recorded answer came from the traced process *at that
syscall*, which need not hold the same identity: a program may `setuid`, a binary may carry file
capabilities, and a child may drop privileges.

Concrete false hit: a program drops to an unprivileged user and probes a mode-`0600` file it can
read through an ACL. `access` succeeds and `None` is recorded. The ACL is later revoked. A replay
running as root still gets success — root bypasses discretionary checks — so the guard compares
success to success and permits reuse, while a fresh run of the same privilege-dropping program
would now observe `EACCES`. The stale answer is replayed as if it were current.

Fix: `AccessCheck` now carries `credential`, a BLAKE3 digest over the `Uid:`, `Gid:`, `Groups:`,
`CapInh:`, `CapPrm:`, `CapEff:` and `CapAmb:` lines of `/proc/<pid>/status` captured at the check.
Validation recomputes the digest for the validating process and requires equality. Any mismatch —
including a record with no digest at all, and any failure to read `/proc/self/status` — fails the
guard, which deoptimizes and retraces. Supplementary groups and capability sets are covered because
they are inside the digest, not inferred from uid.

Cost: one small `read(2)` of `status` per permission check at trace time, and one per check at
validation time. The census shows at most 28 such checks across nine workloads.

### A2 — `AT_EMPTY_PATH` was answered about a path. Severity: high. **[VERIFIED, FIXED]**

`faccessat2(fd, "", mode, AT_EMPTY_PATH)` asks about the descriptor's inode. `resolve_path` produced
the descriptor's *recorded path*, and the replay then asked about that name. For a file descriptor
whose directory was renamed after the open, or whose name was replaced, the replay answers a
different question than the one that was asked. Now refused: the check becomes an unknown effect,
which is not reusable. Empty names without the flag are refused too — they are `ENOENT` probes that
the absence metadata guard covers more cheaply.

### A3 — `..` was collapsed lexically in every recorded path. Severity: high. **[VERIFIED, FIXED]**

Not access-specific, but it makes access checks and every other path-based dependency name the wrong
file. `normalize()` popped the previous component on `ParentDir`, so `/a/link/../b` was recorded as
`/a/b`. When `link` is a symlink, the kernel resolves the link first and the process actually read
`<target-of-link>/../b`, which is generally a different file. The guard then hashed and fingerprinted
`/a/b`, so a change to the file that was really read could go unnoticed — a false-hit path.

`normalize()` now removes only `.` and leaves `..` in place, so the kernel resolves the recorded
string exactly as it resolved the original. The regression test is
`normalize_keeps_parent_components_so_links_resolve_like_the_kernel`.

## Cases from the mandate, with verdicts

| Case | Behaviour | Verdict |
| --- | --- | --- |
| `dirfd`-relative operations | Path resolved through the recorded descriptor path (or `/proc/<pid>/fd/N`) to an absolute path; validated with `AT_FDCWD` on that path | **[INFERENCE]** sound modulo rename-during-execution: a fresh run re-derives its `dirfd` from a path in the same way, so a stale reconstruction produces a *different answer* and deoptimizes rather than a wrong hit |
| `AT_EMPTY_PATH` | Refused as unguardable | **[VERIFIED]** |
| `AT_EACCESS` | Preserved verbatim in `flags`; `faccessat2` replays effective-credential semantics | **[VERIFIED]** (no test forces the distinction) |
| `AT_SYMLINK_NOFOLLOW` | Preserved verbatim; no lexical resolution of the final component | **[VERIFIED]** |
| Real vs effective ids | Entire `Uid:`/`Gid:` quadruple is inside the credential digest | **[VERIFIED]** by the digest content |
| Supplementary groups | `Groups:` inside the digest | **[VERIFIED]** |
| Capabilities / root | `Cap*:` sets inside the digest | **[VERIFIED]** |
| POSIX ACLs | Not read; covered by construction, because the kernel is asked again | **[VERIFIED]** by design, **[UNVERIFIED]** on a filesystem with ACLs actually in use (tempdirs here are `ext4`/`tmpfs` without ACLs) |
| Mount options, `noexec` | Same: re-asked from the kernel | **[INFERENCE]** |
| Namespaces | If the program `unshare`s, its view diverges from the validator's and no syscall records it; `unshare`/`clone(CLONE_NEW*)` are unmodeled, so the execution is already `UNKNOWN` | **[INFERENCE]** |
| Relative paths + `chdir` | Recorded against the traced `cwd`; `chdir` is a control effect | **[VERIFIED]** |
| Deleted or renamed directory | Replay differs → guard fails → deoptimize | **[INFERENCE]** |
| Symlink substituted between record and validate | Replay follows the new link → different answer or `ENOENT` → deoptimize; a substitution that keeps the same answer is by definition the same observable | **[INFERENCE]** |
| Exact return and `errno` equality | Success vs the exact `errno` is compared, not a boolean | **[VERIFIED]** (`access_guard_keeps_a_recorded_denial_that_still_holds`) |
| Validation-to-restore race | Unclosed for every guard, not just this one | **[BLOCKED]** — documented limitation |

## Tests

| Test | Result |
| --- | --- |
| `an_access_check_without_a_recorded_identity_is_refused` | PASS — a record from before A1 deoptimizes instead of being trusted |
| `an_access_check_replays_only_for_the_recorded_identity` | PASS — same identity replays; deleting the file changes the answer and fails the guard |
| `access_guard_replays_the_kernel_answer` | PASS |
| `access_guard_keeps_a_recorded_denial_that_still_holds` | PASS |
| `access_check_is_replayed_as_a_predicate` (integration) | PASS — run 1 executes, run 2 is `HIT`, creating the probed file makes run 3 deoptimize with exit 2, matching a direct run |
| `access_check` / `faccessat_check` fixtures | PASS — `Guarded`, eligible |

## Residual limitations

- The credential digest identifies *who* asks, not *in which namespace or LSM domain*. A recorded
  check made under a different mount namespace or AppArmor profile with the same uid would replay
  under the validator's domain. Reaching that state requires `unshare`/`clone` flags that are
  already unmodeled, so such a run does not become reusable, but the reasoning rests on that.
- ACL behaviour was not exercised: no test creates an ACL, because the CI filesystems here do not
  guarantee `setfacl` support. The design does not need ACL data; it needs the kernel to be asked
  again, which it is.
- The check is still not simultaneous with restoration.

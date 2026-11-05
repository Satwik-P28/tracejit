# Phase 2F: `statfs`, `fstatfs` and inherited descriptor semantics

Two blockers from the Phase 2D/2E refusal chains are modelled in this phase: filesystem statistics
(`statfs`/`fstatfs`, which refused `sed` and `tar`) and inherited regular-file input (which refused
`tr`). Both are modelled as exact observations replayed against the same execution context, not as
"probably stable" values.

## 1. The observed calls

`sed` issues a pathname `statfs` against `/sys/fs/selinux`; `tar` issues `fstatfs` on an open
descriptor. The `explain` output now names them:

```
FSSTAT /sys/fs/selinux
```

On x86_64 the kernel writes a 120-byte `struct statfs`:

| Field | Bytes | Observable content |
| --- | --- | --- |
| `f_type` | 8 | filesystem magic |
| `f_bsize` | 8 | block size |
| `f_blocks`, `f_bfree`, `f_bavail` | 24 | capacity, free and unprivileged-free blocks |
| `f_files`, `f_ffree` | 16 | inode totals and free inodes |
| `f_fsid` | 8 | filesystem identifier |
| `f_namelen`, `f_frsize`, `f_flags` | 24 | name limit, fragment size, mount flags |
| `f_spare[4]` | 32 | padding, kernel-defined |

Every one of these can change while a command runs (`f_bfree` on any write anywhere in the
filesystem, `f_flags` on remount), and all of them are visible to the program. Ignoring the volatile
ones was not an option: `df`-like tools and capacity checks read exactly those fields.

## 2. Model

`FilesystemStats` mirrors all twelve fields (120 bytes). `FilesystemStatsRead` records:

- the resolved path and the **call shape**: pathname `statfs` versus `O_PATH` + `fstatfs`;
- `stats: Option<FilesystemStats>` and, when the kernel refused, the exact `errno` — a cached
  failure is replayed only if it fails identically;
- the `FileFingerprint` of the object the path resolved to when the query ran;
- the credential digest;
- the mount-namespace identity (`NamespaceIdentity { device, inode }` of `/proc/pid/ns/mnt`).

Recording is wired through `PendingSyscall::FsStats`; `fstatfs` resolves the descriptor's recorded
path, so a descriptor obtained by `creat` or `open` is handled the same way. `creat` is treated as
`open(O_CREAT|O_WRONLY|O_TRUNC)`, which is what it is.

## 3. Validation

`statfs_query` repeats **the same call shape** as the record:

- pathname call → `statfs(path)`;
- descriptor call → `open(path, O_PATH|O_CLOEXEC)` then `fstatfs`.

It then compares all twelve fields for equality. Any difference invalidates. The mount namespace
must match, and the credential digest must be present and equal, because the answer for a path can
depend on the caller's namespace and on whether the caller may traverse to it.

Consequences, all deliberate:

- A filesystem filling up or freeing space deoptimizes the entry. That is correct: the program
  observed different numbers. Test
  `filesystem_stat_guard_replays_every_field_and_detects_capacity_change` mutates `f_bfree` and
  `f_ffree` and requires invalidation.
- A remount that changes `f_flags` deoptimizes.
- A path that now resolves to a different filesystem (`f_type`/`f_fsid` change) deoptimizes, and so
  does a bind mount over the path (different device in the fingerprint).
- A cached `ENOENT`/`EACCES` is replayed only while the same call fails the same way; if it starts
  succeeding, the guard fails and the command is retraced.

This is intentionally conservative. `sed` reads `statfs` only to decide whether SELinux is present;
its answer is stable for a given mount, so reuse survives in practice, but a genuine capacity change
will cost a retrace rather than risk a stale value.

## 4. Why not "ignore the free-space fields"

Because the program can print them, branch on them, or write them into its output. There is no
mechanism in TraceJIT that proves a particular field is unobservable, and the Phase 2D research
concluded that no surveyed system certifies a specific dynamic read as dead. Suppressing them would
be exactly the global whitelist of mutable system information the brief forbids.

## 5. Inherited regular-file stdin

`tr` reads its input from fd 0, which the shell had opened on a regular file. Phase 2E refused all
inherited descriptor reads because "an inherited fd" was one undifferentiated case. The cases are
not equivalent:

| fd 0 at trace start | Model |
| --- | --- |
| regular file | content hash + fingerprint + start/end offset (§6) |
| pipe / FIFO | refused — the data comes from another process and cannot be replayed |
| socket | refused |
| terminal | refused — input is external and timing-dependent |
| anonymous (`/dev/null`, `memfd`, eventfd, …) | refused unless it is a recorded regular-file read |
| unknown / unresolvable | refused |

Refusal is the default: `InheritedStream` is created only when `/proc/pid/fd/0` resolves to a
regular file and its initial position is known.

## 6. The regular-file model

At trace start the tracer records, for the inherited descriptor:

- resolved path, `FileFingerprint`, and BLAKE3 content hash;
- `start_offset` from the descriptor position;
- `end_offset` and `bytes_read` when the program finishes reading.

Validation requires the same object (fingerprint), the same content hash, and a descriptor still
positioned at `start_offset`. On a hit, `apply_inherited_stream_offsets` advances the descriptor to
`end_offset`, so a shared open-file description ends where a real run would have left it. If another
process has already advanced the shared offset, the start-offset check fails and the entry
deoptimizes — safe, at the cost of a hit.

A descriptor that is read and then `lseek`ed is handled conservatively: directory descriptors and
tracked stdin streams refuse a non-zero `lseek`/`getdents64` start offset, because the byte stream
would no longer begin where it was recorded. A narrow regression introduced while implementing this
— refusing every `lseek` on inherited fds — blocked Python at `lseek(/dev/null)`; it was reduced to
the directory and tracked-stream cases. This is why the census reports `getrandom`, not `lseek`, for
the Python workloads.

## 7. Evidence that the models engage

Captured at `5db741f` in `benchmarks/results/phase2f/explain-{sed,nm,tr}.txt`:

- `sed`: `FSSTAT /sys/fs/selinux` replaces the former `statfs` refusal; the next refusal is
  `getrandom` (see `PHASE2F_COMPATIBILITY.md`).
- `nm`: `DIRLIST /usr/lib/x86_64-linux-gnu/bfd-plugins (4 calls)` replaces the former enumeration
  refusal, followed by `getrandom` and `prlimit64`.
- `tr`: `STDIN /tmp/.../in.txt [0..375762]` replaces the former inherited-descriptor refusal,
  followed by `getrandom`.

That is the intended outcome of this phase's Priority 1 and 2: the specific blockers are gone and
the chains advance to a different, deeper blocker. It is **not** a new cache hit; §5 of
`PHASE2F_COMPATIBILITY.md` explains why.

## 8. Tests added

- `filesystem_stat_guard_replays_every_field_and_detects_capacity_change`
- `directory_enumeration_guard_replays_the_exact_entry_stream`
- `inherited_stream_guard_refuses_stdin_that_is_not_the_recorded_file`
- `directory_open_guard_replays_o_path_without_read_permission`
- `directory_open_guard_requires_the_recorded_credentials`

plus the pre-existing 95 tests, for **100 passing** in `cargo test --workspace`.

## 9. Remaining assumptions

- The guard's `statfs` runs in the validator's mount namespace; the recorded namespace identity
  must match, but the identity is a digest of the namespace inode, so a namespace recreated with the
  same content is a different inode and invalidates. Fail closed.
- `f_bsize`, `f_frsize` and `f_namelen` are kernel constants per filesystem in practice; they are
  compared anyway.
- A program that reads `statfs` for a path it cannot traverse under the recorded credentials is
  handled by the credential check, not by a replayed errno alone.
- Concurrent filesystem mutation between validation and restore is the general TOCTOU window.

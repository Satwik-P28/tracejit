# Phase 2F: independent audit of the `DirectoryOpened` guard

Phase 2E replaced an over-broad metadata dependency with `Guard::DirectoryOpened`. This audit
reviews that guard against the ten questions in the Phase 2F brief. Two soundness defects and one
path-resolution defect were confirmed and fixed; the rest of the mechanism was found sound within
the stated execution-context assumptions.

Code under review: `886e877` (original guard) → `5db741f` (credential and access-mode fixes) →
`be94f38` (`..` resolution fix). Tests: 100 passing.

## 1. What the original observation actually is

`DirectoryOpened` is completed only for a **successful** `open`/`openat`/`openat2` whose resolved
path is a directory. The recorded facts are the resolved path, the twelve-field
`FileFingerprint` of the directory, the open flags from the entry stop, and (from `5db741f`) a
digest of the credential set that performed the open. A failed directory open never becomes this
dependency; it is recorded as `Metadata`, which compares every timestamp, so a cached success can
never be replayed where a fresh open would fail with `EACCES`, `ENOENT` or `ENOTDIR`.

The guard compares:

| Field | Compared | Why |
| --- | --- | --- |
| `device`, `inode` | yes | the name must still resolve to the same object |
| `mode` (type + permission bits) | yes | `open` can observe type and search/read permission |
| `uid`, `gid` | yes | ownership changes alter a non-root process's answer |
| is-a-directory | yes | `ENOTDIR` must not be replayed as success |
| `atime`/`mtime`/`ctime` | no | an `open` of a directory cannot report them |
| `size`, `blocks`, `nlink` | no | same; `nlink` changes on every child directory |

A probe `open` of the path is replayed with the recorded access mode (see §4), and a failure
invalidates. `stat`, `fstat`, `newfstatat` and failed lookups still produce `Metadata` with all
twelve fields including timestamps; `explicit_directory_metadata_guard_still_compares_timestamps`
pins that the reduced comparison does not leak into a genuine metadata read.

## 2. Defect found: the probe ran under the validator's credentials

Phase 2E's guard performed its probe open as the TraceJIT process and relied on the global
`RuntimeIdentity` guard. That is not sufficient. A traced child may drop privileges, change
supplementary groups, or carry a different capability set before opening the directory; the
validating process may still be privileged. In that case the probe succeeds where a fresh run of
the recorded child fails, and a cached success is returned for a command that would now fail —
a false reuse.

Fix (`5db741f`): `DirectoryOpen` carries `credential: Option<Hash>`, a digest of uid, gid,
supplementary groups and the capability sets, computed by `credential_identity`. The guard calls
`validate_credential_and_namespace` and **refuses when the recorded digest is absent** (an old or
otherwise incomplete record) or differs. This is the same contract as the Phase 2B `access` replay,
which had the identical defect. Regression test:
`directory_open_guard_requires_the_recorded_credentials`.

## 3. Defect found: `O_PATH` was validated as a read open

An `O_PATH` directory open requires only search permission on the path; it does not require read
permission on the directory, and it cannot be used for `getdents64`. Phase 2E's probe always used
`O_RDONLY`, so a recorded `O_PATH` open by an unprivileged child could be rejected during
validation because the validator cannot read the directory — fail closed, but an avoidable loss.
More importantly, the reverse case matters for correctness: replaying an `O_PATH` open as
`O_RDONLY` asks the kernel a *different* question than the original, so the guard was not
representing the observation it claimed to.

Fix (`5db741f`): `DirectoryOpen` records the entry-stop `flags`, and `probe_directory_open`
reproduces the recorded access mode, mapping `O_PATH` to `O_PATH|O_DIRECTORY` and
`O_DIRECTORY|O_NOFOLLOW` to the same shape, otherwise `O_RDONLY|O_DIRECTORY|O_CLOEXEC`. Test:
`directory_open_guard_replays_o_path_without_read_permission`.

## 4. Defect found: `..` was normalised lexically, so the wrong path could be recorded

This is not specific to directories, but the audit of "symlink chains and `..` path components"
exposed it, and it was the most serious finding of the phase.

`normalize()` collapsed `..` textually. The kernel resolves `..` **after** following a symlinked
directory, so for `/a/link/../b` with `link → /x/y` the process opens `/x/b`, while TraceJIT
recorded `/b`. Every guard on that dependency then observes an unrelated object. A workload whose
path traverses a symlink with `..` could therefore be reused on a stale, unrelated file. Phase 2B
had fixed the *symptom* for `access` by preserving `..`, but the recorded path was still not
guaranteed to be the object the kernel resolved.

Fix (`be94f38`): `normalize_join` detects a `ParentDir` component and canonicalises the path with
`fs::canonicalize`. When the leaf does not exist yet (an `O_CREAT` target), it canonicalises the
existing parent and rejoins the file name. Paths without `..` keep the previous treatment, so no
recorded path changes for ordinary workloads.

Residual limitation: this is canonicalisation **at record time**, not proof that the kernel's
resolution was identical (races, and paths that do not exist at any level, fall back to the lexical
form). A stricter design would report the resolved object from `/proc/pid/fd` for descriptor-producing
syscalls and refuse the rest; that is pre-existing work, not introduced here.

## 5. A directory descriptor used as a base

`openat(dirfd, "child")` is resolved by the tracer as `recorded_dir_path.join("child")`. If the
directory is renamed after the open but while the descriptor is still valid, a fresh run would
still succeed through the descriptor, while the guard fails because the recorded path no longer
names the same inode. That is a **lost hit, not a false reuse**, and the behaviour is accepted:
fail closed. If a different directory is moved onto the path, the inode comparison fails. Directory
descriptors are inherited across `fork`/`exec` as `FdState::File(path)`, so the same reasoning
applies after `exec`; a child that `dup`s or closes them keeps the recorded path as the base.

## 6. Replacement, rename and the validation-to-reuse window

The guard's `stat` and probe open happen before cached output is exposed, but they are not atomic
with restoration. A directory replaced between the probe and the restore is the general TOCTOU
limitation already documented for every guard; the executable re-hash narrows the analogous window
for `execve`. No new claim is made here.

## 7. Mount and bind-mount changes

The recorded fingerprint includes the device number, so a bind mount that changes the device of the
resolved path invalidates. A mount over the same underlying inode on the same device is not
distinguishable by the fields an `open` can observe and is also invisible to the original process
at the time of the open; the probe open is performed in the validator's mount namespace, so a child
that unshares a mount namespace after the recorded open is **not** modelled for this guard. This is
a pre-existing, documented assumption of all path-based guards (the tracer resolves paths in its
own namespace); `statfs` and directory enumeration, which are newer, do bind mount-namespace
identity. Closing the gap for path guards is listed as remaining work.

## 8. Descriptor inheritance

Directory descriptors inherited across `fork`/`exec` are tracked by path. Operations on them are
resolved against that path, and therefore inherit the same rename limitation as §5. A directory fd
whose path was unlinked still works for a fresh process, but the guard fails — again fail closed.

## 9. Explicit metadata reads versus ordinary opens

Only `open` produces `DirectoryOpened`. `stat`/`lstat`/`fstat`/`newfstatat`/`statx` produce
`Metadata` (all fields, including timestamps), and `lstat`-style calls produce `SymlinkMetadata`.
The directory guard therefore cannot mask a genuine metadata observation.

## 10. Enumeration

`getdents64` is no longer "known internal" and silently ignored. It is a first-class dependency with
its own guard; see `PHASE2F_DIRECTORY_ENUMERATION.md`. A directory that is opened and then
enumerated produces both dependencies.

## Diagnostics

`TRACEJIT_DIAG_DEPS=` (introduced in Phase 2E) remains opt-in and emits only the recording site,
thread, path, syscall number and open flags. It emits no file contents, no credential material and
no environment, and it is absent unless the variable is set; the Phase 2F benchmark artifacts
(`benchmarks/results/phase2f/`) were produced without it. The new dependency kinds print through
`explain` only (`DIRLIST`, `FSSTAT`, `STDIN`), not during normal runs.

## Verdict

The guard now represents the observation it claims — "this path resolved to this directory, and
this credential set could open it with this access mode, at this point" — and fails closed on
missing credentials, missing flags, `O_PATH` mismatch, rename, replacement, type change and
permission change. The `..` defect was the only finding that could have produced a false reuse; it
is fixed at `be94f38` and is independent of the directory guard itself.

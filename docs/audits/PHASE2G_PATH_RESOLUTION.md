# Phase 2G: path-resolution correctness audit

Verdict: the `be94f38` canonicalisation introduced a **confirmed false cache hit** and has been
removed. The record now keeps the pathname the process used; no false hit was found in the tested
resolution scenarios after the fix. One confirmed release blocker, fixed before any release.

## What a path dependency has to record

A recorded path is not a file. It is a question the kernel answers, and its answer depends on:

| Evidence | Where it lives now |
| --- | --- |
| the pathname the process passed | `path` on every file/metadata/directory dependency, verbatim except `.` |
| the directory descriptor base (for relative paths) | the joined base path, with its own components preserved |
| the inode, device, mode, owner, size, timestamps | the dependency's `FileFingerprint` |
| the bytes, for reads | the dependency's content hash |
| the credentials that performed the observation | credential digest on directory, enumeration, `statfs` and access dependencies |
| the mount namespace | namespace identity on `statfs` and enumeration dependencies |

The guard replays the recorded pathname with `open`, `fs::metadata`, `hash_file`, `statfs` or
`getdents64`. That is the resolution evidence: every condition that made `/a/link/../b` resolve to
the recorded inode is re-evaluated by the kernel itself.

## The defect

`be94f38` replaced any path containing `..` with its canonical target before recording it:

```text
requested  /tmp/x/link/../input.txt      link -> a/sub
recorded   /tmp/a/input.txt
```

The dependency then names a file, not a question. Repointing `link` at `b/sub` changes what a native
run reads, but the guard still hashes the unchanged `/tmp/a/input.txt`, so every guard passes and
the cached result is replayed.

Two integration tests reproduce it. Before the fix both failed with a `Reused` decision and 93/93
guards passing:

- `a_repointed_symlink_before_dotdot_is_never_a_cache_hit`
- `a_repointed_symlink_chain_before_dotdot_is_never_a_cache_hit`

The first records `read_to_stdout` on `<link>/..` reading `alpha\n`, repoints the link, and runs the
identical command again. Native execution reads `beta\n`; the defective build reported `Reused` and
returned the old bytes.

The change was also unnecessary: Phase 2B (`b57bc7f`) had already stopped collapsing `..` lexically,
so the pre-`be94f38` record was a preserved pathname. Canonicalising it was a regression, not a fix.

## The fix

`normalize` now removes only `.` components. Everything else, including `..` and every symlink
component, stays in the recorded path, and the guard asks the kernel the same question the program
asked. Two tests pin the failure pattern and one existing test
(`an_absence_guard_reports_a_file_that_appeared`) pins the negative case.

The observed target is not stored as a separate canonical string because the fingerprint is strictly
stronger: device and inode identify the target even when two pathnames reach it, while a canonical
name would add nothing the kernel does not recompute. Copying the canonical name into the record
would reintroduce exactly the substitution that caused the defect.

## Test matrix

| Scenario | Result | Evidence |
| --- | --- | --- |
| symlink then `..`, link repointed | no reuse; new bytes returned | `a_repointed_symlink_before_dotdot_is_never_a_cache_hit` |
| symlink chain then `..`, second link repointed | no reuse; new bytes returned | `a_repointed_symlink_chain_before_dotdot_is_never_a_cache_hit` |
| relative `dirfd` paths | path is joined with the recorded base and replayed verbatim; the target fingerprint covers a renamed/duplicated base because its inode differs | `plain_file_read` fixtures and `at_empty_path` classification case |
| missing file becomes present | absence fingerprint no longer matches; no reuse | `an_absence_guard_reports_a_file_that_appeared` |
| directory entry created beside an input | still reused; directory *open* does not observe timestamps | `gzip_reuse_survives_creating_entries_beside_the_input` |
| output path through a symlink ancestor | **refused** (`Unknown`): restoration by path would race the link | observed while writing the regression test |
| mount changes | **BLOCKED**: `unshare -m` returns `EPERM` on this host | recorded, not claimed |
| concurrent identical runs | neither fails nor shares unsafe state; substitution between runs is covered by the tests above | `concurrent_identical_runs_neither_fail_nor_reuse_unsafely` |
| substitution during a run | inherent TOCTOU; no claim | limitation 6 below |

## Remaining limitations

1. **Validation-to-restore window.** A path can change between the last guard and output restoration.
   Not closed; every guard has this window.
2. **Restoration is not crash-atomic.** Re-execution repairs an interrupted restore.
3. **Symlinked output ancestors are refused**, conservatively and deliberately, because restoring
   through a repointable path could write outside the recorded tree.
4. **Mount changes are not guarded by path dependencies.** `statfs` and enumeration bind the mount
   namespace; ordinary reads rely on device+inode and content. A bind mount that changes the meaning
   of a path without changing inode or bytes is not detected, and could not change the observed bytes.
5. **`stdin` atime is part of the runtime identity.** A `tr` stdin read can update `atime`, changing
   the lookup key and causing a miss rather than a false hit. This explains why `tr` reused in one
   benchmark session and missed in the other; it is a reach limitation, not a soundness one.
6. **A `dirfd` base that is renamed and replaced by a byte-identical inode** would still be caught by
   the target fingerprint, because the inode differs. A same-inode alias cannot differ in content.

## Reproduction

```bash
cargo test -p tracejit-cli --test linux_integration a_repointed_symlink -- --nocapture
git show be94f38 -- crates/tracejit-trace/src/linux.rs   # the removed canonicalisation
```

# Phase 2R: metadata-replay correctness audit

Base `0aae8c5`, Ubuntu 24.04, glibc 2.39, Linux 6.1.102. Scope: the metadata effects added in
Phase 2Q. No false reuse was reproduced; two latent correctness defects were found and fixed, and
the remaining limits are stated rather than papered over.

## Model

Successful `chmod`, `fchmod`, `fchmodat`, `chown`, `fchown`, `fchownat`, `truncate`, `ftruncate`
and explicit-time `utimensat` are recorded as output mutations. Null-time/`UTIME_NOW` calls are
refused. `umask` is process-internal; the resulting mode is captured from the file. At the end of
a traced execution each output is captured as bytes plus mode, uid, gid, atime and mtime. A hit
stages a temporary file, applies **chown → chmod → timestamps**, then renames it over the
destination. Ownership precedes mode because chown clears set-id bits; mode precedes times because
chmod changes ctime but not the replayed atime/mtime.

## Findings

### F1: legacy artifacts were silently reinterpreted (fixed)

`OutputArtifact`'s new fields used `#[serde(default)]`, so a record written before metadata replay
decoded with `unix_uid/gid/accessed/modified = None`. `stage_output` then skipped ownership and
timestamps entirely, restoring the temporary file's mode and the current time. That is not "no
metadata was observed"; it is an unknown pre-2Q artifact and must not be replayed.

Fix: `OUTPUT_ARTIFACT_VERSION = 2`, a `#[serde(default)] artifact_version` field, and a
`stage_output` precondition that fails closed for any other version. Regression:
`legacy_artifact_without_a_schema_version_fails_closed` removes the field from JSON, checks it
decodes as 0, and checks the destination is untouched and no temporary file remains.

### F2: hashing the output changed the recorded atime (fixed)

`output_from_path` read the bytes (which can update atime under relatime) before calling
`fs::metadata`. The artifact therefore recorded the cache's read time, not the tool's final access
time. Fix: capture metadata before the read. Regression:
`metadata_replay_round_trips_mode_owner_and_times` sets atime=1 s, captures, and asserts the
artifact still holds exactly `1_000_000_000` ns.

### Verified effects

| Effect | Verification | Result |
| --- | --- | --- |
| write + `ftruncate` | two-output probe, cold→warm | size 4, bytes `payl` |
| `chmod` 0600 | same probe | mode 0600 |
| `umask(0027)` + create 0666 | second output, no chmod | mode 0640 |
| explicit `utimensat` | atime/mtime = 1 s / 2 s | replayed exactly |
| uid/gid | cache round-trip at current identity | preserved |
| absent destination | integration probe | created |
| hard-linked destination | `a_hard_linked_destination_is_refused_without_touching_either_link` | refused, both links untouched |
| symlink / directory destination | Phase 2Q regressions | refused, target untouched |
| timestamp out of range | `a_metadata_failure_leaves_the_destination_untouched` | refused before rename |

The earlier integration probe still passes and now also covers `ftruncate`, `umask` and a second
output. `metadata_preserving_program_reuses_and_replays_mode_and_times` observes `Reused`, not just
execution equivalence.

## Inode preservation vs pathname replacement

Reuse always replaces the directory entry. Native `gzip`, `bzip2` and GCC do the same (temporary
file plus rename), so hard links to the old inode keep the old bytes and xattrs are dropped just as
natively. If a tool instead truncates an existing inode in place, the final pathname bytes and
metadata still match, but two secondary effects differ:

- another process holding an open descriptor keeps the old inode after reuse, while an in-place
  native truncate would mutate that descriptor's contents;
- the inode number changes after reuse.

These are documented contract limits, not silently accepted equivalence. A destination with more
than one hard link is refused before any mutation, so the common aliasing case fails closed.
Extended attributes are not modeled: a tool that calls `setxattr` remains ineligible rather than
having its xattrs dropped.

## Failure handling

All outputs are validated and staged before any destination is touched; a corrupt CAS object
fails before the first rename. Partial application is rolled back in reverse order using retained
backups, and a failed rollback is reported separately. Metadata application to the staged file may
fail (bad timestamp, ownership) without touching the destination. Concurrency between validation
and rename keeps the pre-existing TOCTOU window: rename replaces any entry that appears, and a
concurrent writer's descriptor is not reconciled. This is the same bounded window as Phase 2P.

Mount-namespace and cross-user ownership replay were not exercised (no privileges); they are
reported as untested, not as verified.

## Tests and gate

Added four cache tests and extended the integration probe. `cargo fmt --check`, Clippy
`-D warnings`, and `cargo test --workspace` pass with **123 tests**. Cache inspection used the
actual SQLite records; no cached bytes were exposed during the failure tests.

# Concurrent cache safety: prune versus restore

Phase AA left one race unresolved on paper: a cache object can be removed,
truncated or replaced by another process (a manual prune, a `cache clear`, a
partially copied CAS) while a restore is reading it. This phase makes that window
deterministically testable and records what each outcome is.

## 1. Threat model

The cache directory is ordinary user-owned storage. Concurrent actors we assume
can exist:

* another `tracejit run` restoring or inserting into the same cache;
* a user or script deleting cache objects (`rm`, `cache clear`, a packaging step);
* a partially written object from an interrupted copy of the cache directory;
* this process being killed at any point during a restore.

Actors we do **not** assume away: none. The goal is that no actor can cause a
wrong workspace state to be reported as a successful reuse.

## 2. Where the window is

`restore_outputs` has two phases, and only the second mutates the workspace:

1. **stage**: for each output, validate the artifact, open the CAS object, stream
   it through BLAKE3 into a temporary file in the destination's parent, compare
   the digest with the object name, then apply ownership/mode/timestamps to the
   temporary file. Nothing outside the temp file is touched.
2. **apply**: write the restore intent (durable, per-pid), then `rename` each
   staged file over its destination, with backups and soft rollback.

The prune-versus-restore race is therefore entirely inside phase 1: everything
phase 2 consumes was already copied and verified.

## 3. Deterministic injection

A test-only hook (`fault::maybe_mutate_object`, environment variables
`TRACEJIT_TEST_CAS_PATH` and `TRACEJIT_TEST_CAS_ACTION` = `delete` | `truncate` |
`replace`) fires **after the CAS object's descriptor is open and before any byte
is read**. That is the exact interleaving that a timer-based race test cannot
reliably produce. The hook is a no-op in non-test builds, in the same style as
the existing `TRACEJIT_TEST_RESTORE_FAIL_PATH` and
`TRACEJIT_TEST_RESTORE_PAUSE_PATH` hooks that the Phase K4 harness uses.

## 4. Outcomes, by case

| Case | What happens | Why it is safe |
|---|---|---|
| object pruned **before** open | `CacheError::CorruptObject`; the row retraces | a missing object is "this record cannot be served", not a crash; destination untouched |
| object deleted **after** open | restore **succeeds** with the verified bytes | the open descriptor keeps the unlinked inode alive; the digest is checked over exactly the bytes that are copied, and they match the object name |
| object truncated **after** open | `CorruptObject`; retrace | the digest no longer matches the object name |
| object replaced with different bytes **after** open | `CorruptObject`; retrace | same digest check; the check is over the copied bytes, not the path |
| several concurrent restores of one record | all succeed with the cached bytes | unique temp names per restore, single-path `rename`, identical content |
| concurrent insert of the same object | last writer wins, both copies hash to the same name | object names are content digests |
| restorer killed **during staging** | workspace unmodified; no intent written | staging only writes temp files in the destination directory |
| restorer killed **during apply** | next `Cache::open` sees a dead-pid restore intent and refuses HIT until a clean execution | existing Phase K4 protocol; verified again this phase |

The distinction that matters: a *corrupt or absent object* is an operational
outcome that must retrace, while a *deleted object with an open descriptor* is a
verified read of bytes whose content was proven against the record. Neither
produces a wrong workspace.

## 5. Tests added (`crates/tracejit-cache`)

Five permanent tests, all deterministic:

```
deleting_a_cas_object_after_open_still_restores_verified_bytes
truncating_a_cas_object_after_open_fails_closed
replacing_a_cas_object_after_open_fails_closed
a_pruned_cas_object_before_open_fails_closed
concurrent_restores_of_one_record_all_produce_the_cached_bytes
```

Each asserts the workspace result *and* that no `.tmp` file is left behind. The
pruned-before-open and concurrent-restore tests need no hook; only the
"after open" cases use it, because no other mechanism gives that interleaving
deterministically.

Existing coverage that continues to pass unchanged:

* `phase_k4_restore_fault.sh`: soft failure rolls back and retraces; SIGKILL
  mid-apply leaves a mixed workspace that the next run refuses to reuse and
  recovers by re-executing. Measured again this phase: both RESULT lines PASS.
* `scripts/modelcheck/check_state_machines.py`: `reuse_hit` 9 states, 0
  violations; `restore_crash` 14 states, 0 violations; `restore_intent` 5 states,
  0 legal violations plus one planted illegal state detected.
* `crates/tracejit-cache` restoration suite (40 tests): symlink substitution,
  hard-linked destination, create precondition, metadata failure, deletion
  artifacts, rollback of a later replacement, intent lifecycle.

## 6. What this does not claim

* No multi-file atomic visibility. A hard kill between two renames can leave a
  mixed workspace; the intent makes the next run refuse reuse, it does not undo
  the mixture.
* No inode-preserving restore and no protection against a concurrent writer
  mutating a *destination* after the rename.
* The open-descriptor case relies on POSIX/Linux unlink semantics: the data
  remains readable after `unlink`, and the digest is verified over the copied
  bytes. This is an assumption about the kernel interface, stated rather than
  proved.
* SQLite-level concurrency (two processes inserting records) is exercised by the
  concurrent-restore test only indirectly; the storage layer was not redesigned,
  per the mission's instruction.

## 7. Conclusion

The prune-versus-restore window is closed in the sense that matters: every
outcome is either a verified restore of bytes that match the record, or a
fail-closed retrace with the workspace untouched. The cache storage layer was not
redesigned, and no existing invariant needed to be weakened to obtain this.

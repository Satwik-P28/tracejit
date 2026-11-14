# TraceJIT Correctness Obligations

## Reuse invariants

1. **Guard completeness is necessary.** A candidate is reusable only if every compiled guard passes under
   the active `GuardMode` and the current runtime identity.
2. **Contract identity is exact.** A native record and a controlled-contract record never share a reuse
   decision. The contract identifier is in both the lookup key and the selection check.
3. **No partial exposure.** A corrupt stdout, stderr, or output object must not expose bytes or mutate a
   destination. Streams are verified before outputs are restored; output objects are verified and staged
   before the first rename.
4. **Candidate failures are isolated.** A malformed candidate is skipped; it cannot cause a different
   candidate's content to be served. If no valid candidate exists, the command executes.
5. **Deletion is conservative.** A recorded deletion is restored only when the path is absent or is a
   single-link regular file. Anything else is a precondition failure.
6. **Output preconditions are checked before mutation.** Hard-linked destinations, symlink ancestors,
   directories, and unsupported file types are refused.
7. **Inherited stream state is reproduced or refused.** The recorded start offset and content are
   validated; the seek is probed before output restoration and applied after successful restoration.
8. **Uncertainty fails closed.** `UNKNOWN`, `NONDETERMINISTIC`, and `EMPIRICALLY_STABLE` do not reuse in
   V1. `PROVEN` requires installed seccomp and Landlock, not a capability report.
9. **Corruption is never repaired by serving it.** A failed BLAKE3 verification is a miss and retrace;
   the object may be replaced only by bytes whose hash matches its name.
10. **Historical bytes are not rewritten.** A newer observation creates a new version; it does not edit
    an older record or artifact.

## Non-atomicity

`restore_outputs` is a phased transaction with rollback on ordinary errors. It is not a durable
multi-file transaction:

- a hard process kill can leave a mixed workspace;
- there is no recovery journal;
- restoration replaces directory entries, so inode identity and open file descriptions are not
  preserved;
- `PROVEN` enforcement constrains syscalls during execution, but does not make restoration atomic.

Any documentation or UI claim must state this boundary.

## Cache schema

- Current on-disk schema: `user_version = 2`.
- v1 migration copies all rows in one transaction and changes the primary key from `lookup_key` to
  `execution_id`.
- At most eight candidates are retained per identity.
- A missing/corrupt execution JSON is not a reason to serve a different record; valid siblings may still
  be evaluated independently.

## Output metadata

Version-2 artifacts require mode, uid, gid, atime, and mtime for a file, and no content/metadata for a
deletion. Legacy records fail closed. This is necessary because the cache's read of an output must not be
mistaken for the tool's own metadata effect.

## Enforcement

Local host: `landlock no`, `proven no`. A local `SKIP` is not a pass. Hosted CI at `a11ae4b` previously
reported Landlock ABI 8 and a successful integration run, but the Phase 3A commit needs its own observed
run before it can claim end-to-end `PROVEN`.

## Remaining assumptions

- The traced executable is not modified between identity hashing and `execve`; the final window remains
  open and documented.
- The cache root is owned by the invoking user and is not replaced by a symlink after validation.
- Candidate records are decoded from a local SQLite database; a malicious local cache owner is outside
  the threat model.
- Filesystem rename and link semantics are those of the mounted Linux filesystem. Unusual filesystems
  that violate ordinary POSIX expectations are not covered.
- Anonymous and writable file-backed `MAP_SHARED` mappings are refused (`UNKNOWN`); they are not
  replayed. See `docs/research/EXECUTION_EQUIVALENCE.md` for the Phase C contract surface.

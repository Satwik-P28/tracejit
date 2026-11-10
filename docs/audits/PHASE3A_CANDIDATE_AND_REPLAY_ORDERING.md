# Phase 3A: Candidate Retention and Replay Ordering

Status: locally verified and hosted-verified at `3e7f820` (run `42896870132`); no local `PROVEN` claim added.

Starting development tip: `a11ae4b`. The implementation branch is the existing development branch plus
the preceding Phase 2T audit commit and this change. No pushed commit existed for this work at the time
this report was written.

## Findings

### F1 (high): cached streams were verified after output restoration

`run()` called `cache.restore_outputs()` before `cache.get_bytes(candidate.stdout/stderr)`. A corrupt
stdout or stderr object therefore aborted the hit only after cached files had replaced workspace files.
The command was then retraced from a workspace that was not its original pre-state.

Fix: both stream objects are read and BLAKE3-verified before any output destination is touched. A
corrupt stream is treated as a cache miss; no cached bytes are exposed and no file is mutated. Output
objects are still verified and staged by `restore_outputs` before its first rename.

The test gate is `cargo test -p tracejit-cli --test linux_integration`, which now covers 42 Linux
integration cases. The existing corruption test continues to require that no cached bytes are exposed
and that recovery names the corruption.

### F2 (medium): one execution record replaced every alternate input state

`executions.lookup_key` was a SQLite primary key and `put_execution()` used
`ON CONFLICT(lookup_key) DO UPDATE`. File content is a guard, not part of the lookup key, so tracing
input B silently replaced input A. Returning to A retraced even though A's record was still valid.

Fix: schema version 2 keys records by `execution_id` and indexes `(lookup_key, updated_unix_ms)`.
`find_candidates()` returns newest-first candidates for an identity. `run()` validates each candidate's
guards and only then attempts reuse. At most eight candidates are retained per identity; the record just
written plus the seven newest alternates survive pruning. The current record is explicitly excluded from
the prune set, so same-millisecond writes cannot delete the row they just inserted.

The v1 table is migrated in one SQLite transaction. A crash leaves the old table and `user_version`
untouched. `v1_cache_is_migrated_without_losing_its_record` verifies the migration and permits two rows
with the same lookup key.

### F3 (medium, fixed during implementation): pruning could select the current row

The first prune query used `LIMIT -1 OFFSET 8` without excluding the current `execution_id`. If nine
writes shared a millisecond timestamp, the current row could sort into the discard tail and its JSON
file would be removed after commit. Pruning now filters the current record before choosing the tail.

### F6 (high, found by hosted CI): an absent stat-only dependency refused enforcement

The hosted `2aa662d` run failed `enforced_execution_is_proven_reused_and_invalidated` at the second
`--enforce` invocation. The report said `classification: "Guarded"` and `enforcement unavailable for
the recorded output policy; execution remains guarded`. The dependency profile included an absent
`Metadata` observation for `/etc/ld.so.preload`, and `policy_from_record` returned `None` whenever any
dependency path did not exist.

Fix (`7358720`): stat-only dependencies (`Metadata`, `FilesystemStats`, `SymlinkMetadata`) may be
negative observations and are omitted from the sandbox's readable paths when absent. Dependencies that
the child must actually open or execute still require existence and fail closed otherwise.

### F7 (high, found by hosted CI): the ELF interpreter was missing from the sandbox policy

After F6, hosted run `42891829903` at `e77e03f` built the policy but still returned `Guarded` with
`Permission denied` from `execve`. The target is dynamically linked, and the kernel executes its
`PT_INTERP` interpreter before tracing begins, so the interpreter was absent from the recorded
dependencies and Landlock denied the execution.

Fix (`3e7f820`): `policy_from_record` reads `PT_INTERP`, verifies the interpreter exists, and adds it
to the readable paths. A missing interpreter still refuses enforcement.

### F4 (residual, not fixed): restoration is not a single atomic multi-file transaction

`restore_outputs` validates, stages, backs up, and renames in phases. A normal error in a later rename
rolls earlier renames back. A hard kill between renames can still leave a mixed workspace and stray
temporary or backup names; there is no recovery journal. The contract is pathname-visible equivalence,
not inode equivalence. Hard-linked destinations and unsafe deletions remain refused. This phase did not
add an inode-preserving or crash-recovery storage engine.

### F5 (residual, environmental): end-to-end `PROVEN` is not executable here

This host has seccomp but no Landlock. `doctor` reports `landlock no` and `proven no`; the new
`enforced_execution_is_proven_reused_and_invalidated` test reports `SKIP` locally. Hosted CI passed at
`a11ae4b` with Landlock ABI 8. The first Phase 3A run at `2aa662d` failed for F6, and the next run at
`e77e03f` failed for F7. The final run `42896870132` at `3e7f820` passed every step, including Doctor,
Linux integration and Demo. That is hosted evidence, not a local reproduction; the local test remains
`SKIP`.

## Changed behavior

- Alternate guarded records are retained across `A -> B -> A`.
- A malformed candidate is skipped independently; one bad JSON record cannot make a valid sibling
  unusable.
- All cached output and stream objects are verified before output mutation.
- Inherited-stream seek reproducibility is probed before restoration; the probe restores the recorded
  start offset on failure.
- Cache schema is now version 2. Existing v1 databases migrate; no record bytes are dropped.
- Enforcement adds the executable's verified ELF `PT_INTERP` to the readable policy.

## Verification

Commands were run from the workspace root with the Rust toolchain on `PATH`:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture --test-threads=1
cargo build --release --workspace
python3 benchmarks/repos/candidate_reuse.py \
  --binary target/release/tracejit \
  --baseline .baseline/target/release/tracejit \
  --sessions 5 \
  --output benchmarks/results/phase3a/candidate-reuse.json
```

Results:

- fmt: pass
- Clippy with `-D warnings`: pass
- workspace tests: 128 passed, 0 failed
- Linux integration: 42 passed, 0 failed; `PROVEN` test SKIP locally
- release binary: `ce80ac96ef38159b7044c90642d8f1f83233db2ddf268827eec09a2a73573354`
- A/B/A, five sessions, using the pre-change binary `3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`:
  - new binary third invocation: `Reused` in 5/5 sessions, 13.841662 ms median wall
  - pre-change binary third invocation: `Executed` in 5/5 sessions, 20.572657 ms median wall
  - all output bytes correct in both arms
- raw result: `benchmarks/results/phase3a/candidate-reuse.json`

This is a small A/B/A fixture, not a general workflow benchmark. It measures the candidate-retention
decision and wall time for one guarded file copy; it does not establish that TraceJIT beats a build
system or a content cache.

Hosted verification: run `42896870132` at `3e7f820` passed all steps; the Linux integration step
includes the enforced `PROVEN` reuse test. This is a hosted result, not a local reproduction.

## Remaining obligations

1. Measure candidate lookup and guard-validation cost with larger candidate sets; the current bound of
   eight is a policy choice, not a measured optimum.
2. Add an independent test for a corrupt stdout object with a workspace state that would reveal the
   old late-restore ordering. The current regression proves the behavior at the cache level and in the
   integration suite, but it does not isolate that transient state.
3. Do not describe pathname restoration as atomic or inode-equivalent.

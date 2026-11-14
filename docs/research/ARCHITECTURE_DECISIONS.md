# TraceJIT Architecture Decisions

## ADR-3A-001: Retain a bounded set of guarded candidates per lookup key

**Decision:** `executions` is keyed by `execution_id`, with an index on `(lookup_key, updated_unix_ms)`.
Keep at most eight records per identity. Reuse is chosen by validating each candidate's guards.

**Context:** Input contents are guards, not key material. A single row per lookup key made A/B/A
retrace and discarded valid work.

**Rejected alternatives:**

- Put input hashes into the lookup key. This would require knowing every input before execution and would
  duplicate the guard mechanism; it also makes a miss depend on complete dependency discovery.
- Unbounded history. It improves reuse but grows SQLite and candidate validation without a measured
  bound.
- A separate side index keyed by a synthetic input digest. It adds a second source of truth and does not
  solve unknown dependencies.

**Trade-off:** Up to eight guard validations per hit. The benchmark measures only a two-record case; the
bound needs a cost experiment.

## ADR-3A-002: Verify streams before output restoration

**Decision:** Read and hash cached stdout/stderr, then validate output preconditions and stage output
objects, then rename. Probe inherited-stream seekability before restoration; apply offsets after.

**Context:** A late stream failure used to occur after files had been replaced.

**Residual:** Restoration is still not a single atomic multi-file transaction across a hard kill. Do not
claim otherwise.

## ADR-3A-003: Keep pathname-visible restoration

**Decision:** Continue replacing directory entries with CAS content and replaying captured metadata.
Refuse hard-linked destinations, unsafe deletions, symlink ancestors and unsupported outputs.

**Rejected alternatives:**

- Inode-preserving rollback by copying old content. It introduces crash-recovery and open-descriptor
  obligations that the current contract does not promise.
- OverlayFS per command. It is a plausible future managed-workspace design, but it changes the product
  contract and was not justified by the measured workloads.

## ADR-3A-004: Do not add workflow-level caching yet

**Decision:** This cycle does not add a scheduler, dependency graph, speculative execution, remote cache,
or distributed worker.

**Reason:** The Phase 2T negative result shows that correct Make/Ninja and content-cache baselines already
dominate the measured incremental pipeline. Workflow ownership is a separate product decision, not a
small extension of a command cache.

## ADR-3A-005: No fs-verity or chunked CAS without an invalidation model

**Decision:** Keep whole-object BLAKE3 verification in this cycle.

**Reason:** fs-verity can accelerate immutable-file checks, but writable inputs, mount policy changes, and
digest availability need explicit semantics. FastCDC changes artifact identity and restore behavior.
Neither is justified by a measured bottleneck yet.

## ADR-3A-006: Preserve the negative competitive result

**Decision:** Keep Phase 2T's Make/Ninja/content-cache comparison in the documentation and do not replace
it with a more favorable microbenchmark.

**Reason:** The project's value depends on an honest boundary: automatic discovery and recovery from
suspect outputs, not general incremental build speed.

## ADR-C-001: Refuse anonymous MAP_SHARED

**Decision:** Classify anonymous `MAP_SHARED` as `UNKNOWN`. Keep anonymous private `mmap` process-internal.

**Context:** Anonymous shared mappings are cross-fork shared memory with no file write stream. Treating
them as internal (as private anonymous maps are) would miss untracked mutation channels.

**Rejected alternatives:** Tracking page-level stores; allowing shared anon maps inside a single-threaded
tree. Both under-approximate visibility after `clone`/`fork`.

## ADR-C-002: Hard-link creation stays unmodeled

**Decision:** Successful `link`/`linkat` is an explicit `UNKNOWN` effect. Restore remains pathname-visible
CAS rename and continues to refuse multi-link destinations.

**Reason:** Native hard-link creation shares an inode; replay cannot honestly recreate that aliasing
without an inode-preserving restore contract.

## ADR-C-003: Typestate the hit expose path

**Decision:** In `tracejit-core`, require `GuardsPassed` → verified streams → `expose_after_restore`
before a `Reused` report can carry cached stdout/stderr.

**Reason:** The ordering already existed procedurally; typestate makes skipping artifact validation a
type error inside the hit loop. It does not close validate→restore TOCTOU or crash-atomicity.


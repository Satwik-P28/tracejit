# TraceJIT Research Graph

Status: initial graph for Phase 3A. This is a working record, not a claim map.

## Legend

- **P**: observed problem
- **H**: hypothesis
- **M**: mechanism or source-code concept
- **E**: experiment or empirical result
- **C**: counterexample or correctness obligation
- **N**: new direction

Statuses: `fixed`, `verified`, `unverified`, `rejected`, `open`.

## Nodes

### P1 — One record per command identity

`executions.lookup_key` was a primary key. Inputs are guards, so tracing B replaced A.
Status: `fixed`. Evidence: `crates/tracejit-cache/src/lib.rs`; `docs/audits/PHASE3A_CANDIDATE_AND_REPLAY_ORDERING.md`.

### P2 — Cached streams verified after output restoration

The hit path restored files before reading stdout/stderr objects. A corrupt stream could force a retrace
from a mutated workspace.
Status: `fixed`. Evidence: `crates/tracejit-core/src/lib.rs::run`; integration corruption test.

### P3 — Multi-file restoration has no recovery journal

A kill between renames can leave a mixed workspace. Normal failures roll back, but there is no durable
journal.
Status: `open`; deliberately not claimed as atomic. See C3.

### P4 — Guard validation repeatedly hashes unchanged inputs

Strict validation reads and hashes dependencies. This is the dominant warm-hit cost for large inputs.
Status: `open`. No fs-verity or digest cache was added in this phase.

### P5 — Controlled execution changes semantics

Virtual clocks, random streams, and process identity can make more workloads reusable, but only inside an
explicit contract. Native and controlled records must not be interchangeable.
Status: `open`; `allocator-entropy-v1` remains opt-in and outside `PROVEN`.

### P6 — Workflow-level reuse is not implemented

TraceJIT caches individual commands. It does not own a build graph, schedule independent work, or retain
intermediate states across an entire workflow.
Status: `open`; no scheduler was added.

### H1 — Retain multiple guarded candidates per identity

Keep a bounded set of records for one lookup key, verify each candidate's guards, and reuse the one that
matches. This should make A/B/A reuse possible without weakening validation.
Status: `verified` for one fixture. Evidence: E1; 5/5 sessions reused versus 0/5 on the pre-change binary.

### H2 — Verify all cache objects before any visible mutation

Read stdout, stderr, and output objects first; only then restore output paths and apply inherited-stream
offsets. This should remove the late-failure path.
Status: `fixed`; no independent transient-state test yet.

### H3 — Authenticated file digests could reduce guard cost

fs-verity or a kernel-maintained digest could let a guard trust an immutable file without re-reading all
bytes, provided the digest is bound to the exact file identity and mount policy.
Status: `unverified`. No implementation. Requires a sound invalidation model for writable files.

### H4 — Content-defined chunking could reduce artifact storage and restore cost

FastCDC-style boundaries could deduplicate large, shifting outputs and reuse unchanged compressed frames.
Status: `unverified`. BLAKE3 whole-object CAS remains; chunking would change storage semantics and needs a
separate artifact schema.

### H5 — Effect-model refinement can remove unsound refusals

Counterexample-guided refinement of syscall models could admit more real workloads without a broad
allowlist.
Status: `open`; not attempted here.

### M1 — ccache direct-mode manifest

ccache stores a direct-mode manifest containing references to results and the paths and hashes of
include files; it validates those hashes before reuse. This is a compiler-specific instance of a
multi-result, content-keyed dependency record. Source: <https://ccache.dev/manual/latest.html>.

### M2 — Salsa red-green validation

Salsa tracks a database revision and re-executes a tracked function when its inputs may have changed;
if a dependency is re-executed but produces the same value, downstream validation can stop. This is a
potential model for workflow-level validation, not for an arbitrary traced process. Source:
<https://salsa-rs.github.io/salsa/reference/algorithm.html>.

### M3 — Firebuild interposition and shortcut cache

Firebuild describes itself as an automatic build accelerator that caches command outputs and replays
them for equivalent commands. Its documented interception uses a preloaded library for dynamically
linked processes. Relevant competitive baseline; not reused in TraceJIT. Sources:
<https://github.com/firebuild/firebuild>, <https://firebuild.com/>.

### M4 — Landlock and seccomp enforcement

The current `PROVEN` definition requires installed seccomp and Landlock policy, not merely observed
syscalls. This remains the enforcement boundary. Source: `crates/tracejit-sandbox/src/lib.rs`.

### C1 — No reuse without passing guards

Every candidate must pass all compiled guards before its output or streams are exposed. Candidate
ordering must never turn a newer failed record into an implicit fallback.

### C2 — No native/controlled identity mixing

The contract identifier is part of the lookup key and is checked again before reuse.

### C3 — Pathname-visible, not inode-visible

Restoration replaces directory entries. Hard-linked destinations and unsafe deletions are refused; open
descriptors and inode identity are outside the contract.

### C4 — Fail closed on incomplete observations

Malformed candidate JSON is skipped per candidate; if no valid candidate exists, the command executes
rather than serving partial data. A corrupt object is never exposed.

## Edges

- P1 -> H1 -> E1
- P2 -> H2
- P4 -> H3, H4
- P5 -> M4
- P6 -> M2
- H1 -> C1, C3
- H3 -> C3
- H4 -> C3
- M1 -> H1 (conceptual only)
- M3 -> competitive comparison, not implementation

## Next experiments

1. Push the current branch and observe `RESULT proven-reuse PASS` in hosted CI.
2. Measure candidate count versus lookup/validation cost at 1, 2, 4, 8, and 16 records.
3. Build a fixture where a corrupt stdout object would have been discovered after output mutation and
   assert the workspace remains at its original bytes.
4. Profile strict file hashing on a multi-megabyte dependency, then decide whether fs-verity is worth a
   prototype.
5. Only after process-level validation is cheap enough, prototype a workflow-level graph on one
   realistic multi-command recipe.

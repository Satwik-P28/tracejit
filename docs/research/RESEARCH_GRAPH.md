# TraceJIT Research Graph

Status: Phase 3E. This is a working record, not a claim map.

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

### P7 — Output-presence guards are semantically necessary

A first build records a negative `FileMetadata` guard for its own destination. The next run sees
that destination and must retrace; treating the record as an absent-output pre-state for an arbitrary
program would be unsound because presence can steer the written bytes.
Status: `verified` as a necessary invalidation, not fixed. Evidence: E-3B-01; C5.

### P8 — Candidate cost grows with retained records

Record decode and SQLite lookup grow with the number of retained candidates; guard validation stayed
near 1 ms for the small scaling fixture. At 32 candidates a worst-case hit is as expensive as a miss.
Status: `measured`; default bound remains 8. Evidence: E-3B-02.

### P9 — Strict content hashing is linear and expensive at scale

BLAKE3 validation reaches about 2.58 GiB/s on this host, with 99.4 ms at 256 MiB. The complete warm
path also copies the output, so a hash-only optimization cannot remove that separate cost.
Status: `measured`; no trust model changed. Evidence: E-3B-04.

### H1 — Retain multiple guarded candidates per identity

Keep a bounded set of records for one lookup key, verify each candidate's guards, and reuse the one that
matches. This should make A/B/A reuse possible without weakening validation.
Status: `verified` for one fixture. Evidence: E1; 5/5 sessions reused versus 0/5 on the pre-change binary.

### H2 — Verify all cache objects before any visible mutation

Read stdout, stderr, and output objects first; only then restore output paths and apply inherited-stream
offsets. This should remove the late-failure path.
Status: `verified`; independent stdout and stderr transient-state regressions pass. Evidence: E-3B-03.

### H3 — Authenticated file digests could reduce guard cost

fs-verity or a kernel-maintained digest could let a guard trust an immutable file without re-reading all
bytes, provided the digest is bound to the exact file identity and mount policy.
Status: `unverified`. No implementation. Requires a sound invalidation model for writable files.
Measured hashing cost: E-3B-04; 99.4 ms at 256 MiB.

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

### H6 — Dependency-signature index or cost-aware candidate ranking

A cheap input-identity signature could avoid decoding every candidate, or reorder candidates by
observed cost. Both need a proof that a skipped candidate cannot have passed, and that ranking does not
create an implicit fallback. Measured decode cost (E-3B-02) makes this plausible; no implementation was
added because no sound signature was established. Status: `open`.

### H7 — fs-verity authenticated immutable inputs

fs-verity can bind a Merkle digest to an immutable file and reject writes through the file. It is a
precise trust boundary only for immutable storage and a supported filesystem. Status: `rejected for
now`; ordinary writable fixtures dominate and setup is not portable. Source:
<https://docs.kernel.org/filesystems/fsverity.html>.

### H8 — Event-assisted invalidation with overflow recovery

fanotify can report mutations, but a watcher must handle queue overflow, lost events, mount changes,
renames, and startup gaps by falling back to content validation. Status: `unverified`; an event-only
mode would be unsound. Sources: <https://man7.org/linux/man-pages/man7/fanotify.7.html>,
<https://docs.kernel.org/filesystems/overlayfs.html>.

### M5 — sccache dependency manifests and storage

sccache records compiler inputs and cache keys and uses local or remote storage. Its manifest model is
compiler-aware, whereas TraceJIT observes arbitrary processes; the useful transfer is explicit
dependency identity, not a new storage backend. Source: <https://github.com/mozilla/sccache>.

### M6 — Adapton demand-driven incremental computation

Adapton tracks dirty edges and recomputes only affected nodes. It is a workflow-level model; it does
not supply filesystem observation or process-effect semantics. Status: conceptual only. Source:
<https://github.com/adapton/adapton.rust>.

### M7 — Hermit controlled execution

Hermit isolates and makes deterministic selected nondeterministic interfaces inside a controlled
runtime. This supports the existing separation: controlled experiments must not be mixed with native
records. Source: <https://github.com/facebookexperimental/hermit>.

### M8 — CEGAR for syscall-model refinement

Counterexample-guided abstraction refinement can add a narrow model only after a concrete failing
trace disproves the current abstraction. The native census supplies counterexamples, but no refinement
loop was automated. Status: `open`. Source: Clarke et al., CAV 2000,
<https://link.springer.com/chapter/10.1007/10722167_15>.

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
- P7 -> C5 (necessary invalidation)
- P8 -> H6
- P9 -> H3, H7, H8
- H6 -> C1
- H7 -> C3
- H8 -> C4
- M1 -> H1 (conceptual only)
- M3 -> competitive comparison, not implementation
- M5 -> P8 (dependency identity only)
- M6 -> P6 (workflow model only)
- M7 -> C2
- M8 -> P5 (refinement method only)

### C5 — Do not generalize negative output metadata

A negative `stat` of a program's own output is an input dependency, not permission to inject an
absent-output pre-state. Evidence: `un_audited_program_does_not_reuse_across_its_output_presence_change`;
new `output_presence_stdout`/`_stderr` cases. Status: `enforced`.

### C6 — Candidate bound is a cost bound, not a correctness bound

Every retained candidate still validates fully. The bound may change hit rate and cost, never the
requirement that a candidate's guards pass. Status: `enforced`.

### P10 — Verification time was attributed to replay

Phase 3B's stable-workflow harness decompressed the three bzip2 outputs after each command and counted that work in the round wall time. The 231 ms figure was therefore not TraceJIT replay latency.

Status: `rejected measurement`, corrected by E-3C-01. Evidence: `benchmarks/results/phase3c/latency.json`.

### P11 — `/dev/null` seek was caught by the inherited-fd blanket refusal

The census's `lseek` blocker was an inherited `/dev/null`, not a regular file. Every admitted seek on `/dev/null` returns zero and cannot affect a later read.

Status: `fixed narrowly`; exact path only, E-3C-03 and `dev_null_seek_is_reusable`. Other inherited character devices and directory seeks remain refused.

### H9 — Lazy candidate decoding preserves full validation

SQLite can return encoded candidate records newest-first; decode only the candidate currently being validated. A newest hit pays one decode, while an oldest target still decodes all candidates.

Status: `prototype verified`; E-3C-02. This is not a fingerprint shortcut and cannot skip guards.

### H10 — Frequency-aware candidate ordering

A safe frequency index could reduce oldest-target cost, but it needs a persisted hit count or preferred candidate and must fall back to all candidates when the preferred one fails. Status: `open`; no frequency index was added.

### H11 — Leave already-matching outputs unchanged

Skipping a rewrite saves restore time, but changes inode replacement, ctime, hard-link and ownership semantics. Status: `rejected for native equivalence`; only a managed-workspace contract with crash recovery could reconsider it.

### P12 — Descriptor pathname is not descriptor identity

`/proc/<pid>/fd/<fd>` is a magic link to the open object, but its textual target is not proof that the object is `/dev/null`; bind mounts and namespaces can substitute another object. The Phase 3C path-only guard was unsound in principle.

Status: `fixed` by `fstat` of the inherited descriptor with `S_ISCHR` and `st_rdev == makedev(1, 3)`. Evidence: E-3D-01; `null_device_identity_is_not_path_only`.

### P13 — Eager SQLite payload fetch looked lazy

Phase 3C deferred JSON decoding, but `find_candidates` still fetched every `record_json` in one query. Decoding one-at-a-time is not incremental retrieval.

Status: `fixed experimentally` by ID-first retrieval plus one-record fetches. Evidence: E-3D-02. No performance win was measured; the default bound is unchanged.

### P14 — Native census blockers are different information sources

The nine workloads fail for distinct reasons: `getrusage` is execution-produced state; pipe `fstat` and short reads expose scheduling; clocks, randomness and PIDs are unstable observations; `epoll_create1` is an unmodeled object lifetime; output restoration needs a contract.

Status: `measured`, not fixed. Evidence: E-3D-03; `benchmarks/results/phase3d/census-native/`.

### H12 — Controlled execution is required for unstable observations

A guard can only pin an external state that is stable before the command runs. Clocks, entropy, process identity, `getrusage`, and pipe scheduling are not such states. Hermit-style record/replay or an explicit virtual clock/entropy/PID contract is required; an ordinary guard cannot soundly represent them.

Status: `supported by causal inspection`; no controlled runtime was implemented. Evidence: E-3D-03 and the census reason stream.

### H13 — Compact headers can reduce I/O but never validate

A candidate-header table could return identity, generation, and a preferred-candidate hint without payloads. A stale or missing header must fall back to all candidates and every candidate must still pass full guards.

Status: `open`; the ID-first prototype is a necessary precursor, not evidence of a win. See P13/E-3D-02.

### H14 — Effect types need object kind and information source

A syscall name alone is not enough: `fstat` on a regular file is guardable, `fstat` on a pipe exposes buffered bytes, and `lseek` on null is constant-zero. Effect typing should include the object kind, observation source, and whether the value is execution-produced.

Status: `open` research direction; this is the common explanation for P11, P12 and P14.

### M12 — Competing incremental/dependency systems

- Hermit: deterministic record/replay of scheduling and nondeterministic sources; a competitor to native reuse for P14.
- Firebuild: observed process dependencies; useful for coverage, not a substitute for guards.
- Salsa and Adapton: revisioned queries and demand-driven invalidation; useful for candidate metadata, not OS-level proof.
- ccache/sccache: manifest and direct-mode indexing; the closest model for compact candidate headers.
- CEGAR: counterexample-guided refinement of a sound abstraction; it can add object-kind predicates, never delete a failing guard.
- Linux `statx`, `fs-verity`, `fanotify`, `openat2`/`RESOLVE_*`: stronger identity and change detection than path strings, but no help for clocks, entropy or pipe scheduling.

Status: `source map`; these are competing approaches, not claims of equivalence.

### P15 — Automatic admission swallowed cache errors

`find_candidate_by_id(...).ok()` converted SQLite failures into an empty admission set. A missing row from concurrent pruning is a legitimate miss; a database error is not.

Status: `fixed` on PR #6 (`a86b8e2`) with a cache regression. Evidence: E-3E-01.

### P16 — Epoll creation is not event-loop compatibility

The Pillow trace creates an epoll instance with `EPOLL_CLOEXEC` and immediately closes it; it never registers or waits. Creation/close are process-internal, but `epoll_ctl`/`epoll_wait` observe readiness and scheduling.

Status: `measured and narrowly fixed`; create/dup/close admitted, control/wait refused. Evidence: E-3E-02. Census remains 0/9.

### P17 — Python's remaining wall is controlled execution

After epoll, both Python workloads refuse on `getrandom`, monotonic/realtime clocks, and `getpid`/`getppid`/`gettid`. These are runtime observations, not guardable external inputs. Identical output does not make them deterministic.

Status: `measured`, no contract enabled. Evidence: E-3E-03.

### H15 — Restricted internal-descriptor lifecycle

A descriptor whose create/close operations have no observable effect may be modeled without modeling its readiness. Duplication and `CLOEXEC` preserve the object, but any operation that can observe readiness must fall back to refusal.

Status: `verified` for create/dup/close; open for leaks, fd exhaustion, and fork/exec tests.

### H16 — Controlled Python requires an audited contract

A Python contract must fix clocks, entropy and identity per exact interpreter build/call site, and must keep native and controlled records separate. A broad syscall rewrite is not justified by the current evidence.

Status: `open`; no controlled record produced. The existing compiler/allocator contracts are too narrow to reuse.

### M13 — Object × operation × provenance

The Phase 3D/3E results fit one typed distinction: object identity and operation semantics determine whether an observation is external, execution-produced, or schedule-dependent. Only external stable observations are guardable; virtualizable ones need a contract; execution-produced/schedule observations need controlled execution or refusal.

Status: `design direction`; no common type system implemented. Sources: Hermit, rr, Firebuild, Salsa, Adapton, CEGAR, epoll(7).

## Next experiments

1. Test a frequency-aware candidate header index against the 64-candidate oldest-target case, with a fallback that validates every candidate when the preferred header misses.
2. Re-run the latency harness under a controlled writeback policy to separate CAS restore from host fsync variance.
3. Model a managed-workspace unchanged-output contract, including inode, ctime, hard-link, ownership and crash-recovery obligations, before implementing it.
4. Re-run the native census after a second narrow model (not a global syscall exemption) and require an actual workload reuse before claiming compatibility progress.
5. Only after process-level validation is cheap enough, prototype a workflow-level graph on one realistic multi-command recipe.

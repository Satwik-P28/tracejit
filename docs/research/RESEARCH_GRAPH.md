# TraceJIT Research Graph

Status: Phase 3C. This is a working record, not a claim map.

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
- P12 -> C4, C2
- P13 -> H12, C2

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

### P12 — Inherited `/dev/null` read was classified by pathname

The read path admitted a descriptor recorded as `/dev/null` without checking the open object. The
fix requires `fstat` character device 1:3 for `read`, `pread64` and `readv`; otherwise the guarded
regular-file stream model applies or reuse is refused. Status: `fixed narrowly`; E-3F-01. Bind-mount
substitution was not testable on this host.

### P13 — CPython's controlled frontier is call-site specific

The exact host build (CPython 3.12.3, ELF build ID `337d65cf00021797985cc9f77c0cc334a9fbeb38`)
issues `getrandom`, `getpid`/`getppid`, `gettid` and vDSO clock observations during startup, while
application-level calls share the same interfaces. A broad Python exemption is therefore unsound; an
audited runtime-only contract or conservative refusal is required. Status: `open`; E-3F-02.

### H12 — Audited initialization-only CPython observations

Permit only enumerated call sites in one exact build, beginning with the 24-byte `getrandom` at
`Py_InitializeFromConfig+0x198`, and keep application-level observations refused. Status: `open`;
requires multiple equivalent controlled cold runs and a separate controlled identity.

### H9 — Lazy candidate decoding preserves full validation

SQLite can return encoded candidate records newest-first; decode only the candidate currently being validated. A newest hit pays one decode, while an oldest target still decodes all candidates.

Status: `prototype verified`; E-3C-02. This is not a fingerprint shortcut and cannot skip guards.

### H10 — Frequency-aware candidate ordering

A safe frequency index could reduce oldest-target cost, but it needs a persisted hit count or preferred candidate and must fall back to all candidates when the preferred one fails. Status: `open`; no frequency index was added.

### H11 — Leave already-matching outputs unchanged

Skipping a rewrite saves restore time, but changes inode replacement, ctime, hard-link and ownership semantics. Status: `rejected for native equivalence`; only a managed-workspace contract with crash recovery could reconsider it.

## Phase 3G nodes

### P14 — Independently inherited descriptors were outside the runtime identity

`current_runtime_identity()` modelled stdin but not descriptors above stderr. A child could read fd 9
from `/dev/null` while recording and receive `/dev/zero`, a regular file, a pipe, or a closed
descriptor during replay. The recorded EOF was then served as a hit. Status: `fixed by refusal`;
E-3G-01, E-3G-02.

### H13 — Refuse unmodelled inherited descriptors before cache lookup

A preflight over `/proc/self/fd` is captured before `Cache::open`; after cache initialization but
before candidate lookup it sends any execution with a surviving fd above 2 to the direct path without
reading or writing a reusable record. Descriptors marked
`FD_CLOEXEC` are skipped because they cannot reach the child. A trace-layer `Unknown` effect is a
second line of defence. This is smaller and more stable than adding a descriptor table to the lookup
key. Status: `verified`; E-3G-02.

### C7 — No cached record may contain an unmodelled inherited descriptor

Descriptor identity, offset, flags, shared open-description state and fork/exec inheritance are not
guarded by the current stdin model. Any record that would depend on them must remain ineligible.
Evidence: P14; `inherited_descriptor_beyond_stdin_is_never_reused`,
`concurrent_inherited_descriptor_replacements_are_refused`. Status: `enforced`.

### P15 — CPython's 24-byte startup entropy is the hash secret, not time

`PYTHONHASHSEED=0` removes the 24-byte `getrandom` while leaving the 8-byte allocator probe, clocks
and `gettid`. CPython 3.12.3 source places the 24-byte request in
`Python/bootstrap_hash.c::_Py_HashRandomization_Init`; `_PyTime_AsNanoseconds` is a pure conversion.
The Phase 3F stack attribution was unreliable. Status: `corrected`; E-3G-03, E-3G-04, E-3G-05.

### H14 — Versioned CPython hash-secret contract

A contract could fix the exact `_Py_HashRandomization_Init` call site for one ELF build, but it would
change hash randomization for every `str`/`bytes` hash and must enumerate application-visible
ordering effects. It would not by itself remove clocks or `gettid`. Status: `open`; E-3G-04.

### H15 — Virtualized single-process CPython clocks and identity

A contract could supply monotonic values that advance consistently with timeouts and a fixed
pid/tid, but must cover vDSO entries, all clock APIs, signals, threads, subprocesses and extension
modules. A non-advancing clock changes liveness; a fixed pid changes lock and cache naming. Status:
`unverified`; no implementation.

### H16 — Causal noninterference for CPython observations

Some nondeterministic reads may be provably irrelevant to external effects. Repeated identical
output is not such a proof: a rare branch, file name or timeout can still depend on the value.
Status: `open`; rejected as a shortcut.

### C8 — Native and controlled Python identities remain separate

A controlled Python record cannot validate against native execution. The contract identifier is part
of the lookup key. No native Python record had been admitted at Phase 3G; Phase 3I admits controlled
records only under `python-runtime-v1`, and they remain separate from native records. Status:
`enforced`.

### Edges

- P14 -> H13 -> C7
- P14 -> C7
- P15 -> H14, H15, H16
- H14 -> C8
- H15 -> C8
- H16 -> C8
- P15 -> E-3G-03, E-3G-04, E-3G-05

## Next experiments

1. Test a frequency-aware candidate header index against the 64-candidate oldest-target case, with a fallback that validates every candidate when the preferred header misses.
2. Re-run the latency harness under a controlled writeback policy to separate CAS restore from host fsync variance.
3. Model a managed-workspace unchanged-output contract, including inode, ctime, hard-link, ownership and crash-recovery obligations, before implementing it.
4. Re-run the native census after a second narrow model (not a global syscall exemption) and require an actual workload reuse before claiming compatibility progress.
5. Audit the exact CPython build application-level call sites before enabling any controlled contract; require multiple equivalent cold runs.
6. Recreate the epoll commit on `main` only after adding fork/exec, `RLIMIT_NOFILE` and descriptor-transfer regressions.
7. Only after process-level validation is cheap enough, prototype a workflow-level graph on one realistic multi-command recipe.

## Phase 3H nodes

### P16 — `readdir()` failure was silently treated as an empty descriptor table

The inherited-descriptor preflight used every `NULL` from `readdir()` as end-of-directory and never
consulted `errno`. An interrupted or failed enumeration could therefore look empty and let an
execution with an inherited descriptor reach lookup. The guard now returns an explicit result and
fails closed for `opendir`, `dirfd`, `readdir`, `fcntl(F_GETFD)` and `closedir`; CLOEXEC descriptors
are skipped because the kernel closes them before the target runs. Status: `fixed`; E-3H-01.

### H17 — Preflight-to-exec descriptor race

The scan captures one value, not a stable table. A concurrent parent can change the inherited
descriptor set between the scan and `execve`; a helper that scans and execs without an intervening
window, or a parent invariant, is required. Status: `open`; no exploit claimed. This is separate from
the enumeration error fix.

### P17 — Descriptor-number reuse leaked a directory enumeration record

`ProcessState.enumerations` was keyed by descriptor number and survived `close` and reuse. A new
directory at the same number could append to the old record, making the guard replay a concatenation
that no open file description produced. `forget_descriptor` now clears fd, CLOEXEC and enumeration
state on close, dup/dup2, open, pipe and socket creation. Status: `fixed`; E-3H-02.

### P18 — Directory-entry padding is observable and prevents byte-exact reuse

The controlled Python target reached a candidate and deoptimized because `linux_dirent64` padding
after `.` differed (`sl.` versus zeroes), while names, inode, order and offsets matched. The kernel
does not define padding, but a program can read the whole returned buffer. Canonicalising it would
assume a reader call-site; that proof does not exist. Status: `open`; byte-exact refusal retained;
E-3H-03.

### H18 — Versioned CPython clock/identity watchpoints

A branch-only `tracejit.python-runtime.v1` contract controls CPython's realtime/monotonic
`clock_gettime`, `gettimeofday`, seconds `time`, `getpid`, `getppid` and `gettid` for the exact
build `337d65cf...`, records executable hash/build ID, refuses clone/fork and keeps the contract in
the cache identity. It removes the target's clock, identity and randomness blockers but does not
produce a target hit because P18 fails. It is a watchpoint prototype, not a claim of native
equivalence. Status: `prototype`; E-3H-03, E-3H-05.

### H19 — Startup-only clock admission from a syscall class

`Python/pytime.c` and `Modules/timemodule.c` map application and runtime clock calls to the same
`clock_gettime` effects. TraceJIT records no caller or instruction pointer for ordinary `Clock`
effects, so a startup-only whitelist cannot be implemented soundly from the syscall class.
Status: `rejected`; requires per-instance call-site/instruction signatures; E-3H-04.

### C9 — A controlled Python record requires the full effect sequence

An executable/build-ID match and fixed clock/identity values are insufficient. The record must also
have verified call sites, consistent clock progression, single-process/thread semantics, complete
output and filesystem effects, repeated independent cold runs and explicit mismatch rejection. The
smoke hit does not satisfy these obligations; no general Python reuse is admitted. Status:
`enforced as experimental`; H18.

### H20 — Symbol-level identity virtualisation

`LD_PRELOAD` can replace `clock_gettime`, `gettimeofday`, `time`, `getpid` and `getppid`, but CPython
issues `gettid` with a direct syscall. A symbol-only contract therefore cannot cover the thread
identity that `threading.get_native_id()` exposes. Status: `rejected as sufficient`; E-3H-04.

### Edges

- P16 -> H17
- P16 -> C7
- P17 -> P18
- P18 -> C9
- P15 (Phase 3G) -> H18 -> H19
- H18 -> H20
- H18 -> C9
- H19 -> C9
- E-3H-01 -> P16, H17
- E-3H-02 -> P17
- E-3H-03 -> P18, H18, C9
- E-3H-04 -> H19, H20
- E-3H-05 -> H18

## Phase 3H next experiments

1. Add instruction-pointer/caller identity to ordinary clock and `gettid` effects, then retest
   startup-only admission against an application clock counterexample.
2. Decide whether a directory reader's call-site can prove that ABI padding is unobserved; otherwise
   keep the byte-exact guard and report the deopt.
3. Run at least three independent controlled cold executions and a filesystem-effect differential
   before promoting any Python contract.
4. Close the preflight-to-`exec` race with an atomic scan/exec handoff, or keep the refusal bounded
   and state the concurrent-parent limitation.

## Phase 3I nodes

### P16 — `dup2(fd, fd)` erased descriptor state

The Linux same-descriptor `dup2` is a successful no-op. The tracer forgot the destination before
looking up the source, so it lost fd classification, `FD_CLOEXEC` and directory enumeration state.
`dup3(fd, fd)` is `EINVAL` and does not reach the successful path. Status: `fixed`; E-3I-01.
Regression: `7f15832`, `e74f9ee`, `c2f1e9c`.

### P17 — directory padding is uninitialised buffer content, not a stream-boundary defect

`linux_dirent64` alignment padding is not written by the kernel. A user buffer prefilled with
`0xaa`/`0x55` keeps that byte after `getdents64`, while fields and names stay identical. The target's
`sl.`/`ux` bytes are consistent with glibc's `DIR` buffer contents. The audited CPython reader uses
`d_name` only. Status: `A at syscall boundary, C for audited reader`; E-3I-02, E-3I-03.

### H17 — explicit `VirtualZero` contract

Zero alignment padding after `getdents64` and on replay only under the exact `python-runtime-v1`
contract, recording the policy in every request. Native bytes and native guards are unchanged.
Status: `prototyped and controlled hit verified`; target `Reused` 10/10 with correct effects, but no
performance gain. E-3I-03.

### H18 — typed directory-entry guard for an audited reader

Compare semantic fields and call boundaries, excluding padding. It passes the two-fill probe while
byte-exact comparison fails, but it makes padding invisible to a reader that can observe it. Status:
`prototype only, not wired`; would require executable reader identity. E-3I-04.

### C9 — byte-exact native directory guard remains the default

Arbitrary programs can copy or hash all `d_reclen` bytes. Native `DirectoryPaddingPolicy` therefore
stays byte-exact; `VirtualZero` is opt-in and contract-separated. Status: `enforced`.

### C10 — descriptor preflight is fail-closed, with an invariant

Enumeration errors fail the command with status 1 before lookup; there is no direct fallback. The
scan/spawn path is single-threaded and the parent cannot mutate the table, so the earlier
"concurrent parent" race was misstated. A future non-CLOEXEC open between scan and spawn would still
invalidate it; no atomic handoff exists. Status: `behavior tested, invariant open`; E-3I-05.

### Edges

- P16 -> E-3I-01
- P17 -> H17, H18, C9
- H17 -> E-3I-03
- H18 -> E-3I-04
- E-3I-05 -> C10
- E-3I-02 -> P17

## Phase 3I next experiments

1. Hosted CI passed for PR #8 (`43378765278`, `c1c5c4e`) and PR #9 (`43377574220`, `182e9bb`).
2. Do not merge PR #8 before its hosted checks pass; do not merge PR #9's experimental contract.
3. Decide whether a typed reader identity can be made executable and auditable; otherwise keep
   `Native` byte-exact.
4. If clock progression is required, implement an advancing controlled clock with timeout/liveness
   tests instead of the current fixed zero.

## Phase 3J nodes

### H21 — `python-runtime-v2` logical clock

V2 keeps the audited CPython ELF/build-ID and fixed identity but advances realtime and monotonic
clocks by 1 ms per admitted observation. The bounded 1 ms timeout loop goes from 1000 iterations
under v1 to 0 under v2. This is virtual time: sleep, blocking syscalls and scheduler order are not
remapped, and `gettimeofday` is refused because its `timeval` ABI is not the logical `timespec`
payload. Status: `experimental, unmerged`; E-3J-02, E-3J-03.

### P18 — fixed identity is not a process contract

`os.kill(os.getpid(), SIGUSR1)` targets the virtual PID 4242 under both Python contracts and raises
`ProcessLookupError`; direct execution delivers `SIGUSR1`. The attempt is not reusable, but the
first controlled run already differs. Fixed identity is therefore a narrow display/watchpoint, not
general process semantics. Status: `open counterexample`; E-3J-02.

### P19 — repeated virtual observations create guard duplication

A v2 clock probe records 414 `ControlledRuntime` guards naming the same executable. Rehashing the
executable per guard made a warm hit ~0.8 s. A per-validation metadata-generation hash cache keeps
every guard and cuts the same hit to 13.1-13.5 ms. Status: `implemented, soundness boundary
documented`; E-3J-04.

### P20 — controlled reuse has a fixed floor, not a universal speedup

The original ETL's warm report is 21.3 ms (v1) but its cold trace is 181.9-301.0 ms; a ten-warm
complete session remains slower than direct. The 120k-row CSV and 320x240 image workloads have
byte-identical warm outputs and amortize at 2-4 complete runs. Incremental value is workload
duration relative to the ~20-50 ms validation floor, not a property of the contract alone. Status:
`measured`; E-3J-03, E-3J-05.

### C11 — native byte-exact directory guarding remains default

`VirtualZero` is contract-separated; typed projections and cached directory fields are not wired
because a reader can observe padding and the measured directory guard cost is below 1 ms. Status:
`enforced`; E-3J-06.

### Edges

- H21 -> P19
- P18 -> H21 (the identity limitation bounds what v2 may claim)
- P19 -> P20
- P20 -> C11
- E-3J-02 -> H21, P18
- E-3J-03 -> P20
- E-3J-04 -> P19
- E-3J-05 -> P20
- E-3J-06 -> C11

### Graph-of-thoughts chain

`runtime virtualization -> observable effects -> effect provenance -> dependency validation ->
incremental computation -> filesystem replay obligations`

The chain is not a proof of native equivalence. It explains why v1's fixed clock and identity are
insufficient, why v2's logical clock needs sequence-aware guards, why repeated guards should share
an immutable runtime hash, why the original ETL cannot amortize, and why byte-exact filesystem
guarding remains the default.

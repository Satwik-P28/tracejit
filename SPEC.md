# TraceJIT V1

## 0. Codex execution contract

Build the repository exactly from this specification.

Do not ask questions unless blocked by a genuinely impossible requirement.

Do not add features that are not specified.

Do not redesign architecture without a correctness reason.

Prioritize, in order:

1. correctness
2. safety
3. reproducibility
4. low tracing overhead
5. simple architecture
6. performance
7. UI polish

Prefer the smallest correct implementation over abstractions that are not yet needed.

Avoid generated boilerplate, excessive comments, wrapper layers, speculative abstractions, microservices, async runtimes where synchronous code suffices, unnecessary dependencies, and duplicated types.

Every public type/function must exist for a concrete reason.

Use `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, and `cargo test --workspace`.

The final repository must build from a clean Ubuntu environment using documented commands.

Never fabricate benchmark numbers.

Never print a speedup unless it was measured during the current run.

---

# 1. Product thesis

**Can a system automatically infer enough of a process's observable dependencies to safely reuse its computation, while enforcing the assumptions required for that reuse?**

TraceJIT V1 is a Linux execution tracer and guarded computation reuse engine.

A user runs:

```bash
tracejit run -- python report.py
```

First execution:

```text
Tracing execution...

Observed:
  1,284 filesystem reads
  7 environment dependencies
  3 subprocesses
  0 irreversible effects

Classification: GUARDED

Compiled:
  14 runtime guards

Baseline runtime: 8.42s
```

Second execution:

```text
Checking guards...

✓ executable unchanged
✓ input files unchanged
✓ environment unchanged
✓ working directory unchanged
✓ dependency set valid

Execution reused.

Previous execution: 8.42s
Current execution: 37ms
Measured speedup: 227.6x
```

Numbers shown above are illustrative documentation examples only.

The actual CLI must only display measured numbers.

---

# 2. V1 scope

V1 must implement:

- Linux only
- x86_64 first
- Rust
- CLI
- ptrace-based process tracing
- process tree tracing
- filesystem effect capture
- environment dependency capture where technically observable
- working-directory dependency
- process execution dependencies
- clock/randomness detection
- network effect detection
- structured effect model
- dependency reconstruction
- determinism classification
- explicit UNKNOWN effects
- guard compilation
- guarded cache lookup
- local content-addressed storage
- deoptimization/fallback
- optional enforcement sandbox
- seccomp syscall policy
- Landlock filesystem restrictions where supported
- adversarial correctness test suite
- reproducible benchmark harness
- `tracejit explain`
- `tracejit analyze`
- `tracejit run`

V1 does not implement:

- automatic parallelization
- speculative execution
- GPU/CUDA tracing
- distributed caching
- remote execution
- Kubernetes
- model routing
- semantic LLM caching
- GitHub PR bot
- graphical web UI
- macOS
- Windows
- source-code rewriting
- automatic network replay

These may appear only in ROADMAP.md.

---

# 3. Safety model

TraceJIT must prefer refusing reuse over unsafe reuse.

False negative:

```text
TraceJIT reruns something unnecessarily.
```

Acceptable.

False positive:

```text
TraceJIT reuses a result that should have been recomputed.
```

Unacceptable.

Unknown behavior must become:

```text
UNKNOWN
```

not silently treated as deterministic.

---

# 4. Determinism classes

Use exactly:

```rust
pub enum DeterminismClass {
    Proven,
    Guarded,
    EmpiricallyStable,
    Unknown,
    Nondeterministic,
}
```

## PROVEN

Use only when TraceJIT actively constrains execution so the process cannot access undeclared effects.

A valid PROVEN execution requires all applicable enforcement mechanisms to succeed.

At minimum:

- seccomp-BPF restricts disallowed syscall classes
- Landlock restricts filesystem access to declared paths where supported
- network syscalls are denied unless explicitly permitted
- unexpected effect attempts fail execution or deopt
- all relevant dependencies are included in the execution identity

Do not call an execution PROVEN merely because no unexpected behavior was observed.

If enforcement is incomplete:

```text
PROVEN
```

must not be emitted.

## GUARDED

Dependencies were observed and can be revalidated before reuse.

Example:

- input file hash
- binary hash
- argv
- selected environment values
- cwd
- filesystem metadata
- interpreter/runtime identity

## EMPIRICALLY_STABLE

The same relevant observable behavior has occurred repeatedly but structural enforcement is unavailable.

Requirements:

- explicit sample count
- explicit output-equivalence history
- never automatically promoted to GUARDED
- never automatically promoted to PROVEN
- disabled for reuse by default in V1

V1 may report it analytically.

## UNKNOWN

Insufficient evidence or an unmodeled effect exists.

Never reuse.

## NONDETERMINISTIC

Known nondeterminism or irreversible external behavior prevents safe reuse.

Never reuse.

---

# 5. Effect model

Do not use a flat effect enum.

Use structured effects.

Core model:

```rust
pub enum Effect {
    Read(ReadEffect),
    Write(WriteEffect),
    Control(ControlEffect),
    Unknown(UnknownEffect),
}
```

## Read effects

Support at minimum:

```rust
pub enum ReadEffect {
    File(FileRead),
    FileMetadata(FileMetadataRead),
    Environment(EnvironmentRead),
    WorkingDirectory,
    Clock(ClockKind),
    Random(RandomSource),
    Network(NetworkRead),
    KernelState(KernelStateRead),
}
```

## Write effects

```rust
pub enum WriteEffect {
    File(FileWrite),
    Network(NetworkWrite),
    Ipc(IpcWrite),
}
```

## Control effects

```rust
pub enum ControlEffect {
    Spawn(ProcessSpawn),
    Exec(ProcessExec),
    Chdir(PathBuf),
    Signal(SignalEffect),
}
```

Every effect exposes:

```rust
pub struct EffectProperties {
    pub observable: bool,
    pub reversible: bool,
    pub guardable: bool,
    pub cache_key_relevant: bool,
}
```

No effect may disappear because TraceJIT does not understand it.

Unrecognized behavior becomes:

```rust
Effect::Unknown(...)
```

and blocks reuse.

---

# 6. Execution identity

Represent a traced command as:

```rust
pub struct ExecutionIdentity {
    pub executable_hash: Hash,
    pub argv: Vec<OsString>,
    pub cwd: PathBuf,
    pub environment: BTreeMap<OsString, OsString>,
    pub input_dependencies: Vec<InputDependency>,
    pub runtime_identity: RuntimeIdentity,
}
```

Do not blindly hash the entire inherited environment forever.

During discovery, preserve enough environment state to remain safe.

The implementation may later narrow environment dependencies only when justified by observed process access.

Hash algorithm:

```text
BLAKE3
```

Reasons:

- fast
- cryptographically strong
- native Rust ecosystem support
- suitable for content addressing

Canonical serialization must be deterministic.

Do not hash nondeterministically ordered HashMaps.

Use sorted structures or canonical encoding.

---

# 7. Filesystem guards

Guard evaluation order should minimize cost.

For a file dependency:

### Fast path

Compare:

- device
- inode
- size
- modification time

If all relevant metadata matches cached state, optionally accept metadata guard when policy permits.

### Strong path

Calculate BLAKE3 content hash.

Use hashing whenever:

- metadata changed
- metadata cannot establish validity
- strict mode is enabled

CLI:

```bash
tracejit run --guard-mode fast -- command
tracejit run --guard-mode strict -- command
```

Default:

```text
strict
```

for correctness during V1 development.

`fast` may be offered as experimental.

---

# 8. Cache eligibility

V1 may reuse only executions classified:

```text
PROVEN
```

or:

```text
GUARDED
```

and whose guards all pass.

Never reuse:

```text
EMPIRICALLY_STABLE
UNKNOWN
NONDETERMINISTIC
```

unless a future explicit unsafe flag is introduced.

Do not introduce that flag in V1.

---

# 9. Irreversible effects

Treat these conservatively:

- outgoing network writes
- unknown socket communication
- external database mutations
- writes outside captured output set
- IPC with unknown semantics
- device access
- privilege-changing operations
- unmodeled kernel interfaces

Any irreversible or unknown external effect should normally prevent whole-execution reuse.

The first version does not need to cache partial subgraphs.

Whole-command reuse is enough.

---

# 10. Trace architecture

Primary tracer:

```text
ptrace
```

Use:

```rust
nix::sys::ptrace
```

where practical.

Trace descendants using fork/clone/exec events.

Capture at minimum:

- process start
- process exit
- fork/clone
- exec
- open/openat/openat2
- read-related file dependency acquisition
- stat/newfstatat
- access
- chdir/fchdir
- unlink/rename/write-oriented filesystem operations
- socket/connect/send/recv classes
- clock syscalls
- getrandom
- relevant process metadata access

Do not log every `read()` byte operation if `open()` plus descriptor tracking is sufficient to establish the file dependency.

Optimize for semantic effects, not gigantic syscall logs.

Maintain a per-process FD table.

Correctly follow:

- dup
- dup2
- dup3
- close
- fork inheritance
- exec lifecycle

Resolve `/proc/<pid>/fd/<fd>` when needed, but avoid excessive filesystem probes if FD state is already known internally.

---

# 11. TraceIR

Use a compact internal representation.

```rust
pub struct Trace {
    pub execution: ExecutionMetadata,
    pub processes: Vec<ProcessNode>,
    pub effects: Vec<EffectRecord>,
    pub dependencies: Vec<DependencyEdge>,
}
```

Do not build a generic compiler framework in V1.

TraceIR exists only to support:

- analysis
- classification
- guard generation
- explanation
- cache eligibility

Dependency edges:

```rust
pub enum DependencyKind {
    Reads,
    Writes,
    SpawnedBy,
    ExecutedBy,
    DependsOn,
    Unknown,
}
```

Keep it simple.

---

# 12. Guard representation

```rust
pub enum Guard {
    ExecutableHash {
        path: PathBuf,
        expected: Hash,
    },

    FileHash {
        path: PathBuf,
        expected: Hash,
    },

    FileMetadata {
        path: PathBuf,
        expected: FileFingerprint,
    },

    EnvironmentValue {
        key: OsString,
        expected: Option<OsString>,
    },

    WorkingDirectory {
        expected: PathBuf,
    },

    RuntimeIdentity {
        expected: RuntimeIdentity,
    },

    NoUnexpectedEffects,
}
```

A cache hit requires:

```rust
guards.iter().all(Guard::validate)
```

before cached output is served.

Guard checks must never run in the background after reuse.

---

# 13. Deoptimization

Treat fallback as a first-class mechanism.

Conceptually:

```text
candidate cached execution
        ↓
evaluate guards
        ↓
    pass?
    /   \
  yes   no
  ↓      ↓
reuse   deopt
          ↓
       execute normally
          ↓
         retrace
          ↓
      replace profile
```

Persist deoptimization reason.

Example:

```text
DEOPT: input dependency changed
path: ./config.yaml
expected: 91a2...
actual:   c812...
```

`tracejit explain` must expose this.

---

# 14. Output capture

V1 should support safe reuse for commands whose relevant outputs are filesystem artifacts plus process result.

Cache:

- exit code
- stdout
- stderr
- output files explicitly observed as created/modified during the traced run

Store file contents in CAS.

On reuse:

1. validate all guards
2. restore outputs atomically where practical
3. replay stdout
4. replay stderr
5. return cached exit status

Do not restore outputs if guard validation fails.

Never cache commands with unresolved external mutation effects.

---

# 15. Local CAS

Use:

```text
~/.cache/tracejit/
```

Structure:

```text
~/.cache/tracejit/
├── objects/
│   └── <blake3>
├── executions/
│   └── <execution-key>.json
└── db.sqlite3
```

Use SQLite for metadata.

Rust dependency:

```text
rusqlite
```

Use bundled SQLite feature to reduce system setup friction if compatible with final binary goals.

CAS objects:

```text
BLAKE3(content)
```

Use atomic temp-write + rename.

Do not duplicate identical file contents.

---

# 16. Sandbox enforcement

`PROVEN` mode:

```bash
tracejit run --enforce -- command
```

Use:

### seccomp-BPF

Purpose:

- restrict syscall classes
- deny networking when undeclared
- deny dangerous/unmodeled syscall classes
- constrain observable effect surface

Preferred implementation:

Use a maintained Rust seccomp implementation with minimal native dependencies.

### Landlock

Purpose:

- enforce filesystem path access policy

Allow only:

- required executable/runtime paths
- declared read dependencies
- declared writable output paths
- necessary dynamic linker/runtime files

If Landlock is unavailable or policy cannot be applied:

```text
classification cannot be PROVEN
```

Fall back to GUARDED or UNKNOWN.

Do not silently pretend seccomp alone provides path-level confinement.

---

# 17. CLI

Use `clap`.

Commands:

## `tracejit run`

```bash
tracejit run -- <command> [args...]
```

Behavior:

- check for prior eligible execution
- validate guards
- reuse if valid
- otherwise trace baseline execution
- classify
- persist profile
- report result

Options:

```text
--enforce
--guard-mode strict|fast
--verbose
--json
```

## `tracejit analyze`

```bash
tracejit analyze -- <command>
```

Always executes.

Never reuses.

Print:

- runtime
- process count
- effect counts
- input dependencies
- outputs
- irreversible effects
- unknown effects
- determinism class
- whether command would be eligible for reuse
- tracing overhead only when benchmark methodology permits measuring it

## `tracejit explain`

```bash
tracejit explain
tracejit explain <execution-id>
```

Show:

- command
- classification
- effects
- guards
- cache decision
- deoptimization reason
- input hashes
- output hashes
- unknown/nondeterministic reasons

## `tracejit cache`

Minimal subcommands:

```bash
tracejit cache stats
tracejit cache clear
```

Do not add more.

---

# 18. Output style

Default CLI must be terse.

Good:

```text
TraceJIT

classified     GUARDED
dependencies   14
outputs        2
unknown        0
runtime        8.42s

next run is eligible for guarded reuse
```

Second run:

```text
TraceJIT

guards         14/14 passed
cache          HIT
runtime        37ms
saved          8.38s
speedup        227.6x
```

Verbose diagnostic details belong behind:

```text
--verbose
```

Machine-readable output:

```text
--json
```

No emoji in JSON.

---

# 19. Repository structure

Use a Rust workspace.

```text
tracejit/
├── Cargo.toml
├── Cargo.lock
├── LICENSE
├── README.md
├── ARCHITECTURE.md
├── SAFETY.md
├── BENCHMARKS.md
├── ROADMAP.md
├── CONTRIBUTING.md
├── rust-toolchain.toml
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── crates/
│   ├── tracejit-cli/
│   ├── tracejit-core/
│   ├── tracejit-trace/
│   ├── tracejit-effects/
│   ├── tracejit-guards/
│   ├── tracejit-cache/
│   └── tracejit-sandbox/
│
├── tests/
│   ├── adversarial/
│   ├── integration/
│   └── fixtures/
│
├── benchmarks/
│   ├── README.md
│   ├── harness/
│   └── workloads/
│
└── scripts/
    ├── install-dev.sh
    └── benchmark.sh
```

Do not create more crates unless an actual dependency boundary requires one.

---

# 20. Crate responsibilities

## `tracejit-cli`

Only:

- argument parsing
- presentation
- calling core APIs

No tracing logic.

## `tracejit-core`

Orchestration:

```text
lookup
guard
reuse
trace
classify
persist
```

## `tracejit-trace`

- ptrace
- process state
- syscall interpretation
- FD tracking
- raw event normalization

## `tracejit-effects`

- effect types
- effect properties
- dependency reconstruction
- determinism classifier

## `tracejit-guards`

- guard generation
- validation
- fingerprints
- BLAKE3 hashing

## `tracejit-cache`

- CAS
- SQLite metadata
- output save/restore
- atomic writes

## `tracejit-sandbox`

- seccomp
- Landlock
- capability detection
- enforcement result

---

# 21. Rust stack

Use stable Rust.

Core dependencies should remain small.

Preferred:

```text
clap
serde
serde_json
thiserror
anyhow
nix
blake3
rusqlite
tracing
tracing-subscriber
tempfile
libc
```

Optional only if genuinely useful:

```text
postcard
smallvec
indexmap
```

Do not use:

- tokio unless asynchronous IO becomes necessary
- actix
- axum
- tonic
- protobuf
- Kubernetes libraries
- ORM frameworks
- giant dependency trees

Prefer standard library concurrency.

Pin through `Cargo.lock`.

Do not hardcode potentially stale crate versions in documentation.

---

# 22. Error model

Library crates use typed errors with:

```rust
thiserror
```

CLI boundary may use:

```rust
anyhow
```

Never panic for expected runtime conditions.

Panics are acceptable only for impossible internal invariants and tests.

Examples that must return errors:

- ptrace permission denied
- unsupported kernel feature
- cache corruption
- sandbox unavailable
- target binary not found
- target terminated unexpectedly
- hash failure
- filesystem restore failure

---

# 23. Adversarial safety suite

This is a core product feature.

Each adversarial fixture is a tiny executable/script with expected classification and expected cache eligibility.

Required fixtures:

```text
plain_file_read
file_content_changed
file_mtime_changed
symlink_target_changed
cwd_dependency
environment_dependency
unset_environment_dependency
locale_dependency
timezone_dependency
clock_realtime
clock_monotonic
getrandom
urandom
proc_cpuinfo
proc_self
hostname
uid_gid_dependency
tempfile_creation
fork_child
exec_child
child_file_dependency
shared_file_write
write_then_read
rename_output
delete_output
network_connect
network_send
dns_lookup
unix_socket
unknown_ioctl
dynamic_library_dependency
interpreter_dependency
script_dependency
nonzero_exit
stdout_only
stderr_only
```

Every bug found later must gain a permanent regression fixture.

Provide a table generated from tests:

```text
Case                     Expected         Actual          Safe
plain_file_read          GUARDED          GUARDED         ✓
clock_realtime           NONDETERMINISTIC NONDETERMINISTIC ✓
network_send             NONDETERMINISTIC NONDETERMINISTIC ✓
...
```

Never manually maintain this table if it can be generated.

---

# 24. Tests

Required:

## Unit tests

- effect mapping
- canonical hashing
- guard evaluation
- determinism classifier
- CAS integrity
- serialization round-trip

## Integration tests

- trace subprocess
- trace child process
- modify input and verify deopt
- preserve unchanged input and verify hit
- restore output file
- replay stdout/stderr
- altered env causes miss
- nondeterministic workload never reused
- unknown effect blocks reuse

## Sandbox tests

Where kernel supports features:

- forbidden syscall denied
- undeclared filesystem path denied
- declared path succeeds
- undeclared network denied
- unsupported sandbox cannot produce PROVEN

Tests must skip with explicit reason when kernel capability is unavailable.

---

# 25. Benchmark policy

No benchmark number may appear in README until generated by repository scripts.

Every published benchmark must include:

- exact TraceJIT commit
- kernel version
- CPU
- memory
- filesystem
- workload commit/version
- command
- warm/cold state
- number of runs
- median
- p95 where relevant

Report separately:

```text
A. tracing overhead
B. cache/optimization benefit
```

Never combine them.

Benchmark output example:

```text
Baseline median:
...

Traced median:
...

Tracing overhead:
...

Guard-check median:
...

Cached execution median:
...

End-to-end measured speedup:
...
```

First benchmark workload:

a deterministic Python ETL/reporting script committed under:

```text
benchmarks/workloads/python-etl/
```

It must:

- read several input files
- perform enough CPU work to make reuse visible
- create deterministic output
- expose env/cwd dependencies
- run without external services

Add a real external open-source workload only after core correctness passes.

---

# 26. Performance requirements

Do not invent target numbers.

Measure and report.

Engineering goals:

- avoid per-byte tracing
- reduce syscalls to semantic effects
- use BLAKE3 efficiently
- use metadata fast path where safe
- minimize allocations in hot trace loop
- batch SQLite writes
- avoid cloning paths/strings unnecessarily
- prefer IDs/interning where profiling proves beneficial
- do not optimize prematurely at cost of correctness

Profile before micro-optimizing.

---

# 27. README structure

README must be short above the fold.

Start:

```markdown
# TraceJIT

**Make repeated computation disappear, safely.**

TraceJIT observes an unmodified Linux process, infers its observable dependencies,
compiles runtime guards, and reuses previous execution only when those guards pass.

```bash
tracejit run -- python report.py
```
```

Then use a real terminal capture generated from the working repository.

Next sections:

1. demo
2. how it works
3. safety model
4. determinism classes
5. installation
6. CLI
7. benchmarks
8. adversarial safety suite
9. architecture
10. prior art
11. roadmap
12. contributing

Do not bury limitations.

Explicitly mention:

- Linux only
- whole-command reuse in V1
- unknown effects disable reuse
- PROVEN requires enforcement support

---

# 28. Architecture documentation

`ARCHITECTURE.md` must explain:

```text
command
  ↓
cache candidate lookup
  ↓
guards
  ├─ pass → restore
  └─ fail
       ↓
      trace
       ↓
     effects
       ↓
 dependency reconstruction
       ↓
 classification
       ↓
 guard generation
       ↓
 persist
```

Also explain why:

- ptrace first
- eBPF deferred
- seccomp alone is insufficient for path-level policy
- Landlock complements seccomp
- whole-command caching precedes subgraph optimization

---

# 29. Safety documentation

`SAFETY.md` must state:

TraceJIT is conservative.

Never claim arbitrary programs are safe to memoize.

Document:

- observable vs hidden dependencies
- nondeterminism
- irreversible effects
- sandbox limitations
- kernel capability requirements
- TOCTOU concerns
- filesystem metadata weaknesses
- why strict hashing is default
- why UNKNOWN blocks reuse
- security implications of cached outputs

---

# 30. Prior art section

README or ARCHITECTURE must acknowledge related systems accurately.

Include categories, not marketing attacks:

- Nix/Bazel: explicitly modeled/content-addressed builds
- sccache/ccache: compiler result caching
- Firebuild: traced build caching
- Rattle: traced dependencies and speculative build execution
- rr: deterministic record/replay
- strace/ptrace: process observation
- seccomp: syscall filtering
- Landlock: unprivileged filesystem sandboxing

TraceJIT distinction:

```text
automatic effect discovery
+
explicit determinism classification
+
compiled runtime guards
+
enforcement-backed PROVEN mode
+
deoptimization when assumptions fail
```

Do not claim no previous system has explored individual components.

---

# 31. Contributor mechanism

Create issue template:

```text
Break TraceJIT
```

Ask contributors to provide:

- minimal program
- expected effect
- actual TraceJIT behavior
- kernel/environment info

If valid:

1. reproduce
2. fix
3. add permanent fixture
4. credit contributor in fixture metadata/changelog

This adversarial corpus is part of the product.

---

# 32. CI

GitHub Actions:

```text
ubuntu-latest
```

Run:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Run privileged/sandbox tests only where supported.

Do not make ordinary CI flaky because a hosted runner forbids a kernel feature.

Capability-dependent tests must detect and skip.

---

# 33. Installation

V1 developer install:

```bash
cargo install --path crates/tracejit-cli
```

Also provide:

```bash
./scripts/install-dev.sh
```

Do not build curl-pipe installers until releases exist.

---

# 34. Versioning

Start:

```text
0.1.0
```

Repository should be releasable.

Include:

- LICENSE
- changelog optional
- clean Cargo metadata
- binary named exactly `tracejit`

Recommended license:

```text
Apache-2.0 OR MIT
```

Use dual licensing only if implemented correctly.

---

# 35. Definition of done

The build is complete only when all are true:

### Build

```bash
cargo build --workspace
```

passes.

### Lint

```bash
cargo clippy --workspace --all-targets --all-features -- -D warnings
```

passes.

### Tests

```bash
cargo test --workspace
```

passes.

### Behavior

This sequence works:

```bash
tracejit run -- python3 benchmarks/workloads/python-etl/main.py
tracejit run -- python3 benchmarks/workloads/python-etl/main.py
```

Second invocation reuses only if all guards pass.

Changing an input file causes:

```text
cache miss / deopt
```

Changing an observed environment dependency causes miss.

Clock/random/network fixtures are never unsafely reused.

Unknown behavior blocks reuse.

### Explainability

```bash
tracejit explain
```

shows why the last execution was reused or rejected.

### Enforcement

Where supported:

```bash
tracejit run --enforce -- ...
```

can produce PROVEN only when sandbox enforcement succeeds.

### Benchmark integrity

Benchmark script generates all benchmark results.

README contains no invented result.

### Documentation

README, ARCHITECTURE, SAFETY, BENCHMARKS, CONTRIBUTING, ROADMAP all match implementation.

---

# 36. Implementation order

Follow exactly unless blocked by a dependency.

## Phase A

Create workspace and shared types.

Implement:

```text
tracejit-effects
tracejit-guards
tracejit-cache
```

with unit tests.

## Phase B

Implement ptrace engine.

Get correct:

```text
fork
clone
exec
exit
FD tracking
filesystem effects
network detection
clock/random detection
```

before caching anything.

## Phase C

Build adversarial fixtures.

Make classifier conservative.

## Phase D

Implement execution identity and guard compilation.

## Phase E

Implement CAS and output capture/restore.

## Phase F

Implement:

```text
tracejit analyze
tracejit run
tracejit explain
```

## Phase G

Add seccomp + Landlock enforcement.

Do not emit PROVEN before both policy creation and enforcement behavior are tested.

## Phase H

Benchmark and profile.

Only then optimize hot paths.

## Phase I

Write final README using actual output from the finished binary.

---

# 37. Codex efficiency instructions

To minimize token and implementation waste:

- inspect existing files before editing
- batch related edits
- avoid narrating routine operations
- do not repeatedly restate this specification
- do not generate design documents other than those explicitly requested
- avoid TODO placeholders for required V1 behavior
- reuse shared types
- prefer table-driven syscall/effect mappings
- generate adversarial fixtures from small reusable helpers where possible
- write tests alongside implementations
- run focused tests during development
- run full workspace validation only at meaningful checkpoints
- do not dump enormous command output unless it contains an error
- fix compiler/clippy errors at the source rather than suppressing warnings
- use `#[allow(...)]` only with a concrete documented reason
- avoid unsafe Rust except where syscall interfaces require it
- isolate unavoidable unsafe code and document its invariants
- do not rewrite working modules merely for style
- do not create abstractions until at least two concrete call sites justify them

---

# 38. Hard correctness rules

These override every performance goal.

1. UNKNOWN means no reuse.
2. guard failure means no reuse.
3. irreversible effect means no reuse unless explicitly modeled safely.
4. PROVEN requires enforcement, never observation alone.
5. cached result cannot be exposed until every guard succeeds.
6. cache corruption fails closed.
7. output restoration failure fails closed.
8. unsupported kernel feature downgrades classification.
9. unexpected syscall/effect in enforced mode deoptimizes or fails.
10. no benchmark claim without a reproducible measurement.

---

# 39. Final repository quality bar

The repository should feel like a serious systems project, not an AI-generated code dump.

That means:

- small dependency graph
- coherent modules
- obvious invariants
- conservative safety behavior
- reproducible tests
- no fake performance claims
- extensive adversarial testing
- readable tracing core
- explicit limitations
- real benchmark harness
- minimal CLI surface
- technically detailed architecture docs

When choosing between cleverness and auditability, choose auditability.

When choosing between unsafe optimization and recomputation, recompute.

When choosing between pretending to understand an effect and returning UNKNOWN, return UNKNOWN.

The V1 technical claim is not:

> TraceJIT can cache everything.

It is:

> **TraceJIT automatically discovers process effects, compiles guards for what it can safely validate, and refuses reuse when its assumptions cannot be enforced.**

Build that claim completely.

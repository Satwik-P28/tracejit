# Phase 2A.1 — Executable identity contract

Commit: `2edbf0d`.

## The hazard

The cache lookup key is built from `hash_file(executable)` in `PreparedExecution::new`
(`crates/tracejit-core/src/lib.rs:688`), before tracing starts. The tracer then execs a **path**.
Between those two moments the path can resolve to different content — a rebuild in place, a
`rename(2)` of a new binary over the old one, a symlink swap, an in-place `write` of an existing
binary, or a PATH change.

Without a check, the run is traced and its profile is stored under the hash of the executable that
was sampled earlier. Reuse would then replay the output of a binary that never had that identity.
That is the one path by which this design could record a result under an identity that did not
produce it, and it is worse than a stale hit because the key itself is wrong.

## The contract now

`TraceRequest` carries `expected_executable_hash`, set from the identity. Immediately before
spawning, the tracer hashes the exact path it is about to exec:

```rust
if let Some(expected) = request.expected_executable_hash {
    let actual = hash_file(&executable_path)?;
    if actual != expected {
        return Err(TraceError::ExecutableChanged(format!(
            "{} changed between identity construction and execution", executable_path.display())));
    }
}
```

A mismatch produces no profile at all. The command still runs through the fallback path in
`tracejit-core::run`, which retraces, so the user sees a miss and a correct result — never a wrong
profile. Fail closed.

Note that the path hashed is `executable_path`, the path actually passed to `exec`, not the
canonical target: Phase 1.5 showed the kernel-visible exec path is itself observable (a script's
`$0`, and CPython's `sys.prefix`), so both must be the same file *and* the check must cover the one
really being exec'd.

## What is verified

| Check | Result |
| --- | --- |
| `refuses_to_trace_an_executable_that_no_longer_matches_its_identity` (unit) | PASS — a wrong expected hash yields `TraceError::ExecutableChanged` and no trace |
| Happy path | PASS — all 24 Linux integration tests exercise the re-verification on every traced run |
| Script and interpreter fidelity from Phase 1.5 | PASS — unchanged, still covered by `a_traced_script_sees_the_callers_script_path` |

## What is not closed

The check narrows the window to the interval between the re-hash and `execve`. The kernel resolves
the path again at exec time, so a swap inside that interval still wins. [UNVERIFIED] as a
reproduction: it needs a third process racing a microsecond-scale window, and no deterministic
test exists.

Closing it properly requires handing the kernel the very inode that was hashed — `O_PATH` +
`fexecve`/`execveat(AT_EMPTY_PATH)`. That is deliberately **not** done here, because it changes
semantics that Phase 1.5 established as load-bearing: `argv[0]` and the script path the
interpreter receives, PATH-name invocations that cannot be exec'd as a path at all, and shebang
handling. A `fexecve` of a script either fails or changes `$0`. Doing this correctly needs its own
design and its own differential tests, not a rushed addition.

Also unclosed, and unchanged from Phase 1.5:

- `PATH` resolution happens once, before tracing; a PATH directory whose contents change afterwards
  is covered by the executable hash guard on the resolved file, but not by a re-lookup.
- The dynamic loader and shared libraries are guarded by `ExecutableHash`/`FileHash` dependencies,
  not by re-verification at exec time.

## Cost

One BLAKE3 pass over the executable per **traced** execution. Cache hits never pay it: the hit path
never spawns a traced process.

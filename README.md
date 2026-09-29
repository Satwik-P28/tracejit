# TraceJIT

**Make repeated computation disappear, safely.**

TraceJIT observes an unmodified Linux process, infers its observable dependencies,
compiles runtime guards, and reuses previous execution only when those guards pass.

~~~bash
tracejit run -- python report.py
~~~

TraceJIT V1 is Linux x86_64 only. It caches whole commands, not subgraphs. Any
unknown effect disables reuse. PROVEN requires successful seccomp and Landlock
enforcement; observation alone never qualifies.

## Demo

On the first eligible execution, TraceJIT reports the observed classification and
records the baseline. A second invocation validates every guard synchronously,
restores captured files, and replays stdout, stderr, and the exit status. The CLI
prints only timings measured by those invocations.

This repository does not include a fabricated terminal capture. Generate a real
capture on a supported Linux x86_64 host after running the validation sequence in
[BENCHMARKS.md](BENCHMARKS.md).

## How it works

1. Compute a pre-execution identity from the executable, arguments, working
   directory, inherited environment, and runtime identity.
2. Look up a prior execution and validate all of its guards.
3. On a hit, restore content-addressed outputs and replay process results.
4. On a miss, ptrace the process tree, normalize effects, classify the execution,
   compile guards, and persist the result.
5. If a guard fails, record the deoptimization reason and retrace.

## Safety model

False negatives cause recomputation and are acceptable. False positives can return
stale or incorrect results and are not. Unmodeled syscall attempts become UNKNOWN;
clock, randomness, network, signals, and unresolved IPC prevent reuse.
Cache corruption and output restoration failure stop reuse.

See [SAFETY.md](SAFETY.md) for the threat model and current limitations.

## Determinism classes

| Class | Meaning | V1 reuse |
| --- | --- | --- |
| PROVEN | Declared effects are constrained by seccomp and Landlock | yes |
| GUARDED | Observed dependencies have synchronous runtime guards | yes |
| EMPIRICALLY_STABLE | Repetition suggests stability without structural proof | no |
| UNKNOWN | At least one attempted effect is not modeled safely | no |
| NONDETERMINISTIC | Known nondeterminism or irreversible external behavior | no |

TraceJIT does not automatically promote empirical stability.

## Installation

Install stable Rust on Ubuntu, then:

~~~bash
cargo install --path crates/tracejit-cli
~~~

For a repository checkout:

~~~bash
./scripts/install-dev.sh
~~~

No release or curl-pipe installer exists.

## CLI

~~~text
tracejit --version
tracejit doctor
tracejit run [--enforce] [--guard-mode strict|fast] [--verbose] [--json] -- <command> [args...]
tracejit analyze [--verbose] [--json] -- <command> [args...]
tracejit explain [execution-id] [--json]
tracejit cache stats
tracejit cache clear
~~~

`tracejit doctor` reports whether this machine can trace, whether seccomp and Landlock can support PROVEN, and where the cache will be written.

run uses strict content hashing by default. analyze always executes and never
reuses. explain shows the most recent or requested execution, including the last
cache decision and guard failure. JSON mode keeps command output inside JSON fields.

Reuse that TraceJIT refuses names the observation:

~~~text
reuse disabled: process read randomness via getrandom
~~~

An unseeded Python interpreter may call getrandom; TraceJIT then correctly marks
the whole command NONDETERMINISTIC. The benchmark harness sets PYTHONHASHSEED=0,
disables `.pyc` writes, and configures glibc not to draw allocator entropy.
Those are workload settings. They are not exceptions in the classifier.

## Benchmarks

There are no published performance claims. Run ./scripts/benchmark.sh on Linux to
generate reproducible JSON. The harness reports untraced, traced, and cached
end-to-end timings separately. See [BENCHMARKS.md](BENCHMARKS.md).

## Adversarial safety suite

tests/fixtures/cases.json defines the required safety cases and expected
classification. The Linux integration test runs each case, compares expected and
actual eligibility, and prints the table from test results. It covers file and
metadata changes, symlinks, environment and cwd, descendants, output mutation,
clock, randomness, procfs, network, Unix sockets, ioctl, runtimes, and process
result replay.

~~~bash
cargo test -p tracejit-cli --test linux_integration -- --nocapture
~~~

## Architecture

The workspace keeps effect types, guards, tracing, storage, sandboxing,
orchestration, and presentation in separate crates with one-way dependencies. See
[ARCHITECTURE.md](ARCHITECTURE.md).

## Prior art

TraceJIT combines ideas explored by several categories of systems:

- Nix and Bazel model content-addressed builds explicitly.
- sccache and ccache cache compiler results.
- Firebuild traces build dependencies for caching.
- Rattle traces dependencies and explores speculative build execution.
- rr records and replays execution deterministically.
- strace and ptrace observe process behavior.
- seccomp filters syscalls; Landlock confines filesystem paths.

Its V1 combination is automatic effect discovery, explicit determinism
classification, compiled guards, enforcement-backed PROVEN, and deoptimization.
It does not claim those individual mechanisms are unprecedented.

## Roadmap

V1 deliberately excludes partial-subgraph reuse and non-Linux platforms. See
[ROADMAP.md](ROADMAP.md) for deferred work.

## License

TraceJIT is licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT license ([LICENSE-MIT](LICENSE-MIT))

at your option.

## Contributing

Run formatting, clippy, and the full workspace test suite before submitting a
change. Safety bugs require a permanent fixture. See
[CONTRIBUTING.md](CONTRIBUTING.md).

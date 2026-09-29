# TraceJIT

**Make repeated computation disappear, safely.**

TraceJIT can eliminate repeated deterministic work when the saved computation exceeds its guard and cache overhead. It observes an unmodified Linux process, infers dependencies, and reuses a result only after those guards pass.

~~~bash
tracejit run -- ./benchmarks/workloads/c-transform/transform
~~~

TraceJIT V1 is Linux x86_64 only. It caches whole commands, not subgraphs. Any
unknown effect disables reuse. PROVEN requires successful seccomp and Landlock
enforcement; observation alone never qualifies.

## Measured result

TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands.

On commit `63e33638709aacfaed896ab587435e64c0ecea62`, the C ETL baseline median was **7.396 ms** and the guarded cache hit was **7.957 ms** (0.93x, 0.561 ms slower). That result stays in [benchmarks/results/latest.md](benchmarks/results/latest.md).

After the hit path stopped rewriting an unchanged cache record, commit `e9684c1c01a7bbbab4cae50e2389105596d613f1` measured a floor near 4 ms. A **1.796 ms** command still lost (hit 4.165 ms). The fastest measured win was a **5.274 ms** command (hit 4.100 ms, 1.286x). No curve was fit between those points.

The deterministic C transform is the strongest real win from that run: baseline **312.913 ms**, cache hit **3.972 ms**, **78.780x**, **308.941 ms** saved. A shell pipeline and `cc -c` were refused as `UNKNOWN`. Python stayed `NONDETERMINISTIC` because of `getrandom` and `gettid`.

The sweep, phase timings, refusals, and machine details are in [benchmarks/results/break-even.md](benchmarks/results/break-even.md).

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

An unseeded Python interpreter may call getrandom. CPython also calls gettid
while binding its main thread. TraceJIT then marks the whole command
NONDETERMINISTIC. The benchmark records that refusal. It does not hide either
syscall.

## Benchmarks

Published numbers come from the harnesses and are stored under `benchmarks/results/`.
See [BENCHMARKS.md](BENCHMARKS.md). The 7 ms loss and the later break-even table are both kept.

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

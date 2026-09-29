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

## Measured result

Commit `63e33638709aacfaed896ab587435e64c0ecea62`, GitHub-hosted Ubuntu 24.04.5,
kernel `6.17.0-1022-azure`, x86_64. Five warmups and 30 runs. The workload is
`benchmarks/workloads/c-etl`. Direct baseline median was **7.396 ms**. A cold
traced run was **21.024 ms** (184% overhead). An end-to-end guarded cache hit was
**7.957 ms**, which is 0.93x the baseline and 0.561 ms slower. Output bytes,
streams, and exit status matched, and changing `sales.csv` forced a retrace.

This command is too short for reuse to win. Starting TraceJIT and checking guards
costs more than the computation. The internal guard, restore, and replay path was
1.113 ms; most of the hit time is process startup around that path.

`python3 benchmarks/workloads/python-etl/main.py` was not reused:

~~~text
reuse disabled: process read randomness via getrandom
reuse disabled: process read process identity via gettid
~~~

The full record, including CPU, memory, filesystem, and commands, is
[benchmarks/results/latest.md](benchmarks/results/latest.md).

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

Published numbers come only from `./scripts/benchmark.sh` and are stored in
[benchmarks/results/latest.json](benchmarks/results/latest.json). See
[BENCHMARKS.md](BENCHMARKS.md). On the measured 7 ms C workload, guarded reuse is
correct and slower than running the command directly.

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

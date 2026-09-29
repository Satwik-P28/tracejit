# TraceJIT

[![CI](https://github.com/Satwik-P28/tracejit/actions/workflows/ci.yml/badge.svg)](https://github.com/Satwik-P28/tracejit/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0%20OR%20MIT-blue)](LICENSE-APACHE)
[![Platform](https://img.shields.io/badge/platform-Linux%20x86__64-lightgrey)](README.md)

**Make repeated computation disappear, safely.**

TraceJIT traces the observable dependencies of an unmodified Linux command, checks those guards before reuse, and skips the work only when they still hold.

```bash
tracejit run -- ./benchmarks/workloads/c-transform/transform
```

**312.913 ms → 3.972 ms**, 78.780x, on that deterministic C transform. Zero source changes. Linux x86_64 only.

Short commands can be slower. The published 7.396 ms C ETL came back in 7.957 ms on a cache hit (0.929468x, 0.561246 ms slower). Cache hits on the later runner sat near 4 ms, so a command has to outlast that floor.

## Try it

Linux x86_64. This release install does not need Rust:

```bash
curl -fsSL -o tracejit-v0.1.0-x86_64-unknown-linux-gnu.tar.gz \
  https://github.com/Satwik-P28/tracejit/releases/download/v0.1.0/tracejit-v0.1.0-x86_64-unknown-linux-gnu.tar.gz
curl -fsSL -o SHA256SUMS \
  https://github.com/Satwik-P28/tracejit/releases/download/v0.1.0/SHA256SUMS
sha256sum -c SHA256SUMS
tar -xzf tracejit-v0.1.0-x86_64-unknown-linux-gnu.tar.gz
mkdir -p ~/.local/bin
install -m 755 tracejit-v0.1.0-x86_64-unknown-linux-gnu/tracejit ~/.local/bin/tracejit
export PATH="$HOME/.local/bin:$PATH"
tracejit --version
tracejit doctor
```

`scripts/install-release.sh` runs that sequence. It refuses a missing archive, a missing checksum, or a checksum mismatch.

From a checkout, `./scripts/install-dev.sh` installs from source. `cargo install --path crates/tracejit-cli` is the same path when Rust is already installed.

## Is the benchmark real?

Yes. Both results were produced by the harness on GitHub-hosted Ubuntu 24.04 x86_64, with 5 warmups and 30 runs. They are not smoothed.

| Result | Baseline median | Cache-hit median | Speedup |
| --- | ---: | ---: | ---: |
| C transform, commit `e9684c1` | 312.913 ms | 3.972 ms | 78.780x |
| Short C ETL, commit `63e3363` | 7.396 ms | 7.957 ms | 0.929468x |

The sweep's slowest loss was a 1.796 ms command. The fastest win was a 5.274 ms command (hit 4.100 ms, 1.286x). Full tables: [benchmarks/results/break-even.md](benchmarks/results/break-even.md) and [benchmarks/results/latest.md](benchmarks/results/latest.md).

## Is it safe?

Reuse happens only for `GUARDED` or `PROVEN` work. `PROVEN` requires seccomp and Landlock to actually be installed. `UNKNOWN` and `NONDETERMINISTIC` never reuse. Every guard finishes before cached stdout, stderr, exit status, or files are exposed. See [SAFETY.md](SAFETY.md).

## Workloads

| Workload | v0.1.0 |
| --- | --- |
| Deterministic C transform in this repo | Reused. Measured above. |
| Python | Refused. CPython calls `getrandom` and `gettid`. |
| Shell pipeline, `cc -c` | Refused as `UNKNOWN`. Compatibility is incomplete. |

A single real run, including explain and input-change deoptimization, is `./scripts/demo.sh` on Linux x86_64. That script's timings are one execution, not the medians above.

## How it works

trace → effects → guards → reuse → deoptimize if an assumption changes.

Whole-command reuse. ptrace tracing. BLAKE3 content addresses. SQLite metadata. Strict hashing by default.

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

The main loop is Break TraceJIT: a workload that is classified or reused incorrectly becomes a permanent fixture. Compatibility, syscall coverage, and measured performance work are the other useful contributions. See [CONTRIBUTING.md](CONTRIBUTING.md).

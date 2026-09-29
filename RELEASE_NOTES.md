# TraceJIT v0.1.0

Linux x86_64 only. TraceJIT reuses a whole unmodified command after ptrace has observed its dependencies and every guard has passed. `PROVEN` requires seccomp and Landlock to be installed and applied. `UNKNOWN` and `NONDETERMINISTIC` fail closed and are never reused.

On the published GitHub-hosted runner, guarded cache hits sat near 4 ms. The deterministic C transform in this repository went from 312.913 ms to 3.972 ms (78.780x) at commit `e9684c1c01a7bbbab4cae50e2389105596d613f1`. Short commands may be slower: the 7.396 ms C ETL was 7.957 ms on a cache hit (0.929468x) at commit `63e33638709aacfaed896ab587435e64c0ecea62`.

Python is refused because CPython calls `getrandom` and `gettid`. Shell pipelines and `cc -c` are `UNKNOWN`. That compatibility is incomplete.

These are measurements of specific workloads, not a claim that every command gets faster. Tables and machine details: `benchmarks/results/break-even.md` and `benchmarks/results/latest.md`.

## Install

The release archive is `tracejit-v0.1.0-x86_64-unknown-linux-gnu.tar.gz`, checked with `SHA256SUMS`. `scripts/install-release.sh` downloads that archive after it is published. Until then, install from source with `./scripts/install-dev.sh`.

```bash
tracejit --version
tracejit doctor
tracejit run -- <command>
```

## License

Apache-2.0 OR MIT, at your option.

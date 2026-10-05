# TraceJIT v0.1.1

Linux x86_64 only. This does not replace the v0.1.0 release. v0.1.0 remains the previously published binary. It does not print the dependency summary from `tracejit explain`, and it does not use the current `doctor` sentences.

v0.1.1 adds that summary, names an unsupported machine in `doctor`, and refuses a file-backed `MAP_SHARED` mapping that is writable or that `mprotect` makes writable. Those mappings were previously ignored. A private or read-only file mapping is still not itself an effect. The open of that file remains the content guard.

The published timings were not remeasured for this version. The hit path since commit `e9684c1` is unchanged aside from this mmap refusal, and the synthetic transform does not use a shared writable mapping.

On the published GitHub-hosted runner, guarded cache hits sat near 4 ms. The deterministic C transform in this repository went from 312.913 ms to 3.972 ms (78.780x) at commit `e9684c1c01a7bbbab4cae50e2389105596d613f1`. Short commands may be slower: the 7.396 ms C ETL was 7.957 ms on a cache hit (0.929468x) at commit `63e33638709aacfaed896ab587435e64c0ecea62`.

Python is refused because CPython calls `getrandom` and `gettid`. Shell pipelines and `cc -c` are `UNKNOWN`. A clock read that stays in the vDSO is not observed.

These are measurements of specific workloads on those commits, not a claim that every command gets faster, and not a new measurement of v0.1.1. Tables and machine details: `benchmarks/results/break-even.md` and `benchmarks/results/latest.md`.

## Install

From a checkout of this version:

```bash
cargo build --workspace --release
./scripts/demo.sh
```

The release archive, once published, is `tracejit-v0.1.1-x86_64-unknown-linux-gnu.tar.gz`, checked with `SHA256SUMS`. `scripts/install-release.sh` downloads that archive and refuses to install if it is missing.

```bash
tracejit --version
tracejit doctor
tracejit run -- <command>
```

## License

Apache-2.0 OR MIT, at your option.

# TraceJIT v0.3.0-alpha.1 — proposed research prerelease (not yet published)

Status: **prepared, qualified, unpublished.** Publication is a separate, explicit decision. The
previous release, `v0.2.0-beta.1`, is unchanged.

TraceJIT reuses an unmodified Linux x86_64 command only when the dependencies it observed on an
earlier run still pass synchronous guards. Anything it cannot re-check — the clock, entropy,
process identity, the network, an unmodelled syscall — makes it run the command again instead.

## Why alpha

Two things are true at once and both matter:

1. The mechanism is exercised end to end, including enforced reuse on a host that can install
   seccomp and Landlock, and no measurement in the repository produced an incorrect observation
   inside the declared contract.
2. The contract still rests on one assumption it cannot enforce: **no external process may modify
   an input during the reuse window.** A writer that mutates an input between guard validation and
   output restoration causes stale output to be served. That is reproduced, documented, and not
   fixed.

An "alpha" label is the honest description of a tool with a measured, disclosed race.

## What this release contains

- **Guarded whole-command reuse** with a single synchronous guard pass adjacent to the restore, a
  typestate gate that makes unverified cached bytes unexposable, and a re-hash of every cached
  object before exposure.
- **Two execution tiers, never mixed**: native, and the opt-in `allocator-entropy-v1` /
  `compiler-runtime-v1` contracts. Controlled records are never served to a native invocation.
- **`--enforce`** (seccomp + Landlock ABI ≥ 3) producing the `PROVEN` label. `PROVEN` means the
  policy was installed for that execution. It is not a proof of equivalence, and a reuse installs
  no policy of its own.
- **Measured wins and losses**, with the losses in the same table as the wins:
  - `bzip2 -9 -k`, 25 invocations, cold cache: native 2846.7 ms, TraceJIT 545.3 ms — 5.22×,
    80.8 % less cumulative time. Firebuild 0.8.2 and 0.8.6.2 both decline to cache this workload,
    so this is an applicability result, not a replay-speed comparison.
  - `gzip` file output: Firebuild 0.8.6.2 reuses and is faster (254.7 ms vs 425.0 ms over 25 runs).
  - `sed`, 200k lines: Firebuild tuned is faster (561.4 ms vs 885.8 ms).
  - `sha256sum`: a hit re-hashes what the command would have hashed; unprofitable below ~10 MiB.
  - Compilation: `ccache` 4.10.2 is far faster. Whole-command caching is not a compiler cache.

## Supported environments

Linux x86_64 (GNU), `ptrace` permitted. `doctor` refuses other platforms and missing kernel
features rather than degrading silently. `GUARDED` reuse needs no sandbox; `PROVEN` needs
seccomp-BPF and Landlock ABI ≥ 3.

## Before you install

Do not use TraceJIT when a wrong result would be expensive and inputs can change concurrently:
builds running in a shared workspace, pipelines where another process rewrites the inputs, or
anything you cannot freeze for the reuse window. Do not use it as a replacement for ccache,
Firebuild, or your build system.

## Install (from the proposed artifact)

```bash
version=0.3.0-alpha.1
name="tracejit-v${version}-x86_64-unknown-linux-gnu.tar.gz"
# After the release is published:
#   curl -fsSLO "https://github.com/Satwik-P28/tracejit/releases/download/v${version}/${name}"
sha256sum -c --ignore-missing SHA256SUMS
tar -xzf "$name"
install -m 755 "tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit" ~/.local/bin/tracejit
tracejit doctor     # supported yes, ptrace yes, proven yes|no
```

Uninstall: remove `~/.local/bin/tracejit` and the cache directory `doctor` reports.

## Verification

`docs/RELEASE_QUALIFICATION_V03.md` records the exact commands, the artifact digests, the
clean-install test and every capability-dependent skip. Byte-for-byte reproducible builds are
**not** claimed; the provenance manifest exists so a second build can be compared by hand.

## Documentation

- [Correctness contract](FINAL_CORRECTNESS_CONTRACT.md) — the authority on behaviour and limits
- [Research report](FINAL_RESEARCH_REPORT.md) — what was measured and what remains unknown
- [Known limitations](LIMITATIONS.md) · [Safety](../SAFETY.md) · [Security](../SECURITY.md)
- [Reproduction package](REPRODUCTION_PACKAGE.md)
- Paper: `paper/main.tex`

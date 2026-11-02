# Phase 2D: direct-execution compatibility

The Phase 1/2 census invokes every workload through `sh -c`, so its traces contain the shell's own
`/dev/tty`, `getpeername`, `statfs` and `getrandom` calls alongside the workload. That suite is left
**unchanged** so its numbers stay comparable. This is a second, fixed suite that runs real commands
directly, without a shell, from their own working directory, with the arguments a user would type.

Script: `benchmarks/realworld/direct_suite.py`. Raw results:
`benchmarks/results/phase2d/session-a/`, `session-b/`.

## Fixed denominator: 16 workloads

A refusal, a missing tool or a crash stays in the denominator. Nothing is dropped for failing.

| Workload | Command | Classification | Reused | First refusal reason |
| --- | --- | --- | --- | --- |
| gzip | `gzip -9 -c input.txt` | `GUARDED` | **yes** | — (9 dependencies, all guardable) |
| bzip2 | `bzip2 -9 -c input.txt` | `NONDETERMINISTIC` | no | `getrandom` |
| xz | `xz -9 -c input.txt` | `NONDETERMINISTIC` | no | `getrandom`, `sysinfo` |
| tar | `tar -cf bundle.tar input.txt` | `UNKNOWN` | no | `statfs` (137) |
| sed | `sed -e s/alpha/ALPHA/g input.txt` | `UNKNOWN` | no | `statfs` (137) |
| grep | `grep -c alpha input.txt` | `UNKNOWN` | no | `/proc/self/maps` |
| sort | `sort -u input.txt` | `NONDETERMINISTIC` | no | `getrandom`, `sched_getaffinity`, `prlimit64`, `sysinfo` |
| tr | `tr a-z A-Z` (stdin) | `UNKNOWN` | no | inherited descriptor 0 is not replayable |
| base64 | `base64 -w0 input.txt` | `NONDETERMINISTIC` | no | `getrandom` |
| md5sum | `md5sum input.txt` | `NONDETERMINISTIC` | no | `getrandom` |
| wc | `wc -c input.txt` | `NONDETERMINISTIC` | no | `getrandom` |
| jq | `jq -c 'map(select(.v>5))\|length' input.json` | `NONDETERMINISTIC` | no | `getrandom` |
| python-json | `python3 -c '<json sum>'` | `NONDETERMINISTIC` | no | `getpid`, `getrandom`, `getppid`, clock, `gettid` |
| gcc-compile | `gcc -O2 -c hello.c -o hello.o` | `UNKNOWN` | no | `getrusage` (98) |
| assemble | `as hello.s -o hello.o` | `UNKNOWN` | no | `getrusage` (98) |
| strip | `strip -o stripped hello.o` | `NONDETERMINISTIC` | no | `getrandom`, `prlimit64` |

**Result: 1 of 16 reused.** Traced output matched a direct run on **16 of 16**, exit status included.

## Keeping three kinds of failure apart

The suite records the classifier's own reason string, which separates categories the census merged:

- **Genuine nondeterminism** (8 workloads): `getrandom` at process start, before `main`. This is not a
  modelling gap — the value is unknowable in advance and cannot be guarded. bzip2, xz, sort, base64,
  md5sum, wc, jq, python, strip.
- **Missing modelling** (5 workloads): `statfs` (tar, sed), `/proc/self/maps` (grep), inherited
  descriptor reads (tr), `getrusage` (gcc, as). Each is a specific syscall or read that the tracer
  declines to model, not a property of the program.
- **Missing tooling**: `zstd`, `clang`, `pandoc`, `convert`, `ffmpeg`, `cmake` and `yq` are not
  installed, so deterministic image conversion and documentation conversion are **BLOCKED**, not
  refused. They are recorded as missing rather than excluded.

Note that `xz` and `sort` are refused for `getrandom` *plus* a second reason. Removing randomness
alone would not make them reusable; the second reason would have to be modelled too.

## What this changes about the Phase 2C picture

Phase 2C concluded that `sort`, `base64`, `md5sum`, `tr` and `wc` were nondeterministic through
`getrandom`, and that `sed` and `grep` were refused for `statfs` and `/proc/self/maps`. The direct
suite reproduces that, and adds the detail that `sort` is also refused for `sched_getaffinity`,
`prlimit64` and `sysinfo` — three machine-state reads that no randomness modelling would address.

The single reusable workload is still gzip. Compression is the one category here that is a
single-process, clock-free, randomness-free computation over its input.

## Reproduction

```bash
cargo build -p tracejit-cli
python3 benchmarks/realworld/direct_suite.py --runs 20 \
  --output-dir benchmarks/results/phase2d/session-a
```

# TraceJIT break-even

Commit: `6358522e2eee7b8aa7f59acca88e061f72166d8e`

TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands. The earlier 7 ms C ETL result remains in `benchmarks/results/latest.md`.

## Sweep

| Target | Baseline median | Baseline p95 | Traced cold median | Traced cold p95 | Cache hit median | Cache hit p95 | Tracing overhead | Speedup | Time saved |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 ms | 1.688 ms | 1.853 ms | 11.137 ms | 11.999 ms | 3.964 ms | 4.083 ms | 559.77% | 0.426x | -2.276 ms |
| 5 ms | 5.284 ms | 5.356 ms | 15.045 ms | 15.584 ms | 4.079 ms | 5.210 ms | 184.72% | 1.296x | 1.206 ms |
| 10 ms | 9.638 ms | 11.262 ms | 19.600 ms | 20.540 ms | 4.250 ms | 4.373 ms | 103.36% | 2.268x | 5.389 ms |
| 25 ms | 23.031 ms | 25.838 ms | 34.807 ms | 40.139 ms | 4.290 ms | 4.577 ms | 51.13% | 5.368x | 18.741 ms |
| 50 ms | 45.209 ms | 45.767 ms | 57.127 ms | 60.947 ms | 4.074 ms | 4.744 ms | 26.36% | 11.098x | 41.135 ms |
| 100 ms | 88.663 ms | 89.160 ms | 100.607 ms | 107.572 ms | 3.980 ms | 4.923 ms | 13.47% | 22.278x | 84.684 ms |
| 250 ms | 220.352 ms | 223.007 ms | 234.421 ms | 239.688 ms | 4.308 ms | 6.554 ms | 6.39% | 51.144x | 216.043 ms |
| 500 ms | 439.300 ms | 442.704 ms | 455.346 ms | 460.538 ms | 4.000 ms | 4.179 ms | 3.65% | 109.831x | 435.301 ms |
| 1000 ms | 877.550 ms | 880.804 ms | 893.499 ms | 908.516 ms | 4.078 ms | 4.249 ms | 1.82% | 215.187x | 873.472 ms |
| 2000 ms | 1755.219 ms | 1761.673 ms | 1770.951 ms | 1776.655 ms | 4.256 ms | 4.468 ms | 0.90% | 412.381x | 1750.962 ms |
| 5000 ms | 4390.564 ms | 4401.536 ms | 4403.443 ms | 4416.746 ms | 4.101 ms | 4.524 ms | 0.29% | 1070.578x | 4386.463 ms |

## Break-even

The slowest measured loss had direct baseline median 1.688 ms. The fastest measured win had direct baseline median 5.284 ms. No curve was fit between those points.

## Fixed overhead

Phase medians are from cache-hit samples of the short C ETL. `process_startup_ns` uses `/proc` starttime and is not added into the accounted total. Unaccounted time includes process startup, process exit, and gaps between the other timed regions.

| Phase | Median |
| --- | ---: |
| Process startup | 5.748 ms |
| CLI parsing | 0.070 ms |
| Identity, executable hash, filesystem discovery | 0.125 ms |
| Cache directory initialization | 0.015 ms |
| SQLite open | 0.115 ms |
| SQLite schema and pragmas | 0.254 ms |
| Lookup-key hash | 0.008 ms |
| SQLite candidate query | 0.068 ms |
| Candidate JSON decode | 0.187 ms |
| Guard validation | 0.784 ms |
| CAS restore | 0.910 ms |
| Cached stdout/stderr load | 0.021 ms |
| Decision persist | 0.000 ms |
| Stdout/stderr replay to the terminal | 0.034 ms |
| Unaccounted, including process exit | 1.638 ms |

## Real workloads

- `c-transform`: baseline 314.762 ms, cache hit 4.171 ms, speedup 75.472x, saved 310.591 ms.
- `shell-pipeline`: classification `Nondeterministic`, reuse no. process read process identity via getpid; process read randomness via getrandom; process read process identity via getppid; process read system clock: realtime
- `build-sample`: classification `Unknown`, reuse no. successful access check cannot be guarded exactly: /usr/bin/cc; successful access check cannot be guarded exactly: /usr/bin/cc; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /tmp; successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1; unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fffb7630218, 0x80000, 0x2034d60, 0x7f8689a1bc58, 0x0, 0x0]; read from unclassified fd 3; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffd6d169880, 0x0, 0x200, 0x2e5d0ef, 0x0]; unmodeled successful syscall 293: unmodeled syscall 293 args [0x7fffb7630f18, 0x80000, 0x2030380, 0x2034bb8, 0x0, 0x0]; read from unclassified fd 3; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7ffeabd536c0, 0x7ffeabd53c48, 0x7ffeabd53810, 0x0, 0x7ff6d37c3380]

## Before optimization

Commit `25d7c24e25b64382050d6d0ce126560e461855a4` short C ETL baseline 6.545 ms, cache hit 7.420 ms. Decision persist median 3.136 ms. Record decode median 0.750 ms. The slowest measured loss had direct baseline median 4.952 ms. The fastest measured win had direct baseline median 9.226 ms. No curve was fit between those points.

## Daemon

A persistent daemon was not added. The pre-optimization profile showed the hit-path record rewrite near 3.1 ms and record decode near 0.75 ms. Guard checks and CAS restore stay on the hit path because they are the safety check. A warm process would not remove those costs, so the daemon is not worth its protocol and lifecycle.

## Python

Classification: `Nondeterministic`.

PYTHONHASHSEED=0 disables CPython hash-seed randomization. `gettid` still runs while the interpreter binds its main thread and is observable as the native thread id. A remaining `getrandom` is still randomness. Neither call was whitelisted.

Reasons:

- process read process identity via getpid
- process read randomness via getrandom
- process read process identity via getppid
- process read system clock: monotonic
- process read process identity via gettid
- process read system clock: realtime

## Negative short-command result

Short C ETL baseline median 8.337 ms, cache hit 4.230 ms, speedup 1.971x.

The previously published result in `benchmarks/results/latest.md` is unchanged.


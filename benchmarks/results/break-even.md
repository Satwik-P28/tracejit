# TraceJIT break-even

Commit: `e9684c1c01a7bbbab4cae50e2389105596d613f1`

TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands. The earlier 7 ms C ETL result remains in `benchmarks/results/latest.md`.

## Sweep

| Target | Baseline median | Baseline p95 | Traced cold median | Traced cold p95 | Cache hit median | Cache hit p95 | Tracing overhead | Speedup | Time saved |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 ms | 1.796 ms | 1.884 ms | 11.833 ms | 13.347 ms | 4.165 ms | 4.461 ms | 558.93% | 0.431x | -2.369 ms |
| 5 ms | 5.274 ms | 5.427 ms | 15.104 ms | 15.717 ms | 4.100 ms | 4.529 ms | 186.40% | 1.286x | 1.174 ms |
| 10 ms | 9.694 ms | 9.860 ms | 19.544 ms | 21.533 ms | 4.188 ms | 4.607 ms | 101.61% | 2.315x | 5.506 ms |
| 25 ms | 22.598 ms | 22.691 ms | 32.671 ms | 34.612 ms | 4.000 ms | 4.182 ms | 44.58% | 5.649x | 18.598 ms |
| 50 ms | 43.983 ms | 44.137 ms | 54.158 ms | 54.812 ms | 4.165 ms | 4.562 ms | 23.14% | 10.561x | 39.818 ms |
| 100 ms | 86.556 ms | 86.711 ms | 96.321 ms | 98.748 ms | 3.909 ms | 4.457 ms | 11.28% | 22.144x | 82.647 ms |
| 250 ms | 214.120 ms | 215.126 ms | 224.031 ms | 228.600 ms | 3.994 ms | 4.653 ms | 4.63% | 53.615x | 210.127 ms |
| 500 ms | 426.746 ms | 427.215 ms | 436.898 ms | 438.246 ms | 4.277 ms | 4.486 ms | 2.38% | 99.771x | 422.469 ms |
| 1000 ms | 852.097 ms | 853.732 ms | 862.205 ms | 868.598 ms | 4.163 ms | 4.481 ms | 1.19% | 204.665x | 847.934 ms |
| 2000 ms | 1702.052 ms | 1702.893 ms | 1712.741 ms | 1716.313 ms | 4.072 ms | 4.667 ms | 0.63% | 417.991x | 1697.980 ms |
| 5000 ms | 4253.836 ms | 4258.939 ms | 4264.170 ms | 4272.526 ms | 3.958 ms | 5.265 ms | 0.24% | 1074.873x | 4249.879 ms |

## Break-even

The slowest measured loss had direct baseline median 1.796 ms. The fastest measured win had direct baseline median 5.274 ms. No curve was fit between those points.

## Fixed overhead

Phase medians are from cache-hit samples of the short C ETL. `process_startup_ns` uses `/proc` starttime and is not added into the accounted total. Unaccounted time includes process startup, process exit, and gaps between the other timed regions.

| Phase | Median |
| --- | ---: |
| Process startup | 5.330 ms |
| CLI parsing | 0.050 ms |
| Identity, executable hash, filesystem discovery | 0.120 ms |
| Cache directory initialization | 0.013 ms |
| SQLite open | 0.072 ms |
| SQLite schema and pragmas | 0.198 ms |
| Lookup-key hash | 0.021 ms |
| SQLite candidate query | 0.126 ms |
| Candidate JSON decode | 0.548 ms |
| Guard validation | 0.803 ms |
| CAS restore | 0.545 ms |
| Cached stdout/stderr load | 0.018 ms |
| Decision persist | 0.000 ms |
| Stdout/stderr replay to the terminal | 0.032 ms |
| Unaccounted, including process exit | 1.394 ms |

## Real workloads

- `c-transform`: baseline 312.913 ms, cache hit 3.972 ms, speedup 78.780x, saved 308.941 ms.
- `shell-pipeline`: classification `Unknown`, reuse no. process-relative procfs dependency: /proc/self/maps; unmodeled successful syscall 115: unmodeled syscall 115 args [0x0, 0x0, 0xffffff90, 0x7f7d4700ef98, 0x7f7d47205920, 0x0]; unmodeled successful syscall 115: unmodeled syscall 115 args [0x5, 0x16411070, 0x0, 0x16411070, 0x7f7d47204b20, 0x20]
- `build-sample`: classification `Unknown`, reuse no. successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /tmp; successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1; unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc7f82a748, 0x80000, 0x158cd0a0, 0x7f56eb21bc58, 0x0, 0x0]; read from unclassified fd 3; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7fffc6ab0e90, 0x0, 0x200, 0x3ae970ef, 0x0]; unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffc7f82b448, 0x80000, 0x158c8380, 0x158ccef8, 0x0, 0x0]; read from unclassified fd 3; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fffb4000cc0, 0x7fffb4001248, 0x7fffb4000e10, 0x0, 0x7f88b3d14380]

## Before optimization

Commit `25d7c24e25b64382050d6d0ce126560e461855a4` short C ETL baseline 6.545 ms, cache hit 7.420 ms. Decision persist median 3.136 ms. Record decode median 0.750 ms. The slowest measured loss had direct baseline median 4.952 ms. The fastest measured win had direct baseline median 9.226 ms. No curve was fit between those points.

## Daemon

A persistent daemon was not added. The pre-optimization profile showed the hit-path record rewrite near 3.1 ms and record decode near 0.75 ms. Guard checks and CAS restore stay on the hit path because they are the safety check. A warm process would not remove those costs, so the daemon is not worth its protocol and lifecycle.

## Python

Classification: `Nondeterministic`.

PYTHONHASHSEED=0 disables CPython hash-seed randomization. `gettid` still runs while the interpreter binds its main thread and is observable as the native thread id. A remaining `getrandom` is still randomness. Neither call was whitelisted.

Reasons:

- process read randomness via getrandom
- process read process identity via gettid

## Negative short-command result

Short C ETL baseline median 8.493 ms, cache hit 3.940 ms, speedup 2.156x.

The previously published result in `benchmarks/results/latest.md` is unchanged.


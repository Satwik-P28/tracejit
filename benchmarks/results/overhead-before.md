# TraceJIT break-even

Commit: `25d7c24e25b64382050d6d0ce126560e461855a4`

TraceJIT has a fixed-cost floor and is not beneficial for extremely short commands. The earlier 7 ms C ETL result remains in `benchmarks/results/latest.md`.

## Sweep

| Target | Baseline median | Baseline p95 | Traced cold median | Traced cold p95 | Cache hit median | Cache hit p95 | Tracing overhead | Speedup | Time saved |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 ms | 1.610 ms | 3.075 ms | 14.276 ms | 15.075 ms | 7.202 ms | 7.985 ms | 786.47% | 0.224x | -5.591 ms |
| 5 ms | 4.952 ms | 8.730 ms | 17.515 ms | 24.321 ms | 7.201 ms | 9.695 ms | 253.71% | 0.688x | -2.250 ms |
| 10 ms | 9.226 ms | 9.675 ms | 21.635 ms | 22.892 ms | 7.088 ms | 7.321 ms | 134.51% | 1.302x | 2.137 ms |
| 25 ms | 22.073 ms | 22.442 ms | 34.842 ms | 36.419 ms | 7.406 ms | 10.092 ms | 57.85% | 2.981x | 14.668 ms |
| 50 ms | 43.276 ms | 43.694 ms | 55.494 ms | 59.012 ms | 7.473 ms | 11.088 ms | 28.23% | 5.791x | 35.803 ms |
| 100 ms | 85.737 ms | 111.566 ms | 98.996 ms | 167.157 ms | 7.493 ms | 8.424 ms | 15.47% | 11.441x | 78.243 ms |
| 250 ms | 212.797 ms | 223.159 ms | 228.222 ms | 777.671 ms | 7.600 ms | 10.832 ms | 7.25% | 28.001x | 205.197 ms |
| 500 ms | 424.821 ms | 491.205 ms | 440.113 ms | 441.570 ms | 7.536 ms | 8.656 ms | 3.60% | 56.370x | 417.285 ms |
| 1000 ms | 847.715 ms | 848.947 ms | 866.571 ms | 1002.432 ms | 7.856 ms | 8.718 ms | 2.22% | 107.909x | 839.860 ms |
| 2000 ms | 1695.235 ms | 1881.831 ms | 1711.653 ms | 1791.455 ms | 7.293 ms | 7.986 ms | 0.97% | 232.442x | 1687.942 ms |
| 5000 ms | 4235.850 ms | 4555.619 ms | 4252.719 ms | 4585.857 ms | 7.431 ms | 7.849 ms | 0.40% | 570.041x | 4228.419 ms |

## Break-even

The slowest measured loss had direct baseline median 4.952 ms. The fastest measured win had direct baseline median 9.226 ms. No curve was fit between those points.

## Fixed overhead

Phase medians are from cache-hit samples of the short C ETL. Unaccounted time includes process exit and any gap between timed regions. These medians are not summed into a smoothed curve.

| Phase | Median |
| --- | ---: |
| Process startup | 5.690 ms |
| CLI parsing | 0.038 ms |
| Identity, executable hash, filesystem discovery | 0.070 ms |
| Cache directory initialization | 0.006 ms |
| SQLite open | 0.053 ms |
| SQLite schema and pragmas | 0.111 ms |
| Lookup-key hash | 0.015 ms |
| SQLite candidate query | 0.349 ms |
| Candidate JSON decode | 0.750 ms |
| Guard validation | 0.449 ms |
| CAS restore | 0.835 ms |
| Cached stdout/stderr load | 0.007 ms |
| Decision persist | 3.136 ms |
| Stdout/stderr replay to the terminal | 0.021 ms |
| Unaccounted, including process exit | -4.112 ms |

## Real workloads

- `c-transform`: baseline 241.370 ms, cache hit 7.012 ms, speedup 34.425x, saved 234.358 ms.
- `shell-pipeline`: classification `Unknown`, reuse no. process-relative procfs dependency: /proc/self/maps; unmodeled successful syscall 115: unmodeled syscall 115 args [0x0, 0x0, 0xffffff90, 0x7f494a00ef98, 0x7f494a205920, 0x0]; unmodeled successful syscall 115: unmodeled syscall 115 args [0x5, 0x18ef4070, 0x0, 0x18ef4070, 0x7f494a204b20, 0x20]
- `build-sample`: classification `Unknown`, reuse no. successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; successful access check cannot be guarded exactly: /tmp; successful access check cannot be guarded exactly: /usr/libexec/gcc/x86_64-linux-gnu/13/cc1; unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffff75ad2a8, 0x80000, 0x28e090a0, 0x7f63b481bc58, 0x0, 0x0]; read from unclassified fd 3; successful access check cannot be guarded exactly: /usr/lib/gcc/x86_64-linux-gnu/13; unmodeled successful syscall 439: unmodeled syscall 439 args [0xffffff9c, 0x7ffcb0043400, 0x0, 0x200, 0x36cd00ef, 0x0]; unmodeled successful syscall 293: unmodeled syscall 293 args [0x7ffff75adfa8, 0x80000, 0x28e04380, 0x28e08ef8, 0x0, 0x0]; read from unclassified fd 3; unmodeled successful syscall 98: unmodeled syscall 98 args [0x0, 0x7fff324117b0, 0x7fff32411d38, 0x7fff32411900, 0x0, 0x7f027b116380]

## Daemon

A persistent daemon was not added. The cache-hit phase profile is the input to that decision.

## Python

Classification: `Nondeterministic`.

PYTHONHASHSEED=0 disables CPython hash-seed randomization. `gettid` still runs while the interpreter binds its main thread and is observable as the native thread id. A remaining `getrandom` is still randomness. Neither call was whitelisted.

Reasons:

- process read randomness via getrandom
- process read process identity via gettid

## Negative short-command result

Short C ETL baseline median 6.545 ms, cache hit 7.420 ms, speedup 0.882x.

The previously published result in `benchmarks/results/latest.md` is unchanged.


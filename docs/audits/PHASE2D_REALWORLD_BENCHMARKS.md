# Phase 2D: real-world benchmarks

Two independent sessions, same machine, same binary, no competing load. Raw measurements:
`benchmarks/results/phase2d/session-a/` and `session-b/` (`direct-suite.json`, `direct-suite.md`).

- Host: Linux 6.1.102, x86-64, 2 vCPU, ext4 `relatime`.
- Binary: `target/debug/tracejit`, built from a tree whose trace/guard/cache code is identical to
  `bd59a0e`; the only code added in this phase is the benchmark script itself.
- Workload: `gzip -9 -c input.txt`, 480,000 bytes of text, stdout captured in memory.
- 20 timed direct runs and 20 timed cached runs per session.

## `gzip` repeated-use, both sessions

| | Session A | Session B |
| --- | ---: | ---: |
| Direct median | 28.84 ms | 28.78 ms |
| Direct p95 | 29.07 ms | 31.18 ms |
| Cold traced run | 46.26 ms | 47.10 ms |
| Cached median | **4.03 ms** | **4.18 ms** |
| Cached p95 | 4.33 ms | 8.17 ms |
| Speedup | **7.16x** | **6.89x** |
| Saved per run | 24.81 ms | 24.60 ms |
| Tracing penalty | 17.42 ms | 18.32 ms |
| Hits to repay a cold trace | **0.70** | **0.74** |

The first reuse already pays for the cold trace: the penalty (17–18 ms) is smaller than the saving
per hit (24.6–24.8 ms), so the second invocation is net positive and every one after that is pure
gain. This is a different regime from the Phase 2C measurement (18 MB input, 23.84x, 1.99 hits to
repay) — same command, different input size, so the two are not a comparison of anything except
input size.

Cached wall time includes the whole TraceJIT process: parse, cache open, guard validation, output
write. On a 480 KB input that is 4 ms, which is also the floor measured on tiny workloads.

## What is measured and what is not

Measured: direct, cold traced, cached, p50 (as median) and p95 for both, absolute saving, tracing
penalty, and break-even count. Every cached number comes from runs whose decision was checked to be
`Reused`, and whose stdout was compared byte-for-byte against a direct run in the same session.

**Not measured, and deliberately not claimed:**

- Only `gzip` has a timing row. The other 15 workloads never reused, so timing them would measure
  TraceJIT's tracing overhead, not reuse. Tracing overhead for every workload *is* recorded in each
  `direct-suite.json` row (`traced_overhead_ms`), and is a loss, not a gain.
- No competitive comparison. `ccache`, `sccache`, Firebuild and `clang` are not installed on this
  host, and `ccache` would not be comparable to a `gzip` workload in any case. No claim of
  superiority, parity or regression is made.
- No comparison against earlier commits on the same workload. The hit path did not change in this
  phase, and the Phase 2C numbers used a 37x larger input, so a "before/after" table would compare
  input sizes and call it progress.

## Correctness evidence attached to these numbers

- 20/20 cached runs per session reported `Reused`; each was compared to a direct run.
- 16/16 workloads produced stdout identical to a direct run, with matching exit status, in both
  sessions.
- The cold run of every workload matched its direct run, so tracing does not perturb the command.

## The caveat that matters for these numbers

These timings are only achievable while the input's **parent directory** does not change during the
sequence (`PHASE2D_ATIME_ANALYSIS.md`). The suite captures stdout in memory and writes nothing into
the working directory between runs, so the directory stays stable. The equally ordinary pattern

```bash
gzip -9 -c input.txt > input.txt.gz   # writes into the same directory
```

records a `FileMetadata` dependency on that directory and deoptimizes on the next run, because the
directory's `mtime` and `ctime` changed. The 7x above is therefore a real measurement of a real
reuse, and it is *not* a claim that the benefit survives normal output placement. That defect is
open, and it is the most valuable correctness fix available.

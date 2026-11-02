# Phase 2C benchmarks — first positive end-to-end savings on a real command

Commit under test: `bd59a0e` (code unchanged by this phase). Host: Linux 6.1.102, x86-64, 2 vCPU,
18,000,000-byte text input, stdout redirected to `/dev/null`, single session, no competing load.

## `gzip -9 -c` — repeated-use scenario

| Condition | Median | p95 | Notes |
| --- | ---: | ---: | --- |
| Direct execution | 259.41 ms | 272.03 ms | 20 runs |
| Cold traced execution | 504.25 ms | — | one sample; includes recording and persistence |
| Cached reuse | **10.88 ms** | 14.05 ms | 20 runs, each verified `Reused` |

- **Speedup: 23.84x.** Median time saved per run: **248.53 ms**.
- Hits needed to repay one cold trace: **1.99** — two repeated uses break even, the third is pure
  gain.
- Tracing overhead on a cold run: 244.84 ms above direct (94%).
- Output equivalence: byte-identical, asserted on every reused run.

The hit cost decomposes plausibly as the ~4 ms machinery floor measured on tiny workloads plus BLAKE3
over the 18 MB input. It was not profiled in this phase, so that decomposition is **[INFERENCE]**.

### Measurement defect found and corrected in this phase

An earlier measurement in this same session reported `0.38x` (cached slower than direct) for the same
workload. The cause was the harness, not the system: timing was taken with `tracejit run --json`,
which serialises the entire captured stdout as a JSON array of integers — 524 KiB of output became
several MiB of JSON. Timing now runs `tracejit run` without `--json`. The wrong number is recorded
here deliberately so it is not rediscovered as a mystery.

## Synthetic regression check

The committed C ETL harness (`benchmarks/harness/benchmark.py`, 50 runs / 10 warmups) at `9571772`:

| Condition | Median | p95 |
| --- | ---: | ---: |
| Baseline | 8.366 ms | 8.491 ms |
| Traced cold | 21.089 ms | 33.461 ms |
| Guard validation | 1.671 ms | 2.322 ms |
| Cached end-to-end | 4.043 ms | 4.512 ms |

Speedup 2.069x, ≈4.0 hits to repay a cold trace. No code in the cache-hit path changed during this
phase, so this is a regression check, not a new result.

## What is *not* measured

- **No competitive comparison.** `ccache`, `sccache` and Firebuild are not installed on this host;
  `ccache` is not comparable to this workload anyway (it caches compiler invocations, not `gzip`). No
  claim of superiority or parity is made.
- **No repeat session.** One timing session for `gzip`; the p95 spread (10.88 → 14.05 ms) is small,
  but a second session would be needed to quote the speedup with a confidence interval.
- **No cold-run distribution.** A single cold sample. The repayment figure (1.99) should be read as
  "about two", not as a precise constant.
- **The nine-workload census is untouched** and remains 0 of 9. This phase's positive result is
  `gzip` invoked directly, which is outside that fixed suite.

## Interpretation

For the first time the end-to-end question has a positive answer: an ordinary, unmodified developer
command is skipped correctly and profitably. The limits are just as important as the result —
compression is a single-process, clock-free, randomness-free workload, and most neighbouring
utilities (`sort`, `base64`, `md5sum`, `tr`, `wc`) read `getrandom` during startup and remain
ineligible.

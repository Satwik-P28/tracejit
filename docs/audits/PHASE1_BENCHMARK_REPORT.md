# Phase 1 benchmark report

Every number below was produced on this host by the harnesses in this
repository. No value is estimated, interpolated, or carried over from another
machine without being labelled as historical. Raw per-sample timings are stored
alongside this report in `benchmarks/results/phase1/`.

## What was measured, and on what

| Item | Value |
| --- | --- |
| Commit | `6358522e2eee7b8aa7f59acca88e061f72166d8e` **plus** the uncommitted Phase 1 fixes (`working_tree_dirty: true` in every artifact) |
| Branch | `freebuff/c4bae51ae7d50b70f5bd4fc1`, based on `f90b4db15ec066373101692996c822e2c51c67cf` |
| Distribution | Ubuntu 24.04.5 LTS |
| Kernel | `6.1.102`, x86_64, 2 vCPU, 3915 MB RAM (a 2 vCPU cloud VM) |
| Filesystem | overlay rootfs |
| Rust | `cargo`/`rustc` `stable` (rustup), installed for this phase |
| Python | 3.12.3 |
| ptrace | available |
| seccomp | available |
| Landlock | **absent** (`ENOSYS`) — no `PROVEN` can be produced here |
| Workload environment | `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`, `MALLOC_ARENA_MAX=1` |
| Sessions | three: pre-fix audit baseline, post-fix native + census, post-fix duration sweep — each run with no other measurement process alive |

Harness capabilities that this phase added or verified (reliability audit D5):
the exact commit SHA and a `working_tree_dirty` flag are recorded in every
artifact; raw `samples_ns` arrays are saved as JSON; output equivalence of
baseline/traced/cached is checked on exit status, stdout, stderr and output
hashes and fails loudly; the deopt check mutates a dependency and requires the
explanation to name it; direct, cold-traced and cached timings are separate
conditions; negative speedups are reported as negative; `latest.*` is written
next to an immutable `commit-<sha>[-dirty]/` copy so historical results are not
overwritten; the repository is snapshotted before and after a run.

## 1. Current commit — controlled workload (short C ETL)

`benchmarks/harness/benchmark.py --runs 50 --warmups 10`, one workload
(`benchmarks/workloads/c-etl`), run alone.

| Condition | Median | p95 | Minimum | Maximum | Rel. std. dev. | Runs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct execution (baseline) | **8.3527 ms** | 8.4716 ms | 8.2955 ms | 8.5733 ms | 0.61% | 50 |
| Cold traced execution | **18.7356 ms** | 19.8764 ms | 18.1971 ms | 21.3433 ms | 2.79% | 50 |
| Guarded cache hit (end-to-end) | **4.0019 ms** | 4.8178 ms | 3.8451 ms | 5.2256 ms | 7.46% | 50 |
| Guard check only (internal) | 1.5293 ms | 1.6042 ms | 1.4232 ms | 1.6355 ms | 2.66% | 50 |

Derived:

- **Speedup on a cache hit: 2.0872x; absolute time saved: 4.3508 ms per hit.**
- **Initial tracing overhead: +124.31%** (cold traced median versus direct median).
- **Hits needed to amortize one cold trace: 2.39.**
  Formula: `(cold − direct) / (direct − hit)` = `(18.7356 − 8.3527) / (8.3527 − 4.0019)`
  = `10.3829 / 4.3508`. The break-even rows below agree: the 1 ms target loses,
  the 5 ms target wins.
- Hit rate is not the variable; the workload is recomputed only on a miss.

Correctness in the same session: output equivalence **PASS** (baseline, traced and
cached runs produce identical stdout, stderr, exit status and output SHA-256),
mutation/deopt **PASS** (mutating `benchmarks/workloads/python-etl/inputs/sales.csv`
produced `DEOPT`, the explanation named that dependency, and the mutated result
was reproduced). No benchmark failed.

## 2. Current commit — duration sweep and break-even

`benchmarks/harness/break_even.py --runs 50 --warmups 10`. The workload is a
synthetic integer fold whose round count is calibrated to a target duration.

| Target | Baseline median | Baseline p95 | Cold traced median | Cold p95 | Cache hit median | Hit p95 | Tracing overhead | Speedup | Time saved |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 ms | 1.688 ms | 1.853 ms | 11.137 ms | 11.999 ms | 3.964 ms | 4.083 ms | 559.77% | **0.426x** | **−2.276 ms** |
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

- **Break-even:** the slowest measured loss had a direct baseline median of
  **1.688 ms**; the fastest measured win had a direct baseline median of
  **5.284 ms**. No curve was fit between those points.
- Cache-hit time is flat at ~4.0–4.3 ms across three orders of magnitude of
  baseline, so the speedup is essentially `baseline / 4.1 ms` once the baseline
  exceeds ~10 ms. The 5700x span in the table is an artifact of the 5 s target,
  not of the cache getting faster.

## 3. Cache size and output-restoration cost

- **Fixed cost breakdown on the hit path** (medians of the cache-hit samples,
  current commit):

| Phase | Median |
| --- | ---: |
| Process startup (not added into the accounted total) | 5.748 ms |
| CLI parsing | 0.070 ms |
| Identity, executable hash, filesystem discovery | 0.125 ms |
| Cache directory initialization | 0.015 ms |
| SQLite open | 0.115 ms |
| SQLite schema and pragmas | 0.254 ms |
| Lookup-key hash | 0.008 ms |
| SQLite candidate query | 0.068 ms |
| Candidate JSON decode | 0.187 ms |
| Guard validation | 0.784 ms |
| CAS restore (output restoration) | 0.910 ms |
| Cached stdout/stderr load | 0.021 ms |
| Decision persist | 0.000 ms |
| Stdout/stderr replay to the terminal | 0.034 ms |
| Unaccounted, including process exit | 1.638 ms |

  Guard validation (0.784 ms) plus CAS restore (0.910 ms) is the safety work that
  cannot be skipped on a hit; the accounted phases plus unaccounted time
  reproduce the ~4.0 ms hit median. The dominant fixed cost is process startup
  (5.748 ms), which is why short commands cannot win.
- **Cache size:** see `benchmarks/results/phase1/cache-size.md` for the measured
  on-disk size of one saved record for this workload and its largest objects.

## 4. Historical results, clearly labelled

These are the values already committed in this repository, measured on a
**different machine** (a 4 vCPU GitHub-hosted runner on kernel 6.17, AMD EPYC
9V74) — they are not the numbers above and must not be combined with them.

| Source | Commit | Workload | Baseline | Traced cold | Cache hit | Speedup | Overhead |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `benchmarks/results/latest.md` | `63e33638709aacfaed896ab587435e64c0ecea62` | 8 ms C ETL | 7.396 ms | 21.024 ms | 7.957 ms | **0.929x (a loss)** | 184.26% |
| `benchmarks/results/break-even.md` | `e9684c1c01a7bbbab4cae50e2389105596d613f1` | `c-transform` | 312.913 ms | — | 3.972 ms | 78.780x | — |
| `benchmarks/results/break-even.md` | `e9684c1` | short C ETL | 8.493 ms | — | 3.940 ms | 2.156x | — |
| `benchmarks/results/break-even.md` | `e9684c1` | sweep break-even | slowest loss 1.796 ms | — | — | fastest win 5.274 ms | — |

Reading them together:

- The **published loss** in `latest.md` (0.929x) is a real historical result that
  was deliberately kept. It predates the hit-path optimization recorded in
  `break-even.md` (record rewrite near 3.1 ms and record decode near 0.75 ms were
  removed from the hit path), which is why the same workload class now measures
  2.156x (historical, `e9684c1`) and 2.087x (this host, this phase). The current
  number corroborates the historical post-optimization number; it is not a new
  performance claim.
- The break-even band is stable across machines: **1.796 ms / 5.274 ms**
  historically versus **1.688 ms / 5.284 ms** here.
- `c-transform` is **synthetic** (`EXTRA_ROUNDS = 250000000`); 78.78x there says
  nothing about any real workload. It is included because it is part of the
  repository's history, not as evidence of general speedup.

## 5. Pre-fix versus post-fix on this host

The audit baseline was measured on the untouched audit commit before any Phase 1
change, by the same harnesses on the same VM. Both sessions ran alone.

| Condition (native C ETL, 50 runs) | Pre-fix `f90b4db` | Post-fix `6358522` + fixes | Delta |
| --- | ---: | ---: | ---: |
| Direct baseline median | 8.4583 ms | 8.3527 ms | −0.11 ms (session noise) |
| Cold traced median | 26.7081 ms | 18.7356 ms | **−7.97 ms** |
| Cache hit median | 4.3402 ms | 4.0019 ms | −0.34 ms |
| Guard check median | 1.9524 ms | 1.5293 ms | −0.42 ms |
| Tracing overhead | 215.76% | 124.31% | −91.5 points |
| Speedup | 1.9488x | 2.0872x | +0.14x |

| Sweep point | Pre-fix cold | Post-fix cold | Pre-fix hit | Post-fix hit |
| --- | ---: | ---: | ---: | ---: |
| 1 ms | 17.785 ms | 11.137 ms | 4.780 ms | 3.964 ms |
| 5 ms | 21.259 ms | 15.045 ms | 4.542 ms | 4.079 ms |
| 100 ms | 105.255 ms | 100.607 ms | 4.001 ms | 3.980 ms |
| 5000 ms | 4388.074 ms | 4403.443 ms | 4.498 ms | 4.101 ms |

The cold path and the guard check were measurably faster in the post-fix
session, and the direct baseline was unchanged within noise, so overhead fell
from 216% to 124%. **I did not isolate the cause.** Two Phase 1 changes touch the
cold path (cache-integrity recovery and the transactional restoration rewrite)
and one touches the hit path; attributing the delta to any single one would
require a controlled A/B run that this phase did not perform.

## 6. Noise, uncertainty, and unsuccessful runs

Noise and uncertainty:

- Direct baseline relative standard deviation is 0.61%; the cache-hit condition
  is the noisiest at 7.46% (p95 4.82 ms versus median 4.00 ms), consistent with
  a fixed ~4 ms path plus occasional scheduler delay on a shared 2 vCPU VM.
- Single 50-sample session per condition. The brief asks for independent-session
  repeats where practical; the pre-fix/post-fix pair is such a repeat (separate
  sessions hours apart), but I did not repeat the *post-fix* native run in a
  second quiet session, so the ±0.1 ms difference between the two baselines is
  session noise, not a change.
- CPU frequency, turbo state, host CPU steal and neighbouring tenant activity are
  uncontrolled and not recorded. The historical GitHub-runner numbers are
  similarly uncontrolled but on a different machine.
- The sweep's 1 ms point showed a large spread (baseline p95 1.853 ms versus
  median 1.688 ms) because the calibration targets a very short process.

Unsuccessful, discarded, or aborted runs — reported rather than hidden:

1. **Two suite launches were cut short** by a cloud-runner restart in the middle
   of this phase. The first died during the native benchmark; its logs were kept
   and no numbers from it were used.
2. **A concurrent-launcher mistake contaminated one native session.** A second
   suite was started while the first was still sweeping, so the 00:18:58 native
   session ran beside a duration sweep. Those numbers were **discarded**: the
   running processes were stopped by recorded PID and the affected conditions
   were re-measured alone. Every number quoted in this report comes from a
   session with no other measurement process alive (verified with `ps`).
3. **A census run failed on a harness syntax error that I introduced** while
   editing the reason categorizer. It exited 1 with an `IndentationError`, the
   defect was fixed, and the census was re-run; the numbers in the compatibility
   report come from the fixed run.
4. **A pre-fix equivalence failure was found and then fixed rather than
   tolerated**: the Pillow workload's traced run exited 1 with zero writes
   because of the `argv[0]` defect (reliability audit D6). The harness reported
   it as a loud mismatch; after the fix the same workload passes.
5. **Two harness infrastructure failures** in the first suite attempt: the
   output directories did not exist (`--output-dir` is not created by the
   harnesses), so both benchmarks exited immediately. The launch procedure now
   creates them, and this is noted because it is a usability trap, not a
   measurement result.
6. **Repository-mutation check false positive.** The sweep's
   `repository_changes_during_run` lists eight paths, all of which are files
   *this agent* wrote during the long sweep (reports, staged results,
   `PROJECT_STATE.md`). The check behaved correctly — it detected writes during a
   run — but the writer was me, not the benchmark. The native session, which ran
   for three seconds, lists only
   `benchmarks/workloads/python-etl/inputs/sales.csv`, the dependency the deopt
   check mutates on purpose.

## 7. What these numbers do not show

- They are one workload class (C, no allocation, no clock, no randomness) on a
  2 vCPU VM. They are not evidence about Python, compilers, shells, or any other
  workload; the census in the compatibility report shows those are all refused.
- They say nothing about multi-process trees, sandboxed (`--enforce`) runs, or
  `PROVEN` reuse, none of which could be exercised here (no Landlock).
- The `c-transform` speedup is a synthetic workload and is not a product claim.

## Reproducing

```bash
cargo build --workspace --release
python3 benchmarks/harness/benchmark.py --runs 50 --warmups 10 \
  --output-dir benchmarks/results/phase1
python3 benchmarks/harness/break_even.py --runs 50 --warmups 10 \
  --output-dir benchmarks/results/phase1
python3 benchmarks/realworld/census.py --runs 5 --warmups 1 \
  --output-dir benchmarks/results/phase1
```

Raw sample arrays, environment dumps and the phase medians are in
`benchmarks/results/phase1/{native-latest.json,break-even.json,census.json}`.

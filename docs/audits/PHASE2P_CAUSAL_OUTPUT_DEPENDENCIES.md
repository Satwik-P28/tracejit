# Phase 2P: causal output dependencies, reproducible compiler reuse, and cache economics

Base `8dd97cd`. Measured on Ubuntu 24.04, Linux 6.1.102, 8 vCPU, GCC 13.3.0, ccache 4.10.2,
sccache 0.8.2. All benchmarks used `TRACEJIT_CACHE_DIR`; every session had a fresh cache.

## 1. The Phase 2O false hit, and the harness bug that hid it

**A confirmed false hit existed in `8dd97cd`.** A test program that stats its own `-o`-style output
path, writes `ABSENT` when it is missing and `PRESENT` when it exists, was reused across the
presence change: the cached `ABSENT` result was returned and the file contained `ABSENT` while a
native second run contains `PRESENT`. This is a release blocker, not a performance issue.

Two independent defects caused it.

1. **Negative observations were discarded.** `stat` of an absent path produces
   `FileMetadata(absent)`; that is a real dependency, and the `FileMetadata` guard already replays
   it. But the contract normalization dropped *every* `FileMetadata` record whose path the command
   later wrote, including the absent one, so nothing remained to refuse the hit.
2. **The drop was not scoped to the audited toolchain.** It ran for any command behind
   `--contract compiler-runtime-v1`, so an un-audited program inherited the compiler's contract.

The observation audit for `gcc -O2 -c` is:

| Question | Answer |
| --- | --- |
| What was observed? | `stat`/`lstat` of the `-o` target, and `stat` of its parent directory |
| When? | before the write; the parent-directory stat also precedes the command's own entries |
| Produced by this execution? | the *pre-state* was not (it came from the previous build); the hit-time state is |
| Required to stay equivalent? | yes for the presence/type/permission class, no for bytes and timestamps |
| Changes that must not invalidate? | the command's own artifact bytes, inode, mtime, ctime, size |
| Changes that must invalidate? | absent↔directory, file↔symlink, writable↔read-only, ownership change |

`SymlinkMetadata` (lstat) and `FileMetadata` (stat) had been treated asymmetrically: the first kept
its full fingerprint and refused reuse (the Phase 2O harness saw this), the second was dropped
entirely. Both are now one explicit class.

**The Phase 2O hit harness never set the cache variable the CLI reads.** It used
`TRACEJIT_CACHE`; `Cache::default_root` reads `TRACEJIT_CACHE_DIR`, so every arm shared the default
cache. That explains both the zero-hit table and the contradiction with the separate fixture. The
repaired harness in `benchmarks/repos/compiler_hits.py` records the decision, the failing guard and
the artifact hash for every invocation and asserts the cache variable it uses.

## 2. Causal model and correctness contract

The change is deliberately small: one new observation class, one audit bit, and gating.

- `FileMetadataRead` now carries `audited_toolchain`, set by the tracer from `/proc/<pid>/exe` and
  its GNU build ID against `COMPILER_RUNTIME_PROFILES`. It is per observation, not per command.
- Under the contract, a metadata/lstat observation **by an audited process** of a path the command
  writes becomes `ReadEffect::OutputPrestate { path, class }` →
  `InputDependency::OutputPrestate` → `Guard::OutputPrestate`.
- `class` is `AbsentOrWritableFile` or `Other`. `Other` makes the execution ineligible; it is never
  reused. At validation, the current path must be absent or a writable regular file, otherwise the
  guard fails.
- A directory metadata observation by an audited process is downgraded to `DirectoryOpened`
  (identity, mode, uid, gid, plus a probe open) as in Phase 2O, but now only for audited processes.
- **Everything else is unchanged.** An un-audited program's stat of any path, including its own
  output, keeps the ordinary `FileMetadata` guard, positive or negative. The Phase 2P regression
  test exercises exactly that.

Correctness invariants, each tested:

1. A negative observation of a path that is not an audited compiler output is never dropped.
2. A read that precedes a write keeps its content guard; dropping pre-state never drops content.
3. `OutputPrestate` covers only the writability class. A directory, symlink, read-only file or
   special file is `Other` and refuses reuse.
4. `OutputPrestate` exists only under `tracejit.compiler-runtime.v1` for an audited binary; a record
   without the contract is not eligible and records from different contracts never mix.
5. Program-created temporary state is not guarded as an external input; the directory it mutates is
   guarded by identity and permissions, not timestamps.
6. An unsupported shape fails closed (ineligible, or a deoptimizing guard failure), never a hit.

Declared contract, stated plainly: the audited compiler's artifact does not depend on the old bytes,
timestamps, size or inode of its own `-o` path; it depends on the path being absent or a writable
regular file. This is narrower than Phase 2O and refuses the states that change the write's outcome.
It remains a declared contract, not a claim of universal native equivalence.

## 3. Adversarial results

| Case | Result |
| --- | --- |
| un-audited program stats its absent output, then it exists | second run **Deoptimized**, file `PRESENT` (was a false hit) |
| output path replaced by a directory | **Deoptimized**: "output path is no longer a writable regular file" |
| output path replaced by a symlink | **Ineligible**, symlink target untouched |
| output path made read-only (0444) | **Ineligible**, no success replayed |
| header edited between runs | **Deoptimized**: "file content changed" |
| compiler flags changed | different identity, executed |
| failed compilation | exit status matches native (exit 1) |
| four concurrent cold compiles | all correct, no lock error (Phase 2O, unchanged) |
| native record then controlled run | `Executed/Executed`, no reuse across contracts |
| controlled record then native run | `Executed/Ineligible`, no reuse across contracts |

## 4. Repaired benchmark: reuse is reproducible

`benchmarks/results/phase2p/compiler-hits.json`, two sessions with reversed order, two projects
(zlib 1.3.1, lz4 1.9.4), two layouts (external output directory and in-tree source/output), fresh
cache per session, distinct output path per translation unit.

- **Reused: 36 of 36 rows.** In-tree: 18 of 18.
- **Artifacts byte-identical to native: 36 of 36.**
- Cold run is `Executed/Guarded`; every reported hit is a real `Reused` with no failing guard, and
  every arm records `cold_decision`, `hit_decision` and the failing guard reason.

Medians across all rows (`summary.json`):

| Arm | Median |
| --- | --- |
| native | 259.02 ms |
| TraceJIT cold | 586.74 ms (+327.72) |
| TraceJIT hit | 71.67 ms |
| ccache warm | 3.96 ms |
| sccache warm | 8.36 ms |

By project: zlib native 179.61, cold 461.57, hit 71.23; lz4 native 2052.46, cold 2421.63, hit
72.25 (only 1.18x tracing overhead on the 2 MB translation unit, versus 2.6x on the small ones).
Hit latency is 62-79 ms except under concurrent load (334-414 ms in three rows).

## 5. Hit-cost breakdown

`TRACEJIT_PHASE_TIMING=1` on a deflate.c hit, milliseconds:

| Phase | Run 1 | Run 2 |
| --- | --- | --- |
| process startup and CLI parse | 10.4 | 9.6 |
| identity prepare | 0.7 | 0.6 |
| SQLite open, schema, lookup, decode | 8.4 | 6.5 |
| **guard validation** | **47.5** | **45.2** |
| CAS restore | 2.6 | 2.7 |
| decision persist | 19.2 | 0.0 |
| present | 0.04 | 0.03 |

Guard validation is fixed-cost: hashing `gcc` (1.0 MB), `cc1` (30 MB) and `as` (1.0 MB) plus the
source and headers. No optimization was retained. Every candidate that removes the per-run hash
(inode generation, mtime, a persisted fingerprint) is exactly the shortcut the safety rules forbid,
because an edited toolchain could pass it. A content-addressed snapshot still requires reading the
bytes to know they are unchanged. Batched validation within one process is already in place; the
floor is per-process. `decision_persist` is a one-off per record.

## 6. Competitive evaluation

Ten identical rebuilds of one unit after the trace (one cold plus nine hits):

| Arm | Time |
| --- | --- |
| native | 2590 ms |
| TraceJIT | 1232 ms (2.10x faster than native) |
| ccache | 40 ms |
| sccache | 84 ms |

TraceJIT's hit is 18x slower than ccache's and 8.6x slower than sccache's. Against native it wins on
repeated identical compiles, but no real edit-build loop repeats a unit without changing its
inputs, and ccache serves the changed-input case in 4 ms. Cold tracing costs 1.2-2.6x the native
compilation it replaces, so the first build of every unit is a loss.

## 7. Decision

**NO-GO for compiler acceleration.** Reuse is now sound and reproducible in both realistic layouts,
and every artifact matched, but the architecture cannot deliver a meaningful advantage for any
actual compilation workflow: it is 18x slower than the specialist cache on hits, costs more on cold
builds, and its soundness depends on re-hashing the toolchain on every invocation. Continuing would
require either weakening identity validation (forbidden) or removing per-process startup and
validation costs that are inherent to a ptrace-based whole-command cache.

Recommended next workload class: deterministic whole-command utilities and transforms with
file outputs and durations of roughly 100 ms or more, where a 60-70 ms guarded hit still repays the
trace (gzip measured 6.7-7.2x in Phase 2F). Compilers belong to ccache/sccache.

The compiler contract remains experimental and opt-in; native behaviour, classifiers and `PROVEN`
gating are unchanged.

## 8. Gates and limits

- `cargo fmt --all -- --check`, Clippy `-D warnings`, `cargo test --workspace`: **116 tests pass**,
  including the false-hit regression and the output-pre-state guard test. A shared lock serialises
  the two tests whose assertions depend on measured wall-clock thresholds.
- `PROVEN` remains **BLOCKED** (`landlock no`, `seccomp yes`); no enforcement path changed.
- **CI is BLOCKED, not green:** the branch is unpushed, so the only run is
  [42319563118](https://github.com/Satwik-P28/tracejit/actions/runs/42319563118) at `c7f2c68`.
- Not established: concurrent output-path mutation between guard validation and CAS restore keeps
  the existing TOCTOU window that `PROVEN` is meant to close; mount-namespace changes are untested
  (no privileges); the declared output-pre-state class was validated with absent and pre-existing
  objects, not every possible pre-state.
- ccache and sccache were installed as static binaries in `~/.local/bin`; no root was available.

## 9. Reproduce

```bash
cargo build --release --workspace
python3 benchmarks/repos/compiler_hits.py benchmarks/results/phase2p/compiler-hits.json
TRACEJIT_PHASE_TIMING=1 TRACEJIT_PHASE_TIMING_PATH=/tmp/phases.json \
  TRACEJIT_CACHE_DIR=/tmp/tjp ./target/release/tracejit run --contract compiler-runtime-v1 --json -- \
  gcc -O2 -I/tmp/ccbench/zlib-1.3.1 -c /tmp/ccbench/zlib-1.3.1/deflate.c -o /tmp/out.o
```

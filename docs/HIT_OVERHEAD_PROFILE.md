# Warm-hit overhead: where the floor comes from, and the one change that moved it

All numbers on this host (8 vCPU, Linux, glibc 2.39-0ubuntu8.12, gcc 13.3.0),
one binary per column, same corpus. Evidence: `benchmarks/results/phaseab/hit_profile_baseline.json`,
`hit_profile_after.json`, `ab_hits.json`; harnesses `benchmarks/phase_ab/hit_profile.py`
and `ab_hits.py`.

## 1. The measurement, and what Phase AA1's "pre-runtime" really was

`run()` starts its `runtime_ns` clock **after** identity preparation, cache open,
lookup-key construction, the candidate query and record decode (crates/tracejit-core,
`let started = Instant::now()`). Phase AA1 computed "pre-runtime" as
`wall - runtime - persist - present`, so that residual silently contained all of
those phases plus the harness's own `fork`/`exec`/`wait` and pipe setup.

Measured directly, with the clocks TraceJIT already takes on disjoint intervals
(medians of 15 warm hits per workload, plain mode, one `--json` calibration per
row outside the timer):

| Workload | wall | core `runtime_ns` | identity | sqlite open + schema | query | decode | guards | restore | cli parse |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `readelf-header` | 15.46 | 7.77 | 0.70 | 0.61 | 0.58 | 0.45 | 6.89 | **1.73** | 0.17 |
| `cut-columns` | 13.59 | 7.28 | 0.29 | 0.61 | 0.58 | 0.56 | 5.13 | **1.98** | 0.17 |
| `gzip-6-stdout` | 6.90 | 2.44 | 0.32 | 0.55 | 0.34 | 0.24 | 1.09 | **1.58** | 0.16 |
| `sed-substitute-file` | 16.04 | 17.05 | 0.33 | 0.56 | 0.63 | 0.65 | 6.16 | **2.26** | 0.16 |
| `gcc-cc-small-tu` | 63.79 | 51.99 | 0.68 | 0.61 | 1.58 | 1.51 | 48.44 | 3.99 | 0.17 |

(ms; all phases in the table are inside the wall and outside `runtime_ns`.)

A separate floor measurement — `tracejit --version`, i.e. dynamic linking, clap
parsing and exit with no cache open — is **2.3–2.9 ms** on this host. So the
"6.5–16 ms before entering the core runtime" of Phase AA1 is an artefact of the
residual method: the parts a hit actually pays before `runtime_ns` are 2–4 ms
(process + version floor + identity + SQLite + query + decode).

## 2. The one change that mattered: no restore intent without outputs

`Cache::restore_outputs` wrote a durable restore intent — temp-file write,
`fsync`, `rename`, directory `fsync` — and cleared it again for **every** record,
including records with no workspace outputs. A pure filter (`readelf`,
`objdump`, `cut`, `gzip -c`, `sed` to stdout) has no destination to rename, no
backup to roll back, and therefore no window that a hard kill could leave
"mixed". The intent protected nothing and cost 1.6–2.3 ms per hit.

The fix is an early return when `outputs.is_empty()` (crates/tracejit-cache).
The invariant it must not weaken is "a killed restore cannot expose a partial
workspace"; with zero destinations no restore mutation happens at all. Streams
are verified and replayed by the caller, not by `restore_outputs`.

Regression: `restoring_no_outputs_writes_no_restore_intent` asserts that no
intent file is created, that a reopened cache reports no interrupted restore, and
that no temporary remains.

### Paired, interleaved result

`ab_hits.py` runs baseline A and candidate B alternately on twin workspaces with
separate caches and asserts both report `cache HIT` and byte-identical stdout.
25 rounds, median of paired differences, bootstrap 95 % interval:

| Workload | A (before) | B (after) | Δ median | 95 % CI | Distinguishable |
| --- | ---: | ---: | ---: | --- | --- |
| `cut-columns` | 13.77 | 11.29 | −1.91 | 1.65 … 2.71 | yes |
| `gzip-6-stdout` | 8.17 | 5.88 | −2.22 | 1.87 … 2.79 | yes |
| `sed-substitute-file` | 16.83 | 14.00 | −2.45 | 1.12 … 3.90 | yes |
| `gcc-cc-small-tu` | 63.83 | 61.66 | −2.63 | −2.35 … 4.29 | **no (noise)** |
| `readelf-header` | — | — | — | — | baseline warm-up lost its hit to a classification refusal; not measured |

The compiler row is the control: `gcc` writes an object, so it still pays the
intent and the interval spans zero. The others move by the measured intent cost.

`gzip -6` is the practical consequence: 8.17 ms → 5.88 ms against a native median
of 6.2 ms in the frozen corpus. A hit on a 6 ms filter is now a small **win**
rather than a 0.77× loss. That is the difference between "the fixed cost makes
short commands unusable" and "short filters are at parity".

## 3. Decision persistence: paid once, not per hit

Phase AA1 reported 3.5–20 ms of `post_runtime_ns` persistence *per hit*. Measured
per sample on `/bin/true` with phase timings:

| Run | `decision_persist_ns` | What happened |
| --- | ---: | --- |
| 1 | (no phase file) | cold trace: record stored; the CLI writes no phase file for a report without phases (instrumentation gap, §5) |
| 2 | **4.57 ms** | first hit: record's decision flips `Executed`→`Reused`, written durably |
| 3 | 0 | steady-state hit: nothing to write |
| 4 | 0 | steady-state hit |

The code already skips the write when `candidate.last_decision == Reused`
(tracejit-core), and `record_admission` is skipped for the default
`Admission::Always`. So the correct statement is: **one durable write per record
lifetime, not one per hit**. Phase AA1's figure is the first-hit cost. No change
was made here because none is available without changing when a record claims
`Reused` — and that claim is what a crash must not fabricate.

## 4. Candidates examined and rejected

| Candidate | Verdict |
| --- | --- |
| Skip the decision write on every hit | already skipped; measured 0 on steady-state hits |
| Cache the SQLite schema check | already version-gated by `PRAGMA user_version` (0.55–0.61 ms total open+schema) |
| Batch or drop WAL/`synchronous=FULL` | would trade crash consistency for <1 ms; rejected |
| Share digests between guard kinds within a pass | Phase X's same-tick counterexample applies; rejected on correctness, not speed |
| Parallel guard validation | Phase W measured 111.7 → 110.6 ms; rejected |
| Daemon or shared-memory cache | not justified by a 2–4 ms pre-runtime band; rejected |
| Field-precise metadata guards (drop `atime` from content reads) | sound design (see §5) but not implemented this phase |

## 5. What remains, and what it would buy

The compiler hit is dominated by guard validation (48.4 ms of 52.0 ms; 107 MB
hashed, 66 MB of it the same compiler image read under three guard kinds). No
sound reduction was found in this phase. The next two candidates, in order:

1. **Field-precise metadata guards.** A content-read guard currently pins
   `atime`, which the reading command itself updates, so `gzip -9`, `strip` and
   `objcopy` are permanently ineligible after the first run. The sound rule is
   narrow: keep `atime` for a recorded *metadata* observation (the program
   `stat`ed the file), drop it for a recorded *content read*, because the only
   way a program can observe `atime` is a traced metadata syscall. It needs a
   record-format change, a compatibility story for old records, and its own
   adversarial matrix; it was not rushed here.
2. **One hash per file per pass, with pre/post stat equality**, which unproven
   mutations can still defeat; Phase X rejected the cross-run version and this
   phase did not find a proof for the within-pass version either.

Instrumentation gap worth fixing: a cold-trace report carries no `phases`, so the
record-store half of persistence can only be observed indirectly. Attaching the
timings to every report would make the next profile complete.

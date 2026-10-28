# Phase 1.5 final benchmarks

Measured on the final verification commit with the Phase 1.5 fixes included. No measurement in this
document was calculated from a historical artifact; the historical values in §6 are labelled as
such and are never mixed into a current result.

## 1. Provenance

| Field | Value |
| --- | --- |
| Commit measured | `4eb3ad5824fc4c884e153cb5b2e0e5fa85a16962` (then `800a2fc` for harness metadata only) |
| Branch | `verify/phase1-5` |
| Working tree at launch | 2 modified paths — the two harness files being fixed for D10. The recorded `working_tree_dirty: true` is **correct**, not spurious |
| Distribution | Ubuntu 24.04.5 LTS |
| Kernel | 6.1.102 (`freestyle-vm`) |
| Architecture | x86_64 |
| CPU | 2 vCPU (family 19h, model 01h) |
| RAM | 3.8 GiB, no swap |
| Filesystem | ext4 on `/dev/root` |
| Rust / Cargo | rustc 1.99.1 (58cf8f9c3), cargo 1.99.1 |
| Python | 3.12.3 |
| ptrace | available (no Yama restriction) |
| seccomp | available |
| Landlock | **unavailable**: LSM list `capability,selinux`; `ENOSYS` |

Two sessions were run sequentially, with nothing else benchmarking on the host.

## 2. Method

Unchanged from Phase 1: `benchmarks/harness/benchmark.py --runs 50 --warmups 10`. The committed C
ETL workload is built once; baseline samples execute that binary directly; every traced-cold sample
uses a **fresh** cache; cached samples use one unchanged guarded entry and must report a hit; guard
timings are TraceJIT's internal validation, restoration and stream-loading duration, measured from
the report rather than wall clock. The harness fails loudly on an output-equivalence mismatch, on a
failed hit assertion, and on a failed mutation/deoptimization check. OS caches are warm in both
sessions.

## 3. Current results

| Condition | Session 1 median | Session 1 p95 | Session 2 median | Session 2 p95 | Delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct baseline | **8.3414 ms** | 8.4309 ms | **8.3508 ms** | 8.4394 ms | +0.11% |
| Cold traced | **19.0236 ms** | 19.8500 ms | **18.5066 ms** | 19.1962 ms | −2.72% |
| Guard validation | **1.5950 ms** | 1.7305 ms | **1.5548 ms** | 1.8151 ms | −2.52% |
| Warm cache hit | **3.9715 ms** | 4.1878 ms | **3.9912 ms** | 5.2914 ms | +0.50% |

| Derived metric | Session 1 | Session 2 |
| --- | ---: | ---: |
| Cache-hit speedup | **2.1003x** | **2.0923x** |
| Median time saved per hit | **4.3699 ms** | **4.3597 ms** |
| Tracing overhead | **+128.06%** | **+121.61%** |
| Hits to recover one cold trace | **2.44** | **2.33** |
| Output equivalence | PASS | PASS |
| Mutation / deoptimization | PASS | PASS |
| Recorded cache status on every cached sample | HIT (asserted) | HIT (asserted) |

Local dispersion is small: the published `relative_standard_deviation` fields are 0.00% baseline,
0.03% cold, 0.06–0.12% cached and 0.03–0.08% for guard checks in these two sessions. The larger
outlier seen in an earlier Phase 1.5 attempt (p95 15.6 ms against an 8.38 ms median) did not recur
and is attributed to a co-tenant process on this shared VM, not to TraceJIT.

Cache footprint for one record (`stdout_only` fixture): 2 CAS objects, 5 files in total, **48,279
bytes** including a 28,672-byte SQLite database — 1.6x the size of the one byte of stdout it stores,
which is dominated by the schema and WAL.

## 4. Interpretation

The ETL workload is dominated by a 250M-iteration fold, so this measures steady-state reuse of an
expensive computation, which is the best case for any cache. A hit still costs ~3.97 ms against an
8.34 ms baseline, i.e. **47.6% of the direct cost is spent proving that reuse is safe**, of which
guard validation is ~1.56 ms and CAS restoration ~0.9 ms. That ratio, not the 2.1x, is the number
that decides whether reuse is worthwhile for cheaper commands.

Two clean sessions agree to within 0.4% on speedup, so the result is reproducible on this host for
this workload. It says nothing about a different machine, a colder page cache, or a workload whose
baseline is under ~1.7 ms, where reuse is a net loss (Phase 1 measured 0.43x at a 1 ms baseline;
that measurement is historical and on a different host).

## 5. Break-even sweep — NOT COMPLETED

`benchmarks/harness/break_even.py --runs 50 --warmups 10` was launched after the two native
sessions and did not finish inside this verification window (the Phase 1 run of the same harness
took ~13 minutes per session on a 2 vCPU host; the process was still running when this document was
written). **No break-even band from this commit is reported**, because reporting one would mean
either inventing it or borrowing Phase 1's numbers. Status: **BLOCKED on wall-clock time**, with the
command recorded above so it can be completed without changing the method.

What can still be said from measured data: recovery requires **2.33–2.44 hits**, and a hit is a net
loss whenever `baseline < 1.7 ms` at these fixed costs is plausible only if guard validation and
restoration stay proportional; the Phase 1 sweep put the win threshold at 5.28 ms of work.

## 6. Comparison with historical results (not measured together)

| Commit / host | Baseline | Cold | Cached | Speedup | Note |
| --- | ---: | ---: | ---: | ---: | --- |
| `63e3363`, GitHub runner (4 vCPU) | 7.396 ms | 21.024 ms | 7.957 ms | **0.929x (loss)** | recorded honestly as a regression |
| Phase 1 post-fix, this host | 8.3527 ms | 18.7356 ms | 4.0019 ms | 2.0872x | before the D7 fix, same VM family |
| Phase 1.5 session 1 | 8.3414 ms | 19.0236 ms | 3.9715 ms | 2.1003x | clean measurement |
| Phase 1.5 session 2 | 8.3508 ms | 18.5066 ms | 3.9912 ms | 2.0923x | clean measurement |

The Phase 1.5 figures differ from the Phase 1 post-fix figures by ≤0.6% on every condition. That is
within this host's own session-to-session spread, so **there is no evidence of a performance change**
from the Phase 1.5 fixes; the retrace-on-refusal path is not taken during a hit, and the executable
resolution adds one `canonicalize` call per run.

The `c-transform` 78.78x figure (`312.913 ms → 3.972 ms`, `e9684c1`) is a deliberately synthetic
250M-round workload and is not comparable to anything above.

## 7. Raw artifacts

`benchmarks/results/phase1_5/` contains `session-1/latest.json`, `session-1/latest.md`,
`session-2/latest.json`, `session-2/latest.md`, the commit-stamped copies, and the two `explain-*`
transcripts, copied verbatim from the run directories.

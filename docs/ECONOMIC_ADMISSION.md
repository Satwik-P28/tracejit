# Economic admission (Phase AD)

Purpose: stop users wasting time caching what is cheaper to run, without ever letting an
economic decision affect correctness. The metric is total session wall time, not HIT rate.

Harness: `benchmarks/phase_ad/admission_sessions.py`. Raw data:
`benchmarks/results/phasead/admission_sessions.json`.

## 1. Audit of the existing mechanism

`Admission` (`crates/tracejit-core/src/lib.rs`) is a **pre-trace** decision. It cannot promote
a record, bypass a guard, or change a classification: after the decision, the same trace,
classification and guard pipeline runs. Correctness eligibility is decided independently
(`PROVEN`/`GUARDED` only); an economically attractive command is still refused if its effects
are unmodelled.

| policy | rule | first invocation |
| --- | --- | --- |
| `never` | run directly, never trace | direct |
| `always` | trace and store every invocation | traced |
| `auto` (default) | trace when `direct ≥ 2 × max(hit, 6 ms)` **and** `hits + 1 > deopts` | direct, measured |
| `auto-v1` | Phase 2H threshold only: `direct ≥ 2 × max(hit, 6 ms)` | direct, measured |

Recorded per cache identity in SQLite: `direct_ns`, `cold_ns`, `hit_ns`, `hits`, `deopts`,
sample age (discarded after 30 days), and the hit floor `HIT_COST_FLOOR_NS = 6 ms`. The
decision uses the observed hit cost when one exists and the floor otherwise. `auto` is also the
only policy that reacts to invalidation: an identity whose inputs change before every run
(`hits + 1 ≤ deopts`) stops being traced even when it is expensive.

Failure cases found in Phase AA1/AC data and confirmed here:

* **Small filters are never admitted.** `gzip -9 -n -c` of 256 KiB text takes 7.6 ms direct; the
  rule needs `direct ≥ 12 ms`, so six consecutive identical invocations are all `SKIP`. Each
  one misses a ~2.6 ms saving.
* **Cheap hash commands are correctly declined, but only by luck of the floor.** `sha256sum`
  of 1 MiB takes 3.2 ms and its hit costs 13.1 ms: the rule declines it for the right reason.
  A lower floor would admit it and lose.
* **One-shot expensive commands are protected.** A single `bzip2 -9` of 2 MiB costs 232 ms
  directly and 314 ms traced (+82 ms). `auto` pays the measure-only cost; `always` pays the
  trace premium and never recovers it.
* **No policy distinguishes HIT, MISS, DEOPT and refusal in its statistics.** `deopts` counts
  invalidations, but a refusal (ineligible workload) is invisible to admission, so an identity
  that is repeatedly refused still records a `direct_ns` sample and may be re-admitted on the
  next invocation after a policy or contract change. Harmless (the trace refuses again) but it
  burns a trace attempt.
* **Input-size changes are not modelled.** A sample taken on a 1 KiB input justifies tracing a
  10 MiB input; the cache key differs, so the first large run pays a full trace whichever
  policy is chosen. This is a *predictability* gap, not a correctness one.

## 2. Cost model

For one identity observed `k` times in a session, with measured direct cost `D`, cold traced
cost `C`, hit cost `H`, reuse probability `p`, and deopt probability `q`:

```
E[cost | trace]     = C + (k−1)[(1−q)H + q·C′]
E[cost | never]     = k·D
E[cost | auto]      = D + (k−2)·D if not admitted, else trace from invocation 2
```

The break-even repetition count is `k* = 1 + (C−D)/(D−H)` for a stable input, i.e. the integer
`n*` reported in `docs/ARTIFACT_BENCHMARKS.md`. For the measured corpus `C−D` is 8–15 % of `D`,
so `n* = 2` for every compression workload at every size; hash-only workloads have `D < H` and
never break even at ≤10 MiB.

Three candidate policies were considered:

* **A — current `auto`.** Threshold plus an invalidation term, one direct sample first.
* **B — conservative threshold** (`D ≥ 4 × H`, no deopt term). Rejects more tracing; loses the
  small filters permanently and does not protect against one-shots any better than A.
* **C — uncertainty-aware adaptive.** Estimate the remaining repetitions from the identity's
  observed inter-arrival history and admit when the lower confidence bound on cumulative
  benefit is positive. This is the only candidate that could admit a 7.6 ms filter without
  admitting a one-shot, but it needs a history the current schema does not keep (only counts
  and last-run costs), and a wrong estimate costs a trace premium.

## 3. Mixed-session measurement

Session (24 steps, one workspace, one cache): 5× `bzip2 -9` (2 MiB, output deleted), 6×
`gzip -9 -n -c` (256 KiB text), 4× `sha256sum` (small), 3× `sed` (200k lines), 3× `gzip` with a
**changed input each time**, 2× a clock-reading command (permanently ineligible), 1× one-shot
`bzip2 -9`. Two independent repeats.

| arm | total (ms) | HITs | cache |
| --- | ---: | ---: | ---: |
| direct | 1638.8 / 1564.1 | – | – |
| `never` | 1663.3 / 1745.1 | 0 | 0.02 MB |
| `always` | **1229.3 / 1240.2** | 14 | 11.2 MB |
| `auto` (default) | 1284.7 / 1292.3 | 4 | 8.0 MB |
| `auto-v1` | 1279.7 / 1322.9 | 4 | 8.0 MB |
| retrospective oracle | 653.5 / 631.0 | 14 | – |

Trace of the default policy: `bzip2` SKIP → (traced, ineligible-looking second step) → three
HITs; `gzip` text all SKIP; `sha256sum` all SKIP; `sed` SKIP → trace → HIT ×2; changing-input
`gzip` SKIP ×3 (correct); clock SKIP ×2; one-shot `bzip2` SKIP (correct).

Findings:

1. **`never` is worse than direct** by 25–180 ms: TraceJIT's startup and cache open cost is paid
   even when nothing is cached. Users who know their workload is one-shot should not wrap it.
2. **`always` beats the default by 43–55 ms (3.4–4.2 %) in this session**, because it caches
   the small repeated filters the threshold rejects. It also wastes ~90 ms tracing the one-shot.
   The two effects nearly cancel in a session with more repetition; the default is the safer
   choice for sessions dominated by one-shots.
3. **Both online policies are ~2× the oracle.** The oracle's 653 ms is unattainable: it uses a
   HIT only where one was actually produced and direct execution everywhere else, i.e. it knows
   the future. The 590 ms gap is mostly the cold trace of `sed` (310 ms) and the four `bzip2`
   cold traces, which no online policy can avoid without knowing the session length.
4. **Admission never changed a correctness outcome**: every HIT in every arm passed its guards,
   every deopt re-executed, and the clock/entropy commands were refused under every policy.

## 4. Decision

No production change. The measured 4 % gap to `always` is smaller than the 8–35 % penalty
`always` pays on one-shot or mutating sessions (measured: +82 ms on a single `bzip2`, +25 ms on
`never`-style direct overhead), and it was reproduced only twice on one host. The current
threshold's real defect is that it cannot admit a *known-repeated* cheap filter; fixing that
requires session-history state that does not exist yet, and the first attempt would be a
heuristic, which the project's rules forbid without evidence.

What would justify a change later: a workload where `auto` is measured to lose more than 10 %
across at least three sessions and two hosts, plus a policy whose admission decision is a
provable lower bound on cumulative benefit (not a fitted threshold). Until then the honest
recommendation is the one in `docs/RELEASE_READINESS_V03.md`: use `always` for known-repeated
artifact generation, the default for mixed sessions, and skip TraceJIT entirely for one-shots.

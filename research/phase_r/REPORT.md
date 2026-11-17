# Phase R — adaptive candidate selection: native results and decision

**Decision: reject.** Newest-first stays. Every adaptive order evaluated is slower on
real end-to-end runs, including the one workload where it reduces candidate
validations. No production behaviour changes; the experimental modes stay on
`research/phase-r`.

## 1. Audit of the existing implementation

| Property | Current behaviour |
| --- | --- |
| Candidate query | `SELECT record_json … WHERE lookup_key = ? ORDER BY updated DESC, execution_id DESC LIMIT 8` via `prepare_cached` |
| Retention | 8 per identity (`TRACEJIT_CANDIDATE_BOUND`, 1–64 experimental) |
| Decoding | lazy: only candidates reached by the loop are decoded (~0.13 ms each) |
| Failed candidate | decode + candidate checks + **one full `validate_all`** |
| Successful candidate | decode + `validate_all` + stream verify + **second `validate_all`** (TOCTOU recheck) + restore |
| Decision persistence | only when the decision changes (miss→hit, deopt), not on every hit |
| Correctness gate | every candidate is fully validated; ordering never skips guards |

## 2. Implementation (research branch only, default path unchanged)

- `CandidateOrder::{Newest, LastSuccess, HitCount}` selected by
  `TRACEJIT_CANDIDATE_ORDER`; unknown values fall back to `Newest`.
- Schema v3 adds `last_success_unix_ms` and `success_count`; migration is idempotent and
  preserves rows. Malformed statistics `CAST` to 0, which reduces to newest-first.
- `record_candidate_success` runs **only** when a non-default mode is active, and is
  best-effort: a failed statistics write cannot turn a validated hit into an error.
- `candidates_examined` is reported in JSON so the ordering effect is measurable
  without instrumentation builds.
- Newest-first executes exactly the old SQL and performs no extra write.

## 3. Native benchmark

x86_64, release binary, guarded C fixture, 4 MiB inputs, 200 runs/cell after warmups,
isolated cache per cell, paired by run index. `direct` median 15.209 ms.

| Scenario | newest (median) | last-success | hit-count | examined (newest → last / hits) |
| --- | ---: | ---: | ---: | --- |
| single candidate | **28.175 ms** | 30.279 (+1.905 [+1.66, +2.26]) | 32.994 (+4.832 [+3.88, +5.40]) | 1.00 → 1.00 / 1.00 |
| A/B alternation | **31.090** | 34.776 (+3.744 [+3.17, +4.41]) | 36.101 (+5.626 [+5.04, +6.17]) | 1.50 → 2.00 / 2.00 |
| 8-state cycle | **41.260** | 54.948 (+15.365 [+13.90, +16.92]) | 56.820 (+17.689 [+16.10, +19.40]) | 4.47 → 8.00 / 8.00 |
| skewed 80/20 | **32.413** | 34.270 (+2.447 [+0.98, +3.21]) | 33.918 (+0.904 [+0.61, +1.71]) | 1.80 → **1.40** / **1.20** |

Numbers in brackets are percentile-bootstrap 95% CIs for the paired median difference.

## 4. Interpretation

1. **The statistics write costs more than the scan can save.** The single-candidate
   cell does identical validation work in every mode, yet last-success costs +1.9 ms
   and hit-count +4.8 ms per hit. That is the price of one synchronous SQLite UPDATE
   (`synchronous=FULL`) per hit. A zero-write ranking is possible only if it uses
   already-persisted data, which in this cache is stale on steady hits.
2. **Newest-first is already the right predictor for sticky inputs.** In A/B
   alternation and sequential cycles, the candidate that just hit is also the next one
   most likely to hit, or the one just written is the next target; measured examined
   counts for newest are 1.50 and 4.47 per hit.
3. **Last-success is the worst possible order for cycles.** In a cycle the previous
   state is precisely the one that will fail, so examined count rises to 8.00 and wall
   to +15.4 ms.
4. **The one favourable pattern still loses.** With an 80/20 skew, hit-count cuts
   examined candidates from 1.80 to 1.20 (≈1.3 ms of guard work at ~2.2 ms per failed
   validation), but pays +0.9 ms of statistics overhead and loses the rest to variance;
   even the point estimate is not a win, and the CI includes zero.
5. **Maximum realistic cumulative benefit.** Even granting perfect ordering, the prize
   is bounded by the failed-scan work: one candidate validation per skipped record, and
   ordinary sessions show 1.0–1.5 candidates. That is smaller than one fsync.

## 5. Correctness

- `cargo test --workspace`: pass (cache 36 tests, including new ordering/fallback and
  migration tests).
- `linux_integration`: 63/63 pass, including the new
  `candidate_order_override_preserves_reuse_and_outputs` (all three modes: Executed →
  miss → Reused with the right bytes and `candidates_examined ≥ 1`).
- Existing coverage continues to exercise A/B/A retention, timestamp-preserving content
  changes, symlink/hardlink substitution, corrupt artifacts, concurrent writers,
  eviction, interrupted restore and inherited descriptors.
- Ordering changes no classification, no eligibility, no guard set, and no restore
  ordering. A malformed statistics row cannot cause a hit; it only changes which
  retained record is tried first.

## 6. Modeled vs measured

Phase Q's candidate numbers were modelled from measured phase costs on a synthetic hot
distribution. Phase R measures the real path end-to-end. The modelled saving
(0.42 ms probability-weighted at m = 8) is consistent with the native result: at most
~1.3 ms of avoidable guard work, against ≥1.9 ms of persistence cost.

## 7. Limitations

- Synthetic guarded fixture, 4 MiB inputs, single-process runs; no developer corpus and
  no multi-process contention benchmark.
- The 2.2 ms per-failed-candidate estimate comes from the cycle cell, not a per-candidate
  timer.
- QPU/annealing findings from Phase Q are unchanged and remain negative.

## 8. Reproduce

```bash
cargo build --release --workspace
python3 research/phase_r/bench_candidates.py --runs 200
```

Raw: `research/phase_r/results/candidates.json`.

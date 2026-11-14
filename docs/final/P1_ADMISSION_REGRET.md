# P1 §10 — Adaptive admission / regret

Date: 2026-11-14  
Command: `./target/release/tracejit admission-eval`  
Raw: `benchmarks/results/final_p1/admission-eval.txt`  
Commit context: package tip `026e660f6722ee7dddbf8ec00caaf52a817c36cf`

## Invariant

Admission chooses whether to **pay for tracing**. It cannot override safety: it never skips guards, never reuses `UNKNOWN` / `NONDETERMINISTIC` / `EMPIRICALLY_STABLE`, and never invents eligibility.

Break-even (conceptual):

`expected benefit ≈ E[reuses] * (direct − verified_hit) − cold_trace − validation/invalidation/storage − policy overhead`

## Measured held-out matrix (deterministic offline)

```
policy            Never total_ns=866000000 oracle_ns=575000000 regret_ns=291000000 traces=0 hits=0 directs=34
policy           Always total_ns=1086000000 oracle_ns=575000000 regret_ns=511000000 traces=18 hits=16 directs=0
policy      CurrentAuto total_ns=624000000 oracle_ns=575000000 regret_ns=49000000 traces=2 hits=8 directs=24
policy        Threshold total_ns=744000000 oracle_ns=575000000 regret_ns=169000000 traces=10 hits=8 directs=16
policy             Ewma total_ns=744000000 oracle_ns=575000000 regret_ns=169000000 traces=10 hits=8 directs=16
policy  ConfidenceBound total_ns=624000000 oracle_ns=575000000 regret_ns=49000000 traces=2 hits=8 directs=24
RESULT phase-e-admission preferred=CurrentAuto regret_ns=49000000
```

## Decisions

| Hypothesis | Outcome |
| --- | --- |
| Production `CurrentAuto` preferred | **confirmed** (lowest regret among evaluated policies) |
| `ConfidenceBound` beats `CurrentAuto` | **rejected** — tied; prefer simpler CurrentAuto |
| EWMA / Threshold as default | **rejected** — higher regret |
| Always-trace as default | **rejected** — worst regret on this matrix |
| Bandit / contextual ML default | **rejected** (unchanged; no material win justifying complexity) |
| Change production policy in this PR | **no** |

## Live e2e interaction

On the §9 hit-floor shape, AUTO median (3.656 ms) beat always-warm (5.725 ms) by skipping unprofitable work (`Skipped` decisions in `e2e.json`). That is cost avoidance, not a safety bypass.

## Non-claims

- Offline regret is not a proof about every developer session.
- A fast selected HIT can still lose a full session (see §9 objective 3).

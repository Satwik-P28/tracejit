# Phase K9 — Cost-aware admission research (offline re-eval)

Date: 2026-11-14  
Tip: `364331b904d41de3feb7defae152ec0e50112e0e`  
Command: `./target/release/tracejit admission-eval`  
Raw: `benchmarks/results/phase_k9/admission-eval.{txt,json}`

## Invariant (unchanged)

Admission chooses whether to **pay for tracing**. It never skips guards, never reuses `UNKNOWN` / `NONDETERMINISTIC` / `EMPIRICALLY_STABLE`, and never invents eligibility.

## Measured RESULT (deterministic held-out matrix)

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
| Production `CurrentAuto` preferred on held-out matrix | **confirmed** (regret 49 000 000 ns) |
| `ConfidenceBound` beats `CurrentAuto` | **rejected** — tied; `prefer_simpler` keeps CurrentAuto |
| Bandit as default admission | **rejected** (unchanged from Phase E) |
| EWMA / Threshold as production default | **rejected** — higher regret than CurrentAuto |
| Change production policy based on this re-eval | **no** — production unchanged |

## Negative retained

Always-trace is the worst policy on this matrix (regret 511 000 000 ns). Never-trace also loses substantially. Cost-awareness earns its keep offline, but **does not** justify more complex defaults.

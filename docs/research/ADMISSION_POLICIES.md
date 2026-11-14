# Cost-sensitive adaptive admission (Phase E)

## Status

**implemented+verified** — analytical expected-benefit model + offline policy comparison on a held-out synthetic matrix.  
**experimental** — EWMA and confidence-bound policies (research only; production `auto` unchanged).  
**rejected** — introducing a bandit as the default when simpler policies match or beat it on regret.

## Invariant

Policies choose whether to **pay for tracing**. They never skip guards, never reuse `UNKNOWN` / `NONDETERMINISTIC` / `EMPIRICALLY_STABLE`, and never invent eligibility.

## Model

`expected_benefit(AdmissionCost)` uses hit probability `hits/(hits+deopts)` (0 when unsampled — fail closed on optimism):

`E[B] = p_hit * max(direct - hit, 0) - (1 - p_hit) * max(cold - direct, 0)`

## Policies compared

`Never`, `Always`, `CurrentAuto` (production), `Threshold` (Phase 2H), `Ewma`, `ConfidenceBound`.

CLI: `tracejit admission-eval [--json]`  
Library: `compare_policies`, `prefer_simpler`, `held_out_matrix`.

Regret is measured against a per-step offline oracle with foresight of eligibility/deopt for that step only. Prefer the simpler policy on ties. Numbers are printed by the harness/tests only — do not invent them in prose.

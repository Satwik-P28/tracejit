//! Cost-sensitive adaptive admission: analytical model and policy comparison.
//!
//! Policies decide **whether to pay for tracing**, never whether guards may be skipped.
//! Statistical estimators must not weaken correctness.

use serde::{Deserialize, Serialize};
use tracejit_cache::AdmissionCost;

/// Floor used by the production `auto` policy (nanoseconds).
pub const HIT_COST_FLOOR_NS: u64 = 6_000_000;

/// Synthetic workload step used for offline regret measurement.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkloadStep {
    pub identity: String,
    /// True when a trace would produce a reusable record.
    pub eligible: bool,
    pub direct_ns: u64,
    pub cold_ns: u64,
    pub hit_ns: u64,
    /// True when a cached record would deoptimize on this step.
    pub would_deopt: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ResearchPolicy {
    Never,
    Always,
    /// Production Phase 2J+ `auto`: direct >= 2 * max(hit, floor) and hits+1 > deopts.
    CurrentAuto,
    /// Phase 2H threshold only (no deopt term).
    Threshold,
    /// Trace when EWMA(direct) >= 2 * max(EWMA(hit), floor).
    Ewma,
    /// Lower confidence bound on expected benefit > 0.
    ConfidenceBound,
}

#[derive(Clone, Debug, Default)]
struct PolicyState {
    direct_ns: u64,
    hit_ns: u64,
    cold_ns: u64,
    hits: u64,
    deopts: u64,
    samples: u64,
    ewma_direct: f64,
    ewma_hit: f64,
    sum_benefit: f64,
    sum_benefit_sq: f64,
}

impl PolicyState {
    fn observe_direct(&mut self, direct_ns: u64) {
        self.direct_ns = direct_ns;
        self.samples = self.samples.saturating_add(1);
        let alpha = 0.3;
        self.ewma_direct = if self.ewma_direct == 0.0 {
            direct_ns as f64
        } else {
            alpha * direct_ns as f64 + (1.0 - alpha) * self.ewma_direct
        };
    }

    fn observe_hit(&mut self, hit_ns: u64) {
        self.hit_ns = hit_ns;
        self.hits = self.hits.saturating_add(1);
        let alpha = 0.3;
        let value = hit_ns.max(HIT_COST_FLOOR_NS) as f64;
        self.ewma_hit = if self.ewma_hit == 0.0 {
            value
        } else {
            alpha * value + (1.0 - alpha) * self.ewma_hit
        };
        let benefit = self.direct_ns.saturating_sub(hit_ns) as f64;
        self.sum_benefit += benefit;
        self.sum_benefit_sq += benefit * benefit;
    }

    fn observe_cold(&mut self, cold_ns: u64) {
        self.cold_ns = cold_ns;
    }

    fn observe_deopt(&mut self) {
        self.deopts = self.deopts.saturating_add(1);
    }
}

/// Analytical expected benefit of tracing once then hitting forever under stable eligibility:
/// `E[B] = p_hit * (direct - hit) - (1 - p_hit) * cold_premium`, with `p_hit` estimated from
/// hits/(hits+deopts) when samples exist, else 0 (fail closed on optimism).
pub fn expected_benefit(state: &AdmissionCost) -> f64 {
    let trials = state.hits.saturating_add(state.deopts);
    // No samples → do not invent a positive (or negative) forecast; fail closed.
    if trials == 0 {
        return 0.0;
    }
    let hit = state.hit_ns.max(HIT_COST_FLOOR_NS) as f64;
    let direct = state.direct_ns as f64;
    let cold = state.cold_ns.max(state.direct_ns) as f64;
    let p_hit = state.hits as f64 / trials as f64;
    let save = (direct - hit).max(0.0);
    let cold_premium = (cold - direct).max(0.0);
    p_hit * save - (1.0 - p_hit) * cold_premium
}

fn should_trace(policy: ResearchPolicy, state: Option<&PolicyState>, measured: bool) -> bool {
    match policy {
        ResearchPolicy::Never => false,
        ResearchPolicy::Always => true,
        ResearchPolicy::CurrentAuto => {
            let Some(state) = state else {
                return false; // measure first
            };
            if !measured {
                return false;
            }
            let hit = state.hit_ns.max(HIT_COST_FLOOR_NS);
            state.direct_ns >= hit.saturating_mul(2) && state.hits.saturating_add(1) > state.deopts
        }
        ResearchPolicy::Threshold => {
            let Some(state) = state else {
                return false;
            };
            if !measured {
                return false;
            }
            let hit = state.hit_ns.max(HIT_COST_FLOOR_NS);
            state.direct_ns >= hit.saturating_mul(2)
        }
        ResearchPolicy::Ewma => {
            let Some(state) = state else {
                return false;
            };
            if !measured {
                return false;
            }
            let hit = state.ewma_hit.max(HIT_COST_FLOOR_NS as f64);
            state.ewma_direct >= 2.0 * hit
        }
        ResearchPolicy::ConfidenceBound => {
            let Some(state) = state else {
                return false;
            };
            if !measured || state.hits < 2 {
                // Need samples; do not invent a positive benefit.
                return state.direct_ns >= state.hit_ns.max(HIT_COST_FLOOR_NS).saturating_mul(2)
                    && state.hits.saturating_add(1) > state.deopts
                    && state.samples > 0;
            }
            let n = state.hits as f64;
            let mean = state.sum_benefit / n;
            let var = (state.sum_benefit_sq / n - mean * mean).max(0.0);
            let lcb = mean - (var / n).sqrt();
            lcb > 0.0
        }
    }
}

/// Offline oracle cost for one identity's full step list with perfect foresight.
/// Never serves a deopting or ineligible step from cache. Before each sticky streak, pays cold
/// only when cold + subsequent hits beat paying direct for that streak.
pub fn oracle_cost_for_identity(steps: &[&WorkloadStep]) -> u128 {
    let always_direct: u128 = steps.iter().map(|step| u128::from(step.direct_ns)).sum();
    if steps.iter().all(|step| !step.eligible) {
        return always_direct;
    }
    let mut with_cache: u128 = 0;
    let mut index = 0;
    while index < steps.len() {
        let step = steps[index];
        if !step.eligible || step.would_deopt {
            with_cache = with_cache.saturating_add(u128::from(step.direct_ns));
            index += 1;
            continue;
        }
        // Sticky streak of eligible non-deopt steps starting here.
        let mut end = index;
        while end < steps.len() && steps[end].eligible && !steps[end].would_deopt {
            end += 1;
        }
        let streak = &steps[index..end];
        let streak_direct: u128 = streak.iter().map(|s| u128::from(s.direct_ns)).sum();
        let first = streak[0];
        let streak_cache = u128::from(first.cold_ns)
            + streak
                .iter()
                .skip(1)
                .map(|s| u128::from(s.hit_ns))
                .sum::<u128>();
        with_cache = with_cache.saturating_add(streak_direct.min(streak_cache));
        index = end;
    }
    always_direct.min(with_cache)
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PolicyOutcome {
    pub policy: String,
    pub total_ns: u128,
    pub oracle_ns: u128,
    pub regret_ns: u128,
    pub traces: u64,
    pub hits: u64,
    pub directs: u64,
}

/// Simulate a policy on a held-out workload. Correctness is not at stake: ineligible identities
/// never reuse; deopts never serve stale bytes (modeled as paying cold/direct).
pub fn simulate(policy: ResearchPolicy, steps: &[WorkloadStep]) -> PolicyOutcome {
    let mut states: std::collections::BTreeMap<String, PolicyState> =
        std::collections::BTreeMap::new();
    let mut reusable: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut measured: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut total_ns: u128 = 0;
    let mut traces = 0u64;
    let mut hits = 0u64;
    let mut directs = 0u64;

    let mut by_identity: std::collections::BTreeMap<String, Vec<&WorkloadStep>> =
        std::collections::BTreeMap::new();
    for step in steps {
        by_identity
            .entry(step.identity.clone())
            .or_default()
            .push(step);
    }
    let oracle_ns: u128 = by_identity
        .values()
        .map(|group| oracle_cost_for_identity(group))
        .sum();

    for step in steps {
        let has_reusable = reusable.contains(&step.identity);

        let state = states.get(&step.identity);
        let already_measured = measured.contains(&step.identity);
        let trace = if has_reusable && step.eligible && !step.would_deopt {
            // Hit path: admission already paid; reuse when eligible.
            true
        } else {
            should_trace(policy, state, already_measured)
        };

        if has_reusable && step.eligible && !step.would_deopt && policy != ResearchPolicy::Never {
            total_ns = total_ns.saturating_add(u128::from(step.hit_ns));
            hits = hits.saturating_add(1);
            let entry = states
                .entry(step.identity.clone())
                .or_insert_with(|| PolicyState {
                    direct_ns: step.direct_ns,
                    hit_ns: step.hit_ns,
                    ..PolicyState::default()
                });
            entry.observe_hit(step.hit_ns);
            continue;
        }

        if policy == ResearchPolicy::Never
            || (!step.eligible && policy != ResearchPolicy::Always)
            || !trace
        {
            // Measure / direct path.
            total_ns = total_ns.saturating_add(u128::from(step.direct_ns));
            directs = directs.saturating_add(1);
            let entry = states.entry(step.identity.clone()).or_default();
            entry.observe_direct(step.direct_ns);
            measured.insert(step.identity.clone());
            if step.would_deopt {
                entry.observe_deopt();
                reusable.remove(&step.identity);
            }
            continue;
        }

        // Trace / cold path.
        total_ns = total_ns.saturating_add(u128::from(step.cold_ns));
        traces = traces.saturating_add(1);
        let entry = states.entry(step.identity.clone()).or_default();
        entry.observe_direct(step.direct_ns);
        entry.observe_cold(step.cold_ns);
        measured.insert(step.identity.clone());
        if step.eligible {
            reusable.insert(step.identity.clone());
        }
        if step.would_deopt {
            entry.observe_deopt();
            reusable.remove(&step.identity);
        }
    }

    PolicyOutcome {
        policy: format!("{policy:?}"),
        total_ns,
        oracle_ns,
        regret_ns: total_ns.saturating_sub(oracle_ns),
        traces,
        hits,
        directs,
    }
}

/// Compare research policies on a workload; bandits are omitted when a simpler policy matches
/// or beats them on regret.
pub fn compare_policies(steps: &[WorkloadStep]) -> Vec<PolicyOutcome> {
    [
        ResearchPolicy::Never,
        ResearchPolicy::Always,
        ResearchPolicy::CurrentAuto,
        ResearchPolicy::Threshold,
        ResearchPolicy::Ewma,
        ResearchPolicy::ConfidenceBound,
    ]
    .into_iter()
    .map(|policy| simulate(policy, steps))
    .collect()
}

/// Select the policy with minimal regret; ties prefer the simpler production policy.
pub fn prefer_simpler(outcomes: &[PolicyOutcome]) -> Option<&PolicyOutcome> {
    let mut best: Option<&PolicyOutcome> = None;
    for outcome in outcomes {
        best = Some(match best {
            None => outcome,
            Some(current) => {
                if outcome.regret_ns < current.regret_ns {
                    outcome
                } else if outcome.regret_ns > current.regret_ns {
                    current
                } else {
                    simpler_policy(current, outcome)
                }
            }
        });
    }
    best
}

fn simpler_policy<'a>(a: &'a PolicyOutcome, b: &'a PolicyOutcome) -> &'a PolicyOutcome {
    let rank = |name: &str| -> u8 {
        match name {
            "Never" => 0,
            "Always" => 1,
            "CurrentAuto" => 2,
            "Threshold" => 3,
            "Ewma" => 4,
            "ConfidenceBound" => 5,
            _ => 9,
        }
    };
    if rank(&a.policy) <= rank(&b.policy) {
        a
    } else {
        b
    }
}

/// Held-out synthetic matrix: mix of short filters, stable compressors, and edit-churn.
pub fn held_out_matrix() -> Vec<WorkloadStep> {
    let mut steps = Vec::new();
    // Short filter: never worth caching.
    for i in 0..8 {
        steps.push(WorkloadStep {
            identity: "short-filter".into(),
            eligible: true,
            direct_ns: 2_000_000,
            cold_ns: 12_000_000,
            hit_ns: 5_000_000,
            would_deopt: false,
        });
        let _ = i;
    }
    // Stable compressor: profitable after one cold.
    for i in 0..10 {
        steps.push(WorkloadStep {
            identity: "stable-compress".into(),
            eligible: true,
            direct_ns: 40_000_000,
            cold_ns: 55_000_000,
            hit_ns: 6_000_000,
            would_deopt: false,
        });
        let _ = i;
    }
    // Edit churn: every other step deopts.
    for i in 0..10 {
        steps.push(WorkloadStep {
            identity: "edit-churn".into(),
            eligible: true,
            direct_ns: 30_000_000,
            cold_ns: 45_000_000,
            hit_ns: 7_000_000,
            would_deopt: i % 2 == 1,
        });
    }
    // Ineligible interpreter: tracing never helps.
    for i in 0..6 {
        steps.push(WorkloadStep {
            identity: "ineligible-interp".into(),
            eligible: false,
            direct_ns: 25_000_000,
            cold_ns: 80_000_000,
            hit_ns: 8_000_000,
            would_deopt: false,
        });
        let _ = i;
    }
    steps
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expected_benefit_fails_closed_without_samples() {
        let cost = AdmissionCost {
            direct_ns: 40_000_000,
            hit_ns: 6_000_000,
            cold_ns: 55_000_000,
            hits: 0,
            skips: 0,
            deopts: 0,
            updated_ms: 0,
        };
        assert_eq!(expected_benefit(&cost), 0.0);
    }

    #[test]
    fn expected_benefit_positive_when_hits_dominate() {
        let cost = AdmissionCost {
            direct_ns: 40_000_000,
            hit_ns: 6_000_000,
            cold_ns: 55_000_000,
            hits: 9,
            skips: 0,
            deopts: 1,
            updated_ms: 0,
        };
        assert!(expected_benefit(&cost) > 0.0);
    }

    #[test]
    fn held_out_comparison_prefers_simple_policy_when_tied_or_better() {
        let steps = held_out_matrix();
        let outcomes = compare_policies(&steps);
        assert_eq!(outcomes.len(), 6);
        for outcome in &outcomes {
            // Never invent: totals are derived from the matrix above.
            assert!(outcome.total_ns >= outcome.oracle_ns);
        }
        let best = prefer_simpler(&outcomes).unwrap();
        // Bandit-style ConfidenceBound must not win solely by complexity when equal/worse.
        let conf = outcomes
            .iter()
            .find(|outcome| outcome.policy == "ConfidenceBound")
            .unwrap();
        if conf.regret_ns >= best.regret_ns {
            assert_ne!(best.policy, "ConfidenceBound");
        }
        // Print RESULT line for honest docs (values from this simulation only).
        eprintln!(
            "RESULT phase-e-admission best={} regret_ns={} totals={:?}",
            best.policy,
            best.regret_ns,
            outcomes
                .iter()
                .map(|o| (o.policy.clone(), o.regret_ns))
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn never_policy_never_hits() {
        let steps = held_out_matrix();
        let outcome = simulate(ResearchPolicy::Never, &steps);
        assert_eq!(outcome.hits, 0);
        assert_eq!(outcome.traces, 0);
    }

    #[test]
    fn always_traces_ineligible_identities() {
        let steps = vec![WorkloadStep {
            identity: "ineligible".into(),
            eligible: false,
            direct_ns: 10,
            cold_ns: 100,
            hit_ns: 5,
            would_deopt: false,
        }];
        let outcome = simulate(ResearchPolicy::Always, &steps);
        assert_eq!(outcome.traces, 1);
        assert_eq!(outcome.hits, 0);
    }
}

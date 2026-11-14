//! Counterexample-guided abstraction refinement engine (Phase K5).
//!
//! Consumes *external* counterexample traces (refusal reasons, Obs divergence notes) and
//! produces offline refinement proposals. This is not a catalog of hardcoded cycles: the
//! engine classifies holes from the input and never mutates product classification tables.
//!
//! Deployment invariant: proposals stay `BlockedPendingOfflineRetest` or
//! `VerifiedOfflineNotDeployed`. Nothing here auto-admits a syscall into reuse.

use crate::refinement::{
    proposal_is_safe, Abstraction, Counterexample, MinimizedCounterexample, Observation,
    RefinementCycle, RefinementDecision, RetestResult,
};
use crate::registry::{lookup_by_name, ModelStatus};
use serde::{Deserialize, Serialize};

/// One observed step in a differential or adversarial run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservedStep {
    pub syscall: String,
    pub detail: String,
    /// Free-form outcome tag: `refusal`, `guard_fail`, `hit`, `miss`, `ok`, …
    pub outcome: String,
}

/// Counterexample supplied by an oracle, harness, or human — not baked into the engine.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CounterexampleInput {
    pub title: String,
    /// Name of the current abstraction under suspicion (may be empty).
    #[serde(default)]
    pub current_abstraction: String,
    pub steps: Vec<ObservedStep>,
    pub native_obs_summary: String,
    pub tracejit_obs_summary: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum HoleKind {
    /// Model too coarse: false invalidation or wrong Obs under an over-broad fingerprint.
    OverAbstraction,
    /// Surface not modeled; product correctly fails closed today.
    UnmodeledSurface,
    /// Inherent nondeterminism (clocks, getrusage, entropy without contract).
    Nondeterminism,
    /// Hit path would expose diverging Obs — must keep refusing / roll back admit.
    UnsoundAdmit,
    /// Insufficient evidence to propose anything beyond fail-closed.
    InsufficientEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ProposalAction {
    KeepFailClosed {
        rationale: String,
    },
    ProposeNarrowerModel {
        new_model: String,
        rationale: String,
    },
}

/// Product deployment is never performed by this engine.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum DeploymentStatus {
    /// Default: proposal recorded; no product change.
    BlockedPendingOfflineRetest,
    /// Failed `proposal_is_safe` or explicitly unsafe sketch.
    RejectedUnsafe,
    /// Offline retest attached and passed; still not auto-deployed to main classification.
    VerifiedOfflineNotDeployed,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RefinementProposal {
    pub title: String,
    pub hole: HoleKind,
    pub abstraction: Abstraction,
    pub counterexample: Counterexample,
    pub minimized: MinimizedCounterexample,
    pub action: ProposalAction,
    pub safety_ok: bool,
    pub deployment: DeploymentStatus,
    pub registry_hint: Option<String>,
}

impl RefinementProposal {
    /// Map into the Phase E cycle record for tooling that already consumes that shape.
    pub fn as_cycle(&self, retest: RetestResult) -> RefinementCycle {
        let decision = match &self.action {
            ProposalAction::KeepFailClosed { rationale } => RefinementDecision::Reject {
                rationale: rationale.clone(),
            },
            ProposalAction::ProposeNarrowerModel {
                new_model,
                rationale,
            } => RefinementDecision::AcceptProposal {
                new_model: new_model.clone(),
                rationale: rationale.clone(),
            },
        };
        let observation = Observation {
            syscall: self
                .minimized
                .essential_steps
                .first()
                .cloned()
                .unwrap_or_else(|| self.title.clone()),
            detail: self.counterexample.description.clone(),
            classification_reason: format!("{:?}", self.hole),
        };
        crate::refinement::run_cycle(
            observation,
            self.abstraction.clone(),
            self.counterexample.clone(),
            self.minimized.clone(),
            decision,
            retest,
        )
    }
}

/// Classify the abstraction hole from the counterexample text and step outcomes.
///
/// Severity order: Obs divergence / unsound hit → nondeterminism → unmodeled → over-abstraction.
pub fn classify_hole(input: &CounterexampleInput) -> HoleKind {
    let blob = input_blob(input);
    // Highest severity: any Obs divergence (with or without an explicit warm HIT tag).
    if obs_diverge(input) {
        return HoleKind::UnsoundAdmit;
    }
    if contains_any(
        &blob,
        &[
            "getrusage",
            "clock_gettime",
            "gettimeofday",
            "getrandom",
            "nondeterministic",
            "wall clock",
        ],
    ) {
        return HoleKind::Nondeterminism;
    }
    if contains_any(
        &blob,
        &[
            "not modelled",
            "not modeled",
            "are not modeled",
            "unclassified fd",
            "untracked",
            "flags ",
        ],
    ) {
        return HoleKind::UnmodeledSurface;
    }
    if obs_match_native_but_tracejit_refused(input)
        && contains_any(&blob, &["mtime", "metadata", "timestamp", "sibling"])
    {
        return HoleKind::OverAbstraction;
    }
    HoleKind::InsufficientEvidence
}

fn input_blob(input: &CounterexampleInput) -> String {
    let mut parts = Vec::with_capacity(4 + input.steps.len() * 3);
    parts.push(input.title.clone());
    parts.push(input.current_abstraction.clone());
    parts.push(input.native_obs_summary.clone());
    parts.push(input.tracejit_obs_summary.clone());
    for step in &input.steps {
        parts.push(step.syscall.clone());
        parts.push(step.detail.clone());
        parts.push(step.outcome.clone());
    }
    parts.join("\n").to_ascii_lowercase()
}

fn contains_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|n| haystack.contains(n))
}

fn obs_diverge(input: &CounterexampleInput) -> bool {
    let native = input.native_obs_summary.to_ascii_lowercase();
    let tj = input.tracejit_obs_summary.to_ascii_lowercase();
    if native.is_empty() || tj.is_empty() {
        return false;
    }
    native != tj
        && (tj.contains("diverge")
            || tj.contains("mismatch")
            || tj.contains("missing")
            || tj.contains("deleted")
            || (native.contains("present") && tj.contains("absent")))
}

fn obs_match_native_but_tracejit_refused(input: &CounterexampleInput) -> bool {
    let tj = input.tracejit_obs_summary.to_ascii_lowercase();
    let refused = tj.contains("deopt")
        || tj.contains("miss")
        || tj.contains("invalidat")
        || tj.contains("guard_fail")
        || input
            .steps
            .iter()
            .any(|s| s.outcome.eq_ignore_ascii_case("guard_fail"));
    refused && !obs_diverge(input)
}

/// Drop steps that do not contribute keywords for the classified hole.
pub fn minimize(input: &CounterexampleInput, hole: HoleKind) -> MinimizedCounterexample {
    let keywords: &[&str] = match hole {
        HoleKind::OverAbstraction => &[
            "openat",
            "directory",
            "mtime",
            "metadata",
            "sibling",
            "timestamp",
        ],
        HoleKind::UnmodeledSurface => &[
            "not modelled",
            "not modeled",
            "flags",
            "unclassified",
            "untracked",
            "renameat2",
            "openat2",
            "ioctl",
        ],
        HoleKind::Nondeterminism => &["getrusage", "clock", "gettimeofday", "getrandom", "time"],
        HoleKind::UnsoundAdmit => &["hit", "reuse", "diverge", "mismatch", "missing", "exchange"],
        HoleKind::InsufficientEvidence => &[],
    };

    let mut essential = Vec::new();
    let mut discarded = Vec::new();
    for step in &input.steps {
        let line = format!("{} | {} | {}", step.syscall, step.detail, step.outcome);
        let lower = line.to_ascii_lowercase();
        let keep = keywords.is_empty()
            || keywords.iter().any(|k| lower.contains(k))
            || (step.outcome.eq_ignore_ascii_case("hit") && matches!(hole, HoleKind::UnsoundAdmit));
        if keep {
            essential.push(line);
        } else {
            discarded.push(line);
        }
    }
    if essential.is_empty() {
        // Fail closed: keep the whole trace rather than inventing emptiness.
        essential = input
            .steps
            .iter()
            .map(|s| format!("{} | {} | {}", s.syscall, s.detail, s.outcome))
            .collect();
        discarded.clear();
    }
    MinimizedCounterexample {
        essential_steps: essential,
        discarded,
    }
}

fn propose_action(input: &CounterexampleInput, hole: HoleKind) -> ProposalAction {
    match hole {
        HoleKind::UnmodeledSurface => ProposalAction::KeepFailClosed {
            rationale: "Surface is not modeled; TraceJIT must keep failing closed until a \
                verified guard/effect model exists. Do not auto-admit."
                .into(),
        },
        HoleKind::Nondeterminism => ProposalAction::KeepFailClosed {
            rationale: "Observation is nondeterministic or contract-only; refuse native reuse."
                .into(),
        },
        HoleKind::UnsoundAdmit => ProposalAction::KeepFailClosed {
            rationale: "Counterexample shows Obs divergence under reuse; any admit is unsound. \
                Keep or restore fail-closed classification."
                .into(),
        },
        HoleKind::InsufficientEvidence => ProposalAction::KeepFailClosed {
            rationale: "Insufficient structured evidence to propose a narrower model; fail closed."
                .into(),
        },
        HoleKind::OverAbstraction => {
            let blob = input_blob(input);
            if contains_any(&blob, &["directory", "openat"]) {
                ProposalAction::ProposeNarrowerModel {
                    new_model: "ReadEffect::DirectoryOpened / Guard::DirectoryOpened".into(),
                    rationale: "Sibling/mtime noise suggests directory identity+creds guard \
                        without timestamps. Requires offline retest; not auto-deployed."
                        .into(),
                }
            } else {
                ProposalAction::ProposeNarrowerModel {
                    new_model: format!(
                        "narrower-than({})",
                        if input.current_abstraction.is_empty() {
                            "current-metadata-abstraction"
                        } else {
                            &input.current_abstraction
                        }
                    ),
                    rationale: "Over-abstraction suspected from false invalidation without Obs \
                        divergence. Proposal is a sketch only; offline retest required."
                        .into(),
                }
            }
        }
    }
}

/// Run one CEGAR step: classify → minimize → propose. Never deploys.
pub fn refine(input: &CounterexampleInput) -> RefinementProposal {
    let hole = classify_hole(input);
    let minimized = minimize(input, hole);
    let mut action = propose_action(input, hole);

    // Registry veto: known Nondeterministic/Unknown entries cannot become admits via proposal text.
    let registry_hint = input
        .steps
        .iter()
        .find_map(|s| lookup_by_name(&s.syscall).map(|e| (s.syscall.clone(), e)));
    let registry_hint_str = registry_hint
        .as_ref()
        .map(|(name, e)| format!("{name} => {:?}", e.status));

    if let Some((_, entry)) = &registry_hint {
        if matches!(
            entry.status,
            ModelStatus::Nondeterministic | ModelStatus::Unknown | ModelStatus::Unmodeled
        ) {
            if let ProposalAction::ProposeNarrowerModel { .. } = &action {
                action = ProposalAction::KeepFailClosed {
                    rationale: format!(
                        "Registry status {:?} forbids admit-shaped proposals without a separate \
                         verified model change.",
                        entry.status
                    ),
                };
            }
        }
    }

    let decision_for_safety = match &action {
        ProposalAction::KeepFailClosed { rationale } => RefinementDecision::Reject {
            rationale: rationale.clone(),
        },
        ProposalAction::ProposeNarrowerModel {
            new_model,
            rationale,
        } => RefinementDecision::AcceptProposal {
            new_model: new_model.clone(),
            rationale: rationale.clone(),
        },
    };
    let safety_ok = proposal_is_safe(&decision_for_safety);
    let deployment = if safety_ok {
        DeploymentStatus::BlockedPendingOfflineRetest
    } else {
        DeploymentStatus::RejectedUnsafe
    };

    let abstraction_name = if input.current_abstraction.is_empty() {
        format!("{hole:?}")
    } else {
        input.current_abstraction.clone()
    };

    RefinementProposal {
        title: input.title.clone(),
        hole,
        abstraction: Abstraction {
            model_name: abstraction_name,
            summary: format!("classified hole {hole:?} from supplied counterexample"),
        },
        counterexample: Counterexample {
            description: input.title.clone(),
            observable_divergence: format!(
                "native={} | tracejit={}",
                input.native_obs_summary, input.tracejit_obs_summary
            ),
        },
        minimized,
        action,
        safety_ok,
        deployment,
        registry_hint: registry_hint_str,
    }
}

/// Attach an offline retest result. Even on pass, status stays NotDeployed.
pub fn attach_retest(
    mut proposal: RefinementProposal,
    retest: &RetestResult,
) -> RefinementProposal {
    if !proposal.safety_ok {
        proposal.deployment = DeploymentStatus::RejectedUnsafe;
        return proposal;
    }
    if retest.passed {
        proposal.deployment = DeploymentStatus::VerifiedOfflineNotDeployed;
    } else {
        proposal.deployment = DeploymentStatus::BlockedPendingOfflineRetest;
        if let ProposalAction::ProposeNarrowerModel { rationale, .. } = &mut proposal.action {
            *rationale = format!("{rationale} [retest failed: {}]", retest.notes);
        }
    }
    proposal
}

/// Force-reject ignore/whitelist sketches regardless of hole classification.
pub fn reject_if_unsafe_model(mut proposal: RefinementProposal) -> RefinementProposal {
    if let ProposalAction::ProposeNarrowerModel { new_model, .. } = &proposal.action {
        let decision = RefinementDecision::AcceptProposal {
            new_model: new_model.clone(),
            rationale: String::new(),
        };
        if !proposal_is_safe(&decision) {
            proposal.safety_ok = false;
            proposal.deployment = DeploymentStatus::RejectedUnsafe;
            proposal.action = ProposalAction::KeepFailClosed {
                rationale: format!(
                    "Rejected unsafe model sketch `{new_model}` (ignore/whitelist forbidden)"
                ),
            };
        }
    }
    proposal
}

#[cfg(test)]
mod tests {
    use super::*;

    fn step(syscall: &str, detail: &str, outcome: &str) -> ObservedStep {
        ObservedStep {
            syscall: syscall.into(),
            detail: detail.into(),
            outcome: outcome.into(),
        }
    }

    #[test]
    fn rename_exchange_ce_keeps_fail_closed_and_blocked() {
        let input = CounterexampleInput {
            title: "renameat2 RENAME_EXCHANGE false HIT".into(),
            current_abstraction: "rename-as-delete-plus-rename".into(),
            steps: vec![
                step(
                    "renameat2",
                    "renameat2 flags 0x2 are not modeled",
                    "refusal",
                ),
                step("write", "unrelated", "ok"),
            ],
            native_obs_summary: "a=BBB b=AAA both present".into(),
            tracejit_obs_summary: "warm hit deleted a (diverge/missing)".into(),
        };
        let proposal = refine(&input);
        assert_eq!(proposal.hole, HoleKind::UnsoundAdmit);
        assert!(matches!(
            proposal.action,
            ProposalAction::KeepFailClosed { .. }
        ));
        assert!(proposal.safety_ok);
        assert_eq!(
            proposal.deployment,
            DeploymentStatus::BlockedPendingOfflineRetest
        );
        assert!(proposal
            .minimized
            .essential_steps
            .iter()
            .any(|s| s.contains("renameat2")));
    }

    #[test]
    fn unmodeled_flags_are_not_auto_admitted() {
        let input = CounterexampleInput {
            title: "openat2 RESOLVE_BENEATH".into(),
            current_abstraction: String::new(),
            steps: vec![step(
                "openat2",
                "openat2 resolve flags 0x8 are not modeled",
                "refusal",
            )],
            native_obs_summary: "exit=0".into(),
            tracejit_obs_summary: "UNKNOWN refusal".into(),
        };
        let proposal = refine(&input);
        assert_eq!(proposal.hole, HoleKind::UnmodeledSurface);
        assert!(matches!(
            proposal.action,
            ProposalAction::KeepFailClosed { .. }
        ));
        assert_ne!(
            proposal.deployment,
            DeploymentStatus::VerifiedOfflineNotDeployed
        );
    }

    #[test]
    fn directory_mtime_overabstraction_proposes_but_does_not_deploy() {
        let input = CounterexampleInput {
            title: "sibling create invalidates directory open".into(),
            current_abstraction: "FileMetadata".into(),
            steps: vec![
                step(
                    "openat(directory)",
                    "gzip opens parent directory; FileMetadata includes mtime",
                    "ok",
                ),
                step("creat", "unrelated sibling changes directory mtime", "ok"),
                step("guard", "FileMetadata mtime mismatch", "guard_fail"),
            ],
            native_obs_summary: "stdout identical; inputs unchanged".into(),
            tracejit_obs_summary: "deopt every run after sibling create".into(),
        };
        let proposal = refine(&input);
        assert_eq!(proposal.hole, HoleKind::OverAbstraction);
        match &proposal.action {
            ProposalAction::ProposeNarrowerModel { new_model, .. } => {
                assert!(new_model.contains("DirectoryOpened"));
            }
            other => panic!("expected ProposeNarrowerModel, got {other:?}"),
        }
        assert_eq!(
            proposal.deployment,
            DeploymentStatus::BlockedPendingOfflineRetest
        );
        let with_retest = attach_retest(
            proposal,
            &RetestResult {
                passed: true,
                notes: "offline historical Phase 2E evidence".into(),
            },
        );
        assert_eq!(
            with_retest.deployment,
            DeploymentStatus::VerifiedOfflineNotDeployed
        );
    }

    #[test]
    fn getrusage_stays_fail_closed() {
        let input = CounterexampleInput {
            title: "getrusage on as".into(),
            current_abstraction: "ignore_dead_getrusage".into(),
            steps: vec![step(
                "getrusage",
                "process read system information via getrusage",
                "refusal",
            )],
            native_obs_summary: "object bytes stable under perturbation".into(),
            tracejit_obs_summary: "NONDETERMINISTIC".into(),
        };
        let proposal = refine(&input);
        assert_eq!(proposal.hole, HoleKind::Nondeterminism);
        assert!(matches!(
            proposal.action,
            ProposalAction::KeepFailClosed { .. }
        ));
    }

    #[test]
    fn ignore_whitelist_sketch_is_rejected_unsafe() {
        let mut proposal = refine(&CounterexampleInput {
            title: "crafted".into(),
            current_abstraction: "FileMetadata".into(),
            steps: vec![step(
                "openat(directory)",
                "mtime sibling noise",
                "guard_fail",
            )],
            native_obs_summary: "ok".into(),
            tracejit_obs_summary: "deopt".into(),
        });
        proposal.action = ProposalAction::ProposeNarrowerModel {
            new_model: "ignore getrusage whitelist".into(),
            rationale: "bad".into(),
        };
        proposal = reject_if_unsafe_model(proposal);
        assert!(!proposal.safety_ok);
        assert_eq!(proposal.deployment, DeploymentStatus::RejectedUnsafe);
    }

    #[test]
    fn engine_is_driven_by_input_not_hardcoded_cycle_table() {
        let a = refine(&CounterexampleInput {
            title: "a".into(),
            current_abstraction: String::new(),
            steps: vec![step("clock_gettime", "wall clock", "refusal")],
            native_obs_summary: "t1".into(),
            tracejit_obs_summary: "NONDETERMINISTIC".into(),
        });
        let b = refine(&CounterexampleInput {
            title: "b".into(),
            current_abstraction: String::new(),
            steps: vec![step(
                "mmap",
                "anonymous MAP_SHARED untracked shared memory",
                "refusal",
            )],
            native_obs_summary: "ok".into(),
            tracejit_obs_summary: "UNKNOWN".into(),
        });
        assert_ne!(a.hole, b.hole);
    }
}

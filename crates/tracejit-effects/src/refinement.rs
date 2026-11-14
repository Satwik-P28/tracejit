//! CEGAR-inspired effect refinement workflow for TraceJIT guarded reuse.
//!
//! Loop: observe → abstract → counterexample → minimize → refine → retest.
//! This applies the classical CEGAR *shape* to TraceJIT's effect models. It does **not** claim
//! that CEGAR itself is a novel contribution.

use crate::registry::{lookup_by_name, ModelStatus};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Observation {
    pub syscall: String,
    pub detail: String,
    pub classification_reason: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Abstraction {
    pub model_name: String,
    pub summary: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Counterexample {
    pub description: String,
    pub observable_divergence: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct MinimizedCounterexample {
    pub essential_steps: Vec<String>,
    pub discarded: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum RefinementDecision {
    /// Propose a narrower model; must be retested before product use.
    AcceptProposal {
        new_model: String,
        rationale: String,
    },
    /// Keep failing closed; document why a refinement would be unsound.
    Reject { rationale: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RetestResult {
    pub passed: bool,
    pub notes: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RefinementCycle {
    pub observation: Observation,
    pub abstraction: Abstraction,
    pub counterexample: Counterexample,
    pub minimized: MinimizedCounterexample,
    pub decision: RefinementDecision,
    pub retest: RetestResult,
}

/// Run one refinement cycle. Product code changes are out of band; this records the argument.
pub fn run_cycle(
    observation: Observation,
    abstraction: Abstraction,
    counterexample: Counterexample,
    minimized: MinimizedCounterexample,
    decision: RefinementDecision,
    retest: RetestResult,
) -> RefinementCycle {
    RefinementCycle {
        observation,
        abstraction,
        counterexample,
        minimized,
        decision,
        retest,
    }
}

/// Historical Phase 2E refinement: directory `openat` was over-abstracted as Metadata (mtime),
/// causing false invalidation when siblings were created. Minimized CE → DirectoryOpened guard.
pub fn directory_opened_refinement() -> RefinementCycle {
    run_cycle(
        Observation {
            syscall: "openat(directory)".into(),
            detail: "gzip opens the parent directory as a resolution base".into(),
            classification_reason: "was recorded as FileMetadata including mtime".into(),
        },
        Abstraction {
            model_name: "FileMetadata".into(),
            summary: "any open of a directory path fingerprints full metadata including timestamps"
                .into(),
        },
        Counterexample {
            description: "writing an unrelated sibling changes directory mtime".into(),
            observable_divergence:
                "native Obs unchanged for the input file, but TraceJIT deoptimized every run".into(),
        },
        MinimizedCounterexample {
            essential_steps: vec![
                "openat(AT_FDCWD, parent, O_RDONLY|O_DIRECTORY)".into(),
                "create unrelated sibling in parent".into(),
                "reuse attempt fails FileMetadata guard on mtime".into(),
            ],
            discarded: vec![
                "atime hypothesis".into(),
                "path-resolution snapshot hypothesis".into(),
            ],
        },
        RefinementDecision::AcceptProposal {
            new_model: "ReadEffect::DirectoryOpened / Guard::DirectoryOpened".into(),
            rationale:
                "compare device/inode/mode/uid/gid + directory-ness + probe open; drop timestamps"
                    .into(),
        },
        RetestResult {
            passed: true,
            notes: "Phase 2E: ordinary output placement no longer invalidates; getdents still refused without enumeration model (later Phase 2F)."
                .into(),
        },
    )
}

/// Attempted refinement of `getrusage`: values do not reach bytes for surveyed assemblers, but
/// per-run consumption still cannot be guarded in general. Rejected.
pub fn getrusage_refinement_rejected() -> RefinementCycle {
    let entry = lookup_by_name("getrusage").expect("registry entry");
    assert_eq!(entry.status, ModelStatus::Nondeterministic);
    run_cycle(
        Observation {
            syscall: "getrusage".into(),
            detail: "as calls getrusage once (RUSAGE_SELF)".into(),
            classification_reason:
                "NONDETERMINISTIC: process read system information via getrusage".into(),
        },
        Abstraction {
            model_name: "ignore_dead_getrusage".into(),
            summary: "treat getrusage as dead if object bytes are stable under value perturbation"
                .into(),
        },
        Counterexample {
            description: "a future tool can branch on ru_maxrss or print statistics".into(),
            observable_divergence:
                "perturbation coverage on one binary does not certify another binary".into(),
        },
        MinimizedCounterexample {
            essential_steps: vec![
                "override getrusage return with zeros vs absurd numbers".into(),
                "object file byte-identical for surveyed `as`".into(),
                "no general guard for arbitrary consumers".into(),
            ],
            discarded: vec!["global whitelist of getrusage".into()],
        },
        RefinementDecision::Reject {
            rationale: "cannot guard per-run consumption; staying NONDETERMINISTIC fails closed"
                .into(),
        },
        RetestResult {
            passed: true,
            notes: "rejection retained; registry status remains Nondeterministic.".into(),
        },
    )
}

/// Soundness gate: a proposal that would skip guards for an unmodeled class is refused.
pub fn proposal_is_safe(decision: &RefinementDecision) -> bool {
    match decision {
        RefinementDecision::Reject { .. } => true,
        RefinementDecision::AcceptProposal { new_model, .. } => {
            // Accepted proposals must name an explicit effect/guard type, not "ignore".
            let lower = new_model.to_ascii_lowercase();
            !lower.contains("ignore") && !lower.contains("whitelist")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn directory_opened_cycle_is_accepted_and_safe() {
        let cycle = directory_opened_refinement();
        assert!(matches!(
            cycle.decision,
            RefinementDecision::AcceptProposal { .. }
        ));
        assert!(proposal_is_safe(&cycle.decision));
        assert!(cycle.retest.passed);
        assert!(!cycle.minimized.essential_steps.is_empty());
    }

    #[test]
    fn getrusage_cycle_is_rejected() {
        let cycle = getrusage_refinement_rejected();
        assert!(matches!(cycle.decision, RefinementDecision::Reject { .. }));
        assert!(proposal_is_safe(&cycle.decision));
        let entry = lookup_by_name("getrusage").unwrap();
        assert_eq!(entry.status, ModelStatus::Nondeterministic);
    }

    #[test]
    fn ignore_proposals_are_unsafe() {
        let decision = RefinementDecision::AcceptProposal {
            new_model: "ignore getrusage".into(),
            rationale: "bytes looked stable once".into(),
        };
        assert!(!proposal_is_safe(&decision));
    }
}

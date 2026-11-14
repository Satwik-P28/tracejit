//! Structured reuse certificates and an independent structural verifier.
//!
//! A certificate records what a TraceJIT reuse decision claimed and what evidence was available.
//! The verifier checks **internal consistency** of that evidence. It does **not** establish
//! observational equivalence of an arbitrary native execution, and it does not close the
//! validate→restore TOCTOU window: re-checking guards still samples the same mutable filesystem
//! the production hit path samples.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::path::PathBuf;
use tracejit_cache::{CacheDecision, OutputKind, StoredExecution, OUTPUT_ARTIFACT_VERSION};
use tracejit_effects::{DeterminismClass, Hash};
use tracejit_guards::{Guard, GuardReport};

/// Schema id for this certificate format. Bump when fields change meaning.
pub const REUSE_CERTIFICATE_SCHEMA: &str = "tracejit.reuse-certificate.v1";

/// How strong a claim the certificate is allowed to make.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ClaimStrength {
    /// Fields are present and typed so a verifier *could* check them.
    CheckableEvidence,
    /// An independent verifier has checked the embedded evidence for consistency.
    CheckedByVerifier,
    /// A full Obs(E) equivalence proof. TraceJIT V1 never emits this.
    FullEquivalenceProof,
}

/// One guard obligation and the result observed when the certificate was issued.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GuardEvidence {
    pub guard: Guard,
    pub passed: bool,
    pub detail: Option<String>,
}

/// Descriptor-related obligations recorded for independent inspection.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct DescriptorObligations {
    /// Inherited regular-file streams with start/end offsets that must be reproducible.
    pub inherited_streams: Vec<InheritedStreamObligation>,
    /// Explicit note that fds above stderr are refused at preflight (not modeled as reuse).
    pub inherited_beyond_stdin_refused: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InheritedStreamObligation {
    pub path: PathBuf,
    pub start_offset: u64,
    pub end_offset: u64,
    pub expected_hash: Option<Hash>,
}

/// CAS object identities the hit path must have verified before exposing outputs.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CasObjectRef {
    pub role: CasRole,
    pub hash: Hash,
    pub path: Option<PathBuf>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum CasRole {
    Stdout,
    Stderr,
    OutputFile,
}

/// Preconditions that must hold before a restore mutates the workspace.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RestorePrecondition {
    pub path: PathBuf,
    pub kind: OutputKind,
    pub allows_create: bool,
    pub artifact_version: u32,
    pub content: Option<Hash>,
}

/// Explicit limitations so the certificate cannot be read as a stronger claim.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CertificateLimitations {
    pub notes: Vec<String>,
}

impl Default for CertificateLimitations {
    fn default() -> Self {
        Self {
            notes: vec![
                "Independent verification re-samples the same mutable filesystem state as the hit path; it does not close validate→restore TOCTOU.".into(),
                "Multi-output restore is pathname-visible and not crash-atomic under hard kill.".into(),
                "seccomp + Landlock constrain an enforced child; they are not a full Obs equivalence proof.".into(),
                "This certificate is never a FullEquivalenceProof in TraceJIT V1.".into(),
            ],
        }
    }
}

/// Structured evidence for one reuse (or refused reuse) decision.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReuseCertificate {
    pub schema: String,
    pub claim_strength: ClaimStrength,
    pub contract_id: Option<String>,
    pub execution_id: String,
    pub lookup_key: Hash,
    pub classification: DeterminismClass,
    pub decision: CacheDecision,
    pub decision_reason: String,
    pub guards: Vec<GuardEvidence>,
    pub guard_report: Option<GuardReport>,
    pub content_identities: ContentIdentities,
    pub descriptor_obligations: DescriptorObligations,
    pub cas_objects: Vec<CasObjectRef>,
    pub restore_preconditions: Vec<RestorePrecondition>,
    pub limitations: CertificateLimitations,
    /// Digest of the serialized candidate record used to build this certificate (structural).
    pub candidate_digest: Hash,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ContentIdentities {
    pub stdout: Hash,
    pub stderr: Hash,
    pub exit_code: i32,
    pub outputs: Vec<(PathBuf, Option<Hash>)>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct VerificationReport {
    pub ok: bool,
    pub claim_strength: ClaimStrength,
    pub checked: Vec<String>,
    pub rejected: Vec<String>,
}

#[derive(Debug, thiserror::Error)]
pub enum CertificateError {
    #[error("certificate serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("certificate is malformed: {0}")]
    Malformed(String),
}

/// Build a certificate from a stored candidate and the guard report that admitted (or rejected) it.
///
/// The emitted claim is at most [`ClaimStrength::CheckableEvidence`]. Promotion to
/// [`ClaimStrength::CheckedByVerifier`] happens only after [`verify_certificate`] succeeds.
pub fn issue_certificate(
    record: &StoredExecution,
    guard_report: Option<&GuardReport>,
    decision: CacheDecision,
    decision_reason: impl Into<String>,
) -> Result<ReuseCertificate, CertificateError> {
    let decision_reason = decision_reason.into();
    let mut guards = Vec::with_capacity(record.guards.len());
    let failure_index = guard_report.and_then(|report| {
        report.failure.as_ref().and_then(|failure| {
            record
                .guards
                .iter()
                .position(|guard| guard == failure.guard.as_ref())
        })
    });
    for (index, guard) in record.guards.iter().enumerate() {
        let failed = failure_index == Some(index);
        let detail = if failed {
            guard_report
                .and_then(|report| report.failure.as_ref())
                .map(|failure| failure.reason.clone())
        } else {
            None
        };
        let all_passed = guard_report
            .map(|report| report.failure.is_none())
            .unwrap_or(false);
        guards.push(GuardEvidence {
            guard: guard.clone(),
            passed: !failed && all_passed,
            detail,
        });
    }

    let mut descriptor = DescriptorObligations {
        inherited_beyond_stdin_refused: true,
        inherited_streams: Vec::new(),
    };
    for guard in &record.guards {
        if let Guard::InheritedStream {
            path,
            expected_hash,
            start_offset,
            end_offset,
            ..
        } = guard
        {
            descriptor
                .inherited_streams
                .push(InheritedStreamObligation {
                    path: path.clone(),
                    start_offset: *start_offset,
                    end_offset: *end_offset,
                    expected_hash: *expected_hash,
                });
        }
    }

    let mut cas_objects = vec![
        CasObjectRef {
            role: CasRole::Stdout,
            hash: record.stdout,
            path: None,
        },
        CasObjectRef {
            role: CasRole::Stderr,
            hash: record.stderr,
            path: None,
        },
    ];
    let mut restore_preconditions = Vec::new();
    let mut outputs = Vec::new();
    for output in &record.outputs {
        outputs.push((output.path.clone(), output.content));
        if let Some(hash) = output.content {
            cas_objects.push(CasObjectRef {
                role: CasRole::OutputFile,
                hash,
                path: Some(output.path.clone()),
            });
        }
        restore_preconditions.push(RestorePrecondition {
            path: output.path.clone(),
            kind: output.kind,
            allows_create: output.allows_create,
            artifact_version: output.artifact_version,
            content: output.content,
        });
    }

    let candidate_digest = digest_record(record)?;

    Ok(ReuseCertificate {
        schema: REUSE_CERTIFICATE_SCHEMA.into(),
        claim_strength: ClaimStrength::CheckableEvidence,
        contract_id: record.contract.clone(),
        execution_id: record.id.clone(),
        lookup_key: record.lookup_key,
        classification: record.classification,
        decision,
        decision_reason,
        guards,
        guard_report: guard_report.cloned(),
        content_identities: ContentIdentities {
            stdout: record.stdout,
            stderr: record.stderr,
            exit_code: record.exit_code,
            outputs,
        },
        descriptor_obligations: descriptor,
        cas_objects,
        restore_preconditions,
        limitations: CertificateLimitations::default(),
        candidate_digest,
    })
}

fn digest_record(record: &StoredExecution) -> Result<Hash, CertificateError> {
    let bytes = serde_json::to_vec(record)?;
    Ok(Hash::from(blake3::hash(&bytes)))
}

/// Independent structural verifier.
///
/// Distinguishes:
/// - **(a) checkable evidence** — well-typed fields present on the certificate;
/// - **(b) checked by verifier** — consistency checks below all passed;
/// - **(c) full equivalence proof** — never granted here.
///
/// Checks do **not** re-hash live workspace files. Callers that need live validation must run the
/// production guard path; that still trusts mutable state at check time.
pub fn verify_certificate(certificate: &ReuseCertificate) -> VerificationReport {
    let mut checked = Vec::new();
    let mut rejected = Vec::new();

    if certificate.schema != REUSE_CERTIFICATE_SCHEMA {
        rejected.push(format!(
            "unsupported schema {} (expected {REUSE_CERTIFICATE_SCHEMA})",
            certificate.schema
        ));
    } else {
        checked.push("schema id matches reuse-certificate.v1".into());
    }

    if matches!(
        certificate.claim_strength,
        ClaimStrength::FullEquivalenceProof
    ) {
        rejected.push(
            "certificate claims FullEquivalenceProof; TraceJIT V1 verifier never grants that"
                .into(),
        );
    } else {
        checked.push("claim strength is not FullEquivalenceProof".into());
    }

    if certificate.execution_id.is_empty() {
        rejected.push("execution_id is empty".into());
    } else {
        checked.push("execution_id is non-empty".into());
    }

    match certificate.decision {
        CacheDecision::Reused => {
            if !certificate.classification.cache_eligible() {
                rejected.push(format!(
                    "Reused decision with ineligible classification {}",
                    certificate.classification
                ));
            } else {
                checked.push("Reused decision has cache-eligible classification".into());
            }
            if let Some(report) = &certificate.guard_report {
                if report.failure.is_some() {
                    rejected.push("Reused decision embeds a failed guard report".into());
                } else if report.checked == 0 {
                    if certificate.guards.is_empty() {
                        checked.push("empty guard set with empty report".into());
                    } else {
                        rejected
                            .push("guard report checked=0 while certificate lists guards".into());
                    }
                } else if report.passed != report.checked {
                    rejected.push(format!(
                        "guard report inconsistent: checked={} passed={}",
                        report.checked, report.passed
                    ));
                } else {
                    checked.push("guard report shows all guards passed".into());
                }
            } else if !certificate.guards.is_empty() {
                rejected
                    .push("Reused decision missing guard_report while guards are listed".into());
            } else {
                checked.push("Reused decision with no guards and no report".into());
            }
            if certificate.guards.iter().any(|guard| !guard.passed) {
                rejected.push("Reused decision lists a guard marked passed=false".into());
            } else if !certificate.guards.is_empty() {
                checked.push("every listed guard is marked passed".into());
            }
        }
        CacheDecision::Deoptimized | CacheDecision::Ineligible | CacheDecision::Skipped => {
            checked.push(format!(
                "non-reuse decision {:?} is structurally allowed",
                certificate.decision
            ));
        }
        CacheDecision::Executed => {
            checked.push("Executed decision is structurally allowed".into());
        }
    }

    let mut cas_hashes: BTreeSet<Hash> = BTreeSet::new();
    for object in &certificate.cas_objects {
        cas_hashes.insert(object.hash);
    }
    if !cas_hashes.contains(&certificate.content_identities.stdout) {
        rejected.push("stdout content identity missing from cas_objects".into());
    } else {
        checked.push("stdout content identity listed in cas_objects".into());
    }
    if !cas_hashes.contains(&certificate.content_identities.stderr) {
        rejected.push("stderr content identity missing from cas_objects".into());
    } else {
        checked.push("stderr content identity listed in cas_objects".into());
    }
    for (path, content) in &certificate.content_identities.outputs {
        match content {
            Some(hash) if !cas_hashes.contains(hash) => {
                rejected.push(format!(
                    "output {} hash {hash} missing from cas_objects",
                    path.display()
                ));
            }
            Some(_) => checked.push(format!(
                "output {} content identity listed in cas_objects",
                path.display()
            )),
            None => checked.push(format!(
                "output {} is a deletion (no content hash)",
                path.display()
            )),
        }
    }

    let mut precondition_ok = true;
    for precondition in &certificate.restore_preconditions {
        if precondition.kind == OutputKind::File && precondition.content.is_none() {
            rejected.push(format!(
                "file restore precondition at {} lacks content hash",
                precondition.path.display()
            ));
            precondition_ok = false;
        }
        if precondition.kind == OutputKind::File
            && precondition.artifact_version != OUTPUT_ARTIFACT_VERSION
            && certificate.decision == CacheDecision::Reused
        {
            if precondition.artifact_version == 0 {
                rejected.push(format!(
                    "Reused decision references legacy artifact version 0 at {}",
                    precondition.path.display()
                ));
            } else {
                rejected.push(format!(
                    "Reused decision references non-current artifact version {} at {}",
                    precondition.artifact_version,
                    precondition.path.display()
                ));
            }
            precondition_ok = false;
        }
        if precondition.kind == OutputKind::Deleted && precondition.content.is_some() {
            rejected.push(format!(
                "deletion precondition at {} unexpectedly has content",
                precondition.path.display()
            ));
            precondition_ok = false;
        }
    }
    if precondition_ok && !certificate.restore_preconditions.is_empty() {
        checked.push("restore preconditions are internally consistent".into());
    }

    if certificate.limitations.notes.is_empty() {
        rejected.push("limitations.notes must be non-empty so claims stay bounded".into());
    } else {
        checked.push("limitations section is present".into());
    }

    let ok = rejected.is_empty();
    let claim_strength = if ok {
        ClaimStrength::CheckedByVerifier
    } else {
        certificate.claim_strength
    };

    VerificationReport {
        ok,
        claim_strength,
        checked,
        rejected,
    }
}

/// Parse JSON bytes and reject malformed certificates before structural checks.
pub fn parse_certificate(bytes: &[u8]) -> Result<ReuseCertificate, CertificateError> {
    let certificate: ReuseCertificate = serde_json::from_slice(bytes)
        .map_err(|error| CertificateError::Malformed(format!("JSON decode failed: {error}")))?;
    if certificate.schema.is_empty() {
        return Err(CertificateError::Malformed("schema field is empty".into()));
    }
    Ok(certificate)
}

/// Promote a checkable certificate to CheckedByVerifier when verification passes.
pub fn seal_certificate(mut certificate: ReuseCertificate) -> Result<ReuseCertificate, String> {
    let report = verify_certificate(&certificate);
    if !report.ok {
        return Err(report.rejected.join("; "));
    }
    certificate.claim_strength = ClaimStrength::CheckedByVerifier;
    Ok(certificate)
}

/// Helper used by tests and CLI to build a certificate from a record alone.
pub fn certificate_from_record(
    record: &StoredExecution,
) -> Result<ReuseCertificate, CertificateError> {
    issue_certificate(
        record,
        None,
        record.last_decision.decision.clone(),
        record.last_decision.reason.clone(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use tracejit_cache::{DecisionRecord, OutputArtifact};
    use tracejit_effects::{ExecutionIdentity, FileDescriptorIdentity, RuntimeIdentity};

    fn sample_record() -> StoredExecution {
        let stdout = Hash::from(blake3::hash(b"out"));
        let stderr = Hash::from(blake3::hash(b""));
        let content = Hash::from(blake3::hash(b"file"));
        StoredExecution {
            id: "exec-1".into(),
            lookup_key: Hash::from(blake3::hash(b"key")),
            command: vec!["demo".into()],
            executable: PathBuf::from("/bin/demo"),
            identity: ExecutionIdentity {
                executable_hash: Hash::from(blake3::hash(b"bin")),
                argv: vec!["demo".into()],
                cwd: PathBuf::from("/tmp"),
                environment: BTreeMap::new(),
                input_dependencies: vec![],
                runtime_identity: RuntimeIdentity {
                    os: "linux".into(),
                    architecture: "x86_64".into(),
                    kernel_release: "6".into(),
                    kernel_version: "6".into(),
                    hostname: "host".into(),
                    domain_name: "".into(),
                    uid: 0,
                    euid: 0,
                    gid: 0,
                    egid: 0,
                    stack_limit_soft: 0,
                    stack_limit_hard: 0,
                    nofile_limit_soft: 0,
                    nofile_limit_hard: 0,
                    as_limit_soft: 0,
                    as_limit_hard: 0,
                    rss_limit_soft: 0,
                    rss_limit_hard: 0,
                    stdin: FileDescriptorIdentity {
                        target: PathBuf::from("/dev/null"),
                        fingerprint: None,
                    },
                },
            },
            classification: DeterminismClass::Guarded,
            classification_reasons: vec![],
            effects: vec![],
            contract: None,
            guards: vec![Guard::WorkingDirectory {
                expected: PathBuf::from("/tmp"),
            }],
            outputs: vec![OutputArtifact {
                path: PathBuf::from("out.txt"),
                kind: OutputKind::File,
                content: Some(content),
                unix_mode: Some(0o644),
                unix_uid: Some(0),
                unix_gid: Some(0),
                unix_accessed_ns: Some(1),
                unix_modified_ns: Some(1),
                artifact_version: OUTPUT_ARTIFACT_VERSION,
                allows_create: true,
            }],
            stdout,
            stderr,
            exit_code: 0,
            baseline_runtime_ns: 1_000_000,
            process_count: 1,
            trace: Default::default(),
            last_decision: DecisionRecord {
                decision: CacheDecision::Reused,
                reason: "all guards passed".into(),
                guard_failure: None,
                decided_unix_ms: 1,
            },
        }
    }

    #[test]
    fn verifier_accepts_consistent_reuse_certificate() {
        let record = sample_record();
        let report = GuardReport {
            checked: 1,
            passed: 1,
            failure: None,
        };
        let certificate = issue_certificate(
            &record,
            Some(&report),
            CacheDecision::Reused,
            "all guards passed",
        )
        .unwrap();
        let verified = verify_certificate(&certificate);
        assert!(verified.ok, "{verified:?}");
        assert_eq!(verified.claim_strength, ClaimStrength::CheckedByVerifier);
        let sealed = seal_certificate(certificate).unwrap();
        assert_eq!(sealed.claim_strength, ClaimStrength::CheckedByVerifier);
    }

    #[test]
    fn verifier_rejects_reused_with_ineligible_class() {
        let mut record = sample_record();
        record.classification = DeterminismClass::Nondeterministic;
        let report = GuardReport {
            checked: 1,
            passed: 1,
            failure: None,
        };
        let certificate =
            issue_certificate(&record, Some(&report), CacheDecision::Reused, "wrong").unwrap();
        let verified = verify_certificate(&certificate);
        assert!(!verified.ok);
        assert!(verified
            .rejected
            .iter()
            .any(|reason| reason.contains("ineligible classification")));
    }

    #[test]
    fn verifier_rejects_missing_cas_object() {
        let record = sample_record();
        let report = GuardReport {
            checked: 1,
            passed: 1,
            failure: None,
        };
        let mut certificate = issue_certificate(
            &record,
            Some(&report),
            CacheDecision::Reused,
            "all guards passed",
        )
        .unwrap();
        certificate
            .cas_objects
            .retain(|object| object.role != CasRole::Stdout);
        let verified = verify_certificate(&certificate);
        assert!(!verified.ok);
        assert!(verified
            .rejected
            .iter()
            .any(|reason| reason.contains("stdout")));
    }

    #[test]
    fn verifier_rejects_full_equivalence_claim() {
        let record = sample_record();
        let report = GuardReport {
            checked: 1,
            passed: 1,
            failure: None,
        };
        let mut certificate = issue_certificate(
            &record,
            Some(&report),
            CacheDecision::Reused,
            "all guards passed",
        )
        .unwrap();
        certificate.claim_strength = ClaimStrength::FullEquivalenceProof;
        let verified = verify_certificate(&certificate);
        assert!(!verified.ok);
    }

    #[test]
    fn verifier_rejects_legacy_artifact_on_reuse() {
        let mut record = sample_record();
        record.outputs[0].artifact_version = 0;
        let report = GuardReport {
            checked: 1,
            passed: 1,
            failure: None,
        };
        let certificate = issue_certificate(
            &record,
            Some(&report),
            CacheDecision::Reused,
            "all guards passed",
        )
        .unwrap();
        let verified = verify_certificate(&certificate);
        assert!(!verified.ok);
        assert!(verified
            .rejected
            .iter()
            .any(|reason| reason.contains("legacy artifact")));
    }

    #[test]
    fn parse_rejects_malformed_json() {
        let err = parse_certificate(br#"{"schema":""}"#).unwrap_err();
        assert!(matches!(
            err,
            CertificateError::Malformed(_) | CertificateError::Serialization(_)
        ));
    }

    #[test]
    fn limitations_document_mutable_state_trust() {
        let notes = CertificateLimitations::default().notes.join(" ");
        assert!(notes.contains("mutable filesystem"));
        assert!(notes.contains("TOCTOU"));
        assert!(notes.contains("FullEquivalenceProof"));
    }
}

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;
use tracejit_cache::{
    now_unix_ms, output_from_path, Cache, CacheDecision, CacheError, DecisionRecord, OutputKind,
    StoredExecution,
};
use tracejit_effects::{
    classify, reconstruct_dependencies, DeterminismClass, Effect, EffectRecord, EnvironmentRead,
    ExecutionIdentity, FileWriteKind, Hash, InputDependency, ReadEffect, RuntimeIdentity, Trace,
    WriteEffect,
};
use tracejit_guards::{
    canonical_hash, compile_guards, current_runtime_identity, hash_file, validate_all, GuardError,
    GuardMode, GuardReport,
};
use tracejit_sandbox::{capabilities, SandboxPolicy};
use tracejit_trace::{trace_command, TraceError, TraceOutcome, TraceRequest};

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error(transparent)]
    Cache(#[from] CacheError),
    #[error(transparent)]
    Guard(#[from] GuardError),
    #[error(transparent)]
    Trace(#[from] TraceError),
    #[error("command is empty")]
    EmptyCommand,
    #[error("target binary not found: {0:?}")]
    TargetNotFound(OsString),
    #[error("output cannot be captured safely: {0}")]
    UnsafeOutput(PathBuf),
}

#[derive(Clone, Debug)]
pub struct RunOptions {
    pub command: Vec<OsString>,
    pub guard_mode: GuardMode,
    pub enforce: bool,
    pub cache_root: PathBuf,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum RunKind {
    Executed,
    Reused,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EffectCounts {
    pub reads: usize,
    pub writes: usize,
    pub controls: usize,
    pub unknown: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunReport {
    pub execution_id: String,
    pub kind: RunKind,
    pub cache_decision: Option<CacheDecision>,
    pub decision_reason: Option<String>,
    pub classification: DeterminismClass,
    pub eligible_for_reuse: bool,
    pub runtime_ns: u128,
    pub baseline_runtime_ns: u128,
    pub process_count: usize,
    pub effect_counts: EffectCounts,
    pub irreversible_effect_count: usize,
    pub dependency_count: usize,
    pub output_count: usize,
    pub guards: Option<GuardReport>,
    pub reasons: Vec<String>,
    #[serde(skip)]
    pub stdout: Vec<u8>,
    #[serde(skip)]
    pub stderr: Vec<u8>,
    pub exit_code: i32,
}

pub fn run(options: RunOptions) -> Result<RunReport, CoreError> {
    let prepared = PreparedExecution::new(&options.command)?;
    let mut cache = Cache::open(&options.cache_root)?;
    let lookup_key = prepared.lookup_key()?;
    let candidate = cache.find(lookup_key)?;
    let started = Instant::now();

    if let Some(mut candidate) = candidate {
        if candidate.classification.cache_eligible()
            && !(options.enforce && candidate.classification != DeterminismClass::Proven)
        {
            let guards = validate_all(&candidate.guards, options.guard_mode);
            if guards.failure.is_none() {
                cache.restore_outputs(&candidate.outputs)?;
                let stdout = cache.get_bytes(candidate.stdout)?;
                let stderr = cache.get_bytes(candidate.stderr)?;
                let runtime_ns = started.elapsed().as_nanos();
                candidate.last_decision = DecisionRecord {
                    decision: CacheDecision::Reused,
                    reason: "all guards passed and cached outputs were restored".into(),
                    guard_failure: None,
                    decided_unix_ms: now_unix_ms(),
                };
                cache.put_execution(&candidate)?;
                return Ok(report_from_record(
                    &candidate,
                    RunKind::Reused,
                    runtime_ns,
                    Some(guards),
                    stdout,
                    stderr,
                ));
            }
            let failure = guards.failure.clone();
            candidate.last_decision = DecisionRecord {
                decision: CacheDecision::Deoptimized,
                reason: failure.as_ref().map_or_else(
                    || "guard validation failed".into(),
                    |value| value.reason.clone(),
                ),
                guard_failure: failure,
                decided_unix_ms: now_unix_ms(),
            };
            cache.put_execution(&candidate)?;
            return execute_and_store(
                prepared,
                cache,
                lookup_key,
                Some(guards),
                Some("cached execution deoptimized".into()),
                None,
            );
        }

        if options.enforce && candidate.classification == DeterminismClass::Guarded {
            let guards = validate_all(&candidate.guards, options.guard_mode);
            if guards.failure.is_none() {
                let sandbox = policy_from_record(&candidate);
                let reason = if sandbox.is_some() {
                    "executed under policy compiled from the guarded profile"
                } else {
                    "enforcement unavailable for the recorded output policy; execution remains guarded"
                };
                return execute_and_store(
                    prepared,
                    cache,
                    lookup_key,
                    Some(guards),
                    Some(reason.into()),
                    sandbox,
                );
            }
            let failure = guards.failure.clone();
            candidate.last_decision = DecisionRecord {
                decision: CacheDecision::Deoptimized,
                reason: failure.as_ref().map_or_else(
                    || "guard validation failed".into(),
                    |value| value.reason.clone(),
                ),
                guard_failure: failure,
                decided_unix_ms: now_unix_ms(),
            };
            cache.put_execution(&candidate)?;
            return execute_and_store(
                prepared,
                cache,
                lookup_key,
                Some(guards),
                Some("cached execution deoptimized before enforcement".into()),
                None,
            );
        }
    }

    let reason = if options.enforce {
        let capability = capabilities();
        if capability.can_prove() {
            "no declared dependency profile exists; discovery run is not PROVEN".into()
        } else {
            capability
                .reason
                .unwrap_or_else(|| "sandbox unavailable; discovery run is not PROVEN".into())
        }
    } else {
        "no eligible cached execution matched the pre-execution identity".into()
    };
    execute_and_store(prepared, cache, lookup_key, None, Some(reason), None)
}

pub fn analyze(command: Vec<OsString>) -> Result<RunReport, CoreError> {
    let prepared = PreparedExecution::new(&command)?;
    let outcome = trace_command(prepared.trace_request(None))?;
    let mut trace = outcome.trace;
    add_discovery_effects(&mut trace, &prepared.environment, &prepared.cwd);
    let classification = classify(&trace.effects);
    let dependencies = reconstruct_dependencies(&trace.effects);
    let output_count = output_paths(&trace.effects).len();
    Ok(RunReport {
        execution_id: "analysis-only".into(),
        kind: RunKind::Executed,
        cache_decision: None,
        decision_reason: Some("analyze always executes and never uses the cache".into()),
        classification: classification.class,
        eligible_for_reuse: classification.class.cache_eligible(),
        runtime_ns: trace.execution.runtime_ns,
        baseline_runtime_ns: trace.execution.runtime_ns,
        process_count: trace.processes.len(),
        effect_counts: count_effects(&trace.effects),
        irreversible_effect_count: count_irreversible_effects(&trace.effects),
        dependency_count: dependencies.len(),
        output_count,
        guards: None,
        reasons: classification.reasons,
        stdout: outcome.stdout,
        stderr: outcome.stderr,
        exit_code: trace.execution.exit_code,
    })
}

pub fn explain(
    cache_root: PathBuf,
    id: Option<&str>,
) -> Result<Option<StoredExecution>, CoreError> {
    let cache = Cache::open(cache_root)?;
    match id {
        Some(id) => Ok(cache.find_by_id(id)?),
        None => Ok(cache.latest()?),
    }
}

fn execute_and_store(
    prepared: PreparedExecution,
    mut cache: Cache,
    lookup_key: Hash,
    guard_report: Option<GuardReport>,
    mut decision_reason: Option<String>,
    sandbox: Option<SandboxPolicy>,
) -> Result<RunReport, CoreError> {
    let outcome = match trace_command(prepared.trace_request(sandbox.clone())) {
        Ok(outcome) => outcome,
        Err(TraceError::Spawn(error)) if sandbox.is_some() => {
            decision_reason = Some(format!(
                "sandbox policy could not be applied; execution fell back to guarded discovery: {error}"
            ));
            trace_command(prepared.trace_request(None))?
        }
        Err(error) => return Err(error.into()),
    };
    store_outcome(
        prepared,
        &mut cache,
        lookup_key,
        guard_report,
        decision_reason,
        outcome,
    )
}

fn store_outcome(
    prepared: PreparedExecution,
    cache: &mut Cache,
    lookup_key: Hash,
    guard_report: Option<GuardReport>,
    decision_reason: Option<String>,
    mut outcome: TraceOutcome,
) -> Result<RunReport, CoreError> {
    add_discovery_effects(&mut outcome.trace, &prepared.environment, &prepared.cwd);
    let mut classification = classify(&outcome.trace.effects);
    if outcome.sandbox_enforced && classification.class == DeterminismClass::Guarded {
        classification.class = DeterminismClass::Proven;
        classification
            .reasons
            .push("seccomp and Landlock policy applied successfully".into());
    }
    let dependencies = reconstruct_dependencies(&outcome.trace.effects);
    let identity = ExecutionIdentity {
        executable_hash: prepared.executable_hash,
        argv: prepared.command.clone(),
        cwd: prepared.cwd.clone(),
        environment: prepared.environment.clone(),
        input_dependencies: dependencies,
        runtime_identity: prepared.runtime_identity.clone(),
    };
    let guards = compile_guards(prepared.executable.clone(), &identity);
    let mut outputs = Vec::new();
    for (path, (kind, allows_create)) in output_paths(&outcome.trace.effects) {
        if has_symlink_ancestor(&path) || (path.exists() && !is_restorable_regular_file(&path)) {
            classification.class = DeterminismClass::Unknown;
            classification.reasons.push(format!(
                "non-file output cannot be restored: {}",
                path.display()
            ));
            continue;
        }
        outputs.push(output_from_path(
            cache,
            &path,
            matches!(kind, FileWriteKind::Delete),
            allows_create,
        )?);
    }
    let stdout_hash = cache.put_bytes(&outcome.stdout)?;
    let stderr_hash = cache.put_bytes(&outcome.stderr)?;
    let execution_material = (
        lookup_key,
        outcome.trace.execution.started_unix_ms,
        outcome.trace.execution.runtime_ns,
        &outcome.trace.effects,
    );
    let id = canonical_hash(&execution_material)?.to_string()[..16].to_owned();
    let eligible = classification.class.cache_eligible();
    let decision = if guard_report
        .as_ref()
        .is_some_and(|report| report.failure.is_some())
    {
        CacheDecision::Deoptimized
    } else if eligible {
        CacheDecision::Executed
    } else {
        CacheDecision::Ineligible
    };
    let record = StoredExecution {
        id: id.clone(),
        lookup_key,
        command: prepared.command,
        executable: prepared.executable,
        identity,
        classification: classification.class,
        classification_reasons: classification.reasons.clone(),
        effects: outcome.trace.effects.clone(),
        guards,
        outputs,
        stdout: stdout_hash,
        stderr: stderr_hash,
        exit_code: outcome.trace.execution.exit_code,
        baseline_runtime_ns: outcome.trace.execution.runtime_ns,
        trace: outcome.trace,
        last_decision: DecisionRecord {
            decision,
            reason: decision_reason.unwrap_or_else(|| {
                if eligible {
                    "baseline execution recorded".into()
                } else {
                    "classification is not eligible for reuse".into()
                }
            }),
            guard_failure: guard_report
                .as_ref()
                .and_then(|report| report.failure.clone()),
            decided_unix_ms: now_unix_ms(),
        },
    };
    cache.put_execution(&record)?;
    Ok(report_from_record(
        &record,
        RunKind::Executed,
        record.baseline_runtime_ns,
        guard_report,
        outcome.stdout,
        outcome.stderr,
    ))
}

struct PreparedExecution {
    command: Vec<OsString>,
    executable: PathBuf,
    executable_hash: Hash,
    cwd: PathBuf,
    environment: BTreeMap<OsString, OsString>,
    runtime_identity: RuntimeIdentity,
}

impl PreparedExecution {
    fn new(command: &[OsString]) -> Result<Self, CoreError> {
        let program = command.first().ok_or(CoreError::EmptyCommand)?;
        let cwd =
            std::env::current_dir().map_err(|_| CoreError::TargetNotFound(program.clone()))?;
        let environment = std::env::vars_os().collect::<BTreeMap<_, _>>();
        let executable = resolve_executable(program, &cwd, &environment)
            .ok_or_else(|| CoreError::TargetNotFound(program.clone()))?;
        let executable_hash = hash_file(&executable)?;
        let runtime_identity = current_runtime_identity()?;
        Ok(Self {
            command: command.to_vec(),
            executable,
            executable_hash,
            cwd,
            environment,
            runtime_identity,
        })
    }

    fn lookup_key(&self) -> Result<Hash, CoreError> {
        let mut hasher = blake3::Hasher::new();
        hash_component(&mut hasher, self.executable_hash.as_bytes());
        for argument in &self.command {
            hash_os_string(&mut hasher, argument);
        }
        hash_path(&mut hasher, &self.cwd);
        for (key, value) in &self.environment {
            hash_os_string(&mut hasher, key);
            hash_os_string(&mut hasher, value);
        }
        hash_component(
            &mut hasher,
            &serde_json::to_vec(&self.runtime_identity).map_err(GuardError::Serialization)?,
        );
        Ok(Hash::from(hasher.finalize()))
    }

    fn trace_request(&self, sandbox: Option<SandboxPolicy>) -> TraceRequest {
        TraceRequest {
            executable: self.executable.clone(),
            argv: self.command.clone(),
            cwd: self.cwd.clone(),
            environment: self.environment.clone(),
            sandbox,
        }
    }
}

#[cfg(unix)]
fn hash_os_string(hasher: &mut blake3::Hasher, value: &OsStr) {
    use std::os::unix::ffi::OsStrExt;
    hash_component(hasher, value.as_bytes());
}

#[cfg(not(unix))]
fn hash_os_string(hasher: &mut blake3::Hasher, value: &OsStr) {
    hash_component(hasher, value.to_string_lossy().as_bytes());
}

fn hash_path(hasher: &mut blake3::Hasher, value: &Path) {
    hash_os_string(hasher, value.as_os_str());
}

fn hash_component(hasher: &mut blake3::Hasher, value: &[u8]) {
    hasher.update(&(value.len() as u64).to_le_bytes());
    hasher.update(value);
}

fn resolve_executable(
    program: &OsStr,
    cwd: &Path,
    environment: &BTreeMap<OsString, OsString>,
) -> Option<PathBuf> {
    let program_path = Path::new(program);
    if program_path.components().count() > 1 {
        let path = if program_path.is_absolute() {
            program_path.to_path_buf()
        } else {
            cwd.join(program_path)
        };
        return fs::canonicalize(path).ok().filter(|path| path.is_file());
    }
    let search = environment.get(OsStr::new("PATH"))?;
    std::env::split_paths(search)
        .map(|directory| directory.join(program_path))
        .find(|path| path.is_file())
        .and_then(|path| fs::canonicalize(path).ok())
}

fn add_discovery_effects(
    trace: &mut Trace,
    environment: &BTreeMap<OsString, OsString>,
    cwd: &Path,
) {
    let mut sequence = trace.effects.last().map_or(0, |record| record.sequence + 1);
    trace.effects.push(EffectRecord {
        sequence,
        pid: trace.processes.first().map_or(0, |process| process.pid),
        effect: Effect::Read(ReadEffect::WorkingDirectory),
    });
    sequence += 1;
    for (key, value) in environment {
        trace.effects.push(EffectRecord {
            sequence,
            pid: trace.processes.first().map_or(0, |process| process.pid),
            effect: Effect::Read(ReadEffect::Environment(EnvironmentRead {
                key: key.clone(),
                value: Some(value.clone()),
            })),
        });
        sequence += 1;
    }
    trace.dependencies.push(tracejit_effects::DependencyEdge {
        from: "execution".into(),
        to: cwd.display().to_string(),
        kind: tracejit_effects::DependencyKind::DependsOn,
    });
}

fn output_paths(effects: &[EffectRecord]) -> BTreeMap<PathBuf, (FileWriteKind, bool)> {
    effects.iter().fold(BTreeMap::new(), |mut outputs, record| {
        if let Effect::Write(WriteEffect::File(write)) = &record.effect {
            let output = outputs
                .entry(write.path.clone())
                .or_insert((write.operation, false));
            output.0 = write.operation;
            if let Some(allows_create) = write.allows_create {
                output.1 |= allows_create;
            }
        }
        outputs
    })
}

fn is_restorable_regular_file(path: &Path) -> bool {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(_) => return false,
    };
    if !metadata.file_type().is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        metadata.nlink() == 1
    }
    #[cfg(not(unix))]
    {
        true
    }
}

fn has_symlink_ancestor(path: &Path) -> bool {
    path.ancestors().skip(1).any(|ancestor| {
        fs::symlink_metadata(ancestor).is_ok_and(|value| value.file_type().is_symlink())
    })
}

fn policy_from_record(record: &StoredExecution) -> Option<SandboxPolicy> {
    if !capabilities().can_prove() {
        return None;
    }
    let mut readable = BTreeSet::from([record.executable.clone()]);
    for dependency in &record.identity.input_dependencies {
        match dependency {
            InputDependency::Executable { path, .. }
            | InputDependency::File { path, .. }
            | InputDependency::Metadata { path, .. }
            | InputDependency::SymlinkMetadata { path, .. }
            | InputDependency::Symlink { path, .. } => {
                if !path.exists() {
                    return None;
                }
                readable.insert(path.clone());
            }
        }
    }
    let mut writable = BTreeSet::new();
    for output in &record.outputs {
        if output.kind == OutputKind::Deleted || !output.path.exists() {
            return None;
        }
        writable.insert(output.path.clone());
    }
    Some(SandboxPolicy {
        readable_paths: readable.into_iter().collect(),
        writable_paths: writable.into_iter().collect(),
        allow_network: false,
    })
}

fn report_from_record(
    record: &StoredExecution,
    kind: RunKind,
    runtime_ns: u128,
    guards: Option<GuardReport>,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
) -> RunReport {
    RunReport {
        execution_id: record.id.clone(),
        kind,
        cache_decision: Some(record.last_decision.decision.clone()),
        decision_reason: Some(record.last_decision.reason.clone()),
        classification: record.classification,
        eligible_for_reuse: record.classification.cache_eligible(),
        runtime_ns,
        baseline_runtime_ns: record.baseline_runtime_ns,
        process_count: record.trace.processes.len(),
        effect_counts: count_effects(&record.effects),
        irreversible_effect_count: count_irreversible_effects(&record.effects),
        dependency_count: record.identity.input_dependencies.len(),
        output_count: record.outputs.len(),
        guards,
        reasons: record.classification_reasons.clone(),
        stdout,
        stderr,
        exit_code: record.exit_code,
    }
}

fn count_effects(effects: &[EffectRecord]) -> EffectCounts {
    effects.iter().fold(
        EffectCounts {
            reads: 0,
            writes: 0,
            controls: 0,
            unknown: 0,
        },
        |mut counts, record| {
            match record.effect {
                Effect::Read(_) => counts.reads += 1,
                Effect::Write(_) => counts.writes += 1,
                Effect::Control(_) => counts.controls += 1,
                Effect::Unknown(_) => counts.unknown += 1,
            }
            counts
        },
    )
}

fn count_irreversible_effects(effects: &[EffectRecord]) -> usize {
    effects
        .iter()
        .filter(|record| !record.effect.properties().reversible)
        .count()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tracejit_effects::{FileRead, FileWrite};

    #[test]
    fn read_before_write_remains_a_dependency() {
        let path = PathBuf::from("/input");
        let hash = Hash::from(blake3::hash(b"before"));
        let effects = vec![
            EffectRecord {
                sequence: 0,
                pid: 1,
                effect: Effect::Read(ReadEffect::File(FileRead {
                    path: path.clone(),
                    hash: Some(hash),
                    fingerprint: None,
                })),
            },
            EffectRecord {
                sequence: 1,
                pid: 1,
                effect: Effect::Write(WriteEffect::File(FileWrite {
                    path: path.clone(),
                    operation: FileWriteKind::CreateOrModify,
                    allows_create: Some(false),
                })),
            },
        ];
        assert!(matches!(
            reconstruct_dependencies(&effects).as_slice(),
            [InputDependency::File { expected_hash, .. }] if *expected_hash == hash
        ));
    }

    #[test]
    fn write_then_read_is_not_an_input_dependency() {
        let path = PathBuf::from("/output");
        let effects = vec![
            EffectRecord {
                sequence: 0,
                pid: 1,
                effect: Effect::Write(WriteEffect::File(FileWrite {
                    path: path.clone(),
                    operation: FileWriteKind::CreateOrModify,
                    allows_create: Some(false),
                })),
            },
            EffectRecord {
                sequence: 1,
                pid: 1,
                effect: Effect::Read(ReadEffect::File(tracejit_effects::FileRead {
                    path,
                    hash: Some(Hash::from(blake3::hash(b"output"))),
                    fingerprint: None,
                })),
            },
        ];
        assert!(reconstruct_dependencies(&effects).is_empty());
    }
}

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;
use tracejit_cache::{
    now_unix_ms, output_from_path, AdmissionCost, Cache, CacheDecision, CacheError, DecisionRecord,
    OutputKind, StoredExecution,
};
use tracejit_effects::{
    classify, reconstruct_dependencies, DeterminismClass, Effect, EffectRecord, EnvironmentRead,
    ExecutionIdentity, FileWriteKind, Hash, InputDependency, ReadEffect, RuntimeIdentity, Trace,
    WriteEffect,
};
use tracejit_guards::{
    apply_inherited_stream_offsets, canonical_hash, compile_guards, current_runtime_identity,
    hash_file, validate_all, GuardError, GuardMode, GuardReport,
};
use tracejit_sandbox::{capabilities, SandboxPolicy};
pub use tracejit_trace::Contract;
use tracejit_trace::{probe_ptrace, trace_command, TraceError, TraceOutcome, TraceRequest};

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
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

#[derive(Clone, Debug)]
pub struct RunOptions {
    pub command: Vec<OsString>,
    pub guard_mode: GuardMode,
    pub enforce: bool,
    pub cache_root: PathBuf,
    /// `None` is native guarded execution. A contract deliberately fixes selected environmental
    /// nondeterminism and is part of the cache identity, so native and controlled entries never
    /// share a record.
    pub contract: Option<tracejit_trace::Contract>,
    pub admission: Admission,
}

/// When a command is worth tracing and caching at all.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub enum Admission {
    /// Trace and store every invocation, then reuse when the guards pass. Historical behaviour.
    #[default]
    Always,
    /// Measure before committing, then trace when one trace can plausibly repay itself and
    /// observed invalidations have not outnumbered the hits they replaced. The first invocation
    /// always runs directly.
    Auto,
    /// Phase 2H's policy: measure, then trace when `direct >= 2 x max(hit, 6 ms)`.
    AutoLegacy,
    /// Never trace or reuse; run the command directly.
    Never,
}

/// A hit costs process startup, identity, SQLite lookup, guards and restoration. A command whose
/// native runtime is below this is not worth caching even if it would always hit.
const HIT_COST_FLOOR_NS: u64 = 6_000_000;
/// Stale cost samples are discarded rather than trusted forever.
const ADMISSION_SAMPLE_TTL_MS: u128 = 30 * 24 * 60 * 60 * 1000;

fn admission_is_profitable(cost: &AdmissionCost) -> bool {
    let hit = cost.hit_ns.max(HIT_COST_FLOOR_NS);
    cost.direct_ns >= hit.saturating_mul(2)
}

/// Whether continuing to trace this identity can repay itself.
///
/// Two measured quantities, both stored: a direct run must be at least twice the floor-or-observed
/// hit cost, so one hit can pay for a trace; and hits plus one must exceed invalidations, so an
/// identity whose inputs are edited before every run stops paying for traces it cannot reuse. The
/// Phase 2J ablation found the previous smoothed three-invocation model indistinguishable from the
/// Phase 2H threshold, so the extra arithmetic and horizon constant were removed.
fn admission_is_worth_tracing(cost: &AdmissionCost) -> bool {
    admission_is_profitable(cost) && cost.hits.saturating_add(1) > cost.deopts
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum RunKind {
    Executed,
    Reused,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub contract: Option<String>,
    #[serde(skip)]
    pub stdout: Vec<u8>,
    #[serde(skip)]
    pub stderr: Vec<u8>,
    pub exit_code: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phases: Option<PhaseTimings>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PhaseTimings {
    pub process_startup_ns: u64,
    pub cli_parse_ns: u64,
    pub identity_prepare_ns: u64,
    pub cache_prepare_ns: u64,
    pub sqlite_open_ns: u64,
    pub sqlite_schema_ns: u64,
    pub lookup_key_ns: u64,
    pub sqlite_query_ns: u64,
    pub record_decode_ns: u64,
    pub guard_validation_ns: u64,
    pub cas_restore_ns: u64,
    pub stdio_replay_ns: u64,
    pub decision_persist_ns: u64,
    pub present_ns: u64,
}

pub fn phase_timing_enabled() -> bool {
    std::env::var_os("TRACEJIT_PHASE_TIMING").is_some_and(|value| value == "1")
}

pub fn start_ticks_from_stat(stat: &str) -> Option<u64> {
    let (_, rest) = stat.rsplit_once(')')?;
    rest.split_whitespace().nth(19)?.parse().ok()
}

pub fn process_startup_ns() -> u64 {
    #[cfg(target_os = "linux")]
    {
        let Ok(stat) = fs::read_to_string("/proc/self/stat") else {
            return 0;
        };
        let Some(start_ticks) = start_ticks_from_stat(&stat) else {
            return 0;
        };
        let ticks = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
        if ticks <= 0 {
            return 0;
        }
        let mut now = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        if unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut now) } != 0 {
            return 0;
        }
        let now_ns = (now.tv_sec as u64)
            .saturating_mul(1_000_000_000)
            .saturating_add(now.tv_nsec as u64);
        let start_ns = start_ticks.saturating_mul(1_000_000_000) / ticks as u64;
        now_ns.saturating_sub(start_ns)
    }
    #[cfg(not(target_os = "linux"))]
    {
        0
    }
}

pub fn run(options: RunOptions) -> Result<RunReport, CoreError> {
    let timing = phase_timing_enabled();
    let mark = Instant::now();
    let prepared = PreparedExecution::new(&options.command, options.contract)?;
    let identity_prepare_ns = phase_elapsed(timing, mark);
    let mut cache = Cache::open(&options.cache_root)?;
    let open = cache.open_timings;
    let mark = Instant::now();
    let lookup_key = prepared.lookup_key()?;
    let lookup_key_ns = phase_elapsed(timing, mark);
    let (candidate, metadata_recovery) = match cache.find(lookup_key) {
        Ok(candidate) => (candidate, None),
        // A malformed metadata record is a cache-integrity failure, not a reason to refuse
        // to run the command. It is treated as a miss so the execution is retraced and the
        // record is rewritten, and no cached byte is exposed either way.
        Err(CacheError::Serialization(error)) => (
            None,
            Some(format!(
                "stored metadata record could not be decoded ({error}); the execution was retraced"
            )),
        ),
        Err(error) => return Err(error.into()),
    };
    let query = cache.last_query();
    let started = Instant::now();
    let mut phases = PhaseTimings {
        identity_prepare_ns,
        cache_prepare_ns: open.prepare_ns,
        sqlite_open_ns: open.sqlite_open_ns,
        sqlite_schema_ns: open.schema_ns,
        lookup_key_ns,
        sqlite_query_ns: query.query_ns,
        record_decode_ns: query.decode_ns,
        ..PhaseTimings::default()
    };

    // Cost-aware admission. `Always` keeps the historical behaviour. `Auto` learns the direct
    // runtime before it pays for a trace, so a command that cannot repay a hit never pays for one.
    if options.admission != Admission::Always {
        let reusable = candidate.as_ref().is_some_and(|candidate| {
            candidate.classification.cache_eligible()
                && candidate.contract.as_deref() == options.contract.map(|contract| contract.id())
        });
        let mut run_without_cache = options.admission == Admission::Never;
        let mut reason = "admission policy disabled caching for this run";
        let measuring = matches!(options.admission, Admission::Auto | Admission::AutoLegacy);
        if measuring && !reusable {
            // A record that was classified ineligible has already answered the question: tracing
            // this identity again cannot produce a reusable entry, so pay for it once, not forever.
            if candidate
                .as_ref()
                .is_some_and(|candidate| !candidate.classification.cache_eligible())
            {
                run_without_cache = true;
                reason = "admission policy: the recorded classification is not eligible for reuse";
            }
        }
        if measuring && !reusable && !run_without_cache {
            // A changed executable, environment or contract is a different identity, so it has its
            // own (usually absent) cost sample and is re-examined from scratch.
            let cost = cache.admission_cost(lookup_key)?.filter(|cost| {
                now_unix_ms().saturating_sub(cost.updated_ms) <= ADMISSION_SAMPLE_TTL_MS
            });
            match cost {
                None => {
                    run_without_cache = true;
                    reason = "admission policy is measuring this command before deciding whether to cache";
                }
                Some(cost) => {
                    let profitable = match options.admission {
                        Admission::AutoLegacy => admission_is_profitable(&cost),
                        _ => admission_is_worth_tracing(&cost),
                    };
                    if !profitable {
                        run_without_cache = true;
                        reason = "admission policy estimates that a trace cannot repay itself for this identity";
                    }
                }
            }
        }
        if run_without_cache {
            return run_direct(&prepared, &cache, lookup_key, reason, options.contract);
        }
    }

    if let Some(mut candidate) = candidate {
        if candidate.classification.cache_eligible()
            && candidate.contract.as_deref() == options.contract.map(|contract| contract.id())
            && !(options.enforce && candidate.classification != DeterminismClass::Proven)
        {
            let mark = Instant::now();
            let guards = validate_all(&candidate.guards, options.guard_mode);
            phases.guard_validation_ns = phase_elapsed(timing, mark);
            if guards.failure.is_none() {
                // Outputs are staged and every object is verified before any destination is
                // mutated, so a corrupt object stops here without changing the workspace.
                let mark = Instant::now();
                let restore = cache.restore_outputs(&candidate.outputs);
                phases.cas_restore_ns = phase_elapsed(timing, mark);
                let mark = Instant::now();
                let loaded: Result<(Vec<u8>, Vec<u8>), CacheError> = match restore {
                    Ok(()) => cache.get_bytes(candidate.stdout).and_then(|stdout| {
                        cache
                            .get_bytes(candidate.stderr)
                            .map(|stderr| (stdout, stderr))
                    }),
                    Err(error) => Err(error),
                };
                phases.stdio_replay_ns = phase_elapsed(timing, mark);
                match loaded {
                    Ok((stdout, stderr)) => {
                        // A cached execution that read an inherited regular file advanced the
                        // caller's shared open file description. Reproduce that side effect
                        // before reporting the hit, or a following command would read from a
                        // different position than after a direct run.
                        if let Err(error) = apply_inherited_stream_offsets(&candidate.guards) {
                            candidate.last_decision = DecisionRecord {
                                decision: CacheDecision::Deoptimized,
                                reason: format!(
                                    "inherited stream offset could not be reproduced ({error}); retracing"
                                ),
                                guard_failure: None,
                                decided_unix_ms: now_unix_ms(),
                            };
                            cache.put_execution(&candidate)?;
                            return execute_and_store(
                                prepared,
                                cache,
                                lookup_key,
                                Some(guards),
                                Some(
                                    "inherited stream state could not be reproduced; the execution was retraced"
                                        .into(),
                                ),
                                None,
                            );
                        }
                        let runtime_ns = started.elapsed().as_nanos();
                        // The cost history exists for the admission policy. `always` never
                        // consults it, so writing a row on every one of its hits is pure warm
                        // path cost; `never` never reaches a hit. Skip the read and upsert.
                        if options.admission != Admission::Always {
                            cache.record_admission(
                                lookup_key,
                                u64::try_from(candidate.baseline_runtime_ns).unwrap_or(u64::MAX),
                                0,
                                Some(u64::try_from(runtime_ns).unwrap_or(u64::MAX)),
                                false,
                                false,
                            )?;
                        }
                        let persist_decision =
                            candidate.last_decision.decision != CacheDecision::Reused;
                        candidate.last_decision = DecisionRecord {
                            decision: CacheDecision::Reused,
                            reason: "all guards passed and cached outputs were restored".into(),
                            guard_failure: None,
                            decided_unix_ms: now_unix_ms(),
                        };
                        if persist_decision {
                            let mark = Instant::now();
                            cache.put_execution(&candidate)?;
                            phases.decision_persist_ns = phase_elapsed(timing, mark);
                        }
                        let mut report = report_from_record(
                            &candidate,
                            RunKind::Reused,
                            runtime_ns,
                            Some(guards),
                            stdout,
                            stderr,
                        );
                        if timing {
                            report.phases = Some(phases);
                        }
                        return Ok(report);
                    }
                    // The record is readable but a content-addressed object failed
                    // verification. Nothing has been exposed, so retrace instead of failing
                    // the command until the cache is cleared by hand.
                    Err(CacheError::CorruptObject { hash }) => {
                        candidate.last_decision = DecisionRecord {
                            decision: CacheDecision::Deoptimized,
                            reason: format!(
                                "cached object {hash} failed hash verification; retracing"
                            ),
                            guard_failure: None,
                            decided_unix_ms: now_unix_ms(),
                        };
                        cache.put_execution(&candidate)?;
                        return execute_and_store(
                            prepared,
                            cache,
                            lookup_key,
                            Some(guards),
                            Some("cached content was corrupt; the execution was retraced".into()),
                            None,
                        );
                    }
                    // A destination precondition can fail even though no dependency changed: a
                    // hard link to an output, for example, is neither a recorded input nor an
                    // input mutation, so no guard observes it. Refusing the cache entry is
                    // correct, but aborting the command is not, because the identical command
                    // line succeeds when it is simply executed again. `restore_outputs`
                    // validates and stages before it mutates, so a precondition failure leaves
                    // the workspace untouched and a retrace is safe.
                    Err(error @ CacheError::OutputPrecondition { .. }) => {
                        // D4 refuses to reconcile a *deletion* whose path changed shape, and that
                        // refusal stays fatal: re-running such a command would act on the
                        // substituted path instead of restoring a recorded absence. A refused
                        // *replacement* is different, because re-executing rewrites the output
                        // itself, which is exactly what the cache would have restored.
                        let deletion = matches!(
                            &error,
                            CacheError::OutputPrecondition { path, .. }
                                if candidate
                                    .outputs
                                    .iter()
                                    .any(|output| output.path == *path && output.content.is_none())
                        );
                        if deletion {
                            return Err(error.into());
                        }
                        candidate.last_decision = DecisionRecord {
                            decision: CacheDecision::Deoptimized,
                            reason: format!("{error}; retracing"),
                            guard_failure: None,
                            decided_unix_ms: now_unix_ms(),
                        };
                        cache.put_execution(&candidate)?;
                        return execute_and_store(
                            prepared,
                            cache,
                            lookup_key,
                            Some(guards),
                            Some(
                                "a cached output precondition failed; the execution was retraced"
                                    .into(),
                            ),
                            None,
                        );
                    }
                    Err(error) => return Err(error.into()),
                }
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

    let mut reason = if options.enforce {
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
    if let Some(note) = metadata_recovery {
        reason = format!("{note}; {reason}");
    }
    execute_and_store(prepared, cache, lookup_key, None, Some(reason), None)
}

pub fn analyze(command: Vec<OsString>) -> Result<RunReport, CoreError> {
    let prepared = PreparedExecution::new(&command, None)?;
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
        contract: None,
        guards: None,
        reasons: classification.reasons,
        stdout: outcome.stdout,
        stderr: outcome.stderr,
        exit_code: trace.execution.exit_code,
        phases: None,
    })
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DoctorReport {
    pub os: String,
    pub arch: String,
    pub supported: bool,
    pub ptrace: bool,
    pub seccomp: bool,
    pub landlock_abi: Option<i32>,
    pub proven: bool,
    pub cache_path: PathBuf,
    pub cache_writable: bool,
    /// The cache directory is absent, and an existing parent can accept new files.
    pub cache_creatable: bool,
    pub problems: Vec<String>,
}

pub fn doctor() -> DoctorReport {
    let os = std::env::consts::OS.to_string();
    let arch = std::env::consts::ARCH.to_string();
    let supported = cfg!(all(target_os = "linux", target_arch = "x86_64"));
    let ptrace_result = probe_ptrace();
    let sandbox = capabilities();
    let cache_path = Cache::default_root();
    let cache_state = cache_path_state(&cache_path);
    let mut problems = Vec::new();
    if !supported {
        problems.push(format!(
            "This machine is {os} {arch}. TraceJIT V1 observes processes with ptrace and only runs on Linux x86_64, so tracing and reuse are unavailable here."
        ));
    } else {
        if let Err(detail) = &ptrace_result {
            problems.push(detail.clone());
            problems.push(
                "Without ptrace, TraceJIT cannot observe dependencies or reuse a command. A restrictive yama ptrace_scope, a container without SYS_PTRACE, or another sandbox can cause this. TraceJIT will not guess past it.".into(),
            );
        }
        if !sandbox.can_prove() {
            problems.extend(sandbox.reason.clone());
            problems.push(
                "GUARDED reuse does not require seccomp or Landlock. PROVEN does: both must actually be installed. An unenforced run stays GUARDED.".into(),
            );
        }
    }
    if cache_state == CachePathState::Unwritable {
        problems.push(format!(
            "cache path is not writable: {}",
            cache_path.display()
        ));
    }
    DoctorReport {
        os,
        arch,
        supported,
        ptrace: ptrace_result.is_ok(),
        seccomp: sandbox.seccomp,
        landlock_abi: sandbox.landlock_abi,
        proven: supported && ptrace_result.is_ok() && sandbox.can_prove(),
        cache_path,
        cache_writable: cache_state == CachePathState::Writable,
        cache_creatable: cache_state == CachePathState::Creatable,
        problems,
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CachePathState {
    Writable,
    Creatable,
    Unwritable,
}

fn cache_path_state(path: &Path) -> CachePathState {
    if path.is_dir() {
        return if directory_accepts_files(path) {
            CachePathState::Writable
        } else {
            CachePathState::Unwritable
        };
    }
    if path.exists() {
        return CachePathState::Unwritable;
    }
    let mut cursor = path;
    while let Some(parent) = cursor.parent() {
        if parent.as_os_str().is_empty() || parent == cursor {
            break;
        }
        if parent.exists() {
            return if parent.is_dir() && directory_accepts_files(parent) {
                CachePathState::Creatable
            } else {
                CachePathState::Unwritable
            };
        }
        cursor = parent;
    }
    CachePathState::Unwritable
}

fn directory_accepts_files(directory: &Path) -> bool {
    let probe = directory.join(format!(".tracejit-doctor-probe-{}", std::process::id()));
    match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&probe)
    {
        Ok(_) => {
            let _ = std::fs::remove_file(probe);
            true
        }
        Err(_) => false,
    }
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

/// Runs the command without tracing, caching or restoring anything.
///
/// This is ordinary execution: the child inherits stdin, the prepared environment and working
/// directory, and its bytes and status are passed through. It exists so that the admission policy
/// never pays tracing cost for a command that cannot repay it.
fn run_direct(
    prepared: &PreparedExecution,
    cache: &Cache,
    lookup_key: Hash,
    reason: &str,
    contract: Option<tracejit_trace::Contract>,
) -> Result<RunReport, CoreError> {
    let started = Instant::now();
    let output = std::process::Command::new(&prepared.executable)
        .args(prepared.command.iter().skip(1))
        .current_dir(&prepared.cwd)
        .env_clear()
        .envs(&prepared.environment)
        .stdin(std::process::Stdio::inherit())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .output()?;
    let runtime_ns = started.elapsed().as_nanos();
    cache.record_admission(
        lookup_key,
        u64::try_from(runtime_ns).unwrap_or(u64::MAX),
        0,
        None,
        true,
        false,
    )?;
    Ok(RunReport {
        execution_id: "direct".into(),
        kind: RunKind::Executed,
        cache_decision: Some(CacheDecision::Skipped),
        decision_reason: Some(reason.into()),
        classification: DeterminismClass::Unknown,
        eligible_for_reuse: false,
        runtime_ns,
        baseline_runtime_ns: runtime_ns,
        process_count: 1,
        effect_counts: EffectCounts::default(),
        irreversible_effect_count: 0,
        dependency_count: 0,
        output_count: 0,
        guards: None,
        reasons: vec![reason.into()],
        contract: contract.map(|contract| contract.id().to_string()),
        stdout: output.stdout,
        stderr: output.stderr,
        exit_code: output.status.code().unwrap_or(-1),
        phases: None,
    })
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
    // Under the compiler contract a directory's timestamps are not contracted inputs: the
    // compilation itself creates and removes temporary entries in them, so a timestamp guard
    // would refuse every reuse. The directory is still guarded by identity and permissions.
    if prepared.contract == Some(tracejit_trace::Contract::CompilerRuntimeV1) {
        // The command's own outputs are restored by the cache, so their pre-state is not a
        // precondition: a compiler that stats its `-o` path before writing sees "absent" on the
        // first run and "present" on every later one. The output artifact guard is the real
        // contract for that path.
        let outputs = outcome
            .trace
            .effects
            .iter()
            .filter_map(|record| match &record.effect {
                Effect::Write(WriteEffect::File(write)) => Some(write.path.clone()),
                _ => None,
            })
            .collect::<BTreeSet<PathBuf>>();
        let mut rewritten = Vec::with_capacity(outcome.trace.effects.len());
        for mut record in std::mem::take(&mut outcome.trace.effects) {
            let is_output_metadata = matches!(
                &record.effect,
                Effect::Read(tracejit_effects::ReadEffect::FileMetadata(read))
                    if outputs.contains(&read.path)
            );
            if is_output_metadata {
                continue;
            }
            // A directory's timestamps are not contracted inputs: the compilation itself
            // creates and removes entries in them. Identity and permissions are still guarded.
            let replacement = match &record.effect {
                Effect::Read(tracejit_effects::ReadEffect::FileMetadata(read)) => read
                    .fingerprint
                    .as_ref()
                    .filter(|fingerprint| fingerprint.mode & 0o170000 == 0o040000)
                    .map(|fingerprint| (read.path.clone(), fingerprint.clone())),
                _ => None,
            };
            if let Some((path, fingerprint)) = replacement {
                record.effect = Effect::Read(tracejit_effects::ReadEffect::DirectoryOpened(
                    tracejit_effects::DirectoryOpen {
                        path,
                        fingerprint,
                        flags: 0,
                        // The tracee inherits this process's credentials; recording them lets
                        // the guard refuse a replay under different credentials.
                        credential: tracejit_guards::credential_identity(std::process::id()),
                    },
                ));
            }
            rewritten.push(record);
        }
        outcome.trace.effects = rewritten;
    }
    let mut classification = classify(&outcome.trace.effects);
    if outcome.sandbox_enforced && classification.class == DeterminismClass::Guarded {
        classification.class = DeterminismClass::Proven;
        classification
            .reasons
            .push("seccomp and Landlock policy applied successfully".into());
    }
    let contract = prepared.contract.map(|contract| contract.id().to_string());
    // A record that contains contract effects is only meaningful inside its contract. If the
    // contract is not active the execution must not be eligible, even though the effect itself is
    // guardable under the contract.
    if contract.is_none()
        && outcome.trace.effects.iter().any(|record| {
            matches!(
                record.effect,
                Effect::Read(tracejit_effects::ReadEffect::ControlledEntropy(_))
                    | Effect::Read(tracejit_effects::ReadEffect::ControlledRuntime(_))
            )
        })
    {
        classification.class = DeterminismClass::Unknown;
        classification
            .reasons
            .push("a controlled observation was recorded without an active contract".into());
    }
    if let Some(contract) = contract.as_deref() {
        classification.reasons.push(format!(
            "executed under the {contract} contract; reuse is reproducible within that contract, not equivalent to native execution"
        ));
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
        contract,
        guards,
        outputs,
        stdout: stdout_hash,
        stderr: stderr_hash,
        exit_code: outcome.trace.execution.exit_code,
        baseline_runtime_ns: outcome.trace.execution.runtime_ns,
        process_count: outcome.trace.processes.len(),
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
    cache.record_admission(
        lookup_key,
        u64::try_from(record.baseline_runtime_ns).unwrap_or(u64::MAX),
        0,
        None,
        false,
        record.last_decision.decision == CacheDecision::Deoptimized,
    )?;
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
    contract: Option<tracejit_trace::Contract>,
}

impl PreparedExecution {
    fn new(
        command: &[OsString],
        contract: Option<tracejit_trace::Contract>,
    ) -> Result<Self, CoreError> {
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
            contract,
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
        hash_component(
            &mut hasher,
            self.contract
                .map_or("native", |contract| contract.id())
                .as_bytes(),
        );
        Ok(Hash::from(hasher.finalize()))
    }

    fn trace_request(&self, sandbox: Option<SandboxPolicy>) -> TraceRequest {
        TraceRequest {
            executable: self.executable.clone(),
            argv: self.command.clone(),
            cwd: self.cwd.clone(),
            environment: self.environment.clone(),
            expected_executable_hash: Some(self.executable_hash),
            sandbox,
            contract: self.contract,
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
            | InputDependency::DirectoryOpened { path, .. }
            | InputDependency::DirectoryEnumerated { path, .. }
            | InputDependency::FilesystemStats { path, .. }
            | InputDependency::InheritedStream { path, .. }
            | InputDependency::SymlinkMetadata { path, .. }
            | InputDependency::Symlink { path, .. } => {
                if !path.exists() {
                    return None;
                }
                readable.insert(path.clone());
            }
            // An access check may legitimately refer to a path that is absent: the recorded
            // answer is then "denied", and the guard re-checks exactly that answer. The path is
            // only made readable when it exists, so an absent probe adds nothing to the policy.
            InputDependency::Access { path, .. } => {
                if path.exists() {
                    readable.insert(path.clone());
                }
            }
            // Under the controlled contract the runtime library is read by the tracer, not by the
            // child, but a sandbox policy still has to let the child map it.
            InputDependency::ControlledEntropy { library, .. } => {
                readable.insert(library.clone());
            }
            // The audited compiler binary is executed by the caller, so the sandbox must let
            // the child map it; an absent binary cannot be guarded.
            InputDependency::ControlledRuntime { executable, .. } => {
                if !executable.exists() {
                    return None;
                }
                readable.insert(executable.clone());
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
        process_count: if record.process_count > 0 {
            record.process_count
        } else {
            record.trace.processes.len()
        },
        effect_counts: count_effects(&record.effects),
        irreversible_effect_count: count_irreversible_effects(&record.effects),
        dependency_count: record.identity.input_dependencies.len(),
        output_count: record.outputs.len(),
        guards,
        reasons: record.classification_reasons.clone(),
        contract: record.contract.clone(),
        stdout,
        stderr,
        exit_code: record.exit_code,
        phases: None,
    }
}

fn phase_elapsed(enabled: bool, started: Instant) -> u64 {
    if enabled {
        u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
    } else {
        0
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
    use std::os::unix::fs::PermissionsExt;
    use tracejit_effects::{FileRead, FileWrite};

    #[test]
    fn unsupported_platform_explains_why_reuse_is_unavailable() {
        let report = doctor();
        if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
            assert!(report.supported);
        } else {
            assert!(!report.supported);
            assert!(!report.ptrace);
            let text = report.problems.join("\n");
            assert!(text.contains("Linux x86_64"));
            assert!(text.contains(&report.os));
            assert!(text.contains(&report.arch));
        }
    }

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

    #[test]
    fn stat_start_ticks_skip_spaces_inside_comm() {
        let stat = "12 (trace jit) S 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 424242 0";
        assert_eq!(start_ticks_from_stat(stat), Some(424242));
    }

    #[test]
    fn simplified_admission_declines_cheap_and_frequently_invalidating_identities() {
        let cheap = AdmissionCost {
            direct_ns: 2_000_000,
            hit_ns: 1_000_000,
            cold_ns: 3_000_000,
            hits: 0,
            skips: 0,
            deopts: 0,
            updated_ms: 0,
        };
        assert!(!admission_is_worth_tracing(&cheap));

        let expensive = AdmissionCost {
            direct_ns: 300_000_000,
            hit_ns: 6_000_000,
            cold_ns: 312_000_000,
            hits: 0,
            skips: 0,
            deopts: 0,
            updated_ms: 0,
        };
        assert!(admission_is_worth_tracing(&expensive));

        let invalidating = AdmissionCost {
            direct_ns: 300_000_000,
            hit_ns: 6_000_000,
            cold_ns: 312_000_000,
            hits: 0,
            skips: 0,
            deopts: 100,
            updated_ms: 0,
        };
        assert!(!admission_is_worth_tracing(&invalidating));

        let stable = AdmissionCost {
            direct_ns: 300_000_000,
            hit_ns: 6_000_000,
            cold_ns: 312_000_000,
            hits: 20,
            skips: 0,
            deopts: 0,
            updated_ms: 0,
        };
        assert!(admission_is_worth_tracing(&stable));

        // One invalidation after a single hit is still allowed: the next run can recover it. Two
        // invalidations against one hit are not, which stops the edit-every-run loop.
        let balanced = AdmissionCost {
            hits: 1,
            deopts: 1,
            ..stable
        };
        assert!(admission_is_worth_tracing(&balanced));
        let losing = AdmissionCost {
            hits: 1,
            deopts: 2,
            ..stable
        };
        assert!(!admission_is_worth_tracing(&losing));
    }

    fn cache_status_scratch() -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "tracejit-cache-status-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir(&path).expect("scratch directory");
        path
    }

    #[test]
    fn missing_cache_directory_is_creatable_when_an_ancestor_is_writable() {
        let root = cache_status_scratch();
        let cache = root.join("missing").join("tracejit");
        assert_eq!(cache_path_state(&cache), CachePathState::Creatable);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn existing_cache_directory_is_writable_without_being_created() {
        let root = cache_status_scratch();
        let cache = root.join("tracejit");
        std::fs::create_dir(&cache).unwrap();
        assert_eq!(cache_path_state(&cache), CachePathState::Writable);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn cache_path_fails_closed_when_it_cannot_be_created() {
        let root = cache_status_scratch();
        let blocked = root.join("blocked");
        std::fs::write(&blocked, b"not a directory").unwrap();
        assert_eq!(
            cache_path_state(&blocked.join("tracejit")),
            CachePathState::Unwritable
        );

        let sealed = root.join("sealed");
        std::fs::create_dir(&sealed).unwrap();
        let original_mode = std::fs::metadata(&sealed).unwrap().permissions().mode();
        let mut sealed_permissions = std::fs::metadata(&sealed).unwrap().permissions();
        sealed_permissions.set_mode(0o555);
        std::fs::set_permissions(&sealed, sealed_permissions).unwrap();
        let sealed_state = cache_path_state(&sealed.join("tracejit"));
        let mut restore = std::fs::metadata(&sealed).unwrap().permissions();
        restore.set_mode(original_mode);
        std::fs::set_permissions(&sealed, restore).unwrap();
        assert_eq!(sealed_state, CachePathState::Unwritable);
        let _ = std::fs::remove_dir_all(root);
    }
}

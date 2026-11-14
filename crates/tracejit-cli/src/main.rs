use anyhow::{Context, Result};
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde_json::json;
use std::ffi::OsString;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Instant;
use tracejit_cache::{Cache, CacheDecision, OutputArtifact, OutputKind};
use tracejit_core::{
    analyze, certificate_from_record, compare_policies, doctor, explain, held_out_matrix,
    parse_certificate, phase_timing_enabled, prefer_simpler, process_startup_ns, run,
    seal_certificate, verify_certificate, Admission, Contract, PhaseTimings, RunKind, RunOptions,
    RunReport,
};
use tracejit_effects::{
    attach_retest, refine, reject_if_unsafe_model, CounterexampleInput, DeploymentStatus, Effect,
    InputDependency, RetestResult,
};
use tracejit_guards::{Guard, GuardMode};

#[derive(Parser)]
#[command(
    name = "tracejit",
    version,
    about = "Guarded computation reuse for Linux"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Run(RunArgs),
    Analyze(AnalyzeArgs),
    Explain(ExplainArgs),
    Doctor(DoctorArgs),
    Cache(CacheArgs),
    /// Issue a reuse certificate for a stored execution (structural evidence only).
    Certify(CertifyArgs),
    /// Independently verify a reuse certificate JSON file.
    VerifyCertificate(VerifyCertificateArgs),
    /// Offline comparison of cost-sensitive admission policies on a held-out matrix.
    AdmissionEval(AdmissionEvalArgs),
    /// Offline CEGAR refinement from a counterexample JSON file (never auto-deploys).
    Refine(RefineArgs),
}

#[derive(Args)]
struct RunArgs {
    #[arg(long)]
    enforce: bool,
    #[arg(long, value_enum, default_value_t = GuardModeArg::Strict)]
    guard_mode: GuardModeArg,
    /// Controlled, reproducible execution contract.
    ///
    /// The contract deliberately fixes selected environmental nondeterminism. Its results are
    /// reproducible under that contract; they are not claimed to be equivalent to arbitrary
    /// native execution, and records from different contracts are never mixed.
    #[arg(long, value_enum)]
    contract: Option<ContractArg>,
    /// Cache admission policy.
    ///
    /// `auto` measures the command's direct runtime before paying for a trace, so commands too
    /// short to repay a cache hit are run directly and never traced.
    #[arg(long, value_enum, default_value_t = AdmissionArg::Always)]
    admission: AdmissionArg,
    #[arg(long)]
    verbose: bool,
    #[arg(long)]
    json: bool,
    #[arg(last = true, required = true, num_args = 1..)]
    command: Vec<OsString>,
}

#[derive(Args)]
struct AnalyzeArgs {
    #[arg(long)]
    verbose: bool,
    #[arg(long)]
    json: bool,
    #[arg(last = true, required = true, num_args = 1..)]
    command: Vec<OsString>,
}

#[derive(Args)]
struct ExplainArgs {
    execution_id: Option<String>,
    #[arg(long)]
    json: bool,
}

#[derive(Args)]
struct DoctorArgs {
    #[arg(long)]
    json: bool,
}

#[derive(Args)]
struct CacheArgs {
    #[command(subcommand)]
    command: CacheCommand,
}

#[derive(Args)]
struct CertifyArgs {
    execution_id: Option<String>,
    #[arg(long)]
    json: bool,
    /// Write the sealed certificate to this path.
    #[arg(long)]
    output: Option<PathBuf>,
}

#[derive(Args)]
struct VerifyCertificateArgs {
    /// Path to a reuse certificate JSON file.
    path: PathBuf,
    #[arg(long)]
    json: bool,
}

#[derive(Args)]
struct AdmissionEvalArgs {
    #[arg(long)]
    json: bool,
}

#[derive(Args)]
struct RefineArgs {
    /// Path to a CounterexampleInput JSON file.
    #[arg(long)]
    input: PathBuf,
    /// Optional offline retest notes; presence with --retest-pass upgrades deployment status
    /// to VerifiedOfflineNotDeployed (still not product deployment).
    #[arg(long)]
    retest_notes: Option<String>,
    #[arg(long, default_value_t = false)]
    retest_pass: bool,
    #[arg(long)]
    json: bool,
}

#[derive(Subcommand)]
enum CacheCommand {
    Stats,
    Clear,
}

#[derive(Clone, Copy, ValueEnum)]
enum GuardModeArg {
    Strict,
    Fast,
}

impl From<GuardModeArg> for GuardMode {
    fn from(value: GuardModeArg) -> Self {
        match value {
            GuardModeArg::Strict => Self::Strict,
            GuardModeArg::Fast => Self::Fast,
        }
    }
}

#[derive(Clone, Copy, ValueEnum)]
enum AdmissionArg {
    /// Trace and cache every invocation.
    Always,
    /// Measure first, then trace when the estimated cumulative benefit exceeds the trace premium.
    Auto,
    /// Phase 2H's threshold policy, kept for before/after comparison.
    #[value(name = "auto-v1")]
    AutoV1,
    /// Never trace or reuse; always run the command directly.
    Never,
}

impl From<AdmissionArg> for Admission {
    fn from(value: AdmissionArg) -> Self {
        match value {
            AdmissionArg::Always => Self::Always,
            AdmissionArg::Auto => Self::Auto,
            AdmissionArg::AutoV1 => Self::AutoLegacy,
            AdmissionArg::Never => Self::Never,
        }
    }
}

#[derive(Clone, Copy, ValueEnum)]
enum ContractArg {
    /// Fix the runtime's internal allocator entropy probe.
    AllocatorEntropyV1,
    /// Fix the audited GCC 13.3.0 toolchain's incidental runtime observations.
    CompilerRuntimeV1,
}

impl From<ContractArg> for Contract {
    fn from(value: ContractArg) -> Self {
        match value {
            ContractArg::AllocatorEntropyV1 => Self::AllocatorEntropyV1,
            ContractArg::CompilerRuntimeV1 => Self::CompilerRuntimeV1,
        }
    }
}

fn main() -> ExitCode {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_writer(io::stderr)
        .try_init()
        .ok();
    let process_startup_ns = process_startup_ns();
    let parse_started = Instant::now();
    let cli = Cli::parse();
    let cli_parse_ns = u64::try_from(parse_started.elapsed().as_nanos()).unwrap_or(u64::MAX);
    match run_cli(cli, process_startup_ns, cli_parse_ns) {
        Ok(code) => ExitCode::from(code.clamp(0, 255) as u8),
        Err(error) => {
            eprintln!("tracejit: {error:#}");
            ExitCode::FAILURE
        }
    }
}

fn run_cli(cli: Cli, process_startup_ns: u64, cli_parse_ns: u64) -> Result<i32> {
    match cli.command {
        Command::Run(args) => {
            let mut report = run(RunOptions {
                command: args.command,
                guard_mode: args.guard_mode.into(),
                enforce: args.enforce,
                cache_root: Cache::default_root(),
                contract: args.contract.map(Into::into),
                admission: args.admission.into(),
            })?;
            let present_started = Instant::now();
            present_report(&report, args.json, args.verbose)?;
            if let Some(phases) = report.phases.as_mut() {
                phases.process_startup_ns = process_startup_ns;
                phases.cli_parse_ns = cli_parse_ns;
                phases.present_ns =
                    u64::try_from(present_started.elapsed().as_nanos()).unwrap_or(u64::MAX);
                write_phase_file(phases)?;
            }
            Ok(report.exit_code)
        }
        Command::Analyze(args) => {
            let report = analyze(args.command)?;
            present_report(&report, args.json, args.verbose)?;
            Ok(report.exit_code)
        }
        Command::Explain(args) => {
            let record = explain(Cache::default_root(), args.execution_id.as_deref())?
                .context("no recorded execution found")?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&record)?);
            } else {
                println!("TraceJIT explanation\n");
                println!("execution      {}", record.id);
                println!("command        {}", display_command(&record.command));
                println!("classification {}", record.classification);
                println!("cache decision {:?}", record.last_decision.decision);
                println!("reason         {}", record.last_decision.reason);
                println!("effects        {}", record.effects.len());
                println!("guards         {}", record.guards.len());
                println!(
                    "inputs         {}",
                    record.identity.input_dependencies.len()
                );
                println!("outputs        {}", record.outputs.len());
                if let Some(failure) = &record.last_decision.guard_failure {
                    println!("deopt          {}", failure.reason);
                    println!("expected       {}", failure.expected);
                    println!("actual         {}", failure.actual);
                }
                if !record.classification_reasons.is_empty() {
                    println!("details");
                    for reason in &record.classification_reasons {
                        println!("  - {reason}");
                    }
                }
                print_dependency_summary(&record);
                println!("effect detail");
                for effect in &record.effects {
                    println!(
                        "  {} pid {} {:?}",
                        effect.sequence, effect.pid, effect.effect
                    );
                }
                println!("guard detail");
                for guard in &record.guards {
                    println!("  {guard:?}");
                }
                println!("input hashes");
                for dependency in &record.identity.input_dependencies {
                    println!("  {dependency:?}");
                }
                println!("output hashes");
                for output in &record.outputs {
                    println!("  {output:?}");
                }
            }
            Ok(0)
        }
        Command::Doctor(args) => {
            let report = doctor();
            if args.json {
                println!("{}", serde_json::to_string_pretty(&report)?);
            } else {
                println!("os             {}", report.os);
                println!("arch           {}", report.arch);
                println!("supported      {}", yes_no(report.supported));
                println!("ptrace         {}", yes_no(report.ptrace));
                println!("seccomp        {}", yes_no(report.seccomp));
                println!("landlock       {}", landlock_status(report.landlock_abi));
                println!("proven         {}", yes_no(report.proven));
                let cache_state = if report.cache_writable {
                    "writable"
                } else if report.cache_creatable {
                    "not created yet; TraceJIT can create it"
                } else {
                    "not writable"
                };
                println!(
                    "cache          {} ({cache_state})",
                    report.cache_path.display()
                );
                for problem in &report.problems {
                    println!("problem        {problem}");
                }
            }
            Ok(if report.supported && report.ptrace {
                0
            } else {
                1
            })
        }
        Command::Cache(args) => match args.command {
            CacheCommand::Stats => {
                let cache = Cache::open(Cache::default_root())?;
                let stats = cache.stats()?;
                println!("executions   {}", stats.executions);
                println!("objects      {}", stats.objects);
                println!("object bytes {}", stats.object_bytes);
                Ok(0)
            }
            CacheCommand::Clear => {
                let root = Cache::default_root();
                Cache::open(&root)?.clear()?;
                println!("cleared {}", root.display());
                Ok(0)
            }
        },
        Command::Certify(args) => {
            let record = explain(Cache::default_root(), args.execution_id.as_deref())?
                .context("no recorded execution found")?;
            // Stored records do not retain the live GuardReport from the hit. For a Reused
            // decision we synthesize an all-passed report from the recorded guard list so the
            // certificate remains checkable; verify-certificate still only checks structure.
            let issued = if record.last_decision.decision == CacheDecision::Reused {
                let report = tracejit_guards::GuardReport {
                    checked: record.guards.len(),
                    passed: record.guards.len(),
                    failure: None,
                };
                tracejit_core::issue_certificate(
                    &record,
                    Some(&report),
                    CacheDecision::Reused,
                    record.last_decision.reason.clone(),
                )?
            } else {
                certificate_from_record(&record)?
            };
            let sealed = seal_certificate(issued).map_err(anyhow::Error::msg)?;
            if let Some(path) = &args.output {
                std::fs::write(path, serde_json::to_vec_pretty(&sealed)?)?;
            }
            if args.json {
                println!("{}", serde_json::to_string_pretty(&sealed)?);
            } else {
                println!("schema         {}", sealed.schema);
                println!("claim          {:?}", sealed.claim_strength);
                println!("execution      {}", sealed.execution_id);
                println!("classification {}", sealed.classification);
                println!("decision       {:?}", sealed.decision);
                println!("guards         {}", sealed.guards.len());
                println!("cas objects    {}", sealed.cas_objects.len());
                println!("limitations");
                for note in &sealed.limitations.notes {
                    println!("  - {note}");
                }
            }
            Ok(0)
        }
        Command::VerifyCertificate(args) => {
            let bytes = std::fs::read(&args.path)
                .with_context(|| format!("could not read {}", args.path.display()))?;
            let certificate = parse_certificate(&bytes)?;
            let report = verify_certificate(&certificate);
            if args.json {
                println!("{}", serde_json::to_string_pretty(&report)?);
            } else {
                println!("ok             {}", report.ok);
                println!("claim          {:?}", report.claim_strength);
                for item in &report.checked {
                    println!("checked        {item}");
                }
                for item in &report.rejected {
                    println!("rejected       {item}");
                }
            }
            Ok(if report.ok { 0 } else { 1 })
        }
        Command::AdmissionEval(args) => {
            let outcomes = compare_policies(&held_out_matrix());
            let best = prefer_simpler(&outcomes).context("no policies compared")?;
            if args.json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&json!({
                        "outcomes": outcomes,
                        "preferred": best,
                    }))?
                );
            } else {
                for outcome in &outcomes {
                    println!(
                        "policy {:>16} total_ns={} oracle_ns={} regret_ns={} traces={} hits={} directs={}",
                        outcome.policy,
                        outcome.total_ns,
                        outcome.oracle_ns,
                        outcome.regret_ns,
                        outcome.traces,
                        outcome.hits,
                        outcome.directs
                    );
                }
                println!(
                    "RESULT phase-e-admission preferred={} regret_ns={}",
                    best.policy, best.regret_ns
                );
            }
            Ok(0)
        }
        Command::Refine(args) => {
            let bytes = std::fs::read(&args.input)
                .with_context(|| format!("could not read {}", args.input.display()))?;
            let input: CounterexampleInput = serde_json::from_slice(&bytes)
                .context("counterexample JSON must match CounterexampleInput")?;
            let mut proposal = reject_if_unsafe_model(refine(&input));
            if args.retest_pass || args.retest_notes.is_some() {
                proposal = attach_retest(
                    proposal,
                    &RetestResult {
                        passed: args.retest_pass,
                        notes: args
                            .retest_notes
                            .clone()
                            .unwrap_or_else(|| "cli retest flag".into()),
                    },
                );
            }
            if args.json {
                println!("{}", serde_json::to_string_pretty(&proposal)?);
            } else {
                println!("TraceJIT refine (offline; never auto-deploys)\n");
                println!("title          {}", proposal.title);
                println!("hole           {:?}", proposal.hole);
                println!("safety_ok      {}", proposal.safety_ok);
                println!("deployment     {:?}", proposal.deployment);
                if let Some(hint) = &proposal.registry_hint {
                    println!("registry       {hint}");
                }
                println!("action         {:?}", proposal.action);
                println!("essential steps");
                for step in &proposal.minimized.essential_steps {
                    println!("  - {step}");
                }
                println!(
                    "RESULT phase-k5-cegar hole={:?} deployment={:?} safety_ok={}",
                    proposal.hole, proposal.deployment, proposal.safety_ok
                );
            }
            Ok(match proposal.deployment {
                DeploymentStatus::RejectedUnsafe => 2,
                _ => 0,
            })
        }
    }
}

fn write_phase_file(phases: &PhaseTimings) -> Result<()> {
    if !phase_timing_enabled() {
        return Ok(());
    }
    let Some(path) = std::env::var_os("TRACEJIT_PHASE_TIMING_PATH") else {
        return Ok(());
    };
    let bytes = serde_json::to_vec(phases).context("could not encode phase timings")?;
    std::fs::write(&path, bytes).with_context(|| {
        format!(
            "could not write phase timings to {}",
            path.to_string_lossy()
        )
    })?;
    Ok(())
}

fn present_report(report: &RunReport, json_output: bool, verbose: bool) -> Result<()> {
    if json_output {
        // A guard failure can embed a `FileFingerprint::absent()` sentinel, whose `i128::MIN`
        // timestamp is outside JSON's number range. Reporting must never panic, so such a
        // report degrades that one field to text rather than aborting the command.
        let guards = serde_json::to_value(&report.guards)
            .unwrap_or_else(|_| serde_json::Value::String(format!("{:?}", report.guards)));
        let value = json!({
            "execution_id": report.execution_id,
            "kind": report.kind,
            "cache_decision": report.cache_decision,
            "decision_reason": report.decision_reason,
            "classification": report.classification,
            "eligible_for_reuse": report.eligible_for_reuse,
            "runtime_ns": report.runtime_ns,
            "baseline_runtime_ns": report.baseline_runtime_ns,
            "process_count": report.process_count,
            "effect_counts": report.effect_counts,
            "irreversible_effect_count": report.irreversible_effect_count,
            "dependency_count": report.dependency_count,
            "output_count": report.output_count,
            "guards": guards,
            "reasons": report.reasons,
            "contract": report.contract,
            "stdout_bytes": report.stdout,
            "stderr_bytes": report.stderr,
            "exit_code": report.exit_code,
        });
        // Compact JSON. The pretty printer spends most of its time re-indenting the captured
        // stdout and stderr byte arrays, which dominates a large `--json` hit, and this output is
        // machine-readable by contract. Keys and values are unchanged.
        println!("{}", serde_json::to_string(&value)?);
        return Ok(());
    }

    io::stdout().write_all(&report.stdout)?;
    io::stdout().flush()?;
    io::stderr().write_all(&report.stderr)?;
    io::stderr().flush()?;
    // The report is assembled once and written with a single call. Unbuffered `eprintln!` per
    // field costs a syscall per line on the warm path, which is a measurable share of a hit.
    let mut text = String::with_capacity(512);
    {
        use std::fmt::Write as _;
        let _ = writeln!(text, "\nTraceJIT\n");
        if let Some(contract) = &report.contract {
            let _ = writeln!(text, "contract       {contract}");
        }
        match report.kind {
            RunKind::Executed => {
                if let Some(decision) = &report.cache_decision {
                    match decision {
                        CacheDecision::Deoptimized => {
                            let _ = writeln!(text, "cache          DEOPT");
                        }
                        CacheDecision::Executed | CacheDecision::Ineligible => {
                            let _ = writeln!(text, "cache          MISS");
                        }
                        CacheDecision::Skipped => {
                            let _ = writeln!(text, "cache          SKIP (admission policy)");
                        }
                        CacheDecision::Reused => {}
                    }
                }
                let _ = writeln!(text, "classified     {}", report.classification);
                let _ = writeln!(text, "dependencies   {}", report.dependency_count);
                let _ = writeln!(text, "outputs        {}", report.output_count);
                let _ = writeln!(text, "unknown        {}", report.effect_counts.unknown);
                if report.cache_decision.is_none() {
                    let total_effects = report.effect_counts.reads
                        + report.effect_counts.writes
                        + report.effect_counts.controls
                        + report.effect_counts.unknown;
                    let _ = writeln!(text, "processes      {}", report.process_count);
                    let _ = writeln!(text, "effects        {total_effects}");
                    let _ = writeln!(text, "irreversible   {}", report.irreversible_effect_count);
                }
                let _ = writeln!(
                    text,
                    "runtime        {}",
                    format_duration(report.runtime_ns)
                );
                if report.eligible_for_reuse {
                    let _ = writeln!(text, "\nnext run is eligible for guarded reuse");
                } else if report.reasons.is_empty() {
                    let _ = writeln!(text, "\nreuse disabled");
                } else {
                    let _ = writeln!(text);
                    for reason in &report.reasons {
                        let _ = writeln!(text, "reuse disabled: {reason}");
                    }
                }
            }
            RunKind::Reused => {
                if let Some(guards) = &report.guards {
                    let _ = writeln!(
                        text,
                        "guards         {}/{} passed",
                        guards.passed, guards.checked
                    );
                }
                let _ = writeln!(text, "cache          HIT");
                let _ = writeln!(
                    text,
                    "runtime        {}",
                    format_duration(report.runtime_ns)
                );
                let saved = report.baseline_runtime_ns.saturating_sub(report.runtime_ns);
                let _ = writeln!(text, "saved          {}", format_duration(saved));
                if report.runtime_ns > 0 {
                    let speedup = report.baseline_runtime_ns as f64 / report.runtime_ns as f64;
                    let _ = writeln!(text, "speedup        {speedup:.1}x");
                }
            }
        }
        if verbose {
            let _ = writeln!(text, "execution      {}", report.execution_id);
            let _ = writeln!(text, "processes      {}", report.process_count);
            let _ = writeln!(
                text,
                "effects        {} read, {} write, {} control, {} unknown",
                report.effect_counts.reads,
                report.effect_counts.writes,
                report.effect_counts.controls,
                report.effect_counts.unknown
            );
            if report.eligible_for_reuse {
                for reason in &report.reasons {
                    let _ = writeln!(text, "reason         {reason}");
                }
            }
        }
    }
    io::stderr().write_all(text.as_bytes())?;
    io::stderr().flush()?;
    Ok(())
}

fn print_dependency_summary(record: &tracejit_cache::StoredExecution) {
    println!(
        "cache key      argv, cwd, executable hash, runtime identity, and all {} inherited environment entries",
        record.identity.environment.len()
    );
    println!("observed inputs");
    if record.identity.input_dependencies.is_empty() {
        println!("  (none recorded)");
    }
    for dependency in &record.identity.input_dependencies {
        println!("  {}", input_dependency_line(dependency));
    }
    println!("outputs");
    if record.outputs.is_empty() {
        println!("  (none recorded)");
    }
    for output in &record.outputs {
        println!("  {}", output_line(output));
    }
    let unknown = record
        .effects
        .iter()
        .filter(|effect| matches!(effect.effect, Effect::Unknown(_)))
        .count();
    if unknown > 0 {
        println!("unknown        {unknown} unmodeled effects; reuse stays disabled");
    }
    println!("guards");
    let mut printed = 0;
    for guard in &record.guards {
        if matches!(guard, Guard::NoUnexpectedEffects) {
            continue;
        }
        println!("  {}", guard_line(guard));
        printed += 1;
    }
    if printed == 0 {
        println!("  (none recorded)");
    }
}

fn input_dependency_line(dependency: &InputDependency) -> String {
    match dependency {
        InputDependency::File { path, .. } => format!("READ  {}", path.display()),
        InputDependency::Executable { path, .. } => format!("EXEC  {}", path.display()),
        InputDependency::Metadata { path, .. } => format!("META  {}", path.display()),
        InputDependency::DirectoryOpened { path, .. } => format!("DIROP {}", path.display()),
        InputDependency::OutputPrestate { path, .. } => format!("OUTPRE {}", path.display()),
        InputDependency::DirectoryEnumerated { path, requests, .. } => {
            format!("DIRLIST {} ({} calls)", path.display(), requests.len())
        }
        InputDependency::FilesystemStats { path, .. } => {
            format!("FSSTAT {}", path.display())
        }
        InputDependency::InheritedStream {
            path,
            start_offset,
            end_offset,
            ..
        } => format!(
            "STDIN {} [{}..{}]",
            path.display(),
            start_offset,
            end_offset
        ),
        InputDependency::SymlinkMetadata { path, .. } => format!("LSTAT {}", path.display()),
        InputDependency::Symlink { path, target } => {
            let shown = target
                .as_ref()
                .map(|value| value.display().to_string())
                .unwrap_or_else(|| "(absent)".into());
            format!("LINK  {} -> {shown}", path.display())
        }
        InputDependency::Access { path, mode, .. } => {
            format!("ACCESS {} (mode {mode:#x})", path.display())
        }
        InputDependency::ControlledEntropy { library, .. } => {
            format!("ENTROPY {}", library.display())
        }
        InputDependency::ControlledRuntime { executable, .. } => {
            format!("RUNTIME {}", executable.display())
        }
    }
}

fn output_line(output: &OutputArtifact) -> String {
    let kind = match output.kind {
        OutputKind::File => "WRITE",
        OutputKind::Deleted => "DELETE",
    };
    format!("{kind} {}", output.path.display())
}

fn guard_line(guard: &Guard) -> String {
    match guard {
        Guard::ExecutableHash { path, .. } => format!("executable content {}", path.display()),
        Guard::FileHash { path, .. } => format!("file content {}", path.display()),
        Guard::FileMetadata { path, .. } => format!("file metadata {}", path.display()),
        Guard::DirectoryOpened { path, .. } => format!("directory open {}", path.display()),
        Guard::OutputPrestate { path, .. } => {
            format!("output pre-state {}", path.display())
        }
        Guard::DirectoryEnumerated { path, requests, .. } => format!(
            "directory entry stream {} ({} calls)",
            path.display(),
            requests.len()
        ),
        Guard::FilesystemStats { path, .. } => {
            format!("filesystem statistics {}", path.display())
        }
        Guard::InheritedStream {
            path,
            start_offset,
            end_offset,
            ..
        } => format!(
            "inherited stdin {} [{}..{}]",
            path.display(),
            start_offset,
            end_offset
        ),
        Guard::SymlinkTarget { path, .. } => format!("symlink target {}", path.display()),
        Guard::ControlledRuntime { executable, .. } => {
            format!("compiler runtime observation {}", executable.display())
        }
        Guard::SymlinkMetadata { path, .. } => format!("symlink metadata {}", path.display()),
        Guard::AccessCheck { path, mode, .. } => {
            format!("access check {} (mode {mode:#x})", path.display())
        }
        Guard::ControlledEntropy { library, .. } => {
            format!("controlled allocator entropy {}", library.display())
        }
        Guard::EnvironmentValue { key, .. } => {
            format!("environment key {}", key.to_string_lossy())
        }
        Guard::WorkingDirectory { expected } => {
            format!("working directory {}", expected.display())
        }
        Guard::RuntimeIdentity { .. } => "runtime identity".into(),
        Guard::NoUnexpectedEffects => {
            "marker only; classification rejects unmodeled effects before reuse".into()
        }
    }
}

fn display_command(command: &[OsString]) -> String {
    command
        .iter()
        .map(|value| value.to_string_lossy())
        .collect::<Vec<_>>()
        .join(" ")
}

fn yes_no(value: bool) -> &'static str {
    if value {
        "yes"
    } else {
        "no"
    }
}

fn landlock_status(abi: Option<i32>) -> String {
    match abi {
        Some(version) => format!("abi {version}"),
        None => "no".into(),
    }
}

fn format_duration(ns: u128) -> String {
    if ns >= 1_000_000_000 {
        format!("{:.2}s", ns as f64 / 1_000_000_000.0)
    } else if ns >= 1_000_000 {
        format!("{:.2}ms", ns as f64 / 1_000_000.0)
    } else if ns >= 1_000 {
        format!("{:.2}us", ns as f64 / 1_000.0)
    } else {
        format!("{ns}ns")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duration_format_uses_measured_value() {
        assert_eq!(format_duration(1_500_000), "1.50ms");
    }

    #[test]
    fn command_requires_separator_and_program() {
        assert!(Cli::try_parse_from(["tracejit", "run", "--", "echo"]).is_ok());
        assert!(Cli::try_parse_from(["tracejit", "run"]).is_err());
    }

    #[test]
    fn version_flag_is_available() {
        match Cli::try_parse_from(["tracejit", "--version"]) {
            Err(error) => assert_eq!(error.kind(), clap::error::ErrorKind::DisplayVersion),
            Ok(_) => panic!("--version should display the version"),
        }
    }

    #[test]
    fn doctor_command_parses() {
        assert!(Cli::try_parse_from(["tracejit", "doctor"]).is_ok());
        assert!(Cli::try_parse_from(["tracejit", "doctor", "--json"]).is_ok());
    }

    #[test]
    fn dependency_summary_names_effects_without_environment_values() {
        use std::path::PathBuf;
        use tracejit_effects::Hash;

        assert_eq!(
            input_dependency_line(&InputDependency::File {
                path: PathBuf::from("input.dat"),
                expected_hash: Hash::new([0; 32]),
                fingerprint: None,
            }),
            "READ  input.dat"
        );
        assert_eq!(
            guard_line(&Guard::EnvironmentValue {
                key: OsString::from("MODE"),
                expected: Some(OsString::from("secret-value")),
            }),
            "environment key MODE"
        );
        assert_eq!(
            output_line(&OutputArtifact {
                path: PathBuf::from("output.bin"),
                kind: OutputKind::File,
                content: None,
                unix_mode: None,
                unix_uid: None,
                unix_gid: None,
                unix_accessed_ns: None,
                unix_modified_ns: None,
                artifact_version: tracejit_cache::OUTPUT_ARTIFACT_VERSION,
                allows_create: true,
            }),
            "WRITE output.bin"
        );
    }
}

use anyhow::{Context, Result};
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde_json::json;
use std::ffi::OsString;
use std::io::{self, Write};
use std::process::ExitCode;
use std::time::Instant;
use tracejit_cache::{Cache, CacheDecision, OutputArtifact, OutputKind};
use tracejit_core::{
    analyze, doctor, explain, phase_timing_enabled, process_startup_ns, run, PhaseTimings, RunKind,
    RunOptions, RunReport,
};
use tracejit_effects::{Effect, InputDependency};
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
}

#[derive(Args)]
struct RunArgs {
    #[arg(long)]
    enforce: bool,
    #[arg(long, value_enum, default_value_t = GuardModeArg::Strict)]
    guard_mode: GuardModeArg,
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
            "guards": report.guards,
            "reasons": report.reasons,
            "stdout_bytes": report.stdout,
            "stderr_bytes": report.stderr,
            "exit_code": report.exit_code,
        });
        println!("{}", serde_json::to_string_pretty(&value)?);
        return Ok(());
    }

    io::stdout().write_all(&report.stdout)?;
    io::stdout().flush()?;
    io::stderr().write_all(&report.stderr)?;
    io::stderr().flush()?;
    eprintln!("\nTraceJIT\n");
    match report.kind {
        RunKind::Executed => {
            if let Some(decision) = &report.cache_decision {
                match decision {
                    CacheDecision::Deoptimized => eprintln!("cache          DEOPT"),
                    CacheDecision::Executed | CacheDecision::Ineligible => {
                        eprintln!("cache          MISS")
                    }
                    CacheDecision::Reused => {}
                }
            }
            eprintln!("classified     {}", report.classification);
            eprintln!("dependencies   {}", report.dependency_count);
            eprintln!("outputs        {}", report.output_count);
            eprintln!("unknown        {}", report.effect_counts.unknown);
            if report.cache_decision.is_none() {
                let total_effects = report.effect_counts.reads
                    + report.effect_counts.writes
                    + report.effect_counts.controls
                    + report.effect_counts.unknown;
                eprintln!("processes      {}", report.process_count);
                eprintln!("effects        {total_effects}");
                eprintln!("irreversible   {}", report.irreversible_effect_count);
            }
            eprintln!("runtime        {}", format_duration(report.runtime_ns));
            if report.eligible_for_reuse {
                eprintln!("\nnext run is eligible for guarded reuse");
            } else if report.reasons.is_empty() {
                eprintln!("\nreuse disabled");
            } else {
                eprintln!();
                for reason in &report.reasons {
                    eprintln!("reuse disabled: {reason}");
                }
            }
        }
        RunKind::Reused => {
            if let Some(guards) = &report.guards {
                eprintln!("guards         {}/{} passed", guards.passed, guards.checked);
            }
            eprintln!("cache          HIT");
            eprintln!("runtime        {}", format_duration(report.runtime_ns));
            let saved = report.baseline_runtime_ns.saturating_sub(report.runtime_ns);
            eprintln!("saved          {}", format_duration(saved));
            if report.runtime_ns > 0 {
                let speedup = report.baseline_runtime_ns as f64 / report.runtime_ns as f64;
                eprintln!("speedup        {speedup:.1}x");
            }
        }
    }
    if verbose {
        eprintln!("execution      {}", report.execution_id);
        eprintln!("processes      {}", report.process_count);
        eprintln!(
            "effects        {} read, {} write, {} control, {} unknown",
            report.effect_counts.reads,
            report.effect_counts.writes,
            report.effect_counts.controls,
            report.effect_counts.unknown
        );
        if report.eligible_for_reuse {
            for reason in &report.reasons {
                eprintln!("reason         {reason}");
            }
        }
    }
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
        InputDependency::SymlinkMetadata { path, .. } => format!("LSTAT {}", path.display()),
        InputDependency::Symlink { path, target } => {
            let shown = target
                .as_ref()
                .map(|value| value.display().to_string())
                .unwrap_or_else(|| "(absent)".into());
            format!("LINK  {} -> {shown}", path.display())
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
        Guard::SymlinkTarget { path, .. } => format!("symlink target {}", path.display()),
        Guard::SymlinkMetadata { path, .. } => format!("symlink metadata {}", path.display()),
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
                allows_create: true,
            }),
            "WRITE output.bin"
        );
    }
}

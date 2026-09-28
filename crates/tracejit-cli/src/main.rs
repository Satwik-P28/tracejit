use anyhow::{Context, Result};
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde_json::json;
use std::ffi::OsString;
use std::io::{self, Write};
use std::process::ExitCode;
use tracejit_cache::Cache;
use tracejit_cache::CacheDecision;
use tracejit_core::{analyze, explain, run, RunKind, RunOptions, RunReport};
use tracejit_guards::GuardMode;

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
    match run_cli() {
        Ok(code) => ExitCode::from(code.clamp(0, 255) as u8),
        Err(error) => {
            eprintln!("tracejit: {error:#}");
            ExitCode::FAILURE
        }
    }
}

fn run_cli() -> Result<i32> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_writer(io::stderr)
        .try_init()
        .ok();
    match Cli::parse().command {
        Command::Run(args) => {
            let report = run(RunOptions {
                command: args.command,
                guard_mode: args.guard_mode.into(),
                enforce: args.enforce,
                cache_root: Cache::default_root(),
            })?;
            present_report(&report, args.json, args.verbose)?;
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
            } else {
                eprintln!("\nreuse disabled");
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
        for reason in &report.reasons {
            eprintln!("reason         {reason}");
        }
    }
    Ok(())
}

fn display_command(command: &[OsString]) -> String {
    command
        .iter()
        .map(|value| value.to_string_lossy())
        .collect::<Vec<_>>()
        .join(" ")
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
}

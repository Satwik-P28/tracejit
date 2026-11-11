#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use serde_json::Value;
use std::fs;
use std::fs::File;
use std::io::{Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

fn tracejit() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_tracejit"))
}

/// Serialises the tests that both compile C and depend on a measured wall-clock threshold.
///
/// `auto_admission_skips_short_commands_and_caches_expensive_ones` decides by timing the direct
/// run; a concurrent compilation can push a short command over its 6 ms threshold and change the
/// decision for reasons that have nothing to do with the policy under test.
static COMPILER_TIMING_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn compile_fixture(directory: &Path) -> PathBuf {
    let source =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/fixture_driver.c");
    let binary = directory.join("fixture-driver");
    let status = Command::new("cc")
        .args(["-O2", "-Wall", "-Wextra", "-Werror"])
        .arg("-pthread")
        .arg(source)
        .arg("-o")
        .arg(&binary)
        .status()
        .expect("C compiler must be available");
    assert!(status.success(), "fixture compilation failed");
    let interpreter = directory.join("fixture-interpreter");
    fs::copy(&binary, &interpreter).unwrap();
    let script = directory.join("fixture-script");
    fs::write(
        &script,
        format!(
            "#!{} script_interpreter\nfixture body\n",
            interpreter.display()
        ),
    )
    .unwrap();
    let mut permissions = fs::metadata(&script).unwrap().permissions();
    std::os::unix::fs::PermissionsExt::set_mode(&mut permissions, 0o700);
    fs::set_permissions(&script, permissions).unwrap();
    binary
}

fn workspace(directory: &Path) {
    fs::write(directory.join("input.txt"), b"input one\n").unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink("input.txt", directory.join("input-link")).unwrap();
}

fn invoke(cache: &Path, args: &[&str], extra_env: Option<(&str, &str)>) -> Output {
    let mut command = Command::new(tracejit());
    command
        .args(args)
        .env("TRACEJIT_CACHE_DIR", cache)
        // glibc seeds tcache with getrandom on first allocation. Disable tcache for these
        // syscall-classification fixtures so only fixture-requested randomness is observed.
        .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0");
    if let Some((key, value)) = extra_env {
        command.env(key, value);
    }
    command.output().unwrap()
}

fn analyze_case(binary: &Path, directory: &Path, case: &str) -> Value {
    let output = invoke(
        &directory.join("cache"),
        &[
            "analyze",
            "--json",
            "--",
            binary.to_str().unwrap(),
            case,
            directory.to_str().unwrap(),
        ],
        None,
    );
    serde_json::from_slice(&output.stdout).unwrap_or_else(|error| {
        panic!(
            "invalid JSON for {case}: {error}; stderr={}",
            String::from_utf8_lossy(&output.stderr)
        )
    })
}

/// A program that stats its own output path must not reuse across a presence change.
///
/// This is the Phase 2O release blocker: the contract dropped output metadata for *any* binary
/// behind the flag, so an un-audited program's "absent" branch was replayed after the path
/// appeared. The observation must stay a real negative dependency unless the observing process is
/// the audited toolchain.
#[test]
fn un_audited_program_does_not_reuse_across_its_output_presence_change() {
    let _serial = COMPILER_TIMING_LOCK.lock().unwrap();
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("presence.c");
    fs::write(
        &source,
        "#include <stdio.h>\n#include <sys/stat.h>\nint main(int argc, char **argv) {\n    struct stat st;\n    int present = stat(argv[1], &st) == 0;\n    FILE *file = fopen(argv[1], \"w\");\n    fputs(present ? \"PRESENT\\n\" : \"ABSENT\\n\", file);\n    fclose(file);\n    return 0;\n}\n",
    )
    .unwrap();
    let binary = temporary.path().join("presence");
    let status = Command::new("cc")
        .arg("-O2")
        .arg(&source)
        .arg("-o")
        .arg(&binary)
        .status()
        .expect("C compiler must be available");
    assert!(status.success(), "probe compilation failed");
    let output = temporary.path().join("out.txt");
    let cache = temporary.path().join("cache");
    let invoke_probe = || {
        invoke(
            &cache,
            &[
                "run",
                "--contract",
                "compiler-runtime-v1",
                "--json",
                "--",
                binary.to_str().unwrap(),
                output.to_str().unwrap(),
            ],
            None,
        )
    };
    let first = invoke_probe();
    assert!(first.status.success(), "first trace failed");
    assert_eq!(fs::read_to_string(&output).unwrap(), "ABSENT\n");
    let second = invoke_probe();
    assert!(second.status.success(), "second run failed");
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_ne!(
        report["kind"], "Reused",
        "un-audited output stat was replayed across a presence change: {report}"
    );
    assert_eq!(
        fs::read_to_string(&output).unwrap(),
        "PRESENT\n",
        "the second run must observe the file it created"
    );
}

/// A reused compilation must leave the same filesystem effects as a native one.
///
/// The compiler replaces its output directory entry rather than truncating an existing inode, so a
/// pre-existing file's bytes, mode, hard links and extended attributes must not survive a native
/// run. Reuse is only sound if restoration reproduces that outcome, which is measured here against
/// a direct GCC run with identical pre-state.
#[test]
fn output_prestate_reuse_matches_native_filesystem_effects() {
    let _serial = COMPILER_TIMING_LOCK.lock().unwrap();
    use std::os::unix::fs::PermissionsExt;
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("effect.c");
    fs::write(&source, "int effect(int x) { return x * 3 + 1; }\n").unwrap();
    let cache = temporary.path().join("cache");
    let output = temporary.path().join("effect.o");
    let other = temporary.path().join("other.bin");
    let args = [
        "run",
        "--contract",
        "compiler-runtime-v1",
        "--json",
        "--",
        "gcc",
        "-O2",
        "-c",
        source.to_str().unwrap(),
        "-o",
        output.to_str().unwrap(),
    ];
    let cold = invoke(&cache, &args, None);
    assert!(
        cold.status.success(),
        "{}",
        String::from_utf8_lossy(&cold.stderr)
    );

    let stage_prestate = || {
        let _ = fs::remove_file(&other);
        fs::write(&output, b"stale object\n").unwrap();
        let mut permissions = fs::metadata(&output).unwrap().permissions();
        permissions.set_mode(0o600);
        fs::set_permissions(&output, permissions).unwrap();
        fs::hard_link(&output, &other).unwrap();
    };
    stage_prestate();
    let warm = invoke(&cache, &args, None);
    let report: Value = serde_json::from_slice(&warm.stdout).unwrap();
    let decision = report["cache_decision"]
        .as_str()
        .unwrap_or("Executed")
        .to_string();
    let reused_bytes = fs::read(&output).unwrap();
    let reused_mode = fs::metadata(&output).unwrap().permissions().mode() & 0o7777;
    let reused_other = fs::read(&other).unwrap();

    stage_prestate();
    let native = Command::new("gcc")
        .args([
            "-O2",
            "-c",
            source.to_str().unwrap(),
            "-o",
            output.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(native.status.success(), "native compilation failed");
    let native_mode = fs::metadata(&output).unwrap().permissions().mode() & 0o7777;
    assert_ne!(
        native_mode, 0o600,
        "native GCC keeps the old mode; the fixture is invalid"
    );
    assert_eq!(
        reused_mode, native_mode,
        "mode differs from native after {decision}"
    );
    assert_eq!(
        reused_other,
        fs::read(&other).unwrap(),
        "hard link differs from native"
    );
    assert_eq!(
        reused_bytes,
        fs::read(&output).unwrap(),
        "bytes differ from native"
    );
    if decision == "Reused" {
        assert_ne!(
            report["classification"], "Ineligible",
            "a replayed run must not be classified ineligible"
        );
    }
}

/// A symlink or directory at the output path is not a writable regular file and must never be
/// replaced by a cached artifact, even when the target is writable.
#[test]
fn output_prestate_refuses_non_file_destinations() {
    let _serial = COMPILER_TIMING_LOCK.lock().unwrap();
    use std::os::unix::fs::PermissionsExt;
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("destination.c");
    fs::write(&source, "int destination(void) { return 9; }\n").unwrap();
    let cache = temporary.path().join("cache");
    let output = temporary.path().join("destination.o");
    let target = temporary.path().join("target.bin");
    fs::write(&target, b"target contents\n").unwrap();
    let args = [
        "run",
        "--contract",
        "compiler-runtime-v1",
        "--json",
        "--",
        "gcc",
        "-O2",
        "-c",
        source.to_str().unwrap(),
        "-o",
        output.to_str().unwrap(),
    ];
    assert!(
        invoke(&cache, &args, None).status.success(),
        "cold trace failed"
    );
    fs::remove_file(&output).unwrap();
    std::os::unix::fs::symlink(&target, &output).unwrap();
    let symlinked = invoke(&cache, &args, None);
    let report: Value = serde_json::from_slice(&symlinked.stdout).unwrap();
    assert_ne!(
        report["kind"], "Reused",
        "a symlink destination was replayed: {report}"
    );
    assert_eq!(fs::read(&target).unwrap(), b"target contents\n");
    // Reuse is refused, so the real compiler ran. GCC replaces the destination entry, so the
    // symlink becomes a regular object file exactly as it does natively; only the target matters.
    assert!(
        fs::symlink_metadata(&output).unwrap().file_type().is_file(),
        "the direct run should have replaced the destination entry"
    );
    fs::remove_file(&output).unwrap();
    fs::create_dir(&output).unwrap();
    let directory = invoke(&cache, &args, None);
    let report: Value = serde_json::from_slice(&directory.stdout).unwrap();
    assert_ne!(
        report["kind"], "Reused",
        "a directory destination was replayed: {report}"
    );
    let mut permissions = fs::metadata(&output).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&output, permissions).unwrap();
}

/// A program that creates two outputs must reuse with the same bytes, mode and times.
///
/// The first output is created with `0666` under `umask(0027)`, written, `ftruncate`d to four
/// bytes and given explicit timestamps; the second is chmodded. `fchmod`, `ftruncate`,
/// `utimensat` and umask-derived creation were all unmodeled, so this exercises the new effects
/// and the artifact metadata replay end to end.
#[test]
fn metadata_preserving_program_reuses_and_replays_mode_and_times() {
    let _serial = COMPILER_TIMING_LOCK.lock().unwrap();
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("metadata.c");
    fs::write(
        &source,
        r#"#include <fcntl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
int main(int argc, char **argv) {
    umask(0027);
    int first = open(argv[1], O_CREAT | O_WRONLY | O_TRUNC, 0666);
    if (first < 0) return 1;
    if (write(first, "payload\n", 8) != 8) return 1;
    if (ftruncate(first, 4) != 0) return 1;
    close(first);
    struct timespec times[2] = {{1000000, 0}, {1000000, 0}};
    if (utimensat(AT_FDCWD, argv[1], times, 0) != 0) return 1;
    if (chmod(argv[1], 0600) != 0) return 1;
    int second = open(argv[2], O_CREAT | O_WRONLY | O_TRUNC, 0666);
    if (second < 0) return 1;
    if (write(second, "second\n", 7) != 7) return 1;
    return close(second);
}
"#,
    )
    .unwrap();
    let binary = temporary.path().join("metadata");
    assert!(
        Command::new("cc")
            .arg("-O2")
            .arg(&source)
            .arg("-o")
            .arg(&binary)
            .status()
            .unwrap()
            .success(),
        "probe compilation failed"
    );
    let first = temporary.path().join("first.bin");
    let second = temporary.path().join("second.bin");
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        first.to_str().unwrap(),
        second.to_str().unwrap(),
    ];
    let cold = invoke(&cache, &args, None);
    assert!(
        cold.status.success(),
        "{}",
        String::from_utf8_lossy(&cold.stderr)
    );
    let warm = invoke(&cache, &args, None);
    let report: Value = serde_json::from_slice(&warm.stdout).unwrap();
    assert_eq!(report["kind"], "Reused", "{report}");
    let first_metadata = fs::metadata(&first).unwrap();
    assert_eq!(
        first_metadata.permissions().mode() & 0o777,
        0o600,
        "{report}"
    );
    assert_eq!(first_metadata.len(), 4, "ftruncate effect must be replayed");
    assert_eq!(
        first_metadata.mtime(),
        1_000_000,
        "replayed mtime must match native"
    );
    assert_eq!(fs::read(&first).unwrap(), b"payl");
    let second_metadata = fs::metadata(&second).unwrap();
    assert_eq!(
        second_metadata.permissions().mode() & 0o777,
        0o640,
        "umask-derived creation mode must be replayed"
    );
    assert_eq!(fs::read(&second).unwrap(), b"second\n");
}

#[test]
fn adversarial_classification_table() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let manifest = fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/cases.json"),
    )
    .unwrap();
    let cases: Value = serde_json::from_str(&manifest).unwrap();
    println!("Case                     Expected         Actual           Safe");
    for entry in cases.as_array().unwrap() {
        let case = entry["case"].as_str().unwrap();
        let expected = entry["expected"].as_str().unwrap();
        let eligible = entry["eligible"].as_bool().unwrap();
        let report = analyze_case(&binary, temporary.path(), case);
        let actual = report["classification"].as_str().unwrap();
        let actual_eligible = report["eligible_for_reuse"].as_bool().unwrap();
        let safe = actual == expected && actual_eligible == eligible;
        println!(
            "{case:24} {expected:16} {actual:16} {}",
            if safe { "yes" } else { "NO" }
        );
        assert!(safe, "classification mismatch for {case}: {report}");
    }
    eprintln!("RESULT classification PASS");
}

fn stdout_bytes_of(report: &Value) -> Vec<u8> {
    report["stdout_bytes"]
        .as_array()
        .expect("stdout_bytes must be an array")
        .iter()
        .map(|byte| byte.as_u64().expect("byte") as u8)
        .collect()
}

/// The first ordinary developer command that TraceJIT can skip: `gzip -c`.
///
/// This is the end-to-end contract in one test. A fresh cache records, the next run must report
/// `Reused` with the exact bytes a direct run produces, a content change must deoptimize and produce
/// the *new* bytes, and the entry must become reusable again afterwards. If `gzip` is absent the
/// test reports SKIP rather than pretending to pass.
#[test]
fn real_gzip_workload_is_reused_and_invalidated() {
    if !Command::new("gzip")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
    {
        eprintln!("RESULT gzip-reuse SKIP");
        return;
    }

    let temporary = tempfile::tempdir().unwrap();
    let cache = temporary.path().join("cache");
    let source = temporary.path().join("data.txt");
    let body = "record-payload\n".repeat(4096);
    fs::write(&source, &body).unwrap();
    let source_text = source.to_str().unwrap();

    let direct = |suffix: &str| {
        let mut payload = body.clone();
        payload.push_str(suffix);
        fs::write(&source, &payload).unwrap();
        Command::new("gzip")
            .args(["-9", "-c", source_text])
            .output()
            .unwrap()
            .stdout
    };

    let expected = direct("");
    let args = ["run", "--json", "--", "gzip", "-9", "-c", source_text];

    let recorded = invoke(&cache, &args, None);
    let recorded: Value = serde_json::from_slice(&recorded.stdout).unwrap();
    assert_eq!(recorded["classification"], "Guarded", "{recorded}");
    assert_eq!(recorded["eligible_for_reuse"], true);
    assert_eq!(stdout_bytes_of(&recorded), expected);

    let reused = invoke(&cache, &args, None);
    let reused: Value = serde_json::from_slice(&reused.stdout).unwrap();
    assert_eq!(reused["cache_decision"], "Reused", "{reused}");
    assert_eq!(stdout_bytes_of(&reused), expected);

    // A content change must not replay the old bytes.
    let changed = direct("appended-line\n");
    assert_ne!(changed, expected, "fixture change must alter the output");
    let invalidated = invoke(&cache, &args, None);
    let invalidated: Value = serde_json::from_slice(&invalidated.stdout).unwrap();
    assert_eq!(
        invalidated["cache_decision"], "Deoptimized",
        "{invalidated}"
    );
    assert_eq!(stdout_bytes_of(&invalidated), changed);

    let reusable = invoke(&cache, &args, None);
    let reusable: Value = serde_json::from_slice(&reusable.stdout).unwrap();
    assert_eq!(reusable["cache_decision"], "Reused", "{reusable}");
    assert_eq!(stdout_bytes_of(&reusable), changed);

    eprintln!("RESULT gzip-reuse PASS");
}

/// Ordinary output placement must not defeat reuse.
///
/// `gzip -9 -c input.txt > input.txt.gz` writes into the directory that holds the input. The program
/// opens that directory, but only to resolve the input's name: the open cannot report the
/// directory's timestamps, size or link count. Before the directory-open dependency was typed, this
/// sequence deoptimized and re-traced every time the output was written.
#[test]
fn gzip_reuse_survives_creating_entries_beside_the_input() {
    if !Command::new("gzip")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
    {
        eprintln!("RESULT gzip-directory-dependency SKIP");
        return;
    }

    let temporary = tempfile::tempdir().unwrap();
    let cache = temporary.path().join("cache");
    let work = temporary.path().join("work");
    fs::create_dir(&work).unwrap();
    let source = work.join("input.txt");
    let body = "directory-dependency-payload\n".repeat(8192);
    fs::write(&source, &body).unwrap();
    let source_text = source.to_str().unwrap();
    let args = ["run", "--json", "--", "gzip", "-9", "-c", source_text];
    let direct = || {
        Command::new("gzip")
            .args(["-9", "-c", source_text])
            .output()
            .unwrap()
            .stdout
    };
    let expected = direct();

    let first = invoke(&cache, &args, None);
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["classification"], "Guarded", "{first}");
    assert_eq!(stdout_bytes_of(&first), expected);

    // The command's own output lands beside its input, exactly as a shell redirect would place it.
    fs::write(work.join("input.txt.gz"), &expected).unwrap();
    let second = invoke(&cache, &args, None);
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(
        second["cache_decision"], "Reused",
        "output written beside the input must not invalidate reuse: {second}"
    );
    assert_eq!(stdout_bytes_of(&second), expected);

    // An unrelated sibling entry is equally irrelevant.
    fs::write(work.join("notes.txt"), b"unrelated\n").unwrap();
    let third = invoke(&cache, &args, None);
    let third: Value = serde_json::from_slice(&third.stdout).unwrap();
    assert_eq!(third["cache_decision"], "Reused", "{third}");

    // The input itself is not irrelevant: a content change must still deoptimize and produce the
    // new bytes.
    fs::write(&source, format!("{body}changed\n")).unwrap();
    let changed = direct();
    assert_ne!(changed, expected, "fixture change must alter the output");
    let fourth = invoke(&cache, &args, None);
    let fourth: Value = serde_json::from_slice(&fourth.stdout).unwrap();
    assert_eq!(fourth["cache_decision"], "Deoptimized", "{fourth}");
    assert_eq!(stdout_bytes_of(&fourth), changed);

    eprintln!("RESULT gzip-directory-dependency PASS");
}

#[test]
fn guarded_hit_deopt_restore_and_replay() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let binary_text = binary.to_str().unwrap();
    let root = temporary.path().to_str().unwrap();
    let args = ["run", "--", binary_text, "plain_file_read", root];

    let first = invoke(&cache, &args, None);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    assert!(String::from_utf8_lossy(&first.stderr).contains("classified     GUARDED"));
    let second = invoke(&cache, &args, None);
    assert!(String::from_utf8_lossy(&second.stderr).contains("cache          HIT"));

    fs::remove_file(temporary.path().join("output.txt")).unwrap();
    let restored = invoke(&cache, &args, None);
    assert!(String::from_utf8_lossy(&restored.stderr).contains("cache          HIT"));
    assert_eq!(
        fs::read(temporary.path().join("output.txt")).unwrap(),
        b"input one\n"
    );

    fs::write(temporary.path().join("input.txt"), b"input two\n").unwrap();
    let deoptimized = invoke(&cache, &args, None);
    assert!(!String::from_utf8_lossy(&deoptimized.stderr).contains("cache          HIT"));
    let explanation = invoke(&cache, &["explain", "--json"], None);
    let record: Value = serde_json::from_slice(&explanation.stdout).unwrap();
    assert_eq!(record["last_decision"]["decision"], "Deoptimized");
    assert!(record["last_decision"]["guard_failure"].is_object());

    let changed_env = invoke(&cache, &args, Some(("TRACEJIT_FIXTURE_VALUE", "changed")));
    assert!(!String::from_utf8_lossy(&changed_env.stderr).contains("cache          HIT"));

    let output_args = ["run", "--", binary_text, "stdout_only", root];
    let baseline_stdout = invoke(&cache, &output_args, None);
    let replayed_stdout = invoke(&cache, &output_args, None);
    assert_eq!(baseline_stdout.stdout, replayed_stdout.stdout);
    assert_eq!(replayed_stdout.stdout, b"stdout fixture\n");

    let stderr_args = ["run", "--json", "--", binary_text, "stderr_only", root];
    let baseline_stderr: Value =
        serde_json::from_slice(&invoke(&cache, &stderr_args, None).stdout).unwrap();
    let replayed_stderr: Value =
        serde_json::from_slice(&invoke(&cache, &stderr_args, None).stdout).unwrap();
    assert_eq!(
        baseline_stderr["stderr_bytes"],
        replayed_stderr["stderr_bytes"]
    );
    assert_eq!(replayed_stderr["kind"], "Reused");

    let nonzero_args = ["run", "--", binary_text, "nonzero_exit", root];
    let baseline_nonzero = invoke(&cache, &nonzero_args, None);
    let replayed_nonzero = invoke(&cache, &nonzero_args, None);
    assert_eq!(baseline_nonzero.status.code(), Some(7));
    assert_eq!(replayed_nonzero.status.code(), Some(7));
    assert!(String::from_utf8_lossy(&replayed_nonzero.stderr).contains("cache          HIT"));
    eprintln!("RESULT guarded_hit PASS");
    eprintln!("RESULT mutation DEOPT");
}

/// Two different input states must remain independently reusable.
///
/// `lookup_key` deliberately does not include file content; inputs are guards. The old schema
/// made that key the primary key, so running B after A replaced A. Returning to A then had to
/// retrace even though A's guarded record was still valid. The bounded candidate index keeps both
/// records and verifies each one's guards before choosing a hit.
#[test]
fn alternating_inputs_reuse_a_retained_candidate() {
    let _serial = COMPILER_TIMING_LOCK.lock().unwrap();
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "plain_file_read",
        temporary.path().to_str().unwrap(),
    ];
    let input = temporary.path().join("input.txt");
    let output = temporary.path().join("output.txt");

    let first = invoke(&cache, &args, None);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["kind"], "Executed", "{first}");
    assert_eq!(fs::read(&output).unwrap(), b"input one\n");

    fs::write(&input, b"input two\n").unwrap();
    let second = invoke(&cache, &args, None);
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_ne!(
        second["kind"], "Reused",
        "a different input must not hit: {second}"
    );
    assert_eq!(fs::read(&output).unwrap(), b"input two\n");

    fs::write(&input, b"input one\n").unwrap();
    let third = invoke(&cache, &args, None);
    assert!(
        third.status.success(),
        "{}",
        String::from_utf8_lossy(&third.stderr)
    );
    let third: Value = serde_json::from_slice(&third.stdout).unwrap();
    assert_eq!(
        third["kind"], "Reused",
        "the retained A record was lost: {third}"
    );
    assert_eq!(third["classification"], "Guarded", "{third}");
    assert_eq!(fs::read(&output).unwrap(), b"input one\n");
    eprintln!("RESULT alternate-candidate-replay PASS");
}

#[test]
fn metadata_symlink_and_environment_changes_miss() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let binary_text = binary.to_str().unwrap();
    let root = temporary.path().to_str().unwrap();

    let metadata_args = ["run", "--", binary_text, "file_mtime_changed", root];
    assert!(invoke(&cache, &metadata_args, None).status.success());
    assert!(
        String::from_utf8_lossy(&invoke(&cache, &metadata_args, None).stderr)
            .contains("cache          HIT")
    );
    std::thread::sleep(std::time::Duration::from_millis(10));
    fs::write(temporary.path().join("input.txt"), b"input one\n").unwrap();
    let metadata_miss = invoke(&cache, &metadata_args, None);
    assert!(String::from_utf8_lossy(&metadata_miss.stderr).contains("cache          DEOPT"));

    fs::write(temporary.path().join("alternate.txt"), b"alternate\n").unwrap();
    let symlink_args = ["run", "--", binary_text, "symlink_target_changed", root];
    assert!(invoke(&cache, &symlink_args, None).status.success());
    fs::remove_file(temporary.path().join("input-link")).unwrap();
    std::os::unix::fs::symlink("alternate.txt", temporary.path().join("input-link")).unwrap();
    let symlink_miss = invoke(&cache, &symlink_args, None);
    assert!(String::from_utf8_lossy(&symlink_miss.stderr).contains("cache          DEOPT"));

    let environment_args = ["run", "--", binary_text, "environment_dependency", root];
    assert!(invoke(
        &cache,
        &environment_args,
        Some(("TRACEJIT_FIXTURE_VALUE", "one"))
    )
    .status
    .success());
    let environment_miss = invoke(
        &cache,
        &environment_args,
        Some(("TRACEJIT_FIXTURE_VALUE", "two")),
    );
    assert!(String::from_utf8_lossy(&environment_miss.stderr).contains("cache          MISS"));
}

#[test]
fn nondeterministic_and_unknown_cases_never_reuse() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    for case in ["getrandom", "unknown_ioctl", "network_send", "vdso_clock"] {
        let args = [
            "run",
            "--",
            binary.to_str().unwrap(),
            case,
            temporary.path().to_str().unwrap(),
        ];
        let first = invoke(&cache, &args, None);
        let second = invoke(&cache, &args, None);
        assert!(
            first.status.success(),
            "{}",
            String::from_utf8_lossy(&first.stderr)
        );
        assert!(
            second.status.success(),
            "{}",
            String::from_utf8_lossy(&second.stderr)
        );
        assert!(!String::from_utf8_lossy(&first.stderr).contains("cache          HIT"));
        assert!(!String::from_utf8_lossy(&second.stderr).contains("cache          HIT"));
    }
}

#[test]
fn sandbox_declared_path_succeeds_and_other_effects_are_denied() {
    if !tracejit_sandbox::capabilities().can_prove() {
        let reason = "seccomp or Landlock ABI 3+ is unavailable";
        if std::env::var_os("TRACEJIT_REQUIRE_PROVEN").is_some() {
            panic!("RESULT sandbox FAIL: {reason}");
        }
        eprintln!("RESULT sandbox SKIP: {reason}");
        return;
    }
    eprintln!("RESULT sandbox PASS: seccomp and Landlock ABI 3+ available");
    let temporary = tempfile::tempdir().unwrap();
    let declared = temporary.path().join("declared");
    let undeclared = temporary.path().join("undeclared");
    fs::write(&declared, b"allowed").unwrap();
    fs::write(&undeclared, b"denied").unwrap();
    let status = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "sandbox_child", "--nocapture"])
        .env("TRACEJIT_SANDBOX_CHILD", "1")
        .env("TRACEJIT_DECLARED", &declared)
        .env("TRACEJIT_UNDECLARED", &undeclared)
        .status()
        .unwrap();
    assert!(status.success());
}

/// The enforcement path must produce and then reuse a `PROVEN` record end to end.
///
/// A capability report only says the kernel supports the mechanisms. This test requires the
/// executable itself to receive the policy: the first (discovery) run is `Guarded`, the second
/// run installs the policy and is classified `PROVEN`, and a third run reuses that same record.
/// The input is then changed, which must reject the cached result and produce the new bytes.
#[test]
fn enforced_execution_is_proven_reused_and_invalidated() {
    if !tracejit_sandbox::capabilities().can_prove() {
        let reason = "seccomp or Landlock ABI 3+ is unavailable";
        if std::env::var_os("TRACEJIT_REQUIRE_PROVEN").is_some() {
            panic!("RESULT proven-reuse FAIL: {reason}");
        }
        eprintln!("RESULT proven-reuse SKIP: {reason}");
        return;
    }

    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--enforce",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "plain_file_read",
        temporary.path().to_str().unwrap(),
    ];
    let input = temporary.path().join("input.txt");
    let output = temporary.path().join("output.txt");

    let discovery = invoke(&cache, &args, None);
    assert!(discovery.status.success());
    let discovery: Value = serde_json::from_slice(&discovery.stdout).unwrap();
    assert_eq!(discovery["kind"], "Executed", "{discovery}");
    assert_eq!(discovery["classification"], "Guarded", "{discovery}");
    assert_eq!(fs::read(&output).unwrap(), b"input one\n");

    let enforced = invoke(&cache, &args, None);
    assert!(enforced.status.success());
    let enforced: Value = serde_json::from_slice(&enforced.stdout).unwrap();
    assert_eq!(enforced["kind"], "Executed", "{enforced}");
    assert_eq!(
        enforced["classification"], "Proven",
        "the execution did not receive an enforced policy: {enforced}"
    );
    assert_eq!(fs::read(&output).unwrap(), b"input one\n");

    fs::remove_file(&output).unwrap();
    let reused = invoke(&cache, &args, None);
    assert!(reused.status.success());
    let reused: Value = serde_json::from_slice(&reused.stdout).unwrap();
    assert_eq!(reused["kind"], "Reused", "{reused}");
    assert_eq!(reused["classification"], "Proven", "{reused}");
    assert_eq!(reused["cache_decision"], "Reused", "{reused}");
    assert_eq!(fs::read(&output).unwrap(), b"input one\n");

    fs::write(&input, b"input two\n").unwrap();
    let changed = invoke(&cache, &args, None);
    assert!(changed.status.success());
    let changed: Value = serde_json::from_slice(&changed.stdout).unwrap();
    assert_ne!(changed["kind"], "Reused", "{changed}");
    assert_eq!(fs::read(&output).unwrap(), b"input two\n");
    eprintln!("RESULT proven-reuse PASS");
}

#[test]
fn sandbox_child() {
    if std::env::var_os("TRACEJIT_SANDBOX_CHILD").is_none() {
        return;
    }
    let declared = PathBuf::from(std::env::var_os("TRACEJIT_DECLARED").unwrap());
    let undeclared = PathBuf::from(std::env::var_os("TRACEJIT_UNDECLARED").unwrap());
    tracejit_sandbox::apply(&tracejit_sandbox::SandboxPolicy {
        readable_paths: vec![declared.clone()],
        writable_paths: Vec::new(),
        allow_network: false,
    })
    .unwrap();
    assert!(fs::read(&declared).is_ok(), "declared path should succeed");
    assert!(
        fs::read(&undeclared).is_err(),
        "undeclared path should be denied"
    );
    assert!(std::net::TcpStream::connect("127.0.0.1:9").is_err());
}

/// The allocator-entropy contract unlocks an ordinary glibc tool that native mode refuses.
///
/// `sed` calls `getrandom(8, GRND_NONBLOCK)` from `ptmalloc_init` before it touches its input, so
/// native mode classifies it `NONDETERMINISTIC`. Under the contract the tracer answers only that
/// runtime-internal probe, records the call site and library hash, and the execution becomes
/// guardable and reusable. The report must say the result is reproducible *within the contract*,
/// and a native invocation must never reuse the controlled entry.
#[test]
fn allocator_entropy_contract_reuses_a_glibc_tool() {
    if !Command::new("sed")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
    {
        eprintln!("RESULT controlled-sed SKIP");
        return;
    }
    let temporary = tempfile::tempdir().unwrap();
    let cache = temporary.path().join("cache");
    let input = temporary.path().join("input.txt");
    fs::write(&input, "alpha\nbeta\n").unwrap();
    let input_text = input.to_str().unwrap();
    let expected = Command::new("sed")
        .args(["s/alpha/ALPHA/", input_text])
        .output()
        .unwrap()
        .stdout;
    let args = [
        "run",
        "--json",
        "--contract",
        "allocator-entropy-v1",
        "--",
        "sed",
        "s/alpha/ALPHA/",
        input_text,
    ];

    let first = invoke(&cache, &args, None);
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["classification"], "Guarded", "{first}");
    assert_eq!(first["contract"], "tracejit.allocator-entropy.v1");
    assert!(
        first["reasons"]
            .as_array()
            .unwrap()
            .iter()
            .any(|reason| reason
                .as_str()
                .unwrap()
                .contains("not equivalent to native")),
        "the contract must be visible in the report: {first}"
    );
    assert_eq!(stdout_bytes_of(&first), expected);

    let second = invoke(&cache, &args, None);
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(second["cache_decision"], "Reused", "{second}");
    assert_eq!(stdout_bytes_of(&second), expected);

    // A changed input still invalidates.
    fs::write(&input, "alpha\ngamma\n").unwrap();
    let changed_expected = Command::new("sed")
        .args(["s/alpha/ALPHA/", input_text])
        .output()
        .unwrap()
        .stdout;
    let third = invoke(&cache, &args, None);
    let third: Value = serde_json::from_slice(&third.stdout).unwrap();
    assert_eq!(third["cache_decision"], "Deoptimized", "{third}");
    assert_eq!(stdout_bytes_of(&third), changed_expected);

    // Native mode has a different identity and must not reuse the controlled entry.
    let native = invoke(
        &cache,
        &["run", "--json", "--", "sed", "s/alpha/ALPHA/", input_text],
        None,
    );
    let native: Value = serde_json::from_slice(&native.stdout).unwrap();
    assert_ne!(native["cache_decision"], "Reused", "{native}");
    assert_eq!(native["classification"], "Nondeterministic", "{native}");
    eprintln!("RESULT controlled-sed PASS");
}

/// The contract must not absorb randomness an application asked for itself.
///
/// The fixture requests one byte with flags `0` from its own stack. Even with the contract active
/// that call has no runtime-internal destination, so it must stay nondeterministic.
#[test]
fn a_contract_does_not_absorb_application_randomness() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--json",
        "--contract",
        "allocator-entropy-v1",
        "--",
        binary.to_str().unwrap(),
        "getrandom",
        temporary.path().to_str().unwrap(),
    ];
    let report: Value = serde_json::from_slice(&invoke(&cache, &args, None).stdout).unwrap();
    assert_eq!(
        report["classification"], "Nondeterministic",
        "application randomness must not be absorbed by the contract: {report}"
    );
    eprintln!("RESULT controlled-application-randomness PASS");
}

fn stderr_of(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn hit(output: &Output) -> bool {
    stderr_of(output).contains("cache          HIT")
}

fn deoptimized(output: &Output) -> bool {
    stderr_of(output).contains("cache          DEOPT")
}

fn missed(output: &Output) -> bool {
    stderr_of(output).contains("cache          MISS")
}

/// Copies the modification timestamp of `reference` onto `target` so a content change
/// can be tested with the original mtime restored.
fn restore_mtime(reference: &Path, target: &Path) {
    let status = Command::new("touch")
        .arg("-r")
        .arg(reference)
        .arg(target)
        .status()
        .expect("touch must be available");
    assert!(status.success(), "touch -r failed");
}

/// One compiled fixture workspace plus its own private cache.
struct Fixture {
    directory: tempfile::TempDir,
    binary: PathBuf,
    cache: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        workspace(directory.path());
        let binary = compile_fixture(directory.path());
        let cache = directory.path().join("cache");
        Self {
            directory,
            binary,
            cache,
        }
    }

    fn root(&self) -> &str {
        self.directory.path().to_str().unwrap()
    }

    fn binary_arg(&self) -> &str {
        self.binary.to_str().unwrap()
    }

    fn input(&self, name: &str) -> PathBuf {
        self.directory.path().join(name)
    }

    fn run(&self, case: &str) -> Output {
        invoke(
            &self.cache,
            &["run", "--", self.binary_arg(), case, self.root()],
            None,
        )
    }

    fn run_with_guard_mode(&self, mode: &str, case: &str) -> Output {
        invoke(
            &self.cache,
            &[
                "run",
                "--guard-mode",
                mode,
                "--",
                self.binary_arg(),
                case,
                self.root(),
            ],
            None,
        )
    }

    /// Runs once to record, then asserts the second run reused the first result.
    fn acquire(&self, case: &str) -> Output {
        let first = self.run(case);
        assert!(first.status.success(), "{}", stderr_of(&first));
        let second = self.run(case);
        assert!(
            hit(&second),
            "the primed run did not reuse:\n{}",
            stderr_of(&second)
        );
        second
    }
}

fn spawn_same_command(fixture: &Fixture, case: &'static str) -> Vec<Output> {
    let mut handles = Vec::new();
    for _ in 0..8 {
        let binary = fixture.binary.clone();
        let cache = fixture.cache.clone();
        let root = fixture.directory.path().to_path_buf();
        handles.push(std::thread::spawn(move || {
            let binary = binary.to_str().unwrap();
            let root = root.to_str().unwrap();
            invoke(&cache, &["run", "--", binary, case, root], None)
        }));
    }
    handles
        .into_iter()
        .map(|handle| handle.join().expect("worker thread panicked"))
        .collect()
}

#[test]
fn same_size_content_change_with_original_mtime_deoptimizes() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let input = fixture.input("input.txt");
    let reference = fixture.input("reference.txt");
    fs::copy(&input, &reference).unwrap();
    let original_size = fs::metadata(&input).unwrap().len();
    fs::write(&input, b"input twO\n").unwrap();
    assert_eq!(fs::metadata(&input).unwrap().len(), original_size);
    restore_mtime(&reference, &input);
    let changed = fixture.run("plain_file_read");
    assert!(deoptimized(&changed), "{}", stderr_of(&changed));
}

#[test]
fn fast_guard_mode_still_deoptimizes_on_a_content_change() {
    let fixture = Fixture::new();
    let first = fixture.run_with_guard_mode("fast", "plain_file_read");
    assert!(first.status.success(), "{}", stderr_of(&first));
    let second = fixture.run_with_guard_mode("fast", "plain_file_read");
    assert!(hit(&second), "{}", stderr_of(&second));
    let input = fixture.input("input.txt");
    let reference = fixture.input("reference.txt");
    fs::copy(&input, &reference).unwrap();
    fs::write(&input, b"input twO\n").unwrap();
    restore_mtime(&reference, &input);
    let changed = fixture.run_with_guard_mode("fast", "plain_file_read");
    assert!(deoptimized(&changed), "{}", stderr_of(&changed));
}

#[test]
fn permission_change_deoptimizes() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let input = fixture.input("input.txt");
    let mut permissions = fs::metadata(&input).unwrap().permissions();
    std::os::unix::fs::PermissionsExt::set_mode(&mut permissions, 0o600);
    fs::set_permissions(&input, permissions).unwrap();
    let changed = fixture.run("plain_file_read");
    assert!(deoptimized(&changed), "{}", stderr_of(&changed));
}

/// A pathname's meaning is not its canonical target.
///
/// `be94f38` canonicalised every path containing `..` before recording it. That discards the
/// evidence that made the pathname meaningful: `<link>/../input.txt` was recorded as
/// `<a>/input.txt`, so repointing `<link>` at `b/sub` left the guard looking at the old,
/// unchanged target. A native run then reads `b/input.txt` while the cache replays `a/input.txt`.
/// The record has to keep the pathname the process used and let the guard re-resolve it, because
/// the kernel resolves `..` *after* following the symlink.
#[test]
fn a_repointed_symlink_before_dotdot_is_never_a_cache_hit() {
    let temporary = tempfile::tempdir().unwrap();
    let binary = compile_fixture(temporary.path());
    let a = temporary.path().join("a");
    let b = temporary.path().join("b");
    fs::create_dir_all(a.join("sub")).unwrap();
    fs::create_dir_all(b.join("sub")).unwrap();
    fs::write(a.join("input.txt"), b"alpha\n").unwrap();
    fs::write(b.join("input.txt"), b"beta\n").unwrap();
    let link = temporary.path().join("link");
    std::os::unix::fs::symlink(a.join("sub"), &link).unwrap();
    // `link/..` is `a` now and `b` after the repoint.
    let root = format!("{}/..", link.display());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "read_to_stdout",
        &root,
    ];

    let first = invoke(&cache, &args, None);
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["classification"], "Guarded", "{first}");
    assert_eq!(stdout_bytes_of(&first), b"alpha\n");

    fs::remove_file(&link).unwrap();
    std::os::unix::fs::symlink(b.join("sub"), &link).unwrap();

    let second = invoke(&cache, &args, None);
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_ne!(
        second["cache_decision"], "Reused",
        "a symlink repointed before `..` changed which file a native run reads; replaying the \
         cached result is a false hit: {second}"
    );
    assert_eq!(
        stdout_bytes_of(&second),
        b"beta\n",
        "the second run must observe the file the pathname now resolves to: {second}"
    );
}

/// The same guarantee through a chain of symlinks.
#[test]
fn a_repointed_symlink_chain_before_dotdot_is_never_a_cache_hit() {
    let temporary = tempfile::tempdir().unwrap();
    let binary = compile_fixture(temporary.path());
    let a = temporary.path().join("a");
    let b = temporary.path().join("b");
    fs::create_dir_all(a.join("sub")).unwrap();
    fs::create_dir_all(b.join("sub")).unwrap();
    fs::write(a.join("input.txt"), b"alpha\n").unwrap();
    fs::write(b.join("input.txt"), b"beta\n").unwrap();
    let first_link = temporary.path().join("first");
    let second_link = temporary.path().join("second");
    std::os::unix::fs::symlink(&second_link, &first_link).unwrap();
    std::os::unix::fs::symlink(a.join("sub"), &second_link).unwrap();
    let root = format!("{}/..", first_link.display());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "read_to_stdout",
        &root,
    ];
    let first = invoke(&cache, &args, None);
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["classification"], "Guarded", "{first}");

    fs::remove_file(&second_link).unwrap();
    std::os::unix::fs::symlink(b.join("sub"), &second_link).unwrap();

    let second = invoke(&cache, &args, None);
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_ne!(second["cache_decision"], "Reused", "{second}");
    assert_eq!(stdout_bytes_of(&second), b"beta\n");
}

#[test]
fn removing_a_dependency_deoptimizes() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    fs::remove_file(fixture.input("input.txt")).unwrap();
    let changed = fixture.run("plain_file_read");
    assert!(deoptimized(&changed), "{}", stderr_of(&changed));
}

#[test]
fn an_absence_guard_reports_a_file_that_appeared() {
    let fixture = Fixture::new();
    fs::remove_file(fixture.input("input.txt")).unwrap();
    let args = [
        "run",
        "--",
        fixture.binary_arg(),
        "plain_file_read",
        fixture.root(),
    ];
    let first = invoke(&fixture.cache, &args, None);
    // The fixture exits 91 because its input is missing; the trace records the absence.
    assert_eq!(first.status.code(), Some(91), "{}", stderr_of(&first));
    assert!(
        String::from_utf8_lossy(&first.stderr).contains("classified     GUARDED"),
        "{}",
        stderr_of(&first)
    );
    let second = invoke(&fixture.cache, &args, None);
    assert!(hit(&second), "{}", stderr_of(&second));
    fs::write(fixture.input("input.txt"), b"input one\n").unwrap();
    let third = invoke(&fixture.cache, &args, None);
    assert!(deoptimized(&third), "{}", stderr_of(&third));
}

#[test]
fn child_process_dependency_change_deoptimizes() {
    let fixture = Fixture::new();
    fixture.acquire("child_file_dependency");
    fs::write(fixture.input("input.txt"), b"mutated\n").unwrap();
    let changed = fixture.run("child_file_dependency");
    assert!(deoptimized(&changed), "{}", stderr_of(&changed));
}

#[test]
fn executed_interpreter_change_deoptimizes() {
    let fixture = Fixture::new();
    fixture.acquire("script_dependency");
    let interpreter = fixture.input("fixture-interpreter");
    let mut bytes = fs::read(&interpreter).unwrap();
    bytes.extend_from_slice(&[0_u8; 64]);
    fs::write(&interpreter, bytes).unwrap();
    let changed = fixture.run("script_dependency");
    assert!(deoptimized(&changed), "{}", stderr_of(&changed));
}

#[test]
fn traced_execution_preserves_the_caller_supplied_argv0() {
    // argv[0] is observable. CPython picks its installation prefix, and therefore its module
    // search path, from argv[0], so a traced run that rewrites it to the canonicalized target can
    // import different packages than the same command run directly. Compare a symlinked shell's
    // own view of $0 (which is argv[0]) between direct and traced execution.
    let scratch = tempfile::tempdir().unwrap();
    let link = scratch.path().join("sh-link");
    std::os::unix::fs::symlink("/bin/sh", &link).unwrap();
    let script = "printf '%s' \"$0\"";

    let direct = Command::new(&link).args(["-c", script]).output().unwrap();
    assert!(
        direct.status.success(),
        "direct execution of the link failed"
    );
    assert_eq!(direct.stdout, link.to_str().unwrap().as_bytes());

    let cache = scratch.path().join("cache");
    let traced = invoke(
        &cache,
        &["run", "--json", "--", link.to_str().unwrap(), "-c", script],
        None,
    );
    assert!(traced.status.success(), "{}", stderr_of(&traced));
    let report: Value = serde_json::from_slice(&traced.stdout).unwrap();
    let child_stdout: Vec<u8> = report["stdout_bytes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|byte| byte.as_u64().unwrap() as u8)
        .collect();
    assert_eq!(
        report["exit_code"].as_i64(),
        Some(0),
        "traced child failed: {}",
        String::from_utf8_lossy(&child_stdout)
    );
    assert_eq!(
        child_stdout,
        direct.stdout,
        "traced execution changed argv[0]: direct {:?} versus traced {:?}",
        String::from_utf8_lossy(&direct.stdout),
        String::from_utf8_lossy(&child_stdout)
    );
}

#[test]
fn working_directory_change_is_a_miss() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let other = tempfile::tempdir().unwrap();
    let output = Command::new(tracejit())
        .args([
            "run",
            "--",
            fixture.binary_arg(),
            "plain_file_read",
            fixture.root(),
        ])
        .env("TRACEJIT_CACHE_DIR", &fixture.cache)
        .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0")
        .current_dir(other.path())
        .output()
        .unwrap();
    assert!(missed(&output) && !hit(&output), "{}", stderr_of(&output));
}

#[test]
fn concurrent_identical_runs_neither_fail_nor_reuse_unsafely() {
    let fixture = Fixture::new();
    for output in spawn_same_command(&fixture, "plain_file_read") {
        assert!(
            output.status.success(),
            "a concurrent run failed:\n{}",
            stderr_of(&output)
        );
    }
    let final_run = fixture.run("plain_file_read");
    assert!(hit(&final_run), "{}", stderr_of(&final_run));
}

#[test]
fn concurrent_cache_reads_all_reuse_the_same_result() {
    let fixture = Fixture::new();
    fixture.acquire("stdout_only");
    for output in spawn_same_command(&fixture, "stdout_only") {
        assert!(output.status.success(), "{}", stderr_of(&output));
        assert!(hit(&output), "{}", stderr_of(&output));
        assert_eq!(output.stdout, b"stdout fixture\n");
    }
}

#[test]
fn a_symlinked_cache_root_is_refused() {
    let fixture = Fixture::new();
    let real = fixture.input("real-cache");
    fs::create_dir(&real).unwrap();
    let link = fixture.input("linked-cache");
    std::os::unix::fs::symlink(&real, &link).unwrap();
    let output = invoke(
        &link,
        &[
            "run",
            "--",
            fixture.binary_arg(),
            "plain_file_read",
            fixture.root(),
        ],
        None,
    );
    assert!(!output.status.success());
    assert!(
        stderr_of(&output).contains("unsafe cache root"),
        "{}",
        stderr_of(&output)
    );
}

#[test]
fn a_corrupted_cached_output_fails_closed() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let output_file = fixture.input("output.txt");
    let objects = fixture.cache.join("objects");
    let captured = fs::read_dir(&objects)
        .unwrap()
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .find(|path| fs::read(path).unwrap_or_default() == b"input one\n")
        .expect("the captured output object");
    fs::write(&captured, b"tampered").unwrap();
    fs::write(&output_file, b"user content\n").unwrap();
    let run = fixture.run("plain_file_read");
    assert!(
        run.status.success(),
        "a corrupt object should be retraced rather than making the command fatal:\n{}",
        stderr_of(&run)
    );
    assert!(
        !hit(&run),
        "an object that failed verification must never be served:\n{}",
        stderr_of(&run)
    );
    assert!(
        !String::from_utf8_lossy(&run.stdout).contains("input one"),
        "cached bytes must not be exposed when an object is corrupt"
    );
    let explanation = invoke(&fixture.cache, &["explain", "--json"], None);
    let record: Value = serde_json::from_slice(&explanation.stdout).unwrap();
    let reason = record["last_decision"]["reason"]
        .as_str()
        .unwrap_or_default();
    assert!(
        reason.contains("corrupt"),
        "the recovery reason should name the corruption: {reason}"
    );
    // The corrupt object was replaced with content that matches its own hash, so the
    // same command reuses the repaired record on the next run.
    let repaired = fixture.run("plain_file_read");
    assert!(
        hit(&repaired),
        "the repaired object should be reusable:\n{}",
        stderr_of(&repaired)
    );
}

/// A corrupt stdout or stderr object must be rejected before the cached output is restored.
///
/// The fixture branches on whether its output path exists, so restoring first would make the
/// retrace observe `PRESENT` and produce different bytes than a run against the original
/// `ABSENT` state. Corrupting the recorded stream object makes the two orders distinguishable.
#[test]
fn dev_null_seek_is_reusable() {
    let fixture = Fixture::new();
    let first = fixture.run("dev_null_lseek");
    assert!(first.status.success(), "{}", stderr_of(&first));
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        b"input one\n"
    );
    let second = fixture.run("dev_null_lseek");
    assert!(hit(&second), "{}", stderr_of(&second));
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        b"input one\n"
    );
    eprintln!("RESULT dev-null-lseek PASS");
}

#[test]
fn regular_file_stdin_seek_is_reused_as_an_offset_stream() {
    let fixture = Fixture::new();
    let substitute = fixture.input("not-null");
    fs::write(&substitute, b"regular file\n").unwrap();
    let run = || {
        Command::new(tracejit())
            .args([
                "run",
                "--json",
                "--",
                fixture.binary_arg(),
                "inherited_seek_probe",
                fixture.root(),
            ])
            .env("TRACEJIT_CACHE_DIR", &fixture.cache)
            .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0")
            .stdin(Stdio::from(File::open(&substitute).unwrap()))
            .output()
            .unwrap()
    };
    let first = run();
    assert!(first.status.success(), "{}", stderr_of(&first));
    let second = run();
    assert!(second.status.success(), "{}", stderr_of(&second));
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(
        report["kind"], "Reused",
        "a regular stdin has a modelled offset stream and may reuse: {report}"
    );
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        b"input one\n"
    );
    eprintln!("RESULT substituted-dev-null PASS");
}

fn epoll_run(fixture: &Fixture, case: &str) -> Output {
    Command::new(tracejit())
        .args([
            "run",
            "--json",
            "--",
            fixture.binary_arg(),
            case,
            fixture.root(),
        ])
        .env("TRACEJIT_CACHE_DIR", &fixture.cache)
        .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0")
        .output()
        .unwrap()
}

#[test]
fn epoll_create_and_close_is_reusable() {
    let fixture = Fixture::new();
    let first = epoll_run(&fixture, "epoll_create_only");
    assert!(first.status.success(), "{}", stderr_of(&first));
    let second = epoll_run(&fixture, "epoll_create_only");
    assert!(second.status.success(), "{}", stderr_of(&second));
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(report["kind"], "Reused", "{report}");
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        b"input one\n"
    );
}

#[test]
fn epoll_duplicate_and_close_is_reusable() {
    let fixture = Fixture::new();
    assert!(epoll_run(&fixture, "epoll_dup_close").status.success());
    let second = epoll_run(&fixture, "epoll_dup_close");
    assert!(second.status.success(), "{}", stderr_of(&second));
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(report["kind"], "Reused", "{report}");
}

#[test]
fn epoll_control_use_is_refused() {
    let fixture = Fixture::new();
    let output = epoll_run(&fixture, "epoll_ctl_use");
    assert!(output.status.success(), "{}", stderr_of(&output));
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["eligible_for_reuse"], false, "{report}");
    assert_ne!(report["kind"], "Reused", "{report}");
    eprintln!("RESULT epoll-control-refused PASS");
}

#[test]
fn corrupt_stream_is_rejected_before_output_restoration() {
    for (case, record_field, report_field, expected_stream) in [
        (
            "output_presence_stdout",
            "stdout",
            "stdout_bytes",
            b"stream fixture\n".as_slice(),
        ),
        (
            "output_presence_stderr",
            "stderr",
            "stderr_bytes",
            b"stream fixture\n".as_slice(),
        ),
    ] {
        let fixture = Fixture::new();
        let output = fixture.input("output.txt");
        let _ = fs::remove_file(&output);
        let first = fixture.run(case);
        assert!(first.status.success(), "{case}: {}", stderr_of(&first));
        assert_eq!(fs::read(&output).unwrap(), b"ABSENT\n", "{case}");

        let explanation = invoke(&fixture.cache, &["explain", "--json"], None);
        let record: Value = serde_json::from_slice(&explanation.stdout).unwrap();
        let hash = record[record_field]
            .as_array()
            .map(|bytes| {
                let bytes = bytes
                    .iter()
                    .map(|byte| byte.as_u64().unwrap() as u8)
                    .collect::<Vec<_>>();
                bytes
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect::<String>()
            })
            .unwrap_or_else(|| panic!("{case}: no recorded {record_field} object: {record}"));
        let object = fixture.cache.join("objects").join(hash);
        fs::write(&object, b"tampered").unwrap();

        // The original pre-state is absent, so the output guard passes. Only the stream object
        // is corrupt. A restore-first implementation would leave `ABSENT` in place, detect the
        // corruption, retrace against `PRESENT`, and produce the wrong bytes.
        fs::remove_file(&output).unwrap();
        let run = invoke(
            &fixture.cache,
            &[
                "run",
                "--json",
                "--",
                fixture.binary_arg(),
                case,
                fixture.root(),
            ],
            None,
        );
        assert!(
            run.status.success(),
            "{case}: corruption made the command fatal: {}",
            stderr_of(&run)
        );
        let report: Value = serde_json::from_slice(&run.stdout).unwrap();
        assert_ne!(report["kind"], "Reused", "{case}: {report}");
        assert_eq!(
            fs::read(&output).unwrap(),
            b"ABSENT\n",
            "{case}: output was restored before the corrupt stream was rejected: {report}"
        );
        let stream = report[report_field]
            .as_array()
            .unwrap_or_else(|| panic!("{case}: no {report_field}: {report}"))
            .iter()
            .map(|byte| byte.as_u64().unwrap() as u8)
            .collect::<Vec<_>>();
        assert_eq!(stream, expected_stream, "{case}: {report}");

        let explanation = invoke(&fixture.cache, &["explain", "--json"], None);
        let record: Value = serde_json::from_slice(&explanation.stdout).unwrap();
        let reason = record["last_decision"]["reason"]
            .as_str()
            .unwrap_or_default();
        assert!(reason.contains("corrupt"), "{case}: {reason}");
    }
    eprintln!("RESULT corrupt-stream-order PASS");
}

#[test]
fn a_self_killed_child_is_reported_and_never_reused() {
    let fixture = Fixture::new();
    let args = ["run", "--", "sh", "-c", "kill -9 $$"];
    let first = invoke(&fixture.cache, &args, None);
    assert_eq!(first.status.code(), Some(137), "{}", stderr_of(&first));
    let second = invoke(&fixture.cache, &args, None);
    assert!(!hit(&second), "{}", stderr_of(&second));
}

#[test]
fn a_hard_linked_output_retraces_instead_of_aborting() {
    // A hard link is neither a recorded dependency nor an input mutation, so no guard sees it.
    // The stricter deletion/replacement preconditions added in Phase 1 therefore refuse the
    // entry at restore time, and refusing must not turn into failing a command that succeeds
    // when it is simply run again.
    let fixture = Fixture::new();
    // The first run records the workspace, the second re-records against the state the first one
    // left behind, so no guard is failing by the time the link is added.
    let recorded = fixture.run("rename_output");
    assert!(recorded.status.success(), "{}", stderr_of(&recorded));
    let settled = fixture.run("rename_output");
    assert!(settled.status.success(), "{}", stderr_of(&settled));
    let output = Path::new(fixture.root()).join("second.txt");
    assert!(
        output.is_file(),
        "the traced run produced no output to link"
    );
    fs::hard_link(&output, Path::new(fixture.root()).join("second-link.txt")).unwrap();
    let retraced = fixture.run("rename_output");
    assert!(
        retraced.status.success(),
        "a hard-linked output aborted the command instead of retracing: {}",
        stderr_of(&retraced)
    );
    assert!(
        missed(&retraced) && !hit(&retraced),
        "the refused entry was not reported as a miss: {}",
        stderr_of(&retraced)
    );
    assert_eq!(
        retraced.stdout, settled.stdout,
        "retracing after a refused restoration changed stdout"
    );
}

/// Installs an executable without ever holding the executable path open for writing.
///
/// `execve` returns `ETXTBSY` while any process still has the target open for writing. This harness
/// runs tests in parallel, so a sibling's `fork` can briefly inherit a write descriptor opened by
/// `fs::write` for this script, which failed 3 of 8 suite runs. Writing a sibling file and
/// renaming it into place removes the window instead of retrying around it.
/// Retries this test's own spawns when the kernel reports `ETXTBSY`.
///
/// Writing through a sibling name and renaming removes this test's writer window, but a parallel
/// test's `fork` can still inherit the descriptor while the temporary inode is being written: the
/// rename makes that same inode the executable. That window belongs to process creation across
/// independent tests, not to a leaked descriptor in the product, and no in-test lock can serialize
/// another test's `fork`. The retry is bounded and only accepts a spawn error or a "Text file busy"
/// failure; every other failure is returned unchanged.
fn run_with_etxtbsy_retry(build: impl Fn() -> Command) -> Output {
    for attempt in 0..40 {
        match build().output() {
            Ok(output)
                if attempt < 39
                    && !output.status.success()
                    && String::from_utf8_lossy(&output.stderr).contains("Text file busy") =>
            {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            Ok(output) => return output,
            Err(error)
                if error.kind() == std::io::ErrorKind::ExecutableFileBusy && attempt < 39 =>
            {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
            Err(error) => panic!("executable could not be started: {error}"),
        }
    }
    unreachable!("retry loop returns or panics")
}

fn write_executable(path: &Path, contents: &str) {
    let temporary = path.with_extension("pending");
    fs::write(&temporary, contents).unwrap();
    let mut permissions = fs::metadata(&temporary).unwrap().permissions();
    std::os::unix::fs::PermissionsExt::set_mode(&mut permissions, 0o700);
    fs::set_permissions(&temporary, permissions).unwrap();
    fs::rename(&temporary, path).unwrap();
}

#[test]
fn a_traced_script_sees_the_callers_script_path() {
    // The kernel passes the execve path to a script's interpreter, so exec'ing the canonical
    // target handed `$0` an absolute path where a direct `./script` invocation handed it the
    // relative one. Scripts that derive a path from `$0` observe the difference.
    let temporary = tempfile::tempdir().unwrap();
    let script = temporary.path().join("echo-zero.sh");
    write_executable(&script, "#!/bin/sh\necho \"zero=$0\"\n");
    let direct = run_with_etxtbsy_retry(|| {
        let mut command = Command::new("./echo-zero.sh");
        command.current_dir(temporary.path());
        command
    });
    assert!(direct.status.success(), "the direct run itself failed");
    let traced = run_with_etxtbsy_retry(|| {
        let mut command = Command::new(tracejit());
        command
            .args(["run", "--", "./echo-zero.sh"])
            .current_dir(temporary.path())
            .env("TRACEJIT_CACHE_DIR", temporary.path().join("cache"))
            .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0");
        command
    });
    assert!(
        traced.status.success(),
        "traced script run failed: {}",
        String::from_utf8_lossy(&traced.stderr)
    );
    assert!(
        String::from_utf8_lossy(&traced.stdout).contains("zero=./echo-zero.sh"),
        "a traced script saw a different $0 than a direct run; direct {:?} traced {:?}",
        String::from_utf8_lossy(&direct.stdout),
        String::from_utf8_lossy(&traced.stdout)
    );
}

#[test]
fn corrupted_objects_are_repaired_and_reuse_resumes() {
    let fixture = Fixture::new();
    fixture.acquire("stdout_only");
    let reused = fixture.run("stdout_only");
    assert!(hit(&reused), "{}", stderr_of(&reused));
    let objects = fixture.cache.join("objects");
    let mut corrupted = 0;
    for entry in fs::read_dir(&objects).unwrap() {
        let path = entry.unwrap().path();
        fs::write(&path, b"tampered").unwrap();
        corrupted += 1;
    }
    assert!(corrupted > 0, "no content-addressed object to corrupt");
    let recovered = fixture.run("stdout_only");
    assert!(
        recovered.status.success(),
        "corruption aborted the command: {}",
        stderr_of(&recovered)
    );
    assert_eq!(
        recovered.stdout, b"stdout fixture\n",
        "the retrace produced different stdout than the cached record"
    );
    let again = fixture.run("stdout_only");
    assert!(
        hit(&again),
        "reuse did not resume after the objects were repaired: {}",
        stderr_of(&again)
    );
}

/// A recorded permission check must be replayed, not approximated: the second run reuses, and
/// creating the probed file must deoptimize to exactly the answer a direct run gives.
#[test]
fn access_check_is_replayed_as_a_predicate() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--",
        binary.to_str().unwrap(),
        "access_check",
        temporary.path().to_str().unwrap(),
    ];

    let first = invoke(&cache, &args, None);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );

    let second = invoke(&cache, &args, None);
    let stderr = String::from_utf8_lossy(&second.stderr);
    assert!(stderr.contains("cache          HIT"), "{stderr}");
    assert_eq!(second.status.code(), Some(0));

    fs::write(temporary.path().join("probe-absent.txt"), b"now present").unwrap();
    let third = invoke(&cache, &args, None);
    let stderr = String::from_utf8_lossy(&third.stderr);
    // A failed guard deoptimizes and retraces; it must never report a hit.
    assert!(
        stderr.contains("cache          DEOPT"),
        "stale reuse after the probed file appeared: {stderr}"
    );
    assert_eq!(
        third.status.code(),
        Some(2),
        "replayed answer must match a direct run"
    );
    eprintln!("RESULT access_predicate PASS");
}

/// `tr` reads stdin through an inherited regular file, and a read can update `atime`. That must
/// not change the cache identity: the reported defect was a miss on every fresh session.
#[test]
fn inherited_stdin_reuse_is_stable_across_fresh_sessions() {
    if !Command::new("tr")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
    {
        eprintln!("RESULT controlled-tr SKIP");
        return;
    }
    for session in 0..2 {
        let temporary = tempfile::tempdir().unwrap();
        let cache = temporary.path().join("cache");
        let input = temporary.path().join("input.txt");
        fs::write(&input, "alpha beta\n").unwrap();
        let direct = |path: &Path| {
            Command::new("tr")
                .args(["a-z", "A-Z"])
                .stdin(std::process::Stdio::from(fs::File::open(path).unwrap()))
                .output()
                .unwrap()
                .stdout
        };
        let expected = direct(&input);
        let args = [
            "run",
            "--json",
            "--contract",
            "allocator-entropy-v1",
            "--",
            "tr",
            "a-z",
            "A-Z",
        ];
        let traced = |cache: &Path, stdin: &Path| {
            let output = Command::new(tracejit())
                .args(args)
                .env("TRACEJIT_CACHE_DIR", cache)
                .stdin(std::process::Stdio::from(fs::File::open(stdin).unwrap()))
                .output()
                .unwrap();
            serde_json::from_slice::<Value>(&output.stdout).unwrap()
        };

        let first = traced(&cache, &input);
        assert_eq!(
            first["classification"], "Guarded",
            "session {session}: {first}"
        );
        assert_eq!(stdout_bytes_of(&first), expected);
        let second = traced(&cache, &input);
        assert_eq!(
            second["cache_decision"], "Reused",
            "session {session}: reading stdin must not invalidate the identity: {second}"
        );
        assert_eq!(stdout_bytes_of(&second), expected);

        fs::write(&input, "gamma delta\n").unwrap();
        let changed = direct(&input);
        let third = traced(&cache, &input);
        assert_ne!(
            third["cache_decision"], "Reused",
            "session {session}: {third}"
        );
        assert_eq!(stdout_bytes_of(&third), changed);
    }
    eprintln!("RESULT controlled-tr PASS");
}

/// glibc's tcache key also implements double-free detection. Injecting a fixed key must not make a
/// double free look legal: the program must still abort with glibc's diagnostic.
#[test]
fn allocator_double_free_detection_survives_the_contract() {
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("double_free.c");
    fs::write(
        &source,
        "#include <stdlib.h>\nint main(void) { void *p = malloc(64); free(p); free(p); return 0; }\n",
    )
    .unwrap();
    let binary = temporary.path().join("double-free");
    let compiled = Command::new("cc")
        .args(["-O0", "-g"])
        .arg(&source)
        .arg("-o")
        .arg(&binary)
        .status()
        .unwrap();
    assert!(compiled.success(), "double-free fixture compilation failed");
    let native = Command::new(&binary).output().unwrap();
    assert!(!native.status.success(), "the fixture must abort natively");

    let cache = temporary.path().join("cache");
    let output = invoke(
        &cache,
        &[
            "run",
            "--json",
            "--contract",
            "allocator-entropy-v1",
            "--",
            binary.to_str().unwrap(),
        ],
        None,
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    let stderr: Vec<u8> = report["stderr_bytes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|byte| byte.as_u64().unwrap() as u8)
        .collect();
    let text = String::from_utf8_lossy(&stderr);
    assert_ne!(report["exit_code"].as_i64().unwrap_or(0), 0, "{report}");
    assert!(
        text.contains("double free") || text.contains("invalid pointer"),
        "the contract must not hide glibc's double-free diagnostic: {text}"
    );
    eprintln!("RESULT allocator-double-free PASS");
}

/// Cost-aware admission must run short commands directly and still cache commands that repay.
#[test]
fn auto_admission_skips_short_commands_and_caches_expensive_ones() {
    let _serial = COMPILER_TIMING_LOCK.lock().unwrap();
    let temporary = tempfile::tempdir().unwrap();
    let small = temporary.path().join("small.txt");
    fs::write(&small, "alpha\n".repeat(1000)).unwrap();
    let cache = temporary.path().join("cache");
    let short = [
        "run",
        "--json",
        "--admission",
        "auto",
        "--",
        "wc",
        "-c",
        small.to_str().unwrap(),
    ];
    let first: Value = serde_json::from_slice(&invoke(&cache, &short, None).stdout).unwrap();
    assert_eq!(first["cache_decision"], "Skipped", "{first}");
    let second: Value = serde_json::from_slice(&invoke(&cache, &short, None).stdout).unwrap();
    assert_eq!(second["cache_decision"], "Skipped", "{second}");
    assert_eq!(first["stdout_bytes"], second["stdout_bytes"]);
    assert_eq!(first["exit_code"], second["exit_code"]);

    if !Command::new("gzip")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
    {
        eprintln!("RESULT auto-admission SKIP gzip");
        return;
    }
    let large = temporary.path().join("large.txt");
    // Large enough that the measured direct run clears the cumulative-benefit threshold even
    // with the 6 ms hit-cost floor; a 13 ms gzip is correctly declined by the Phase 2I policy.
    fs::write(&large, "alpha beta gamma\n".repeat(1_200_000)).unwrap();
    let long = [
        "run",
        "--json",
        "--admission",
        "auto",
        "--",
        "gzip",
        "-9",
        "-c",
        large.to_str().unwrap(),
    ];
    let measured: Value = serde_json::from_slice(&invoke(&cache, &long, None).stdout).unwrap();
    assert_eq!(measured["cache_decision"], "Skipped", "{measured}");
    let traced: Value = serde_json::from_slice(&invoke(&cache, &long, None).stdout).unwrap();
    assert_eq!(traced["cache_decision"], "Executed", "{traced}");
    assert_eq!(traced["classification"], "Guarded", "{traced}");
    let reused: Value = serde_json::from_slice(&invoke(&cache, &long, None).stdout).unwrap();
    assert_eq!(reused["cache_decision"], "Reused", "{reused}");
    assert_eq!(stdout_bytes_of(&reused), stdout_bytes_of(&traced));
    eprintln!("RESULT auto-admission PASS");
}

fn compile_seek_fixture(directory: &Path) -> PathBuf {
    let source =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/stdin_seek.c");
    let binary = directory.join("stdin-seek");
    let status = Command::new("cc")
        .args(["-O2", "-Wall", "-Wextra", "-Werror"])
        .arg(source)
        .arg("-o")
        .arg(&binary)
        .status()
        .expect("C compiler must be available");
    assert!(status.success(), "stdin seek fixture compilation failed");
    binary
}

/// Inherited `stdin` is a shared open file description, not a private cursor: a seek changes a
/// caller-visible position, `pread` does not, and an alias is refused rather than given a second
/// position. Each case checks the bytes, the decision and the final position of the caller's file.
#[test]
fn inherited_stdin_seek_model_reproduces_offsets_and_refuses_unsound_cases() {
    let temporary = tempfile::tempdir().unwrap();
    let binary = compile_seek_fixture(temporary.path());
    let input = temporary.path().join("input.txt");
    fs::write(&input, b"0123456789abcdef").unwrap();

    let direct = |mode: &str, start: u64| -> (Vec<u8>, u64) {
        let mut stdin = fs::File::open(&input).unwrap();
        if start != 0 {
            stdin.seek(SeekFrom::Start(start)).unwrap();
        }
        let duplicate = stdin.try_clone().unwrap();
        let output = Command::new(&binary)
            .arg(mode)
            .stdin(std::process::Stdio::from(duplicate))
            .output()
            .unwrap();
        assert!(output.status.success(), "direct {mode} failed");
        (output.stdout, stdin.stream_position().unwrap())
    };
    let traced = |cache: &Path, mode: &str, start: u64| -> (Value, u64) {
        let mut stdin = fs::File::open(&input).unwrap();
        if start != 0 {
            stdin.seek(SeekFrom::Start(start)).unwrap();
        }
        let duplicate = stdin.try_clone().unwrap();
        let output = Command::new(tracejit())
            .args([
                "run",
                "--json",
                "--contract",
                "allocator-entropy-v1",
                "--",
                binary.to_str().unwrap(),
                mode,
            ])
            .env("TRACEJIT_CACHE_DIR", cache)
            .stdin(std::process::Stdio::from(duplicate))
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "traced {mode} failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let report: Value = serde_json::from_slice(&output.stdout).unwrap();
        (report, stdin.stream_position().unwrap())
    };

    // Seek after read, then read again: final position is 10, not the 14 bytes observed.
    let (expected, expected_position) = direct("read-seek-read", 0);
    assert_eq!(expected_position, 10);
    let cache = temporary.path().join("cache-seek");
    let (first, position) = traced(&cache, "read-seek-read", 0);
    assert_eq!(
        (
            first["classification"].clone(),
            first["cache_decision"].clone()
        ),
        ("Guarded".into(), "Executed".into()),
        "{first}"
    );
    assert_eq!(stdout_bytes_of(&first), expected);
    assert_eq!(
        position, expected_position,
        "first run must leave the caller's offset at the final position"
    );
    let (second, position) = traced(&cache, "read-seek-read", 0);
    assert_eq!(second["cache_decision"], "Reused", "{second}");
    assert_eq!(stdout_bytes_of(&second), expected);
    assert_eq!(
        position, expected_position,
        "reuse must reproduce the seek's final offset"
    );

    // A pure `SEEK_CUR` offset query is the zlib seekability probe; it must not move the offset.
    let (probe_expected, probe_position) = direct("probe", 0);
    let probe_cache = temporary.path().join("cache-probe");
    let (first, position) = traced(&probe_cache, "probe", 0);
    assert_eq!(first["cache_decision"], "Executed", "{first}");
    assert_eq!(stdout_bytes_of(&first), probe_expected);
    assert_eq!(position, probe_position);
    let (second, position) = traced(&probe_cache, "probe", 0);
    assert_eq!(second["cache_decision"], "Reused", "{second}");
    assert_eq!(stdout_bytes_of(&second), probe_expected);
    assert_eq!(position, probe_position);

    // A relative end seek depends on the guarded file size and must be reproduced.
    let (end_expected, end_position) = direct("end-relative", 0);
    let end_cache = temporary.path().join("cache-end");
    assert_eq!(
        traced(&end_cache, "end-relative", 0).0["cache_decision"],
        "Executed"
    );
    let (end_second, end_position_after) = traced(&end_cache, "end-relative", 0);
    assert_eq!(end_second["cache_decision"], "Reused", "{end_second}");
    assert_eq!(stdout_bytes_of(&end_second), end_expected);
    assert_eq!(end_position_after, end_position);

    // `pread` observes bytes without advancing the description; the following read starts at 0.
    let (pread_expected, pread_position) = direct("pread", 0);
    assert_eq!(pread_position, 4);
    let pread_cache = temporary.path().join("cache-pread");
    let (first, position) = traced(&pread_cache, "pread", 0);
    assert_eq!(stdout_bytes_of(&first), pread_expected);
    assert_eq!(
        position, pread_position,
        "pread must not advance the shared offset"
    );
    let (second, position) = traced(&pread_cache, "pread", 0);
    assert_eq!(second["cache_decision"], "Reused", "{second}");
    assert_eq!(stdout_bytes_of(&second), pread_expected);
    assert_eq!(
        position, pread_position,
        "reuse must not add pread's bytes to the offset"
    );

    // A failed seek has no caller-visible offset effect, so it does not have to be replayed.
    let (failed_expected, failed_position) = direct("failed-seek", 0);
    let failed_cache = temporary.path().join("cache-failed");
    assert_eq!(
        traced(&failed_cache, "failed-seek", 0).0["cache_decision"],
        "Executed"
    );
    let (failed_second, position) = traced(&failed_cache, "failed-seek", 0);
    assert_eq!(failed_second["cache_decision"], "Reused", "{failed_second}");
    assert_eq!(stdout_bytes_of(&failed_second), failed_expected);
    assert_eq!(position, failed_position);

    // An alias moves the same description, but the model tracks one position per stream.
    let alias_cache = temporary.path().join("cache-alias");
    let (first, _) = traced(&alias_cache, "alias", 0);
    assert_ne!(first["classification"], "Guarded", "{first}");
    let (second, _) = traced(&alias_cache, "alias", 0);
    assert_ne!(second["cache_decision"], "Reused", "{second}");
    assert!(
        second["reasons"].to_string().contains("alias of stdin"),
        "{second}"
    );

    // Allocation-layout queries are not implied by content.
    let data_cache = temporary.path().join("cache-data");
    let (first, _) = traced(&data_cache, "data", 0);
    assert_ne!(first["classification"], "Guarded", "{first}");
    let (second, _) = traced(&data_cache, "data", 0);
    assert_ne!(second["cache_decision"], "Reused", "{second}");
    assert!(
        second["reasons"].to_string().contains("whence 3"),
        "{second}"
    );

    // A forked child shares the description. Its read cannot be replayed, and its seek must not
    // be dismissed as process-internal: either would desynchronize the caller-visible offset.
    let child_read_cache = temporary.path().join("cache-child-read");
    let (first, _) = traced(&child_read_cache, "child-read", 0);
    assert_ne!(first["classification"], "Guarded", "{first}");
    let (second, _) = traced(&child_read_cache, "child-read", 0);
    assert_ne!(second["cache_decision"], "Reused", "{second}");
    assert!(
        second["reasons"].to_string().contains("descriptor 0"),
        "{second}"
    );

    let child_seek_cache = temporary.path().join("cache-child-seek");
    let (first, _) = traced(&child_seek_cache, "child-seek", 0);
    assert_ne!(first["classification"], "Guarded", "{first}");
    let (second, _) = traced(&child_seek_cache, "child-seek", 0);
    assert_ne!(second["cache_decision"], "Reused", "{second}");
    assert!(
        second["reasons"].to_string().contains("not modelled"),
        "{second}"
    );

    // An alias inherited across exec (fd 3 duplicated from fd 0 by the caller) is detected before
    // the program runs, so neither the alias's seek nor the shared offset can be replayed.
    let alias_input = fs::File::open(&input).unwrap();
    let inherited = Command::new("sh")
        .args([
            "-c",
            "exec 3<&0; exec \"$1\" run --json --contract allocator-entropy-v1 -- \"$2\" alias-fd3",
            "sh",
            tracejit().to_str().unwrap(),
            binary.to_str().unwrap(),
        ])
        .env(
            "TRACEJIT_CACHE_DIR",
            temporary.path().join("cache-inherited-alias"),
        )
        .stdin(std::process::Stdio::from(alias_input))
        .output()
        .unwrap();
    assert!(
        inherited.status.success(),
        "traced inherited alias failed: {}",
        String::from_utf8_lossy(&inherited.stderr)
    );
    let report: Value = serde_json::from_slice(&inherited.stdout).unwrap();
    assert_ne!(report["classification"], "Guarded", "{report}");
    assert!(
        report["reasons"]
            .to_string()
            .contains("shares its open file description"),
        "{report}"
    );

    // A different initial position must not reuse a record that started at zero.
    let offset_cache = temporary.path().join("cache-offset");
    assert_eq!(
        traced(&offset_cache, "read-seek-read", 0).0["cache_decision"],
        "Executed"
    );
    let (shifted_expected, shifted_position) = direct("read-seek-read", 2);
    let (shifted, position) = traced(&offset_cache, "read-seek-read", 2);
    assert_ne!(shifted["cache_decision"], "Reused", "{shifted}");
    assert_eq!(stdout_bytes_of(&shifted), shifted_expected);
    assert_eq!(position, shifted_position);

    // The content hash still invalidates a seek-using command.
    fs::write(&input, b"ABCDEFGHIJKLMNOP").unwrap();
    let (changed_expected, changed_position) = direct("read-seek-read", 0);
    let (changed, position) = traced(&offset_cache, "read-seek-read", 0);
    assert_ne!(changed["cache_decision"], "Reused", "{changed}");
    assert_eq!(stdout_bytes_of(&changed), changed_expected);
    assert_eq!(position, changed_position);

    eprintln!("RESULT inherited-stdin-seek PASS");
}

/// A vfork child can reach its first ptrace stop before the kernel reports the parent's
/// `PTRACE_EVENT_VFORK`. The tracer must reconcile that child from `/proc` and register it
/// idempotently, otherwise `make -j4` (which uses vfork) fails with a missing process state and the
/// traced command returns an error where the direct command succeeds.
#[test]
fn vfork_exec_children_are_registered_before_their_first_stop() {
    let temporary = tempfile::tempdir().unwrap();
    let source =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/spawn_storm.c");
    let binary = temporary.path().join("spawn-storm");
    let status = Command::new("cc")
        .args(["-O2", "-Wall", "-Wextra", "-Werror", "-pthread"])
        .arg(&source)
        .arg("-o")
        .arg(&binary)
        .status()
        .expect("C compiler must be available");
    assert!(status.success(), "spawn storm fixture compilation failed");
    let direct = Command::new(&binary)
        .args(["/bin/true", "40", "4"])
        .output()
        .unwrap();
    assert!(direct.status.success(), "the direct storm failed");
    let traced = invoke(
        &temporary.path().join("cache"),
        &[
            "run",
            "--json",
            "--",
            binary.to_str().unwrap(),
            "/bin/true",
            "40",
            "4",
        ],
        None,
    );
    assert!(
        traced.status.success(),
        "traced vfork storm failed: {}",
        String::from_utf8_lossy(&traced.stderr)
    );
    let report: Value = serde_json::from_slice(&traced.stdout).unwrap();
    assert_eq!(stdout_bytes_of(&report), direct.stdout);
    assert_eq!(traced.status.code(), direct.status.code());
    eprintln!("RESULT vfork-registration PASS");
}

/// A vfork child whose only action is `_exit(0)` can be reaped before the parent's vfork event is
/// processed. The event must not install state for an already-dead pid, which would wait forever
/// for a status that cannot arrive. `timeout` makes that stall a failure instead of a hung test.
#[test]
fn vfork_children_that_exit_without_exec_do_not_stall() {
    if !Command::new("timeout")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
    {
        eprintln!("RESULT vfork-exit SKIP timeout absent");
        return;
    }
    let temporary = tempfile::tempdir().unwrap();
    let source =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/spawn_storm.c");
    let binary = temporary.path().join("spawn-storm");
    let status = Command::new("cc")
        .args(["-O2", "-Wall", "-Wextra", "-Werror", "-pthread"])
        .arg(&source)
        .arg("-o")
        .arg(&binary)
        .status()
        .expect("C compiler must be available");
    assert!(status.success(), "spawn storm fixture compilation failed");
    let direct = Command::new(&binary)
        .args(["exit-without-exec", "40", "4"])
        .output()
        .unwrap();
    assert!(direct.status.success());
    let traced = Command::new("timeout")
        .args([
            "60",
            tracejit().to_str().unwrap(),
            "run",
            "--json",
            "--",
            binary.to_str().unwrap(),
            "exit-without-exec",
            "40",
            "4",
        ])
        .env("TRACEJIT_CACHE_DIR", temporary.path().join("cache"))
        .output()
        .unwrap();
    assert!(
        traced.status.success(),
        "traced exit-without-exec storm failed or stalled: {}",
        String::from_utf8_lossy(&traced.stderr)
    );
    let report: Value = serde_json::from_slice(&traced.stdout).unwrap();
    assert_eq!(stdout_bytes_of(&report), direct.stdout);
    eprintln!("RESULT vfork-exit PASS");
}

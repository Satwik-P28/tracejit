#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

fn tracejit() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_tracejit"))
}

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

#[test]
fn a_self_killed_child_is_reported_and_never_reused() {
    let fixture = Fixture::new();
    let args = ["run", "--", "sh", "-c", "kill -9 $$"];
    let first = invoke(&fixture.cache, &args, None);
    assert_eq!(first.status.code(), Some(137), "{}", stderr_of(&first));
    let second = invoke(&fixture.cache, &args, None);
    assert!(!hit(&second), "{}", stderr_of(&second));
}

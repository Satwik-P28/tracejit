#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use serde_json::Value;
use std::fs;
use std::fs::File;
use std::io::{Seek, SeekFrom, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

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

/// Marks every descriptor the harness did not hand to this child close-on-exec, **in the child**.
///
/// TraceJIT correctly refuses reuse when a non-CLOEXEC descriptor above stderr reaches the traced
/// child, so a descriptor this test process inherited from cargo, the shell or a CI runner makes
/// every ordinary integration test refuse. GitHub Actions hands the test process descriptors (142
/// and 145 in run `44235001207`) that no test created, no test owns, and no test can know about.
///
/// The sweep runs in `pre_exec`: after `fork`, before `exec`, in a child with exactly one thread
/// and a private copy of the descriptor table. That placement is the whole correctness argument.
///
/// * It cannot touch a descriptor belonging to an unrelated test or thread, because the parent's
///   table is not involved: the child owns its copy and is the only process that observes the
///   change. No lock, and no coordination with `std::process`, is required.
/// * `close_range(…, CLOSE_RANGE_CLOEXEC)` is one kernel call, so there is no
///   `F_GETFD`/`F_SETFD` window in which a slot could be closed and reused, and it reaches every
///   descriptor the process can own rather than a fixed 3..1023 range.
/// * It closes nothing. Every descriptor stays open and valid for the process that owns it; it
///   merely drops it from the `exec`. `Command`'s own spawn-error and stdio pipes are created
///   close-on-exec already and are installed with `dup2`, which clears the flag on the new
///   standard descriptors, so marking them again is a no-op.
///
/// This replaced a process-wide scan of descriptors 3..1023 run from a `Once` during normal
/// parallel test execution. That scan mutated descriptors owned by unrelated live threads, could
/// change another thread's intended child inheritance, could not reach descriptors above 1023, and
/// had a window between the flag query and the update.
fn without_inherited_descriptors(command: &mut Command) {
    let limit = descriptor_limit();
    // SAFETY: the closure runs between fork and exec in the child. It issues only the
    // `close_range`/`fcntl` syscalls, allocates nothing and takes no lock, so it is
    // async-signal-safe and cannot interact with a lock another thread held at `fork`.
    unsafe {
        command.pre_exec(move || {
            mark_above_stderr_close_on_exec(limit);
            Ok(())
        });
    }
}

/// Sets `FD_CLOEXEC` on every descriptor at or above 3 in the calling process.
///
/// Called only from `pre_exec`, where the calling process is the freshly forked child.
fn mark_above_stderr_close_on_exec(limit: u32) {
    let first = 3_u32;
    // SAFETY: `close_range` rewrites descriptor flags and borrows no memory from Rust.
    let flagged = unsafe {
        libc::syscall(
            libc::SYS_close_range,
            first,
            u32::MAX,
            libc::CLOSE_RANGE_CLOEXEC,
        )
    };
    if flagged == 0 {
        return;
    }
    // `close_range` arrived in Linux 5.9 and `CLOSE_RANGE_CLOEXEC` in 5.11. On an older kernel the
    // loop is still race-free for the same reason the syscall is: it runs in the forked child,
    // which has one thread, so no slot can be closed or reused between `F_GETFD` and `F_SETFD`.
    // It walks to `RLIMIT_NOFILE`, above which no descriptor can exist, so nothing escapes it.
    for fd in first..limit {
        let fd = fd as i32;
        // SAFETY: F_GETFD/F_SETFD only read or set descriptor flags; EBADF means an empty slot.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        if flags < 0 || flags & libc::FD_CLOEXEC != 0 {
            continue;
        }
        // SAFETY: the descriptor is open, so its descriptor flags can be updated.
        unsafe {
            libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC);
        }
    }
}

/// The first descriptor number that cannot exist in this process.
///
/// Read before the fork: the fallback sweep has to reach the highest possible descriptor, and
/// resolving `RLIM_INFINITY` means reading `/proc/sys/fs/nr_open`, which the child must not do
/// because it is not async-signal-safe.
fn descriptor_limit() -> u32 {
    let mut limit = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    // SAFETY: getrlimit writes the limits into the struct it is given.
    if unsafe { libc::getrlimit(libc::RLIMIT_NOFILE, &mut limit) } != 0 {
        return 1 << 20;
    }
    let limit = if limit.rlim_cur == libc::RLIM_INFINITY {
        fs::read_to_string("/proc/sys/fs/nr_open")
            .ok()
            .and_then(|value| value.trim().parse::<u64>().ok())
            .unwrap_or(1 << 20)
    } else {
        limit.rlim_cur
    };
    u32::try_from(limit).unwrap_or(u32::MAX).max(1 << 10)
}

/// Serialises the tests that both compile C and depend on a measured wall-clock threshold.
///
/// `auto_admission_skips_short_commands_and_caches_expensive_ones` decides by timing the direct
/// run; a concurrent compilation can push a short command over its 6 ms threshold and change the
/// decision for reasons that have nothing to do with the policy under test.
///
/// Poisoning is recovered rather than propagated. The guarded value is `()`: this lock orders
/// execution and protects no data, so there is no state that could be left inconsistent and
/// nothing a poisoned guard could hide. Propagating the poison would instead turn one real panic
/// into one failure plus a `PoisonError` panic in every later test that needs the lock, burying
/// the original defect. libtest still reports the test that actually panicked.
fn serial_timing_lock() -> std::sync::MutexGuard<'static, ()> {
    static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
    LOCK.lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

/// Runs one `#[test]` body in its own process and returns false in the parent.
///
/// Tests that deliberately leave a non-CLOEXEC descriptor open must not run beside tests that
/// spawn TraceJIT from the same process: the sibling's child inherits the descriptor and the
/// product correctly refuses it, which looks like a spurious failure. Re-executing this test
/// binary with `--exact` gives the test an otherwise empty descriptor table, so the behaviour it
/// asserts is its own and cannot affect any other test.
fn run_in_isolated_process(name: &str) -> bool {
    if std::env::var_os("TRACEJIT_ISOLATED_TEST_CHILD").is_some() {
        return true;
    }
    let executable = std::env::current_exe().expect("current test executable");
    let mut command = Command::new(executable);
    command
        .args(["--exact", name, "--nocapture", "--test-threads=1"])
        .env("TRACEJIT_ISOLATED_TEST_CHILD", "1");
    without_inherited_descriptors(&mut command);
    let output = command
        .output()
        .expect("re-execute the test binary for an isolated case");
    assert!(
        output.status.success(),
        "isolated case {name} failed: status {:?}\nstdout:\n{}\nstderr:\n{}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    false
}

/// Re-executes this test binary with `descriptors` open **and inheritable**, the way a CI runner
/// hands descriptors to the harness, and returns false in the parent.
///
/// The descriptors are installed with `dup2` in `pre_exec`, so they cross a real `exec` into the
/// new process: the reproduction does not depend on whatever a particular runner happens to leave
/// open, and the numbers (including one above the old 1023 sweep) are exact.
fn run_in_process_inheriting(name: &str, descriptors: &[i32]) -> bool {
    if std::env::var_os("TRACEJIT_ISOLATED_TEST_CHILD").is_some() {
        return true;
    }
    let executable = std::env::current_exe().expect("current test executable");
    let source = File::open("/dev/null").expect("/dev/null must be available");
    let source_fd = source.as_raw_fd();
    let numbers = descriptors.to_vec();
    let recorded = descriptors
        .iter()
        .map(i32::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let mut command = Command::new(executable);
    command
        .args(["--exact", name, "--nocapture", "--test-threads=1"])
        .env("TRACEJIT_ISOLATED_TEST_CHILD", "1")
        .env("TRACEJIT_INHERITED_TEST_DESCRIPTORS", &recorded);
    // SAFETY: pre_exec runs between fork and exec; dup2/fcntl are async-signal-safe and the source
    // descriptor stays open in the parent until the child has exec'd.
    unsafe {
        command.pre_exec(move || {
            for number in &numbers {
                if libc::dup2(source_fd, *number) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                // dup2 already clears FD_CLOEXEC on the new descriptor; state it so the
                // reproduction cannot silently become inheritable-descriptor-free.
                if libc::fcntl(*number, libc::F_SETFD, 0) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    let output = command
        .output()
        .expect("re-execute the test binary with inherited descriptors");
    assert!(
        output.status.success(),
        "isolated case {name} failed: status {:?}\nstdout:\n{}\nstderr:\n{}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    false
}

/// Marks a descriptor the harness hands to a child as close-on-exec.
///
/// The sweep in [`without_inherited_descriptors`] already covers the file itself; keeping its
/// descriptor close-on-exec states that the harness only means to pass it as stdio.
fn set_cloexec(file: &File) {
    // SAFETY: fcntl operates on a live descriptor owned by `file`.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFD) };
    assert!(flags >= 0, "F_GETFD failed");
    // SAFETY: the same live descriptor accepts F_SETFD with the existing flags plus CLOEXEC.
    let result = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_SETFD, flags | libc::FD_CLOEXEC) };
    assert_eq!(result, 0, "F_SETFD failed");
}

/// A `tracejit` invocation whose child cannot see a descriptor the harness did not hand it.
fn tracejit_command() -> Command {
    let mut command = Command::new(tracejit());
    without_inherited_descriptors(&mut command);
    command
}

fn invoke(cache: &Path, args: &[&str], extra_env: Option<(&str, &str)>) -> Output {
    match extra_env {
        Some(pair) => invoke_with_env(cache, args, &[pair]),
        None => invoke_with_env(cache, args, &[]),
    }
}

/// [`invoke`] with any number of extra environment variables.
fn invoke_with_env(cache: &Path, args: &[&str], extra_env: &[(&str, &str)]) -> Output {
    let mut command = tracejit_command();
    command
        .args(args)
        .env("TRACEJIT_CACHE_DIR", cache)
        // glibc seeds tcache with getrandom on first allocation. Disable tcache for these
        // syscall-classification fixtures so only fixture-requested randomness is observed.
        .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0");
    for (key, value) in extra_env {
        command.env(key, value);
    }
    command.output().unwrap()
}

/// GNU build ID of the runtime libc this host's dynamic linker resolves.
///
/// The `allocator-entropy-v1` contract admits exactly one audited build (build ID, call site,
/// destination and instruction bytes). A runner image whose libc was patched between image
/// rollouts is *legitimately* refused, which is the fail-closed behaviour itself; a contract test
/// that asserts a controlled HIT must therefore first establish that this runtime is the audited
/// one. `ci.yml` publishes this ID as a notice annotation on every run.
fn runtime_libc_build_id() -> Option<String> {
    [
        "/lib/x86_64-linux-gnu/libc.so.6",
        "/usr/lib/x86_64-linux-gnu/libc.so.6",
    ]
    .iter()
    .find_map(|path| tracejit_effects::elf_build_id(Path::new(path)))
}

/// Like [`invoke`], but the child keeps this process's descriptor table exactly as it is.
///
/// Only the inherited-descriptor regressions use this: they must present TraceJIT with a descriptor
/// this process deliberately holds, which sanitising the child would remove.
fn invoke_inheriting(cache: &Path, args: &[&str]) -> Output {
    Command::new(tracejit())
        .args(args)
        .env("TRACEJIT_CACHE_DIR", cache)
        .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0")
        .output()
        .unwrap()
}

/// Like [`invoke`], but with an explicit workload cwd.
///
/// CI runners often leave non-CLOEXEC descriptors above stderr; TraceJIT correctly refuses
/// reuse when those are inherited. The child is swept close-on-exec (see
/// [`without_inherited_descriptors`]) so the intended syscall path (O_TMPFILE, fcntl, renameat2, …)
/// is what produces Unknown — not the inherited-fd preflight.
fn invoke_in_workdir(cache: &Path, work: &Path, args: &[&str]) -> Output {
    let mut command = tracejit_command();
    command
        .args(args)
        .current_dir(work)
        .env("TRACEJIT_CACHE_DIR", cache)
        .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0");
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

/// `O_TMPFILE` must never be modeled as a pathname open/write of the parent directory.
///
/// The pathname argument is only a directory; the created inode is unnamed until a later
/// `linkat(AT_EMPTY_PATH)`. Recording Write against the directory path is incorrect Obs.
#[test]
fn otmpfile_is_unknown_and_never_reused() {
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("otmpfile.c");
    fs::write(
        &source,
        r#"#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#ifndef O_TMPFILE
#define O_TMPFILE (020000000 | O_DIRECTORY)
#endif
int main(void) {
    int fd = open(".", O_TMPFILE | O_RDWR, 0600);
    if (fd < 0) return 2;
    if (write(fd, "ZZZ", 3) != 3) return 3;
    close(fd);
    puts("ok");
    return 0;
}
"#,
    )
    .unwrap();
    let binary = temporary.path().join("otmpfile");
    assert!(
        Command::new("cc")
            .arg("-O0")
            .arg(&source)
            .arg("-o")
            .arg(&binary)
            .status()
            .unwrap()
            .success(),
        "otmpfile compilation failed"
    );
    let cache = temporary.path().join("cache");
    let work = temporary.path().join("work");
    fs::create_dir(&work).unwrap();
    let args = ["run", "--json", "--", binary.to_str().unwrap()];
    let cold = invoke_in_workdir(&cache, &work, &args);
    assert!(
        cold.status.success(),
        "{}",
        String::from_utf8_lossy(&cold.stderr)
    );
    let cold_report: Value = serde_json::from_slice(&cold.stdout).unwrap();
    assert_eq!(cold_report["classification"], "Unknown", "{cold_report}");
    assert_eq!(cold_report["eligible_for_reuse"], false, "{cold_report}");
    let reasons = cold_report["reasons"].as_array().unwrap();
    assert!(
        reasons
            .iter()
            .any(|reason| reason.as_str().unwrap_or_default().contains("O_TMPFILE")),
        "expected explicit O_TMPFILE refuse, got {cold_report}"
    );
    assert!(
        reasons.iter().all(|reason| {
            !reason
                .as_str()
                .unwrap_or_default()
                .contains("inherited descriptor")
        }),
        "harness must close inherited fds so O_TMPFILE is observed: {cold_report}"
    );

    let warm = invoke_in_workdir(&cache, &work, &args);
    assert!(
        warm.status.success(),
        "{}",
        String::from_utf8_lossy(&warm.stderr)
    );
    let warm_report: Value = serde_json::from_slice(&warm.stdout).unwrap();
    assert_ne!(
        warm_report["kind"], "Reused",
        "O_TMPFILE must never HIT: {warm_report}"
    );
}

/// Mutating `fcntl` commands (e.g. `F_SETFL`) must not be silently treated as process-internal.
#[test]
fn fcntl_setfl_is_unknown_and_never_reused() {
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("fcntl_setfl.c");
    fs::write(
        &source,
        r#"#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(void) {
    int fd = open("out.txt", O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) return 1;
    if (write(fd, "AA", 2) != 2) return 1;
    int fl = fcntl(fd, F_GETFL);
    if (fl < 0) return 1;
    if (fcntl(fd, F_SETFL, fl | O_APPEND) != 0) return 1;
    if (write(fd, "BB", 2) != 2) return 1;
    close(fd);
    puts("ok");
    return 0;
}
"#,
    )
    .unwrap();
    let binary = temporary.path().join("fcntl_setfl");
    assert!(
        Command::new("cc")
            .arg("-O0")
            .arg(&source)
            .arg("-o")
            .arg(&binary)
            .status()
            .unwrap()
            .success(),
        "fcntl_setfl compilation failed"
    );
    let cache = temporary.path().join("cache");
    let work = temporary.path().join("work");
    fs::create_dir(&work).unwrap();
    let args = ["run", "--json", "--", binary.to_str().unwrap()];
    let cold = invoke_in_workdir(&cache, &work, &args);
    assert!(
        cold.status.success(),
        "{}",
        String::from_utf8_lossy(&cold.stderr)
    );
    let cold_report: Value = serde_json::from_slice(&cold.stdout).unwrap();
    assert_eq!(cold_report["classification"], "Unknown", "{cold_report}");
    assert_eq!(cold_report["eligible_for_reuse"], false, "{cold_report}");
    let reasons = cold_report["reasons"].as_array().unwrap();
    // `O_APPEND` changes where the next write lands. The status-flag rule admits only an
    // `O_NONBLOCK` change on a private regular file, so this rewrite must still refuse and name
    // the flag it rejected.
    assert!(
        reasons.iter().any(|reason| {
            let text = reason.as_str().unwrap_or_default();
            text.contains("status-flag change") && text.contains("beyond O_NONBLOCK")
        }),
        "expected the O_APPEND rewrite to be refused, got {cold_report}"
    );
    assert!(
        reasons.iter().all(|reason| {
            !reason
                .as_str()
                .unwrap_or_default()
                .contains("inherited descriptor")
        }),
        "harness must close inherited fds so fcntl is observed: {cold_report}"
    );

    let warm = invoke_in_workdir(&cache, &work, &args);
    assert!(
        warm.status.success(),
        "{}",
        String::from_utf8_lossy(&warm.stderr)
    );
    let warm_report: Value = serde_json::from_slice(&warm.stdout).unwrap();
    assert_ne!(
        warm_report["kind"], "Reused",
        "fcntl F_SETFL must never HIT: {warm_report}"
    );
    assert_eq!(fs::read(work.join("out.txt")).unwrap(), b"AABB");
}

/// A leftover restore-intent marker from a dead pid must refuse HIT (hard-kill recovery).
#[test]
fn interrupted_restore_intent_refuses_hit() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    // Simulate hard-kill of another process: plant a dead-pid intent under the cache root.
    let dead_pid = 2_147_483_646_u32;
    let intent = fixture
        .cache
        .join(format!("restore-intent.v1.{dead_pid}.json"));
    fs::write(
        &intent,
        format!(r#"{{"version":1,"pid":{dead_pid},"destinations":["/tmp/synthetic-output"]}}"#),
    )
    .unwrap();
    let warm = invoke(
        &fixture.cache,
        &[
            "run",
            "--json",
            "--",
            fixture.binary_arg(),
            "plain_file_read",
            fixture.root(),
        ],
        None,
    );
    assert!(warm.status.success(), "{}", stderr_of(&warm));
    let report: Value = serde_json::from_slice(&warm.stdout).unwrap();
    assert_ne!(
        report["kind"], "Reused",
        "interrupted restore must not HIT: {report}"
    );
    let reason = report["decision_reason"].as_str().unwrap_or_default();
    assert!(
        reason.contains("restore was interrupted") || reason.contains("refusing HIT"),
        "expected interrupted-restore reason, got {report}"
    );
    assert!(
        !intent.exists(),
        "dead intent must be consumed so a later clean run is not blocked forever"
    );
}

/// The pre-restore guard pass must refuse a HIT when an input changed before it ran.
///
/// Uses `TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH` (test hook; unset in production) to inject the
/// mutation deterministically immediately before that pass. Residual TOCTOU during the restore
/// remains a documented limitation.
#[test]
fn toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let input = fixture.input("input.txt");
    let before = fs::read(&input).unwrap();
    assert_ne!(before, b"TOCTOU-MUTATED\n");

    let warm = invoke(
        &fixture.cache,
        &[
            "run",
            "--json",
            "--",
            fixture.binary_arg(),
            "plain_file_read",
            fixture.root(),
        ],
        Some((
            "TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH",
            input.to_str().unwrap(),
        )),
    );
    assert!(warm.status.success(), "{}", stderr_of(&warm));
    let report: Value = serde_json::from_slice(&warm.stdout).unwrap_or_else(|_| {
        panic!(
            "invalid JSON: stdout={} stderr={}",
            String::from_utf8_lossy(&warm.stdout),
            stderr_of(&warm)
        )
    });
    assert_ne!(
        report["kind"], "Reused",
        "mutated input in validate→restore window must not HIT: {report}"
    );
    // Hook overwrote the input; retrace must observe the mutated world rather than stale cache.
    assert_eq!(fs::read(&input).unwrap(), b"TOCTOU-MUTATED\n");
}

/// The class Phase X newly accepts, proved sound: an input that changes inside the window the
/// removed first pass used to cover, and is reverted before the surviving pass, is a hit whose
/// bytes equal native execution.
///
/// The pre-load hook mutates `input.txt` and then writes the recorded bytes back, so the surviving
/// pass sees exactly what the record expects. Under the old two-pass order the first pass would
/// have refused this (it observed the mutated content); the surviving pass is the one that decides,
/// and the state it validates is the state the restore runs against.
#[test]
fn a_mutation_before_candidate_loading_that_is_restored_is_a_sound_hit() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let input = fixture.input("input.txt");
    let recorded = fs::read(&input).unwrap();
    let restored = recorded
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let native = Command::new(fixture.binary_arg())
        .args(["plain_file_read", fixture.root()])
        .output()
        .unwrap();
    assert!(native.status.success());

    let run = invoke_with_env(
        &fixture.cache,
        &[
            "run",
            "--json",
            "--",
            fixture.binary_arg(),
            "plain_file_read",
            fixture.root(),
        ],
        &[
            (
                "TRACEJIT_TEST_PRE_LOAD_MUTATE_PATH",
                input.to_str().unwrap(),
            ),
            ("TRACEJIT_TEST_PRE_LOAD_RESTORE_HEX", restored.as_str()),
        ],
    );
    assert!(run.status.success(), "{}", stderr_of(&run));
    let report: Value = serde_json::from_slice(&run.stdout).unwrap();
    assert_eq!(
        report["cache_decision"], "Reused",
        "a mutation reverted before the surviving pass must not poison a hit: {report}"
    );
    assert_eq!(
        stdout_bytes_of(&report),
        native.stdout,
        "replayed bytes must equal native execution: {report}"
    );
    assert_eq!(
        report["exit_code"].as_i64(),
        native.status.code().map(i64::from),
        "exit status"
    );
    assert_eq!(
        fs::read(&input).unwrap(),
        recorded,
        "the input is back to the recorded content"
    );
    eprintln!("RESULT pre-load-mutate-restored PASS");
}

/// A cached object that is missing must deopt and retrace, not abort the command.
///
/// Manual pruning, a partial copy or an interrupted eviction leaves a live record naming an
/// object that is gone. Serving it is impossible; failing the command is also wrong, because the
/// identical command line succeeds when simply executed again.
#[test]
fn a_missing_cached_object_retraces_instead_of_aborting() {
    let fixture = Fixture::new();
    let output = fixture.input("output.txt");
    let _ = fs::remove_file(&output);
    let args = [
        "run",
        "--json",
        "--",
        fixture.binary_arg(),
        "output_presence_stdout",
        fixture.root(),
    ];
    let first = invoke(&fixture.cache, &args, None);
    assert!(first.status.success(), "{}", stderr_of(&first));
    assert_eq!(fs::read(&output).unwrap(), b"ABSENT\n");

    let explanation = invoke(&fixture.cache, &["explain", "--json"], None);
    let record: Value = serde_json::from_slice(&explanation.stdout).unwrap();
    let hash = record["stdout"]
        .as_array()
        .map(|bytes| {
            bytes
                .iter()
                .map(|byte| format!("{:02x}", byte.as_u64().unwrap() as u8))
                .collect::<String>()
        })
        .unwrap_or_else(|| panic!("no recorded stdout object: {record}"));
    fs::remove_file(fixture.cache.join("objects").join(hash)).unwrap();
    fs::remove_file(&output).unwrap();

    let run = invoke(&fixture.cache, &args, None);
    assert!(
        run.status.success(),
        "a pruned object must not make the command fatal: {}",
        stderr_of(&run)
    );
    let report: Value = serde_json::from_slice(&run.stdout).unwrap();
    assert_ne!(report["kind"], "Reused", "{report}");
    assert_eq!(stdout_bytes_of(&report), b"stream fixture\n");
    assert_eq!(fs::read(&output).unwrap(), b"ABSENT\n");
    eprintln!("RESULT missing-object-retrace PASS");
}

/// Retained candidates whose inputs no longer match must never be selected by process of
/// elimination. The third content is recorded by neither candidate, so the only sound outcome is
/// a retrace that observes it.
#[test]
fn retained_candidates_with_an_unrecorded_input_never_hit() {
    let fixture = Fixture::new();
    let input = fixture.input("input.txt");
    for content in [b"input one\n".as_slice(), b"second variant\n"] {
        fs::write(&input, content).unwrap();
        let run = fixture.run("plain_file_read");
        assert!(run.status.success(), "{}", stderr_of(&run));
    }
    fs::write(&input, b"third variant\n").unwrap();
    let native = Command::new(fixture.binary_arg())
        .args(["plain_file_read", fixture.root()])
        .output()
        .unwrap();
    let run = fixture.run("plain_file_read");
    assert!(run.status.success(), "{}", stderr_of(&run));
    assert!(
        !hit(&run),
        "neither retained candidate describes the current input: {}",
        stderr_of(&run)
    );
    assert_eq!(
        run.stdout, native.stdout,
        "the retrace must observe the current input"
    );
    eprintln!("RESULT mixed-candidates-unrecorded-input PASS");
}

/// `renameat2(RENAME_EXCHANGE)` must never become a Guarded hit.
///
/// Phase K adversarial audit: the tracer previously ignored renameat2 flags and recorded
/// Delete(from)+RenameDestination(to). On HIT that deleted `from` while a native exchange leaves
/// both paths present with swapped bytes — a false-positive Obs mismatch. Fail closed.
#[test]
fn renameat2_exchange_is_unknown_and_never_reused() {
    let temporary = tempfile::tempdir().unwrap();
    let source = temporary.path().join("exchange.c");
    fs::write(
        &source,
        r#"#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>
#ifndef RENAME_EXCHANGE
#define RENAME_EXCHANGE (1 << 1)
#endif
int main(void) {
    int fd = open("a", O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 1;
    if (write(fd, "AAA", 3) != 3) return 1;
    close(fd);
    fd = open("b", O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return 1;
    if (write(fd, "BBB", 3) != 3) return 1;
    close(fd);
    return syscall(SYS_renameat2, AT_FDCWD, "a", AT_FDCWD, "b", RENAME_EXCHANGE) != 0;
}
"#,
    )
    .unwrap();
    let binary = temporary.path().join("exchange");
    assert!(
        Command::new("cc")
            .arg("-O0")
            .arg(&source)
            .arg("-o")
            .arg(&binary)
            .status()
            .unwrap()
            .success(),
        "exchange compilation failed"
    );
    let cache = temporary.path().join("cache");
    let args = ["run", "--json", "--", binary.to_str().unwrap()];
    let work = temporary.path().join("work");
    fs::create_dir(&work).unwrap();
    let cold = invoke_in_workdir(&cache, &work, &args);
    assert!(
        cold.status.success(),
        "{}",
        String::from_utf8_lossy(&cold.stderr)
    );
    let cold_report: Value = serde_json::from_slice(&cold.stdout).unwrap();
    assert_eq!(cold_report["classification"], "Unknown", "{cold_report}");
    assert_eq!(cold_report["eligible_for_reuse"], false, "{cold_report}");
    let cold_a = fs::read(work.join("a")).unwrap_or_default();
    let cold_b = fs::read(work.join("b")).unwrap_or_default();
    assert_eq!(cold_a, b"BBB", "native exchange must leave a=BBB");
    assert_eq!(cold_b, b"AAA", "native exchange must leave b=AAA");

    let warm = invoke_in_workdir(&cache, &work, &args);
    assert!(
        warm.status.success(),
        "{}",
        String::from_utf8_lossy(&warm.stderr)
    );
    let warm_report: Value = serde_json::from_slice(&warm.stdout).unwrap();
    assert_ne!(
        warm_report["kind"], "Reused",
        "exchange must never HIT: {warm_report}"
    );
    assert_ne!(
        warm_report["cache_decision"], "Reused",
        "exchange must never HIT: {warm_report}"
    );
    let warm_a = fs::read(work.join("a")).unwrap_or_default();
    let warm_b = fs::read(work.join("b")).unwrap_or_default();
    assert_eq!(
        warm_a, b"BBB",
        "warm Obs must match native a=BBB, not delete a"
    );
    assert_eq!(warm_b, b"AAA", "warm Obs must match native b=AAA");
}

/// A program that stats its own output path must not reuse across a presence change.
///
/// This is the Phase 2O release blocker: the contract dropped output metadata for *any* binary
/// behind the flag, so an un-audited program's "absent" branch was replayed after the path
/// appeared. The observation must stay a real negative dependency unless the observing process is
/// the audited toolchain.
#[test]
fn un_audited_program_does_not_reuse_across_its_output_presence_change() {
    let _serial = serial_timing_lock();
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
    let _serial = serial_timing_lock();
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
    let _serial = serial_timing_lock();
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
    let _serial = serial_timing_lock();
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
    let _serial = serial_timing_lock();
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

/// A delete that the same execution replaces must not pin the next run to the old bytes.
///
/// This is the compiler pattern (`cc` removes its object, then recreates it). The tracer takes a
/// pre-`unlink` snapshot for its own bookkeeping; recording that snapshot as an input dependency
/// made every record describe the bytes it destroyed, so after a source edit the *next* run
/// deoptimised again because the object on disk was now the one the previous execution had just
/// produced. Two deoptimisations per edit, for one real input change.
#[test]
fn superseded_delete_does_not_pin_the_next_run_to_the_old_bytes() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "replace_output",
        temporary.path().to_str().unwrap(),
    ];
    let input = temporary.path().join("input.txt");
    let output = temporary.path().join("output.txt");
    // A previous build's result: the command's unlink succeeds, exactly as `cc -o` removes an
    // object it is about to replace. Deleting a path that does not exist is an unguardable failed
    // effect and correctly classifies the run as Unknown.
    fs::write(&output, b"stale result\n").unwrap();

    let first = invoke(&cache, &args, None);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["kind"], "Executed", "{first}");
    assert_eq!(first["classification"], "Guarded", "{first}");
    assert_eq!(fs::read(&output).unwrap(), b"input one\n");

    // One real input change: the next run must execute and produce the new bytes.
    fs::write(&input, b"input two\n").unwrap();
    let second = invoke(&cache, &args, None);
    assert!(second.status.success());
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_ne!(second["kind"], "Reused", "{second}");
    assert_eq!(fs::read(&output).unwrap(), b"input two\n");

    // Nothing changed since that execution. The record it produced describes this exact workspace
    // state; the bytes it removed on the way are not an input.
    let third = invoke(&cache, &args, None);
    assert!(third.status.success());
    let third: Value = serde_json::from_slice(&third.stdout).unwrap();
    assert_eq!(
        third["kind"], "Reused",
        "a replaced pre-state must not force a second deoptimisation: {third}"
    );
    assert_eq!(fs::read(&output).unwrap(), b"input two\n");

    // A destructive external change to the output is still restored, because the record only
    // claims the pre-state class it actually needs.
    fs::write(&output, b"externally corrupted\n").unwrap();
    let restored = invoke(&cache, &args, None);
    assert!(restored.status.success());
    let restored: Value = serde_json::from_slice(&restored.stdout).unwrap();
    assert_eq!(restored["kind"], "Reused", "{restored}");
    assert_eq!(fs::read(&output).unwrap(), b"input two\n");
    eprintln!("RESULT superseded-delete PASS");
}

/// A terminal deletion still depends on the bytes it removed.
///
/// The complementary rule to the test above: when the execution leaves the path absent, the
/// content that existed before it is part of the recorded effect, so a path that now holds
/// different data must deoptimise rather than be silently deleted from a stale record.
#[test]
fn terminal_delete_still_requires_the_deleted_bytes() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let output = temporary.path().join("output.txt");
    fs::write(&output, b"keep one\n").unwrap();
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "delete_only",
        temporary.path().to_str().unwrap(),
    ];

    let first = invoke(&cache, &args, None);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["kind"], "Executed", "{first}");
    assert!(!output.exists());

    // Re-create the path with different bytes. A HIT here would delete data the traced run never
    // observed, so the record must refuse.
    fs::write(&output, b"keep two\n").unwrap();
    let second = invoke(&cache, &args, None);
    assert!(second.status.success());
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(
        second["cache_decision"], "Deoptimized",
        "a terminal deletion must validate the bytes it removes: {second}"
    );
    assert!(!output.exists());
    eprintln!("RESULT terminal-delete PASS");
}

/// The source side of a rename is content that moves, not pre-state that disappears.
///
/// `rename(output, second)` moves the previous result to another pathname the record restores as
/// an output, and only then re-creates `output`. Treating the source snapshot as superseded
/// pre-state dropped the only guard on those bytes: a warm run whose `output.txt` held different
/// data reused the record and restored the *old* bytes into `second.txt`, which native execution
/// never produces. The destination's own pre-state may still be elided; the source's may not.
#[test]
fn rename_source_bytes_are_an_input_even_when_the_source_is_recreated() {
    let temporary = tempfile::tempdir().unwrap();
    workspace(temporary.path());
    let binary = compile_fixture(temporary.path());
    let cache = temporary.path().join("cache");
    let output = temporary.path().join("output.txt");
    let second = temporary.path().join("second.txt");
    fs::write(&output, b"old result\n").unwrap();
    let args = [
        "run",
        "--json",
        "--",
        binary.to_str().unwrap(),
        "rename_aside_recreate",
        temporary.path().to_str().unwrap(),
    ];

    let first = invoke(&cache, &args, None);
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let first: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(first["kind"], "Executed", "{first}");
    assert_eq!(first["classification"], "Guarded", "{first}");
    assert_eq!(fs::read(&second).unwrap(), b"old result\n");
    assert_eq!(fs::read(&output).unwrap(), b"fresh\n");

    // Different pre-state bytes: the bytes that would be moved into `second.txt` differ, so a
    // cached destination is a false hit.
    fs::write(&output, b"changed result that is longer\n").unwrap();
    let second_run = invoke(&cache, &args, None);
    assert!(second_run.status.success());
    let second_run: Value = serde_json::from_slice(&second_run.stdout).unwrap();
    assert_ne!(
        second_run["kind"], "Reused",
        "a relocated pre-state must not be replayed from stale bytes: {second_run}"
    );
    assert_eq!(
        fs::read(&second).unwrap(),
        b"changed result that is longer\n"
    );
    assert_eq!(fs::read(&output).unwrap(), b"fresh\n");

    // The guard is a real dependency, not a permanent refusal: put the pre-state the record
    // describes back, and the execution must replay with the same restored destination.
    fs::write(&output, b"changed result that is longer\n").unwrap();
    let third = invoke(&cache, &args, None);
    assert!(third.status.success());
    let third: Value = serde_json::from_slice(&third.stdout).unwrap();
    assert_eq!(third["kind"], "Reused", "{third}");
    assert_eq!(
        fs::read(&second).unwrap(),
        b"changed result that is longer\n"
    );
    assert_eq!(fs::read(&output).unwrap(), b"fresh\n");
    eprintln!("RESULT rename-source-flow PASS");
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
    for case in [
        "getrandom",
        "unknown_ioctl",
        "network_send",
        "vdso_clock",
        "mmap_anon_shared",
        "hardlink_create",
        "rename_exchange",
        "at_empty_path",
    ] {
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
    let mut sandbox = Command::new(std::env::current_exe().unwrap());
    sandbox
        .args(["--exact", "sandbox_child", "--nocapture"])
        .env("TRACEJIT_SANDBOX_CHILD", "1")
        .env("TRACEJIT_DECLARED", &declared)
        .env("TRACEJIT_UNDECLARED", &undeclared);
    without_inherited_descriptors(&mut sandbox);
    let status = sandbox.status().unwrap();
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
    assert_eq!(first["contract"], "tracejit.allocator-entropy.v1");
    let second = invoke(&cache, &args, None);
    let second: Value = serde_json::from_slice(&second.stdout).unwrap();
    if let Some(build_id) = runtime_libc_build_id()
        .filter(|build_id| tracejit_effects::allocator_entropy_profile(build_id).is_none())
    {
        // An unaudited runtime is refused; that refusal, and the identical bytes, are what the
        // contract promises. The audited-runtime reuse path is exercised whenever the runner
        // image carries the audited glibc build.
        assert_eq!(first["classification"], "Nondeterministic", "{first}");
        assert_ne!(second["cache_decision"], "Reused", "{second}");
        assert_eq!(stdout_bytes_of(&first), expected);
        assert_eq!(stdout_bytes_of(&second), expected);
        eprintln!("RESULT controlled-sed SKIP unaudited runtime {build_id}");
        return;
    }
    assert_eq!(first["classification"], "Guarded", "{first}");
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
    let output = tracejit_command()
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
fn run_with_stdin(fixture: &Fixture, case: &str, stdin: &Path) -> Output {
    let mut command = tracejit_command();
    command
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
        .stdin(Stdio::from(File::open(stdin).unwrap()));
    command.output().unwrap()
}

/// Runs the fixture with descriptor 9 independently supplied from `source`, or closed. `traced`
/// selects TraceJIT with a shared cache; the direct arm uses the same descriptor setup so the
/// output comparison is against native execution.
fn run_with_fd9(fixture: &Fixture, case: &str, source: Option<&File>, traced: bool) -> Output {
    let source_fd = source.map_or(-1, AsRawFd::as_raw_fd);
    let mut command = if traced {
        let mut command = tracejit_command();
        command.args([
            "run",
            "--json",
            "--",
            fixture.binary_arg(),
            case,
            fixture.root(),
        ]);
        command.env("TRACEJIT_CACHE_DIR", &fixture.cache);
        command.env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0");
        command
    } else {
        let mut command = Command::new(fixture.binary_arg());
        command.args([case, fixture.root()]);
        command
    };
    command.stdin(Stdio::null());
    // SAFETY: pre_exec runs between fork and exec; dup2/fcntl/close are async-signal-safe and the
    // source descriptor remains open in the parent until the child has exec'd. The sweep that
    // marks unrelated descriptors close-on-exec is registered first, so the descriptor installed
    // here survives it and only descriptor 9 is touched afterwards.
    unsafe {
        command.pre_exec(move || {
            if source_fd >= 0 {
                install_inheritable_fd9(source_fd)?;
            } else {
                // SAFETY: close is async-signal-safe; EBADF means 9 was already empty.
                libc::close(9);
            }
            Ok(())
        });
    }
    command.output().unwrap()
}

/// Place `source_fd` at descriptor 9 **without** FD_CLOEXEC so it survives `exec` of TraceJIT.
///
/// `std::fs::File::open` uses `O_CLOEXEC`. Linux `dup2(old, old)` is a no-op that preserves
/// CLOEXEC, so when the harness source already is fd 9 (common under parallel tests that fill
/// 3..8), a naive dup2 leaves CLOEXEC set and the kernel drops fd 9 at exec — TraceJIT then
/// traces a child that gets EBADF on `read(9)`, exits 3, and the test sees empty stderr.
fn install_inheritable_fd9(source_fd: i32) -> std::io::Result<()> {
    if source_fd != 9 {
        // SAFETY: dup2 is async-signal-safe; caller verified source_fd is live.
        if unsafe { libc::dup2(source_fd, 9) } < 0 {
            return Err(std::io::Error::last_os_error());
        }
        // SAFETY: close is async-signal-safe; source_fd is distinct from 9.
        unsafe {
            libc::close(source_fd);
        }
    }
    // Clear CLOEXEC whether we dup2'd or source_fd was already 9.
    // SAFETY: F_SETFD on the live fd 9 we just installed.
    if unsafe { libc::fcntl(9, libc::F_SETFD, 0) } < 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

fn pipe_with_data() -> File {
    let mut descriptors = [-1; 2];
    // CLOEXEC matters here: a plain `pipe` would stay inheritable in the shared test process and
    // every concurrently spawned TraceJIT child would inherit it, correctly refusing reuse for a
    // descriptor this test created. The child still receives the bytes because `run_with_fd9`
    // installs descriptor 9 itself in `pre_exec`.
    // SAFETY: the array has room for both descriptors; successful pipe2 initializes them.
    assert_eq!(
        unsafe { libc::pipe2(descriptors.as_mut_ptr(), libc::O_CLOEXEC) },
        0
    );
    // SAFETY: ownership of each successful pipe descriptor is transferred exactly once.
    let read_end = unsafe { File::from_raw_fd(descriptors[0]) };
    // SAFETY: ownership of each successful pipe descriptor is transferred exactly once.
    let mut write_end = unsafe { File::from_raw_fd(descriptors[1]) };
    write_end.write_all(b"pipe bytes\n").unwrap();
    drop(write_end);
    read_end
}

/// A descriptor the *parent* holds without `FD_CLOEXEC` really is inherited by the traced child.
///
/// Reuse must be refused before lookup: the description's identity, flags and offset are not part
/// of the cache key, so a later run could point the same number at a different source. This case
/// exercises the ordinary inheritance path (no `pre_exec`), which is how a caller's shell or build
/// tool supplies descriptors, rather than the explicit descriptor-9 fixture below.
///
/// Isolated: the descriptor is deliberately inheritable, so it must never be visible to a sibling
/// test's spawn.
#[test]
fn an_inheritable_parent_descriptor_is_refused() {
    if !run_in_isolated_process("an_inheritable_parent_descriptor_is_refused") {
        return;
    }
    let fixture = Fixture::new();
    let args = [
        "run",
        "--json",
        "--",
        fixture.binary_arg(),
        "plain_file_read",
        fixture.root(),
    ];

    // 1. Baseline: with nothing extra inherited the command is eligible and genuinely reused, so a
    // refusal below cannot be caused by anything but the descriptor this test adds. The baseline
    // spawn sweeps its child, so a descriptor this process inherited from its own parent cannot
    // stand in for the one added below.
    let baseline_first: Value =
        serde_json::from_slice(&invoke(&fixture.cache, &args, None).stdout).unwrap();
    assert_eq!(
        baseline_first["eligible_for_reuse"], true,
        "{baseline_first}"
    );
    assert_eq!(baseline_first["kind"], "Executed", "{baseline_first}");
    let baseline_second: Value =
        serde_json::from_slice(&invoke(&fixture.cache, &args, None).stdout).unwrap();
    assert_eq!(
        baseline_second["kind"], "Reused",
        "the baseline must reuse before a descriptor is added: {baseline_second}"
    );

    // 2. A descriptor this process deliberately leaves inheritable.
    let source = File::open(fixture.input("input.txt")).unwrap();
    let fd = source.as_raw_fd();
    assert!(
        fd > 2,
        "the inherited descriptor must be above stderr: {fd}"
    );
    // SAFETY: fcntl operates on the live descriptor owned by `source`.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    assert!(flags >= 0, "F_GETFD failed");
    assert_eq!(
        unsafe { libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) },
        0,
        "clearing FD_CLOEXEC failed"
    );
    let expected = format!("inherited descriptor {fd}");

    // 3. No HIT while the descriptor is inherited, and the reason names its number. Repeat, because
    // a first refusal that wrote or consumed a record would show up as a HIT the second time.
    // These spawns keep the descriptor table: the descriptor has to reach TraceJIT to be refused.
    let first = invoke_inheriting(&fixture.cache, &args);
    assert!(first.status.success(), "{}", stderr_of(&first));
    let first_report: Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(
        first_report["eligible_for_reuse"], false,
        "an inherited descriptor must never be eligible: {first_report}"
    );
    assert!(
        first_report["reasons"].to_string().contains(&expected),
        "the refusal must name descriptor {fd}: {first_report}"
    );
    let second = invoke_inheriting(&fixture.cache, &args);
    assert!(second.status.success(), "{}", stderr_of(&second));
    let second_report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(
        second_report["kind"], "Executed",
        "no HIT may be served while the descriptor is inherited: {second_report}"
    );
    assert!(
        second_report["reasons"].to_string().contains(&expected),
        "{second_report}"
    );

    // The fallback runs the command natively, so its observation is the native one.
    let native = Command::new(fixture.binary_arg())
        .args(["plain_file_read", fixture.root()])
        .output()
        .unwrap();
    assert_eq!(
        second_report["exit_code"].as_i64(),
        native.status.code().map(i64::from)
    );
    assert_eq!(stdout_bytes_of(&second_report), native.stdout);

    // 4. Closing it restores reuse: the refusal is scoped to the inherited table and does not
    // poison the record written while the table was clean.
    drop(source);
    let restored: Value =
        serde_json::from_slice(&invoke(&fixture.cache, &args, None).stdout).unwrap();
    assert_eq!(
        restored["kind"], "Reused",
        "reuse must return once the extra descriptor is closed: {restored}"
    );
    eprintln!("RESULT inherited-parent-descriptor-refused PASS");
}

/// The descriptor table a CI runner hands the harness must not contaminate ordinary runs, and a
/// genuinely inherited descriptor must still be refused.
///
/// Run `44235001207` failed because the runner left descriptors 142 and 145 open without
/// `FD_CLOEXEC` in the integration binary. This case re-executes the test binary with exactly those
/// descriptors (plus 1500, above the old 3..1023 sweep) open and inheritable, so the condition
/// crosses a real `exec` and is deterministic instead of depending on a particular runner.
#[test]
fn runner_inherited_descriptors_do_not_contaminate_runs_and_are_still_refused() {
    let name = "runner_inherited_descriptors_do_not_contaminate_runs_and_are_still_refused";
    if !run_in_process_inheriting(name, &[142, 145, 1500]) {
        return;
    }
    let inherited: Vec<i32> = std::env::var("TRACEJIT_INHERITED_TEST_DESCRIPTORS")
        .expect("the parent records the descriptors it installed")
        .split(',')
        .map(|value| value.parse().expect("a descriptor number"))
        .collect();
    assert_eq!(inherited, vec![142, 145, 1500]);
    for fd in &inherited {
        // SAFETY: F_GETFD only reads descriptor flags.
        let flags = unsafe { libc::fcntl(*fd, libc::F_GETFD) };
        assert!(flags >= 0, "descriptor {fd} was not inherited");
        assert_eq!(
            flags & libc::FD_CLOEXEC,
            0,
            "descriptor {fd} must still be inheritable: that is the runner condition"
        );
    }

    let fixture = Fixture::new();
    let args = [
        "run",
        "--json",
        "--",
        fixture.binary_arg(),
        "plain_file_read",
        fixture.root(),
    ];

    // 1. A spawn that sweeps its child is unaffected: no inherited-descriptor refusal, no `EBADF`
    //    from the spawn-error or stdio pipes, and an ordinary HIT. This is exactly what failed on
    //    the runner.
    let baseline: Value =
        serde_json::from_slice(&invoke(&fixture.cache, &args, None).stdout).unwrap();
    assert_eq!(baseline["kind"], "Executed", "{baseline}");
    let reused_output = invoke(&fixture.cache, &args, None);
    assert!(
        reused_output.status.success(),
        "{}",
        stderr_of(&reused_output)
    );
    let reused: Value = serde_json::from_slice(&reused_output.stdout).unwrap();
    assert_eq!(
        reused["kind"], "Reused",
        "an ordinary run must ignore the runner's descriptors: {reused}"
    );

    // 2. Handing the same table over unchanged is refused before lookup. `/proc` enumeration order
    //    is not sorted, so the refusal names one of the inherited descriptors; the single-descriptor
    //    case below pins the identity exactly.
    let handed = invoke_inheriting(&fixture.cache, &args);
    assert!(handed.status.success(), "{}", stderr_of(&handed));
    let handed_report: Value = serde_json::from_slice(&handed.stdout).unwrap();
    assert_eq!(
        handed_report["eligible_for_reuse"], false,
        "an inherited runner descriptor must never be eligible: {handed_report}"
    );
    let reasons = handed_report["reasons"].to_string();
    assert!(
        inherited
            .iter()
            .any(|fd| reasons.contains(format!("inherited descriptor {fd}").as_str())),
        "the refusal must name an inherited descriptor: {handed_report}"
    );

    // The refusal path still runs the program natively, so output and status are the native ones.
    let native = Command::new(fixture.binary_arg())
        .args(["plain_file_read", fixture.root()])
        .output()
        .unwrap();
    assert_eq!(
        handed_report["exit_code"].as_i64(),
        native.status.code().map(i64::from)
    );
    assert_eq!(stdout_bytes_of(&handed_report), native.stdout);

    // 3. A descriptor above 1023 is enumerated too: neither the sweep nor the preflight is a fixed
    //    range, so the last remaining inherited descriptor is named exactly.
    // SAFETY: 142 and 145 belong to this private process.
    unsafe {
        libc::close(142);
        libc::close(145);
    }
    let high = invoke_inheriting(&fixture.cache, &args);
    assert!(high.status.success(), "{}", stderr_of(&high));
    let high_report: Value = serde_json::from_slice(&high.stdout).unwrap();
    assert!(
        high_report["reasons"]
            .to_string()
            .contains("inherited descriptor 1500"),
        "a descriptor above the old 1023 sweep must still be refused: {high_report}"
    );

    // 4. Closing it restores reuse: the refusal was scoped to the inherited table and did not
    //    poison the record written while the table was clean.
    // SAFETY: 1500 belongs to this private process.
    unsafe {
        libc::close(1500);
    }
    let restored: Value =
        serde_json::from_slice(&invoke(&fixture.cache, &args, None).stdout).unwrap();
    assert_eq!(
        restored["kind"], "Reused",
        "reuse must return once the inherited descriptors are closed: {restored}"
    );
    eprintln!("RESULT runner-descriptors PASS");
}

#[test]
fn inherited_descriptor_beyond_stdin_is_never_reused() {
    let fixture = Fixture::new();
    let null = File::open("/dev/null").unwrap();
    let zero = File::open("/dev/zero").unwrap();
    let regular_path = fixture.input("fd9-regular");
    fs::write(&regular_path, b"regular payload\n").unwrap();
    let regular = File::open(&regular_path).unwrap();
    let pipe = pipe_with_data();

    for (label, source) in [
        ("zero", Some(&zero)),
        ("regular", Some(&regular)),
        ("pipe", Some(&pipe)),
        ("closed", None),
    ] {
        use std::os::unix::process::ExitStatusExt;
        let first = run_with_fd9(&fixture, "inherited_fd9_read", Some(&null), true);
        assert!(
            first.status.success(),
            "{label} baseline code={:?} signal={:?} stderr={:?} stdout={:?}",
            first.status.code(),
            first.status.signal(),
            stderr_of(&first),
            String::from_utf8_lossy(&first.stdout)
        );
        let second = run_with_fd9(&fixture, "inherited_fd9_read", Some(&null), true);
        assert!(
            second.status.success(),
            "{label} baseline code={:?} signal={:?} stderr={:?} stdout={:?}",
            second.status.code(),
            second.status.signal(),
            stderr_of(&second),
            String::from_utf8_lossy(&second.stdout)
        );
        let second_report: Value = serde_json::from_slice(&second.stdout).unwrap();
        assert_ne!(second_report["kind"], "Reused", "{label}: {second_report}");
        assert!(
            second_report["reasons"]
                .to_string()
                .contains("inherited descriptor 9"),
            "{label}: the refusal should name descriptor 9: {second_report}"
        );

        let direct = run_with_fd9(&fixture, "inherited_fd9_read", source, false);
        let traced = run_with_fd9(&fixture, "inherited_fd9_read", source, true);
        let report: Value = serde_json::from_slice(&traced.stdout).unwrap();
        assert_ne!(report["kind"], "Reused", "{label}: {report}");
        let traced_stdout = report["stdout_bytes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|byte| byte.as_u64().unwrap() as u8)
            .collect::<Vec<_>>();
        assert_eq!(
            report["exit_code"].as_i64(),
            direct.status.code().map(i64::from),
            "{label}: exit status"
        );
        assert_eq!(traced_stdout, direct.stdout, "{label}: stdout");
    }
    eprintln!("RESULT inherited-descriptor-beyond-stdin PASS");
}

#[test]
fn dup2_same_descriptor_preserves_directory_and_pipe_tracking() {
    let fixture = Fixture::new();
    fs::create_dir(fixture.input("enumdir")).unwrap();
    fs::write(fixture.input("enumdir/a"), b"a").unwrap();
    fs::write(fixture.input("enumdir/b"), b"b").unwrap();
    for case in ["dup2_same_file", "dup2_same_directory", "dup2_same_pipe"] {
        let first = fixture.run(case);
        assert!(first.status.success(), "{case}: {}", stderr_of(&first));
        assert!(
            !hit(&first),
            "{case}: the first run must not be a cached hit: {}",
            stderr_of(&first)
        );
        let second = fixture.run(case);
        assert!(second.status.success(), "{case}: {}", stderr_of(&second));
        assert!(
            hit(&second),
            "{case}: same-descriptor duplicate lost tracking: {}",
            stderr_of(&second)
        );
        assert_eq!(
            fs::read(fixture.input("output.txt")).unwrap(),
            b"input one\n",
            "{case}"
        );
    }
    eprintln!("RESULT dup2-same-descriptor PASS");
}

#[test]
fn close_on_exec_descriptor_is_not_an_inherited_boundary() {
    let fixture = Fixture::new();
    fixture.acquire("plain_file_read");
    let source = File::open("/dev/null").unwrap();
    let source_fd = source.as_raw_fd();
    let run = || {
        let mut command = tracejit_command();
        command.args([
            "run",
            "--json",
            "--",
            fixture.binary_arg(),
            "plain_file_read",
            fixture.root(),
        ]);
        command.env("TRACEJIT_CACHE_DIR", &fixture.cache);
        command.env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0");
        // SAFETY: pre_exec runs between fork and exec; helpers only use async-signal-safe calls.
        unsafe {
            command.pre_exec(move || {
                install_inheritable_fd9(source_fd)?;
                // This case wants CLOEXEC so the traced child does *not* see fd 9.
                if libc::fcntl(9, libc::F_SETFD, libc::FD_CLOEXEC) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        command.output().unwrap()
    };
    let first = run();
    assert!(first.status.success(), "{}", stderr_of(&first));
    let second = run();
    assert!(second.status.success(), "{}", stderr_of(&second));
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(
        report["kind"], "Reused",
        "a close-on-exec descriptor cannot change the child: {report}"
    );
    eprintln!("RESULT close-on-exec PASS");
}

fn compile_readdir_fault_shim(directory: &Path) -> PathBuf {
    let source = directory.join("readdir_fault.c");
    let library = directory.join("libreaddir_fault.so");
    fs::write(
        &source,
        r#"#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static struct dirent *(*real_readdir)(DIR *);
static long seen;
static int failed;

struct dirent *readdir(DIR *directory) {
    if (real_readdir == NULL) {
        real_readdir = (struct dirent *(*)(DIR *))dlsym(RTLD_NEXT, "readdir");
    }
    if (failed) {
        errno = EIO;
        return NULL;
    }
    int fd = dirfd(directory);
    char link[64];
    char target[256];
    snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
    ssize_t length = readlink(link, target, sizeof target - 1);
    if (length > 0) {
        target[length] = 0;
    }
    if (length > 0 && strncmp(target, "/proc/", 6) == 0 && strstr(target, "/fd") != NULL) {
        const char *value = getenv("TRACEJIT_TEST_READDIR_FAIL_AFTER");
        long after = value == NULL ? -1 : strtol(value, NULL, 10);
        if (after >= 0 && seen++ >= after) {
            failed = 1;
            errno = EIO;
            return NULL;
        }
    }
    return real_readdir(directory);
}
"#,
    )
    .unwrap();
    let status = Command::new("cc")
        .args(["-shared", "-fPIC", "-O2"])
        .arg(&source)
        .arg("-o")
        .arg(&library)
        .arg("-ldl")
        .status()
        .expect("C compiler must be available");
    assert!(status.success(), "readdir fault shim compilation failed");
    library
}

#[test]
fn descriptor_enumeration_failure_is_fail_closed() {
    let _serial = serial_timing_lock();
    let fixture = Fixture::new();
    let shim = compile_readdir_fault_shim(fixture.directory.path());
    for (label, after) in [("before-first", "0"), ("after-one-entry", "1")] {
        let mut command = tracejit_command();
        command
            .args([
                "run",
                "--json",
                "--",
                fixture.binary_arg(),
                "plain_file_read",
                fixture.root(),
            ])
            .env("TRACEJIT_CACHE_DIR", &fixture.cache)
            .env("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0")
            .env("LD_PRELOAD", &shim)
            .env("TRACEJIT_TEST_READDIR_FAIL_AFTER", after);
        let output = command.output().unwrap();
        let stderr = stderr_of(&output);
        assert!(
            !output.status.success(),
            "{label}: enumeration failure must fail closed, got success: {stderr}"
        );
        assert_eq!(
            output.status.code(),
            Some(1),
            "{label}: preflight errors must fail the invocation, not fall back to direct execution"
        );
        assert!(
            !fixture.input("output.txt").exists(),
            "{label}: the target ran despite a failed descriptor preflight"
        );
        assert!(
            stderr.contains("could not establish the inherited descriptor table"),
            "{label}: missing fail-closed diagnostic: {stderr}"
        );
        assert!(
            !stderr.contains("cache          HIT"),
            "{label}: failure must not expose a cached hit: {stderr}"
        );
        assert!(
            !stderr.contains("cache          MISS"),
            "{label}: failure must not record an admission: {stderr}"
        );
    }
    eprintln!("RESULT descriptor-enumeration-failure PASS");
}

/// Regression for the CI flake on concurrent/baseline fd9 tests: when the harness source fd
/// **is already 9** and carries `O_CLOEXEC` from `File::open`, `dup2(9,9)` alone leaves CLOEXEC
/// set and `exec` drops fd 9. TraceJIT then exits with the child's code 3 and empty stderr.
#[test]
fn cloexec_source_already_on_fd9_still_reaches_the_child() {
    use std::os::unix::process::ExitStatusExt;

    // Isolated: this case installs a descriptor at slot 9 in the test process itself. `dup2` onto
    // a slot silently closes whatever another thread held there, so running it beside the rest of
    // the suite corrupted unrelated spawns (`EBADF` from `Command::output`, even on stdout). A
    // private process makes the slot manipulation unobservable to every other test.
    if !run_in_isolated_process("cloexec_source_already_on_fd9_still_reaches_the_child") {
        return;
    }

    let fixture = Fixture::new();
    let donor = File::open("/dev/null").unwrap();
    let donor_fd = donor.as_raw_fd();
    // SAFETY: install a CLOEXEC descriptor at slot 9, modeling File::open landing on 9 under load.
    unsafe {
        if donor_fd != 9 {
            assert_eq!(libc::dup2(donor_fd, 9), 9, "dup2 onto 9");
        }
        assert_eq!(
            libc::fcntl(9, libc::F_SETFD, libc::FD_CLOEXEC),
            0,
            "set CLOEXEC on 9"
        );
    }
    let flags = unsafe { libc::fcntl(9, libc::F_GETFD) };
    assert!(
        flags >= 0 && flags & libc::FD_CLOEXEC != 0,
        "precondition: fd9 CLOEXEC"
    );

    // SAFETY: borrow fd 9 without taking ownership away from this process until forget below.
    let source_on_nine = unsafe { File::from_raw_fd(9) };
    let output = run_with_fd9(&fixture, "inherited_fd9_read", Some(&source_on_nine), true);
    std::mem::forget(source_on_nine);
    drop(donor);
    if donor_fd != 9 {
        unsafe {
            libc::close(9);
        }
    }

    assert!(
        output.status.success(),
        "code={:?} signal={:?} stderr={:?} stdout={:?}",
        output.status.code(),
        output.status.signal(),
        stderr_of(&output),
        String::from_utf8_lossy(&output.stdout)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_ne!(report["kind"], "Reused", "{report}");
    let bytes = report["stdout_bytes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|byte| byte.as_u64().unwrap() as u8)
        .collect::<Vec<_>>();
    assert_eq!(bytes, b"EOF\n", "{report}");
    eprintln!("RESULT cloexec-fd9-survives-exec PASS");
}

#[test]
fn concurrent_inherited_descriptor_replacements_are_refused() {
    use std::os::unix::process::ExitStatusExt;

    let null = File::open("/dev/null").unwrap();
    let zero = File::open("/dev/zero").unwrap();
    let (null_output, zero_output) = std::thread::scope(|scope| {
        let null_run = scope.spawn(|| {
            let fixture = Fixture::new();
            run_with_fd9(&fixture, "inherited_fd9_read", Some(&null), true)
        });
        let zero_run = scope.spawn(|| {
            let fixture = Fixture::new();
            run_with_fd9(&fixture, "inherited_fd9_read", Some(&zero), true)
        });
        (null_run.join().unwrap(), zero_run.join().unwrap())
    });
    for (label, output, expected) in [
        ("null", null_output, b"EOF\n".as_slice()),
        ("zero", zero_output, b"DATA\n".as_slice()),
    ] {
        assert!(
            output.status.success(),
            "{label}: code={:?} signal={:?} stderr={:?} stdout={:?} \
             (code 3 + empty stderr + JSON stdout usually means fd9 never reached the child; \
             code 1 + empty stdio usually meant harness closed Rust's spawn-error socket)",
            output.status.code(),
            output.status.signal(),
            stderr_of(&output),
            String::from_utf8_lossy(&output.stdout)
        );
        let report: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_ne!(report["kind"], "Reused", "{label}: {report}");
        let bytes = report["stdout_bytes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|byte| byte.as_u64().unwrap() as u8)
            .collect::<Vec<_>>();
        assert_eq!(bytes, expected, "{label}: {report}");
    }
    eprintln!("RESULT concurrent-inherited-descriptor PASS");
}

#[test]
fn dev_null_read_family_is_reusable() {
    for case in ["dev_null_read", "dev_null_reads", "dev_null_alias_read"] {
        let fixture = Fixture::new();
        let null = Path::new("/dev/null");
        let first = run_with_stdin(&fixture, case, null);
        assert!(first.status.success(), "{}: {}", case, stderr_of(&first));
        let second = run_with_stdin(&fixture, case, null);
        assert!(second.status.success(), "{}: {}", case, stderr_of(&second));
        let report: Value = serde_json::from_slice(&second.stdout).unwrap();
        assert_eq!(report["kind"], "Reused", "{case}: {report}");
        assert_eq!(
            fs::read(fixture.input("output.txt")).unwrap(),
            b"input one\n",
            "{case}"
        );
    }
    eprintln!("RESULT dev-null-read-family PASS");
}

#[test]
fn regular_file_stdin_read_uses_the_offset_stream_model() {
    let fixture = Fixture::new();
    let substitute = fixture.input("not-null");
    fs::write(&substitute, b"regular file\n").unwrap();
    let run = || run_with_stdin(&fixture, "inherited_read_probe", &substitute);
    let first = run();
    assert!(first.status.success(), "{}", stderr_of(&first));
    let second = run();
    assert!(second.status.success(), "{}", stderr_of(&second));
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_eq!(report["kind"], "Reused", "{report}");
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        b"input one\n"
    );
}

#[test]
fn changing_stdin_from_null_to_regular_is_not_reused() {
    let fixture = Fixture::new();
    let substitute = fixture.input("not-null");
    fs::write(&substitute, b"regular file\n").unwrap();
    let first = run_with_stdin(&fixture, "inherited_read_probe", Path::new("/dev/null"));
    assert!(first.status.success(), "{}", stderr_of(&first));
    let second = run_with_stdin(&fixture, "inherited_read_probe", &substitute);
    assert!(second.status.success(), "{}", stderr_of(&second));
    let report: Value = serde_json::from_slice(&second.stdout).unwrap();
    assert_ne!(
        report["kind"], "Reused",
        "a changed descriptor identity must not reuse the null-read record: {report}"
    );
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        b"input one\n"
    );
}

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
        let source = File::open(&substitute).unwrap();
        set_cloexec(&source);
        tracejit_command()
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
            .stdin(Stdio::from(source))
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

/// Runs one fixture case under a fresh-from-JSON report with the census's allocator tuning, so
/// the glibc tcache probe cannot mask a descriptor decision under test.
fn observation_report(fixture: &Fixture, case: &str) -> Value {
    let output = tracejit_command()
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
        .unwrap();
    assert!(output.status.success(), "{}", stderr_of(&output));
    serde_json::from_slice(&output.stdout).unwrap()
}

/// The null device is a content-free source and sink, so opening it must not refuse reuse.
#[test]
fn null_device_open_is_reusable() {
    let fixture = Fixture::new();
    let first = observation_report(&fixture, "dev_null_open_write");
    assert_eq!(first["kind"], "Executed", "{first}");
    let second = observation_report(&fixture, "dev_null_open_write");
    assert_eq!(second["kind"], "Reused", "{second}");
    assert_eq!(
        fs::read(fixture.input("output.txt")).unwrap(),
        fs::read(fixture.input("input.txt")).unwrap()
    );
    eprintln!("RESULT null-device-reuse PASS");
}

/// A create-only epoll instance is process-internal: nothing can observe it before close.
#[test]
fn create_only_epoll_is_reusable() {
    let fixture = Fixture::new();
    assert_eq!(
        observation_report(&fixture, "epoll_create_close")["kind"],
        "Executed"
    );
    let second = observation_report(&fixture, "epoll_create_close");
    assert_eq!(second["kind"], "Reused", "{second}");
    eprintln!("RESULT epoll-create-reuse PASS");
}

/// Registering a descriptor makes readiness observable, so `epoll_ctl` must keep refusing.
#[test]
fn epoll_registration_is_refused() {
    let fixture = Fixture::new();
    let first = observation_report(&fixture, "epoll_ctl_use");
    assert_eq!(first["eligible_for_reuse"], false, "{first}");
    let second = observation_report(&fixture, "epoll_ctl_use");
    assert_eq!(second["eligible_for_reuse"], false, "{second}");
    assert_ne!(second["kind"], "Reused", "{second}");
    eprintln!("RESULT epoll-registration-refused PASS");
}

/// `O_NONBLOCK` on a private regular-file descriptor cannot change anything the program sees.
#[test]
fn regular_file_blocking_bit_is_reusable() {
    for case in ["regular_file_setfl_nonblock", "regular_file_fionbio"] {
        let fixture = Fixture::new();
        assert_eq!(
            observation_report(&fixture, case)["kind"],
            "Executed",
            "{case}"
        );
        let second = observation_report(&fixture, case);
        assert_eq!(second["kind"], "Reused", "{case}: {second}");
    }
    eprintln!("RESULT regular-file-blocking-bit PASS");
}

/// The same rewrite on a pipe, and an `O_APPEND` rewrite on a regular file, stay refused.
#[test]
fn observable_status_flag_rewrites_are_refused() {
    for case in ["pipe_setfl_nonblock", "regular_file_setfl_append"] {
        let fixture = Fixture::new();
        assert_eq!(
            observation_report(&fixture, case)["eligible_for_reuse"],
            false,
            "{case} must not be eligible"
        );
        let second = observation_report(&fixture, case);
        assert_ne!(second["kind"], "Reused", "{case}: {second}");
    }
    eprintln!("RESULT observable-status-flags-refused PASS");
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
        let mut command = tracejit_command();
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

/// A negative pathname lookup is a real dependency: creating the missing path must deoptimize.
#[test]
fn negative_lookup_deopts_when_the_path_appears() {
    let fixture = Fixture::new();
    let reused = fixture.acquire("negative_lookup");
    assert_eq!(reused.stdout, b"absent\n");
    fs::write(fixture.input("optional-missing.txt"), b"now present").unwrap();
    let third = fixture.run("negative_lookup");
    assert!(
        deoptimized(&third),
        "stale reuse after a negative lookup path appeared: {}",
        stderr_of(&third)
    );
    assert_eq!(third.status.code(), Some(2));
    assert_ne!(third.stdout, b"absent\n");
}

/// Reading through a hard-linked name still keys the dependency by that pathname. Replacing the
/// name with a new inode must not return the previous run's bytes.
#[test]
fn hardlink_input_path_replacement_is_never_a_stale_hit() {
    let fixture = Fixture::new();
    fs::hard_link(fixture.input("input.txt"), fixture.input("input-alias.txt")).unwrap();
    let reused = fixture.acquire("hardlink_input_read");
    assert_eq!(reused.stdout, b"input one\n");
    fs::remove_file(fixture.input("input-alias.txt")).unwrap();
    fs::write(fixture.input("input-alias.txt"), b"replaced alias\n").unwrap();
    let third = fixture.run("hardlink_input_read");
    assert!(
        deoptimized(&third) || missed(&third),
        "pathname replacement reused stale hard-link bytes: {}",
        stderr_of(&third)
    );
    assert_eq!(third.stdout, b"replaced alias\n");
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
            let source = fs::File::open(stdin).unwrap();
            set_cloexec(&source);
            let mut command = tracejit_command();
            command
                .args(args)
                .env("TRACEJIT_CACHE_DIR", cache)
                .stdin(std::process::Stdio::from(source));
            let output = command.output().unwrap();
            serde_json::from_slice::<Value>(&output.stdout).unwrap()
        };

        let first = traced(&cache, &input);
        let second = traced(&cache, &input);
        if let Some(build_id) = runtime_libc_build_id()
            .filter(|build_id| tracejit_effects::allocator_entropy_profile(build_id).is_none())
        {
            // Same runtime guard as `allocator_entropy_contract_reuses_a_glibc_tool`: an
            // unaudited libc is refused, and the refusal must still replay the same bytes.
            assert_eq!(
                first["classification"], "Nondeterministic",
                "session {session}: {first}"
            );
            assert_ne!(
                second["cache_decision"], "Reused",
                "session {session}: {second}"
            );
            assert_eq!(stdout_bytes_of(&first), expected);
            assert_eq!(stdout_bytes_of(&second), expected);
            eprintln!("RESULT controlled-tr SKIP unaudited runtime {build_id}");
            return;
        }
        assert_eq!(
            first["classification"], "Guarded",
            "session {session}: {first}"
        );
        assert_eq!(stdout_bytes_of(&first), expected);
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
    let _serial = serial_timing_lock();
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
    // The first run never pays for a trace: it only measures the direct cost. That is independent
    // of how fast the host is.
    assert_eq!(first["cache_decision"], "Skipped", "{first}");
    // The second run applies the policy to the cost the first run measured
    // (`admission_is_worth_tracing`: a trace must repay twice the hit-cost floor). Assert *that*
    // rule rather than assuming this host can run `wc` inside the break-even window: under default
    // test parallelism on an oversubscribed machine the same command measures 11-25 ms, and then
    // paying for one trace is the correct decision, not a defect. Both branches assert the policy;
    // neither is skipped.
    let measured_direct = first["baseline_runtime_ns"]
        .as_u64()
        .expect("the measuring run must report the direct runtime it sampled");
    let break_even = 2 * tracejit_core::HIT_COST_FLOOR_NS;
    let second: Value = serde_json::from_slice(&invoke(&cache, &short, None).stdout).unwrap();
    if measured_direct < break_even {
        assert_eq!(
            second["cache_decision"], "Skipped",
            "a command measured at {measured_direct} ns cannot repay a trace: {second}"
        );
    } else {
        assert_ne!(
            second["cache_decision"], "Skipped",
            "a command measured at {measured_direct} ns must be traced: {second}"
        );
    }
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
        // The child's table is swept close-on-exec, so only its stdio reaches TraceJIT and the
        // spawn machinery's own pipes are untouched.
        let mut command = tracejit_command();
        command
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
            .stdin(std::process::Stdio::from(duplicate));
        let output = command.output().unwrap();
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

    // An alias inherited across exec (fd 3 duplicated from fd 0 by the caller) is an unmodelled
    // inherited descriptor. It is refused before the program runs, so neither the alias's seek nor
    // the caller-visible shared offset can be replayed.
    let alias_input = fs::File::open(&input).unwrap();
    let mut shell = Command::new("sh");
    shell
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
        .stdin(std::process::Stdio::from(alias_input));
    // Only the alias this case creates is inherited: the sweep leaves fd 3 alone because the shell
    // installs it after `pre_exec` runs.
    without_inherited_descriptors(&mut shell);
    let inherited = shell.output().unwrap();
    assert!(
        inherited.status.success(),
        "traced inherited alias failed: {}",
        String::from_utf8_lossy(&inherited.stderr)
    );
    let report: Value = serde_json::from_slice(&inherited.stdout).unwrap();
    assert_ne!(report["classification"], "Guarded", "{report}");
    assert!(
        report["decision_reason"]
            .as_str()
            .unwrap_or_default()
            .contains("inherited descriptor 3"),
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
    let mut guarded = Command::new("timeout");
    guarded
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
        .env("TRACEJIT_CACHE_DIR", temporary.path().join("cache"));
    without_inherited_descriptors(&mut guarded);
    let traced = guarded.output().unwrap();
    assert!(
        traced.status.success(),
        "traced exit-without-exec storm failed or stalled: {}",
        String::from_utf8_lossy(&traced.stderr)
    );
    let report: Value = serde_json::from_slice(&traced.stdout).unwrap();
    assert_eq!(stdout_bytes_of(&report), direct.stdout);
    eprintln!("RESULT vfork-exit PASS");
}

/// Phase K2: CLI-only independent Obs oracle (no product crate validation imports).
#[test]
fn phase_k2_independent_obs_oracle_seed7() {
    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../benchmarks/oracle/independent_obs.py");
    let output_dir = tempfile::tempdir().unwrap();
    let status = Command::new("python3")
        .arg(&script)
        .args(["--seed", "7", "--output"])
        .arg(output_dir.path())
        .env(
            "PATH",
            format!(
                "{}:{}",
                tracejit().parent().unwrap().display(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .status()
        .expect("python3 must be available");
    assert!(
        status.success(),
        "independent Obs oracle reported incorrect_hit or regress_eligible"
    );
    eprintln!("RESULT phase-k2-oracle PASS");
}

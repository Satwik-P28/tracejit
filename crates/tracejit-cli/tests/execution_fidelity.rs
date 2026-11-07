//! Native-versus-TraceJIT execution fidelity for ordinary developer commands.
//!
//! Every workload is counted in the denominator. A workload that cannot run on this host is
//! reported as `Unavailable`, never silently dropped, and a mismatch is `FidelityFailure` rather
//! than an adjusted expectation. The comparison covers exit status, stdout, stderr, the resulting
//! file tree (content, mode and symlink targets) and, for the inherited-stdin case, the caller's
//! own descriptor position.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

fn tracejit() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_tracejit"))
}

fn hex(bytes: &[u8]) -> String {
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        text.push_str(&format!("{byte:02x}"));
    }
    text
}

fn snapshot(root: &Path) -> BTreeMap<String, String> {
    fn walk(base: &Path, directory: &Path, entries: &mut BTreeMap<String, String>) {
        let mut collected = fs::read_dir(directory)
            .expect("workload directory must be readable")
            .flatten()
            .collect::<Vec<_>>();
        collected.sort_by_key(|entry| entry.file_name());
        for entry in collected {
            let path = entry.path();
            let relative = path
                .strip_prefix(base)
                .unwrap()
                .to_string_lossy()
                .into_owned();
            let metadata = fs::symlink_metadata(&path).unwrap();
            if metadata.file_type().is_symlink() {
                entries.insert(
                    relative,
                    format!("link:{}", fs::read_link(&path).unwrap().display()),
                );
            } else if metadata.is_dir() {
                entries.insert(relative.clone(), "dir".into());
                walk(base, &path, entries);
            } else {
                let bytes = fs::read(&path).unwrap_or_default();
                let digest = if bytes.len() <= 4 * 1024 * 1024 {
                    hex(&bytes)
                } else {
                    format!("large:{}", bytes.len())
                };
                entries.insert(
                    relative,
                    format!("file:{:o}:{digest}", metadata.permissions().mode()),
                );
            }
        }
    }
    let mut entries = BTreeMap::new();
    walk(root, root, &mut entries);
    entries
}

struct Execution {
    status: Option<i32>,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    tree: BTreeMap<String, String>,
    decision: Option<String>,
    classification: Option<String>,
    stdin_position: Option<u64>,
}

fn stdin_file(path: &Path) -> Option<fs::File> {
    fs::File::open(path).ok()
}

fn run_direct(directory: &Path, program: &str, args: &[String], input: Option<&Path>) -> Execution {
    let mut command = Command::new(program);
    command.args(args).current_dir(directory);
    let mut source = None;
    if let Some(path) = input {
        let file = stdin_file(path).unwrap();
        source = Some(file.try_clone().unwrap());
        command.stdin(Stdio::from(file));
    }
    let output: Output = command.output().unwrap();
    let position = source
        .as_mut()
        .map(|file| std::io::Seek::stream_position(file).unwrap_or(0));
    Execution {
        status: output.status.code(),
        stdout: output.stdout,
        stderr: output.stderr,
        tree: snapshot(directory),
        decision: None,
        classification: None,
        stdin_position: position,
    }
}

fn run_traced(
    cache: &Path,
    directory: &Path,
    program: &str,
    args: &[String],
    input: Option<&Path>,
) -> Execution {
    let mut command = Command::new(tracejit());
    command
        .args([
            "run",
            "--json",
            "--contract",
            "allocator-entropy-v1",
            "--admission",
            "always",
            "--",
            program,
        ])
        .args(args)
        .current_dir(directory)
        .env("TRACEJIT_CACHE_DIR", cache);
    let mut source = None;
    if let Some(path) = input {
        let file = stdin_file(path).unwrap();
        source = Some(file.try_clone().unwrap());
        command.stdin(Stdio::from(file));
    }
    let output = command.output().unwrap();
    let position = source
        .as_mut()
        .map(|file| std::io::Seek::stream_position(file).unwrap_or(0));
    let report: Value = serde_json::from_slice(&output.stdout).unwrap_or_else(|error| {
        panic!(
            "traced {program} returned no report: {error}; stderr={}",
            String::from_utf8_lossy(&output.stderr)
        )
    });
    let bytes = |name: &str| -> Vec<u8> {
        report[name]
            .as_array()
            .unwrap_or(&Vec::new())
            .iter()
            .map(|byte| byte.as_u64().unwrap() as u8)
            .collect()
    };
    Execution {
        status: report["exit_code"].as_i64().map(|code| code as i32),
        stdout: bytes("stdout_bytes"),
        stderr: bytes("stderr_bytes"),
        tree: snapshot(directory),
        decision: report["cache_decision"].as_str().map(str::to_owned),
        classification: report["classification"].as_str().map(str::to_owned),
        stdin_position: position,
    }
}

struct Workload {
    name: &'static str,
    program: &'static str,
    args: Vec<String>,
    stdin: Option<String>,
    unavailable: Option<&'static str>,
}

fn workloads() -> Vec<Workload> {
    vec![
        Workload {
            name: "autoconf-configure",
            program: "autoconf",
            args: vec!["--version".into()],
            stdin: None,
            unavailable: Some("autoconf is not installed on this host"),
        },
        Workload {
            name: "configure-style-shell",
            program: "sh",
            args: vec!["./configure".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "make-build-parallel",
            program: "make",
            args: vec!["-j4".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "make-build-serial",
            program: "make",
            args: vec!["-j1".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "make-test-target",
            program: "make",
            args: vec!["test".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "gzip-compression",
            program: "gzip",
            args: vec!["-n".into(), "-9".into(), "-c".into(), "data.txt".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "gzip-decompression",
            program: "gzip",
            args: vec!["-n".into(), "-d".into(), "-c".into(), "data.txt.gz".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "data-transformation-sort",
            program: "sort",
            args: vec!["data.txt".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "compiler-invocation",
            program: "cc",
            args: vec![
                "-O2".into(),
                "-c".into(),
                "unit.c".into(),
                "-o".into(),
                "unit.o".into(),
            ],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "test-runner",
            program: "sh",
            args: vec!["./run-tests.sh".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "shell-file-mutations",
            program: "sh",
            args: vec!["./mutate.sh".into()],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "multi-process-pipeline",
            program: "sh",
            args: vec![
                "-c".into(),
                "printf 'b\\na\\nb\\n' | sort -u | wc -l".into(),
            ],
            stdin: None,
            unavailable: None,
        },
        Workload {
            name: "inherited-stdin-offset",
            program: "./stdin-seek",
            args: vec!["read-seek-read".into()],
            stdin: Some("stdin.txt".into()),
            unavailable: None,
        },
        Workload {
            name: "nonzero-exit-with-stderr",
            program: "sh",
            args: vec![
                "-c".into(),
                "echo stdout-line; echo stderr-line >&2; exit 7".into(),
            ],
            stdin: None,
            unavailable: None,
        },
    ]
}

fn prepare(directory: &Path) {
    fs::create_dir_all(directory).unwrap();
    fs::write(
        directory.join("configure"),
        "#!/bin/sh\n\
         # A configure-shaped check: compiler presence, a generated header and a summary.\n\
         set -e\n\
         printf '%s\\n' \"checking for cc... yes\"\n\
         cc -O2 -c probe.c -o probe.o\n\
         printf '#define HAVE_PROBE 1\\n' > config.h\n\
         printf 'all:\\n\\t@echo built\\n' > Makefile\n\
         printf '%s\\n' \"configure: creating config.h\"\n\
         printf 'configure: exit 0\\n'\n",
    )
    .unwrap();
    let mut permissions = fs::metadata(directory.join("configure"))
        .unwrap()
        .permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(directory.join("configure"), permissions).unwrap();
    fs::write(directory.join("probe.c"), "int probe(void) { return 1; }\n").unwrap();
    fs::write(directory.join("unit.c"), "int unit(void) { return 42; }\n").unwrap();
    fs::write(
        directory.join("main.c"),
        "#include <stdio.h>\nint main(void) { puts(\"app-output\"); return 0; }\n",
    )
    .unwrap();
    fs::write(
        directory.join("Makefile"),
        "app: main.c\n\tcc -O2 main.c -o app\n\ntest: app\n\t@./app-check\n\t@echo tests-passed\n",
    )
    .unwrap();
    fs::write(directory.join("data.txt"), "alpha\ncharlie\nbravo\nalpha\n").unwrap();
    let compressed = Command::new("gzip")
        .args(["-n", "-9", "-c"])
        .arg(directory.join("data.txt"))
        .output()
        .unwrap();
    assert!(compressed.status.success(), "gzip setup failed");
    fs::write(directory.join("data.txt.gz"), &compressed.stdout).unwrap();
    fs::write(
        directory.join("run-tests.sh"),
        "#!/bin/sh\n\
         set -e\n\
         test -f unit.c\n\
         cc -O2 -c unit.c -o unit-test.o\n\
         ./app-check >/dev/null\n\
         echo 'PASS 3 checks'\n",
    )
    .unwrap();
    fs::write(directory.join("app-check"), "#!/bin/sh\nexit 0\n").unwrap();
    for script in ["run-tests.sh", "app-check"] {
        let mut permissions = fs::metadata(directory.join(script)).unwrap().permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(directory.join(script), permissions).unwrap();
    }
    fs::write(
        directory.join("mutate.sh"),
        "#!/bin/sh\n\
         set -e\n\
         mkdir -p out/nested\n\
         printf 'payload\\n' > out/nested/file.txt\n\
         ln -sf nested/file.txt out/link\n\
         mv out/nested/file.txt out/nested/renamed.txt\n\
         rmdir out/nested/empty 2>/dev/null || true\n\
         mkdir out/nested/empty\n\
         rmdir out/nested/empty\n\
         echo mutated\n",
    )
    .unwrap();
    let mut permissions = fs::metadata(directory.join("mutate.sh"))
        .unwrap()
        .permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(directory.join("mutate.sh"), permissions).unwrap();
    fs::write(directory.join("stdin.txt"), "0123456789abcdef").unwrap();
}

fn compile_stdin_fixture(directory: &Path) {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/stdin_seek.c")
        .canonicalize()
        .unwrap();
    let status = Command::new("cc")
        .args(["-O2", "-Wall", "-Wextra", "-Werror"])
        .arg(source)
        .arg("-o")
        .arg(directory.join("stdin-seek"))
        .status()
        .unwrap();
    assert!(status.success(), "stdin fixture compilation failed");
}

#[test]
fn ordinary_developer_commands_execute_like_native() {
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path();
    let mut categories: BTreeMap<&str, usize> = BTreeMap::new();
    let mut failures = Vec::new();
    println!("{:<28} {:<26} decision", "workload", "category");
    for (index, workload) in workloads().iter().enumerate() {
        let direct_dir = root.join(format!("{index}-direct"));
        let traced_dir = root.join(format!("{index}-traced"));
        prepare(&direct_dir);
        prepare(&traced_dir);
        if workload.name == "inherited-stdin-offset" {
            compile_stdin_fixture(&direct_dir);
            compile_stdin_fixture(&traced_dir);
        }
        if let Some(reason) = workload.unavailable {
            *categories.entry("Unavailable").or_default() += 1;
            println!("{:<28} {:<26} {reason}", workload.name, "Unavailable");
            continue;
        }
        let input_path = workload
            .stdin
            .as_ref()
            .map(|name| direct_dir.join(name))
            .zip(workload.stdin.as_ref().map(|name| traced_dir.join(name)));
        let direct = run_direct(
            &direct_dir,
            workload.program,
            &workload.args,
            input_path.as_ref().map(|(path, _)| path.as_path()),
        );
        let cache = root.join(format!("{index}-cache"));
        let cold = run_traced(
            &cache,
            &traced_dir,
            workload.program,
            &workload.args,
            input_path.as_ref().map(|(_, path)| path.as_path()),
        );
        let mut mismatch = Vec::new();
        if direct.status != cold.status {
            mismatch.push(format!("exit {:?} != {:?}", direct.status, cold.status));
        }
        if direct.stdout != cold.stdout {
            mismatch.push("stdout differs".into());
        }
        if direct.stderr != cold.stderr {
            mismatch.push(format!(
                "stderr differs: native {:?} traced {:?}",
                String::from_utf8_lossy(&direct.stderr),
                String::from_utf8_lossy(&cold.stderr)
            ));
        }
        if direct.tree != cold.tree {
            let keys = direct
                .tree
                .keys()
                .chain(cold.tree.keys())
                .filter(|key| direct.tree.get(*key) != cold.tree.get(*key))
                .cloned()
                .collect::<Vec<_>>();
            mismatch.push(format!("file tree differs at {keys:?}"));
        }
        if direct.stdin_position != cold.stdin_position {
            mismatch.push(format!(
                "caller stdin position {:?} != {:?}",
                direct.stdin_position, cold.stdin_position
            ));
        }
        if !mismatch.is_empty() {
            *categories.entry("FidelityFailure").or_default() += 1;
            failures.push(format!("{}: {}", workload.name, mismatch.join("; ")));
            println!(
                "{:<28} {:<26} {}",
                workload.name,
                "FidelityFailure",
                mismatch.join("; ")
            );
            continue;
        }
        // The same command again: a hit must reproduce the same observations, otherwise the
        // workload is only safe when it is not reused.
        let warm = run_traced(
            &cache,
            &traced_dir,
            workload.program,
            &workload.args,
            input_path.as_ref().map(|(_, path)| path.as_path()),
        );
        let category = if warm.decision.as_deref() == Some("Reused")
            && warm.stdout == cold.stdout
            && warm.stderr == cold.stderr
            && warm.status == cold.status
            && warm.tree == cold.tree
        {
            "SafelyReused"
        } else if warm.classification.as_deref() == Some("Guarded") {
            "ExecutedWithoutReuse"
        } else {
            "UnsupportedSafelyExecuted"
        };
        *categories.entry(category).or_default() += 1;
        println!(
            "{:<28} {:<26} {:?}/{:?}",
            workload.name, category, cold.classification, warm.decision
        );
    }
    eprintln!("RESULT fidelity {categories:?}");
    assert!(
        failures.is_empty(),
        "execution-fidelity failures: {failures:#?}"
    );
    let accounted: usize = categories.values().sum();
    assert_eq!(
        accounted,
        workloads().len(),
        "every workload must be counted exactly once"
    );
    eprintln!("RESULT execution-fidelity PASS");
}

//! Phase K3: run the finite-state checkers for hit-path and restore-crash machines.

#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use std::path::PathBuf;
use std::process::Command;

#[test]
fn phase_k3_state_machine_checker_passes() {
    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../scripts/modelcheck/check_state_machines.py");
    let output = Command::new("python3")
        .arg(&script)
        .output()
        .expect("python3 must be available");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "modelcheck failed: stdout={stdout} stderr={stderr}"
    );
    assert!(
        stdout.contains("RESULT phase-k3-modelcheck PASS"),
        "missing PASS marker: {stdout}"
    );
}

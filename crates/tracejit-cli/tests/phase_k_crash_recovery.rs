//! Phase K4: run the restore fault-injection harness.

#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

use std::path::PathBuf;
use std::process::Command;

#[test]
fn phase_k4_restore_fault_harness_passes() {
    let script =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../scripts/phase_k4_restore_fault.sh");
    let binary = PathBuf::from(env!("CARGO_BIN_EXE_tracejit"));
    let output = Command::new("bash")
        .arg(&script)
        .arg(&binary)
        .output()
        .expect("bash must be available");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "phase_k4 harness failed: stdout={stdout} stderr={stderr}"
    );
    assert!(
        stdout.contains("RESULT phase-k4-soft-fail-retrace PASS"),
        "missing soft-fail marker: {stdout}"
    );
    assert!(
        stdout.contains("RESULT phase-k4-hard-kill-recovery PASS"),
        "missing hard-kill marker: {stdout}"
    );
}

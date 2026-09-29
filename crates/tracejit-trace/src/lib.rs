use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::path::PathBuf;
use tracejit_effects::Trace;

#[derive(Debug, thiserror::Error)]
pub enum TraceError {
    #[error("tracing is unsupported: {0}")]
    Unsupported(String),
    #[error("target binary not found: {0}")]
    TargetNotFound(PathBuf),
    #[error("could not start target: {0}")]
    Spawn(String),
    #[error("ptrace failed: {0}")]
    Ptrace(String),
    #[error("target terminated unexpectedly: {0}")]
    TargetTerminated(String),
    #[error("output capture failed: {0}")]
    OutputCapture(String),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TraceRequest {
    pub executable: PathBuf,
    pub argv: Vec<OsString>,
    pub cwd: PathBuf,
    pub environment: BTreeMap<OsString, OsString>,
    pub sandbox: Option<tracejit_sandbox::SandboxPolicy>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TraceOutcome {
    pub trace: Trace,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
    pub sandbox_enforced: bool,
}

pub fn probe_ptrace() -> Result<(), String> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        linux::probe_ptrace()
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        Err("TraceJIT V1 requires Linux x86_64".into())
    }
}

pub fn trace_command(request: TraceRequest) -> Result<TraceOutcome, TraceError> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        linux::trace_command(request)
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        let _ = request;
        Err(TraceError::Unsupported(
            "TraceJIT V1 requires Linux x86_64".into(),
        ))
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod linux;

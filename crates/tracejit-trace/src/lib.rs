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
    #[error("the executable changed between identity construction and execution: {0}")]
    ExecutableChanged(String),
    #[error("could not start target: {0}")]
    Spawn(String),
    #[error("ptrace failed: {0}")]
    Ptrace(String),
    #[error("target terminated unexpectedly: {0}")]
    TargetTerminated(String),
    #[error("output capture failed: {0}")]
    OutputCapture(String),
}

/// A controlled, reproducible execution contract.
///
/// It exists so that environmental nondeterminism can be *deliberately controlled* rather than
/// ignored. A result recorded under a contract is reproducible under that contract; it is not
/// claimed to be equivalent to arbitrary native execution, and native mode never admits the
/// effects a contract fixes.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Contract {
    /// Fixes the runtime's internal allocator entropy probe (`getrandom` of eight bytes with
    /// `GRND_NONBLOCK`, destination in the issuing shared library's private writable data).
    AllocatorEntropyV1,
    /// Fixes two incidental observations of the audited GCC 13.3.0 toolchain: the assembly
    /// step's own CPU time and the compiler's available-memory picture. Application buffers,
    /// other toolchain builds and every other call site stay ordinary effects.
    CompilerRuntimeV1,
    /// Experimental CPython single-process contract. It fixes the audited startup clock reads
    /// and process/thread identity syscalls for `/usr/bin/python3.12` only. It does not claim
    /// native equivalence and does not admit application clock or random reads.
    PythonRuntimeV1,
}

impl Contract {
    pub const fn id(self) -> &'static str {
        match self {
            Self::AllocatorEntropyV1 => tracejit_effects::ALLOCATOR_ENTROPY_CONTRACT,
            Self::CompilerRuntimeV1 => tracejit_effects::COMPILER_RUNTIME_CONTRACT,
            Self::PythonRuntimeV1 => tracejit_effects::PYTHON_RUNTIME_CONTRACT,
        }
    }

    pub const fn controlled_value(self) -> u64 {
        match self {
            Self::AllocatorEntropyV1 => tracejit_effects::ALLOCATOR_ENTROPY_VALUE,
            Self::CompilerRuntimeV1 => tracejit_effects::COMPILER_RUNTIME_SYSINFO_TOTALRAM,
            Self::PythonRuntimeV1 => 0,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TraceRequest {
    pub executable: PathBuf,
    pub argv: Vec<OsString>,
    pub cwd: PathBuf,
    pub environment: BTreeMap<OsString, OsString>,
    /// Hash of the executable sampled when the cache identity was built, re-verified
    /// immediately before `exec` so a replaced path cannot file a result under an identity
    /// that did not produce it.
    pub expected_executable_hash: Option<tracejit_effects::Hash>,
    pub sandbox: Option<tracejit_sandbox::SandboxPolicy>,
    /// `None` is native guarded execution: no environmental nondeterminism is controlled and the
    /// contract effect stays ineligible.
    #[serde(default)]
    pub contract: Option<Contract>,
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

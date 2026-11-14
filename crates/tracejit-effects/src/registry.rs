//! Semantic syscall registry for modeled effect classes.
//!
//! Entries document how TraceJIT treats a syscall class under guarded reuse. This is not a claim
//! that CEGAR itself is novel; it is the vocabulary the refinement workflow uses when proposing
//! or rejecting a model change.

use serde::{Deserialize, Serialize};

/// How an observed syscall class participates in reuse.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ModelStatus {
    /// Fully modeled with guards; eligible when classification allows.
    Guarded,
    /// Process-internal; ignored for classification.
    ProcessInternal,
    /// Always refuses reuse (`NONDETERMINISTIC`).
    Nondeterministic,
    /// Always refuses reuse (`UNKNOWN`).
    Unknown,
    /// Only under an explicit controlled-execution contract.
    ContractOnly,
    /// Not yet modeled; observation fails closed as unknown/unclassified.
    Unmodeled,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SyscallRegistryEntry {
    pub name: &'static str,
    /// Linux x86_64 syscall number when unique; `None` for multi-number families.
    pub nr: Option<i64>,
    pub status: ModelStatus,
    pub effect_class: &'static str,
    pub notes: &'static str,
}

/// Registry subset covering classes touched by Phase E refinement work and closely related models.
pub fn phase_e_registry() -> &'static [SyscallRegistryEntry] {
    PHASE_E_REGISTRY
}

const PHASE_E_REGISTRY: &[SyscallRegistryEntry] = &[
    SyscallRegistryEntry {
        name: "getrusage",
        nr: Some(libc_sys::SYS_GETRUSAGE),
        status: ModelStatus::Nondeterministic,
        effect_class: "KernelState::resource_usage",
        notes: "Per-run consumption cannot be guarded; Phase 2C/E-Phase-E rejected admitting it.",
    },
    SyscallRegistryEntry {
        name: "openat(directory)",
        nr: Some(libc_sys::SYS_OPENAT),
        status: ModelStatus::Guarded,
        effect_class: "ReadEffect::DirectoryOpened",
        notes:
            "CEGAR-style refinement from Metadata→DirectoryOpened; identity+mode+creds, not mtime.",
    },
    SyscallRegistryEntry {
        name: "getdents64",
        nr: Some(libc_sys::SYS_GETDENTS64),
        status: ModelStatus::Guarded,
        effect_class: "ReadEffect::DirectoryEnumerated",
        notes: "Exact byte stream guarded; order and cookies matter.",
    },
    SyscallRegistryEntry {
        name: "statfs/fstatfs",
        nr: None,
        status: ModelStatus::Guarded,
        effect_class: "ReadEffect::FilesystemStats",
        notes: "All returned bytes + mount namespace + credentials.",
    },
    SyscallRegistryEntry {
        name: "access/faccessat/faccessat2",
        nr: None,
        status: ModelStatus::Guarded,
        effect_class: "ReadEffect::Access",
        notes: "Replay exact errno under recorded credential digest.",
    },
    SyscallRegistryEntry {
        name: "mmap MAP_SHARED anonymous",
        nr: Some(libc_sys::SYS_MMAP),
        status: ModelStatus::Unknown,
        effect_class: "UnknownEffect::shared_anon_memory",
        notes: "Phase C: untracked cross-fork shared memory.",
    },
    SyscallRegistryEntry {
        name: "link/linkat",
        nr: None,
        status: ModelStatus::Unknown,
        effect_class: "UnknownEffect::hardlink_create",
        notes: "Phase C: not pathname-equivalent to CAS restore.",
    },
    SyscallRegistryEntry {
        name: "getrandom (allocator probe)",
        nr: Some(libc_sys::SYS_GETRANDOM),
        status: ModelStatus::ContractOnly,
        effect_class: "ReadEffect::ControlledEntropy",
        notes: "Only under allocator-entropy-v1 audited call-site profile.",
    },
    SyscallRegistryEntry {
        name: "clock_gettime/gettimeofday/time",
        nr: None,
        status: ModelStatus::Nondeterministic,
        effect_class: "KernelState::clock",
        notes: "Native clocks refuse; controlled contracts may fix values but are not native Obs.",
    },
    SyscallRegistryEntry {
        name: "fcntl F_SETFD / F_DUPFD*",
        nr: Some(libc_sys::SYS_FCNTL),
        status: ModelStatus::Guarded,
        effect_class: "descriptor_lifecycle",
        notes: "CLOEXEC and dup variants update FdState; other fcntl cmds stay process-internal.",
    },
    SyscallRegistryEntry {
        name: "fcntl (other cmds)",
        nr: Some(libc_sys::SYS_FCNTL),
        status: ModelStatus::ProcessInternal,
        effect_class: "process_internal",
        notes: "PendingSyscall::None; not a classification input.",
    },
    SyscallRegistryEntry {
        name: "lseek on /dev/null",
        nr: Some(libc_sys::SYS_LSEEK),
        status: ModelStatus::Guarded,
        effect_class: "InheritedStream::dev_null_seek",
        notes: "Narrow admit with fstat char-device 1:3 identity.",
    },
];

/// Local constants so the registry compiles without pulling `libc` into effects' public API.
mod libc_sys {
    // Linux x86_64 numbers from the kernel UAPI; verified against libc on CI hosts.
    pub const SYS_GETRUSAGE: i64 = 98;
    pub const SYS_OPENAT: i64 = 257;
    pub const SYS_GETDENTS64: i64 = 217;
    pub const SYS_MMAP: i64 = 9;
    pub const SYS_GETRANDOM: i64 = 318;
    pub const SYS_FCNTL: i64 = 72;
    pub const SYS_LSEEK: i64 = 8;
}

pub fn lookup_by_name(name: &str) -> Option<&'static SyscallRegistryEntry> {
    PHASE_E_REGISTRY.iter().find(|entry| entry.name == name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn getrusage_stays_nondeterministic() {
        let entry = lookup_by_name("getrusage").unwrap();
        assert_eq!(entry.status, ModelStatus::Nondeterministic);
    }

    #[test]
    fn directory_open_is_guarded() {
        let entry = lookup_by_name("openat(directory)").unwrap();
        assert_eq!(entry.status, ModelStatus::Guarded);
        assert!(entry.notes.contains("DirectoryOpened"));
    }

    #[test]
    fn registry_has_no_duplicate_names() {
        let mut names: Vec<&str> = PHASE_E_REGISTRY.iter().map(|e| e.name).collect();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), PHASE_E_REGISTRY.len());
    }
}

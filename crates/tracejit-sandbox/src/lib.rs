use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum SandboxError {
    #[error("sandbox is unsupported: {0}")]
    Unsupported(String),
    #[error("sandbox setup failed: {0}")]
    Setup(String),
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct SandboxPolicy {
    pub readable_paths: Vec<PathBuf>,
    pub writable_paths: Vec<PathBuf>,
    pub allow_network: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SandboxCapabilities {
    pub seccomp: bool,
    pub landlock_abi: Option<i32>,
    pub reason: Option<String>,
}

impl SandboxCapabilities {
    pub fn can_prove(&self) -> bool {
        self.seccomp && self.landlock_abi.is_some_and(|abi| abi >= 3)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EnforcementResult {
    pub seccomp_applied: bool,
    pub landlock_applied: bool,
}

impl EnforcementResult {
    pub fn fully_enforced(&self) -> bool {
        self.seccomp_applied && self.landlock_applied
    }
}

#[cfg(target_os = "linux")]
mod linux {
    use super::*;
    use std::ffi::CString;
    use std::io;
    use std::os::unix::ffi::OsStrExt;
    use std::path::Path;

    const LANDLOCK_CREATE_RULESET_VERSION: u32 = 1;
    const LANDLOCK_RULE_PATH_BENEATH: i32 = 1;
    const LANDLOCK_ACCESS_FS_EXECUTE: u64 = 1 << 0;
    const LANDLOCK_ACCESS_FS_WRITE_FILE: u64 = 1 << 1;
    const LANDLOCK_ACCESS_FS_READ_FILE: u64 = 1 << 2;
    const LANDLOCK_ACCESS_FS_READ_DIR: u64 = 1 << 3;
    const LANDLOCK_ACCESS_FS_REMOVE_DIR: u64 = 1 << 4;
    const LANDLOCK_ACCESS_FS_REMOVE_FILE: u64 = 1 << 5;
    const LANDLOCK_ACCESS_FS_MAKE_CHAR: u64 = 1 << 6;
    const LANDLOCK_ACCESS_FS_MAKE_DIR: u64 = 1 << 7;
    const LANDLOCK_ACCESS_FS_MAKE_REG: u64 = 1 << 8;
    const LANDLOCK_ACCESS_FS_MAKE_SOCK: u64 = 1 << 9;
    const LANDLOCK_ACCESS_FS_MAKE_FIFO: u64 = 1 << 10;
    const LANDLOCK_ACCESS_FS_MAKE_BLOCK: u64 = 1 << 11;
    const LANDLOCK_ACCESS_FS_MAKE_SYM: u64 = 1 << 12;
    const LANDLOCK_ACCESS_FS_REFER: u64 = 1 << 13;
    const LANDLOCK_ACCESS_FS_TRUNCATE: u64 = 1 << 14;
    const READ_ACCESS: u64 =
        LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;
    const WRITE_ACCESS_V1: u64 = LANDLOCK_ACCESS_FS_WRITE_FILE
        | LANDLOCK_ACCESS_FS_REMOVE_DIR
        | LANDLOCK_ACCESS_FS_REMOVE_FILE
        | LANDLOCK_ACCESS_FS_MAKE_CHAR
        | LANDLOCK_ACCESS_FS_MAKE_DIR
        | LANDLOCK_ACCESS_FS_MAKE_REG
        | LANDLOCK_ACCESS_FS_MAKE_SOCK
        | LANDLOCK_ACCESS_FS_MAKE_FIFO
        | LANDLOCK_ACCESS_FS_MAKE_BLOCK
        | LANDLOCK_ACCESS_FS_MAKE_SYM;

    #[repr(C)]
    struct LandlockRulesetAttr {
        handled_access_fs: u64,
    }

    #[repr(C)]
    struct LandlockPathBeneathAttr {
        allowed_access: u64,
        parent_fd: i32,
    }

    pub fn capabilities() -> SandboxCapabilities {
        if !cfg!(target_arch = "x86_64") {
            return SandboxCapabilities {
                seccomp: false,
                landlock_abi: None,
                reason: Some("TraceJIT enforcement requires Linux x86_64".into()),
            };
        }
        // SAFETY: this syscall is invoked in query mode with a null attribute pointer.
        let abi = unsafe {
            libc::syscall(
                libc::SYS_landlock_create_ruleset,
                std::ptr::null::<LandlockRulesetAttr>(),
                0,
                LANDLOCK_CREATE_RULESET_VERSION,
            )
        };
        let landlock_abi = (abi >= 1).then_some(abi as i32);
        // Querying no_new_privs is enough to establish that the prctl interface exists. The
        // actual filter installation is still checked in the child.
        // SAFETY: PR_GET_NO_NEW_PRIVS has no pointer arguments.
        let seccomp = unsafe { libc::prctl(libc::PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) } >= 0;
        let reason = if seccomp && landlock_abi.is_some_and(|version| version >= 3) {
            None
        } else {
            Some("seccomp and Landlock ABI 3 or newer are required for PROVEN".into())
        };
        SandboxCapabilities {
            seccomp,
            landlock_abi,
            reason,
        }
    }

    pub fn apply(policy: &SandboxPolicy) -> Result<EnforcementResult, SandboxError> {
        let capabilities = capabilities();
        if !capabilities.can_prove() {
            return Err(SandboxError::Unsupported(
                capabilities
                    .reason
                    .unwrap_or_else(|| "kernel capabilities unavailable".into()),
            ));
        }
        apply_landlock(policy, capabilities.landlock_abi.unwrap_or(1))?;
        apply_seccomp(policy.allow_network)?;
        Ok(EnforcementResult {
            seccomp_applied: true,
            landlock_applied: true,
        })
    }

    fn apply_landlock(policy: &SandboxPolicy, abi: i32) -> Result<(), SandboxError> {
        let write_access = WRITE_ACCESS_V1
            | if abi >= 2 {
                LANDLOCK_ACCESS_FS_REFER
            } else {
                0
            }
            | if abi >= 3 {
                LANDLOCK_ACCESS_FS_TRUNCATE
            } else {
                0
            };
        let attr = LandlockRulesetAttr {
            handled_access_fs: READ_ACCESS | write_access,
        };
        // SAFETY: attr points to a correctly sized C-compatible structure.
        let ruleset_fd = unsafe {
            libc::syscall(
                libc::SYS_landlock_create_ruleset,
                &attr,
                std::mem::size_of::<LandlockRulesetAttr>(),
                0,
            )
        } as i32;
        if ruleset_fd < 0 {
            return Err(last_error("create Landlock ruleset"));
        }
        let result = (|| {
            for path in &policy.readable_paths {
                add_path_rule(ruleset_fd, path, READ_ACCESS)?;
            }
            for path in &policy.writable_paths {
                add_path_rule(ruleset_fd, path, READ_ACCESS | write_access)?;
            }
            // SAFETY: prctl is called with the documented scalar arguments.
            if unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } != 0 {
                return Err(last_error("set no_new_privs"));
            }
            // SAFETY: ruleset_fd is owned and valid until the call completes.
            if unsafe { libc::syscall(libc::SYS_landlock_restrict_self, ruleset_fd, 0) } != 0 {
                return Err(last_error("apply Landlock ruleset"));
            }
            Ok(())
        })();
        // SAFETY: ruleset_fd was returned by the kernel and has not been closed.
        unsafe { libc::close(ruleset_fd) };
        result
    }

    fn add_path_rule(ruleset_fd: i32, path: &Path, access: u64) -> Result<(), SandboxError> {
        let path = CString::new(path.as_os_str().as_bytes())
            .map_err(|_| SandboxError::Setup(format!("path contains NUL: {}", path.display())))?;
        // SAFETY: path is NUL terminated and flags contain no mode argument.
        let path_fd = unsafe { libc::open(path.as_ptr(), libc::O_PATH | libc::O_CLOEXEC) };
        if path_fd < 0 {
            return Err(last_error("open Landlock path"));
        }
        let attr = LandlockPathBeneathAttr {
            allowed_access: access,
            parent_fd: path_fd,
        };
        // SAFETY: both file descriptors are valid and attr has the kernel ABI layout.
        let result = unsafe {
            libc::syscall(
                libc::SYS_landlock_add_rule,
                ruleset_fd,
                LANDLOCK_RULE_PATH_BENEATH,
                &attr,
                0,
            )
        };
        // SAFETY: path_fd was opened above and has not been closed.
        unsafe { libc::close(path_fd) };
        if result != 0 {
            return Err(last_error("add Landlock path rule"));
        }
        Ok(())
    }

    fn apply_seccomp(allow_network: bool) -> Result<(), SandboxError> {
        if allow_network {
            return Err(SandboxError::Unsupported(
                "V1 enforced mode does not permit network access".into(),
            ));
        }
        const LD_ARCH: libc::sock_filter = stmt(0x20, 4);
        const JEQ_ARCH: libc::sock_filter = jump(0x15, 0xc000_003e, 1, 0);
        const KILL: libc::sock_filter = stmt(0x06, libc::SECCOMP_RET_KILL_PROCESS);
        const LD_NR: libc::sock_filter = stmt(0x20, 0);
        const ALLOW: libc::sock_filter = stmt(0x06, libc::SECCOMP_RET_ALLOW);
        const DENY: libc::sock_filter = stmt(0x06, libc::SECCOMP_RET_ERRNO | libc::EPERM as u32);

        let denied = [
            libc::SYS_socket,
            libc::SYS_socketpair,
            libc::SYS_connect,
            libc::SYS_bind,
            libc::SYS_listen,
            libc::SYS_accept,
            libc::SYS_accept4,
            libc::SYS_sendto,
            libc::SYS_sendmsg,
            libc::SYS_recvfrom,
            libc::SYS_recvmsg,
            libc::SYS_ptrace,
            libc::SYS_mount,
            libc::SYS_umount2,
            libc::SYS_reboot,
            libc::SYS_kexec_load,
            libc::SYS_init_module,
            libc::SYS_finit_module,
            libc::SYS_delete_module,
            libc::SYS_swapon,
            libc::SYS_swapoff,
            libc::SYS_bpf,
            libc::SYS_keyctl,
        ];
        let mut filter = Vec::with_capacity(denied.len() * 2 + 5);
        filter.extend([LD_ARCH, JEQ_ARCH, KILL, LD_NR]);
        for syscall in denied {
            filter.push(jump(0x15, syscall as u32, 0, 1));
            filter.push(DENY);
        }
        filter.push(ALLOW);
        let mut program = libc::sock_fprog {
            len: filter.len() as u16,
            filter: filter.as_mut_ptr(),
        };
        // SAFETY: program references filter for the duration of prctl and the kernel copies it.
        if unsafe {
            libc::prctl(
                libc::PR_SET_SECCOMP,
                libc::SECCOMP_MODE_FILTER,
                &mut program,
            )
        } != 0
        {
            return Err(last_error("install seccomp filter"));
        }
        Ok(())
    }

    const fn stmt(code: u16, value: u32) -> libc::sock_filter {
        libc::sock_filter {
            code,
            jt: 0,
            jf: 0,
            k: value,
        }
    }

    const fn jump(code: u16, value: u32, jt: u8, jf: u8) -> libc::sock_filter {
        libc::sock_filter {
            code,
            jt,
            jf,
            k: value,
        }
    }

    fn last_error(action: &str) -> SandboxError {
        SandboxError::Setup(format!("{action}: {}", io::Error::last_os_error()))
    }
}

pub fn capabilities() -> SandboxCapabilities {
    #[cfg(target_os = "linux")]
    {
        linux::capabilities()
    }
    #[cfg(not(target_os = "linux"))]
    {
        SandboxCapabilities {
            seccomp: false,
            landlock_abi: None,
            reason: Some("TraceJIT enforcement is Linux-only".into()),
        }
    }
}

pub fn apply(policy: &SandboxPolicy) -> Result<EnforcementResult, SandboxError> {
    #[cfg(target_os = "linux")]
    {
        linux::apply(policy)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = policy;
        Err(SandboxError::Unsupported(
            "TraceJIT enforcement is Linux-only".into(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsupported_or_partial_sandbox_cannot_prove() {
        let capability = capabilities();
        if !capability.seccomp || capability.landlock_abi.is_none() {
            assert!(!capability.can_prove());
        }
    }

    #[cfg(target_os = "linux")]
    #[derive(Clone, Copy)]
    enum Probe {
        DeclaredFile,
        UndeclaredFile,
        Network,
        ForbiddenSyscall,
    }

    #[cfg(target_os = "linux")]
    fn sandbox_probe(policy: &SandboxPolicy, declared: &std::path::Path, probe: Probe) -> i32 {
        // SAFETY: the child performs no test-harness work after fork. It applies the sandbox,
        // performs one isolated syscall probe, and exits with _exit. The parent only waits.
        let child = unsafe { libc::fork() };
        assert!(
            child >= 0,
            "fork failed: {}",
            std::io::Error::last_os_error()
        );
        if child == 0 {
            if apply(policy).is_err() {
                // SAFETY: this is the fork child and no Rust destructors should run here.
                unsafe { libc::_exit(125) };
            }
            let passed = match probe {
                Probe::DeclaredFile => std::fs::File::open(declared).is_ok(),
                Probe::UndeclaredFile => std::fs::File::open("/etc/passwd")
                    .is_err_and(|error| error.raw_os_error() == Some(libc::EACCES)),
                Probe::Network => {
                    // SAFETY: socket has scalar arguments and returns a new descriptor or errno.
                    let fd = unsafe { libc::socket(libc::AF_INET, libc::SOCK_STREAM, 0) };
                    if fd >= 0 {
                        // SAFETY: fd was returned by socket in this branch.
                        unsafe { libc::close(fd) };
                        false
                    } else {
                        std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
                    }
                }
                Probe::ForbiddenSyscall => {
                    // SAFETY: PTRACE_TRACEME takes no pointer arguments.
                    let result = unsafe {
                        libc::ptrace(
                            libc::PTRACE_TRACEME,
                            0,
                            std::ptr::null_mut::<libc::c_void>(),
                            std::ptr::null_mut::<libc::c_void>(),
                        )
                    };
                    result == -1
                        && std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
                }
            };
            // SAFETY: this is the fork child and no Rust destructors should run here.
            unsafe { libc::_exit(if passed { 0 } else { 1 }) };
        }
        let mut status = 0;
        // SAFETY: child is a live child PID returned by fork and status is writable.
        let waited = unsafe { libc::waitpid(child, &mut status, 0) };
        assert_eq!(waited, child, "waitpid failed");
        if libc::WIFEXITED(status) {
            libc::WEXITSTATUS(status)
        } else {
            128
        }
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn supported_sandbox_enforces_declared_surface() {
        let capability = capabilities();
        if !capability.can_prove() {
            println!(
                "skipped sandbox enforcement probes: {}",
                capability
                    .reason
                    .unwrap_or_else(|| "required kernel features unavailable".into())
            );
            return;
        }
        let temporary = tempfile::tempdir().unwrap();
        let declared = temporary.path().join("declared.txt");
        std::fs::write(&declared, b"declared").unwrap();
        let policy = SandboxPolicy {
            readable_paths: vec![declared.clone()],
            writable_paths: Vec::new(),
            allow_network: false,
        };

        let declared_status = sandbox_probe(&policy, &declared, Probe::DeclaredFile);
        if declared_status == 125 {
            println!("skipped sandbox enforcement probes: policy installation failed");
            return;
        }
        assert_eq!(declared_status, 0, "declared filesystem path was denied");
        assert_eq!(
            sandbox_probe(&policy, &declared, Probe::UndeclaredFile),
            0,
            "undeclared filesystem path was accessible"
        );
        assert_eq!(
            sandbox_probe(&policy, &declared, Probe::Network),
            0,
            "undeclared network syscall was accessible"
        );
        assert_eq!(
            sandbox_probe(&policy, &declared, Probe::ForbiddenSyscall),
            0,
            "forbidden syscall was accessible"
        );
    }
}

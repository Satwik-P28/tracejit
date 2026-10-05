use super::{TraceError, TraceOutcome, TraceRequest};
use nix::errno::Errno;
use nix::sys::ptrace;
use nix::sys::signal::{kill, Signal};
use nix::sys::wait::{waitpid, WaitPidFlag, WaitStatus};
use nix::unistd::Pid;
use std::collections::{HashMap, HashSet};
use std::ffi::OsString;
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::unix::ffi::OsStringExt;
use std::os::unix::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tracejit_effects::{
    ClockKind, ControlEffect, DependencyEdge, DependencyKind, Effect, EffectRecord,
    ExecutionMetadata, FileMetadataRead, FileRead, FileWrite, FileWriteKind, IpcWrite,
    KernelStateRead, NetworkRead, NetworkWrite, ProcessExec, ProcessNode, ProcessSpawn,
    RandomSource, ReadEffect, SignalEffect, SymlinkRead, Trace, UnknownEffect, WriteEffect,
};
use tracejit_guards::{fingerprint, hash_file, symlink_fingerprint};

const OPTIONS: ptrace::Options = ptrace::Options::PTRACE_O_TRACESYSGOOD
    .union(ptrace::Options::PTRACE_O_TRACEFORK)
    .union(ptrace::Options::PTRACE_O_TRACEVFORK)
    .union(ptrace::Options::PTRACE_O_TRACECLONE)
    .union(ptrace::Options::PTRACE_O_TRACEEXEC)
    .union(ptrace::Options::PTRACE_O_EXITKILL);

#[derive(Clone)]
struct ProcessState {
    cwd: PathBuf,
    fds: HashMap<i32, FdState>,
    close_on_exec: HashSet<i32>,
    entering: bool,
    synchronize_on_next_syscall: bool,
    pending: Option<PendingSyscall>,
    file_mappings: Vec<FileMapping>,
    /// False after exec until vDSO time entry points are redirected to syscalls.
    vdso_disarmed: bool,
}

#[derive(Clone)]
struct FileMapping {
    start: u64,
    end: u64,
    shared: bool,
    /// Kept so a split mapping still records whether the range is writable.
    /// The reuse decision uses the protection being applied, so this bit is
    /// not read again on the non-test path.
    #[allow(dead_code)]
    writable: bool,
}

#[derive(Clone)]
enum FdState {
    File(PathBuf),
    InheritedFile(PathBuf),
    Network,
    Other,
}

#[derive(Clone)]
enum PendingSyscall {
    Open {
        path: PathBuf,
        flags: i32,
        before_hash: Option<tracejit_effects::Hash>,
        before_fingerprint: Option<tracejit_effects::FileFingerprint>,
    },
    Metadata {
        path: PathBuf,
    },
    SymlinkMetadata {
        path: PathBuf,
    },
    ReadLink {
        path: PathBuf,
    },
    TerminalProbe {
        path: PathBuf,
    },
    InheritedTerminalProbe,
    Access {
        path: PathBuf,
    },
    Chdir {
        path: PathBuf,
    },
    ExecAttempt {
        path: PathBuf,
    },
    CreateDirectory {
        path: PathBuf,
    },
    Dup {
        source: i32,
        destination: Option<i32>,
        close_on_exec: bool,
    },
    Close {
        fd: i32,
    },
    SetCloseOnExec {
        fd: i32,
        enabled: bool,
    },
    Rename {
        from: PathBuf,
        to: PathBuf,
        from_snapshot: PathSnapshot,
        to_snapshot: PathSnapshot,
    },
    Delete {
        path: PathBuf,
        snapshot: PathSnapshot,
    },
    Read {
        fd: i32,
    },
    Write {
        fd: i32,
    },
    Network {
        kind: NetworkOperation,
    },
    Clock {
        kind: ClockKind,
    },
    Random,
    KernelState {
        kind: KernelStateRead,
    },
    Signal {
        signal: i32,
        target: i64,
    },
    Mmap {
        length: u64,
        prot: u64,
        flags: u64,
    },
    Mprotect {
        address: u64,
        length: u64,
        prot: u64,
    },
    Munmap {
        address: u64,
        length: u64,
    },
    Mremap {
        address: u64,
        old_length: u64,
    },
    Unknown {
        number: i64,
        detail: String,
    },
    None,
}

#[derive(Clone)]
enum PathSnapshot {
    File {
        hash: tracejit_effects::Hash,
        fingerprint: tracejit_effects::FileFingerprint,
    },
    Metadata(tracejit_effects::FileFingerprint),
    Absent,
    Unavailable,
}

#[derive(Clone, Copy)]
enum NetworkOperation {
    Socket,
    Read(&'static str),
    Write(&'static str),
}

struct Collector {
    sequence: u64,
    effects: Vec<EffectRecord>,
    dependencies: Vec<DependencyEdge>,
}

struct TraceeGuard {
    pids: Vec<Pid>,
    active: bool,
}

impl Drop for TraceeGuard {
    fn drop(&mut self) {
        if self.active {
            for pid in &self.pids {
                let _ = kill(*pid, Signal::SIGKILL);
            }
        }
    }
}

impl Collector {
    fn push(&mut self, pid: Pid, effect: Effect) {
        let kind = match &effect {
            Effect::Read(_) => DependencyKind::Reads,
            Effect::Write(_) => DependencyKind::Writes,
            Effect::Control(ControlEffect::Spawn(_)) => DependencyKind::SpawnedBy,
            Effect::Control(ControlEffect::Exec(_)) => DependencyKind::ExecutedBy,
            Effect::Control(_) => DependencyKind::DependsOn,
            Effect::Unknown(_) => DependencyKind::Unknown,
        };
        self.dependencies.push(DependencyEdge {
            from: format!("process:{}", pid.as_raw()),
            to: effect_target(&effect),
            kind,
        });
        self.effects.push(EffectRecord {
            sequence: self.sequence,
            pid: pid.as_raw() as u32,
            effect,
        });
        self.sequence += 1;
    }
}

pub(super) fn trace_command(request: TraceRequest) -> Result<TraceOutcome, TraceError> {
    if !request.executable.is_file() {
        return Err(TraceError::TargetNotFound(request.executable));
    }
    let started_unix_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let started = Instant::now();
    let mut command = Command::new(&request.executable);
    if request.argv.len() > 1 {
        command.args(&request.argv[1..]);
    }
    command
        .current_dir(&request.cwd)
        .env_clear()
        .envs(&request.environment)
        .stdin(Stdio::inherit())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let sandbox = request.sandbox.clone();
    // SAFETY: pre_exec runs in the single-threaded child between fork and exec. The closure only
    // performs async-signal-safe syscalls and returns an io::Error if setup fails.
    unsafe {
        command.pre_exec(move || {
            ptrace::traceme().map_err(std::io::Error::other)?;
            if let Some(policy) = &sandbox {
                tracejit_sandbox::apply(policy).map_err(std::io::Error::other)?;
            }
            Ok(())
        });
    }
    let mut child = command
        .spawn()
        .map_err(|error| TraceError::Spawn(error.to_string()))?;
    let root_pid = Pid::from_raw(child.id() as i32);
    let mut tracee_guard = TraceeGuard {
        pids: vec![root_pid],
        active: true,
    };
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| TraceError::OutputCapture("stdout pipe unavailable".into()))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| TraceError::OutputCapture("stderr pipe unavailable".into()))?;
    let stdout_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut stream = stdout;
        stream.read_to_end(&mut bytes).map(|_| bytes)
    });
    let stderr_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut stream = stderr;
        stream.read_to_end(&mut bytes).map(|_| bytes)
    });

    match waitpid(root_pid, None).map_err(ptrace_error)? {
        WaitStatus::Stopped(_, Signal::SIGTRAP) => {}
        status => {
            return Err(TraceError::TargetTerminated(format!(
                "expected exec trap, received {status:?}"
            )))
        }
    }
    // The legacy exec stop is the new program's entry point. No userspace
    // instruction has run, so libc has not yet cached a vDSO time pointer.
    let initial_vdso = disarm_vdso_time(root_pid);
    ptrace::setoptions(root_pid, OPTIONS)
        .map_err(|error| ptrace_operation("set initial options", root_pid, error))?;
    ptrace::syscall(root_pid, None)
        .map_err(|error| ptrace_operation("resume initial process", root_pid, error))?;

    let mut states = HashMap::from([(
        root_pid,
        ProcessState {
            cwd: request.cwd.clone(),
            fds: (0..=2)
                .map(|fd| (fd, inherited_fd_state(root_pid, fd)))
                .collect(),
            close_on_exec: HashSet::new(),
            entering: true,
            synchronize_on_next_syscall: false,
            pending: None,
            file_mappings: Vec::new(),
            vdso_disarmed: true,
        },
    )]);
    let mut processes = vec![ProcessNode {
        pid: root_pid.as_raw() as u32,
        parent_pid: None,
        executable: Some(request.executable.clone()),
        exit_code: None,
    }];
    let mut collector = Collector {
        sequence: 0,
        effects: Vec::new(),
        dependencies: Vec::new(),
    };
    collector.push(
        root_pid,
        Effect::Control(ControlEffect::Exec(ProcessExec {
            path: request.executable.clone(),
            hash: hash_file(&request.executable).ok(),
            fingerprint: fingerprint(&request.executable).ok(),
        })),
    );
    if let Err(detail) = initial_vdso {
        collector.push(
            root_pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail,
            }),
        );
    }
    let mut root_exit = None;

    while !states.is_empty() {
        let status = match waitpid(Pid::from_raw(-1), Some(WaitPidFlag::__WALL)) {
            Ok(status) => status,
            Err(Errno::ECHILD) => break,
            Err(error) => return Err(ptrace_error(error)),
        };
        match status {
            WaitStatus::PtraceSyscall(pid) => {
                ensure_vdso_disarmed(pid, &mut states, &mut collector);
                handle_syscall(pid, &mut states, &mut collector, request.sandbox.is_some())?;
                ptrace::syscall(pid, None)
                    .map_err(|error| ptrace_operation("resume after syscall", pid, error))?;
            }
            WaitStatus::PtraceEvent(pid, Signal::SIGTRAP, event)
                if event == libc::PTRACE_EVENT_FORK
                    || event == libc::PTRACE_EVENT_VFORK
                    || event == libc::PTRACE_EVENT_CLONE =>
            {
                let child_pid = Pid::from_raw(ptrace::getevent(pid).map_err(ptrace_error)? as i32);
                tracee_guard.pids.push(child_pid);
                let inherited = states
                    .get(&pid)
                    .cloned()
                    .ok_or_else(|| TraceError::Ptrace(format!("missing parent state for {pid}")))?;
                states.insert(
                    child_pid,
                    ProcessState {
                        // A newly attached fork/clone child resumes at the exit side of the
                        // creating syscall on common kernels, but the first reported boundary
                        // varies across ptrace implementations. Synchronize from x86_64's
                        // entry-stop return-register sentinel before decoding it.
                        entering: false,
                        synchronize_on_next_syscall: true,
                        pending: None,
                        ..inherited
                    },
                );
                processes.push(ProcessNode {
                    pid: child_pid.as_raw() as u32,
                    parent_pid: Some(pid.as_raw() as u32),
                    executable: None,
                    exit_code: None,
                });
                collector.push(
                    pid,
                    Effect::Control(ControlEffect::Spawn(ProcessSpawn {
                        child_pid: child_pid.as_raw() as u32,
                    })),
                );
                if event == libc::PTRACE_EVENT_CLONE {
                    collector.push(
                        pid,
                        Effect::Unknown(UnknownEffect {
                            syscall: None,
                            detail: "clone file-descriptor and cwd sharing semantics are not eligible for V1 reuse"
                                .into(),
                        }),
                    );
                }
                ptrace::syscall(pid, None).map_err(ptrace_error)?;
            }
            WaitStatus::PtraceEvent(pid, Signal::SIGTRAP, event)
                if event == libc::PTRACE_EVENT_EXEC =>
            {
                let path = fs::read_link(format!("/proc/{}/exe", pid.as_raw()))
                    .unwrap_or_else(|_| PathBuf::from("<unresolved>"));
                collector.push(
                    pid,
                    Effect::Control(ControlEffect::Exec(ProcessExec {
                        hash: hash_file(&path).ok(),
                        fingerprint: fingerprint(&path).ok(),
                        path: path.clone(),
                    })),
                );
                if let Some(process) = processes
                    .iter_mut()
                    .find(|process| process.pid == pid.as_raw() as u32)
                {
                    process.executable = Some(path);
                }
                if let Some(state) = states.get_mut(&pid) {
                    let closed = state.close_on_exec.drain().collect::<Vec<_>>();
                    for fd in closed {
                        state.fds.remove(&fd);
                    }
                    state.entering = false;
                    state.synchronize_on_next_syscall = true;
                    state.pending = None;
                    state.file_mappings.clear();
                    state.vdso_disarmed = false;
                }
                ptrace::syscall(pid, None).map_err(ptrace_error)?;
            }
            WaitStatus::Stopped(pid, signal) => {
                ensure_vdso_disarmed(pid, &mut states, &mut collector);
                ptrace::setoptions(pid, OPTIONS)
                    .map_err(|error| ptrace_operation("set process options", pid, error))?;
                let deliver = if signal == Signal::SIGSTOP {
                    None
                } else {
                    if signal != Signal::SIGCHLD {
                        collector.push(
                            pid,
                            Effect::Control(ControlEffect::Signal(SignalEffect {
                                signal: signal as i32,
                                target_pid: pid.as_raw() as i64,
                            })),
                        );
                    }
                    Some(signal)
                };
                ptrace::syscall(pid, deliver).map_err(ptrace_error)?;
            }
            WaitStatus::Exited(pid, code) => {
                if pid == root_pid {
                    root_exit = Some(code);
                }
                if let Some(process) = processes
                    .iter_mut()
                    .find(|process| process.pid == pid.as_raw() as u32)
                {
                    process.exit_code = Some(code);
                }
                states.remove(&pid);
                tracee_guard.pids.retain(|tracee| *tracee != pid);
            }
            WaitStatus::Signaled(pid, signal, _) => {
                let code = 128 + signal as i32;
                if pid == root_pid {
                    root_exit = Some(code);
                }
                if let Some(process) = processes
                    .iter_mut()
                    .find(|process| process.pid == pid.as_raw() as u32)
                {
                    process.exit_code = Some(code);
                }
                states.remove(&pid);
                tracee_guard.pids.retain(|tracee| *tracee != pid);
            }
            WaitStatus::Continued(_) | WaitStatus::StillAlive => {}
            other => {
                return Err(TraceError::Ptrace(format!(
                    "unhandled wait status: {other:?}"
                )))
            }
        }
    }
    let stdout = stdout_reader
        .join()
        .map_err(|_| TraceError::OutputCapture("stdout reader panicked".into()))?
        .map_err(|error| TraceError::OutputCapture(error.to_string()))?;
    let stderr = stderr_reader
        .join()
        .map_err(|_| TraceError::OutputCapture("stderr reader panicked".into()))?
        .map_err(|error| TraceError::OutputCapture(error.to_string()))?;
    let exit_code = root_exit
        .ok_or_else(|| TraceError::TargetTerminated("root process exit was not observed".into()))?;
    let trace = Trace {
        execution: ExecutionMetadata {
            command: request.argv,
            started_unix_ms,
            runtime_ns: started.elapsed().as_nanos(),
            exit_code,
        },
        processes,
        effects: collector.effects,
        dependencies: collector.dependencies,
    };
    tracee_guard.active = false;
    Ok(TraceOutcome {
        trace,
        stdout,
        stderr,
        sandbox_enforced: request.sandbox.is_some(),
    })
}

fn handle_syscall(
    pid: Pid,
    states: &mut HashMap<Pid, ProcessState>,
    collector: &mut Collector,
    enforced: bool,
) -> Result<(), TraceError> {
    let registers =
        ptrace::getregs(pid).map_err(|error| ptrace_operation("read registers", pid, error))?;
    let state = states
        .get_mut(&pid)
        .ok_or_else(|| TraceError::Ptrace(format!("missing process state for {pid}")))?;
    if state.synchronize_on_next_syscall {
        state.entering = registers.rax as i64 == -(libc::ENOSYS as i64);
        state.synchronize_on_next_syscall = false;
    }
    if state.entering {
        state.pending = Some(decode_entry(pid, state, &registers)?);
        state.entering = false;
    } else {
        let result = registers.rax as i64;
        let pending = state.pending.take().unwrap_or(PendingSyscall::None);
        if result >= 0 {
            complete_syscall(pid, state, pending, result, collector);
        } else if enforced
            && (result == -(libc::EPERM as i64) || result == -(libc::EACCES as i64))
            && !matches!(pending, PendingSyscall::None)
        {
            collector.push(
                pid,
                Effect::Unknown(UnknownEffect {
                    syscall: Some(registers.orig_rax as i64),
                    detail: format!(
                        "enforced policy denied an unexpected effect: {}",
                        pending_description(&pending)
                    ),
                }),
            );
        } else {
            complete_failed_syscall(pid, pending, -result, collector);
        }
        state.entering = true;
    }
    Ok(())
}

fn decode_entry(
    pid: Pid,
    state: &ProcessState,
    registers: &libc::user_regs_struct,
) -> Result<PendingSyscall, TraceError> {
    let number = registers.orig_rax as i64;
    let args = [
        registers.rdi,
        registers.rsi,
        registers.rdx,
        registers.r10,
        registers.r8,
        registers.r9,
    ];
    let pending = match number {
        libc::SYS_open => open_pending(pid, state, libc::AT_FDCWD, args[0], args[1] as i32)?,
        libc::SYS_openat => open_pending(pid, state, args[0] as i32, args[1], args[2] as i32)?,
        libc::SYS_openat2 => {
            let flags = read_word(pid, args[2])? as i32;
            open_pending(pid, state, args[0] as i32, args[1], flags)?
        }
        libc::SYS_stat => PendingSyscall::Metadata {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_access => PendingSyscall::Access {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_faccessat => PendingSyscall::Access {
            path: resolve_path(pid, state, args[0] as i32, args[1])?,
        },
        libc::SYS_fstat => state
            .fds
            .get(&(args[0] as i32))
            .and_then(|fd| match fd {
                FdState::File(path) | FdState::InheritedFile(path) => {
                    Some(PendingSyscall::Metadata { path: path.clone() })
                }
                FdState::Other if args[0] <= 2 => Some(PendingSyscall::None),
                _ => None,
            })
            .unwrap_or_else(|| PendingSyscall::Unknown {
                number,
                detail: format!("fstat on unclassified fd {}", args[0]),
            }),
        libc::SYS_lstat => PendingSyscall::SymlinkMetadata {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_readlink => readlink_pending(pid, state, libc::AT_FDCWD, args[0], number)?,
        libc::SYS_readlinkat => readlink_pending(pid, state, args[0] as i32, args[1], number)?,
        libc::SYS_newfstatat
            if args[3] as i32 & libc::AT_EMPTY_PATH != 0
                && read_c_string(pid, args[1])?.is_empty() =>
        {
            state
                .fds
                .get(&(args[0] as i32))
                .and_then(|fd| match fd {
                    FdState::File(path) | FdState::InheritedFile(path) => {
                        Some(PendingSyscall::Metadata { path: path.clone() })
                    }
                    FdState::Other if args[0] <= 2 => Some(PendingSyscall::None),
                    _ => None,
                })
                .unwrap_or_else(|| PendingSyscall::Unknown {
                    number,
                    detail: format!("newfstatat AT_EMPTY_PATH on unclassified fd {}", args[0]),
                })
        }
        libc::SYS_newfstatat if args[3] as i32 & libc::AT_SYMLINK_NOFOLLOW != 0 => {
            PendingSyscall::SymlinkMetadata {
                path: resolve_path(pid, state, args[0] as i32, args[1])?,
            }
        }
        libc::SYS_statx if args[2] as i32 & libc::AT_SYMLINK_NOFOLLOW != 0 => {
            PendingSyscall::Unknown {
                number,
                detail: "statx AT_SYMLINK_NOFOLLOW result is not modeled".into(),
            }
        }
        libc::SYS_newfstatat => PendingSyscall::Metadata {
            path: resolve_path(pid, state, args[0] as i32, args[1])?,
        },
        libc::SYS_statx => PendingSyscall::Unknown {
            number,
            detail: "statx result is not modeled".into(),
        },
        libc::SYS_chdir => PendingSyscall::Chdir {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_execve => PendingSyscall::ExecAttempt {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_execveat => PendingSyscall::ExecAttempt {
            path: resolve_path(pid, state, args[0] as i32, args[1])?,
        },
        libc::SYS_mkdir => PendingSyscall::CreateDirectory {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_mkdirat => PendingSyscall::CreateDirectory {
            path: resolve_path(pid, state, args[0] as i32, args[1])?,
        },
        libc::SYS_fchdir => state
            .fds
            .get(&(args[0] as i32))
            .and_then(|fd| match fd {
                FdState::File(path) => Some(PendingSyscall::Chdir { path: path.clone() }),
                _ => None,
            })
            .unwrap_or_else(|| PendingSyscall::Unknown {
                number,
                detail: format!("fchdir on unclassified fd {}", args[0]),
            }),
        libc::SYS_dup => PendingSyscall::Dup {
            source: args[0] as i32,
            destination: None,
            close_on_exec: false,
        },
        libc::SYS_dup2 => PendingSyscall::Dup {
            source: args[0] as i32,
            destination: Some(args[1] as i32),
            close_on_exec: false,
        },
        libc::SYS_dup3 => PendingSyscall::Dup {
            source: args[0] as i32,
            destination: Some(args[1] as i32),
            close_on_exec: args[2] as i32 & libc::O_CLOEXEC != 0,
        },
        libc::SYS_fcntl
            if args[1] as i32 == libc::F_DUPFD || args[1] as i32 == libc::F_DUPFD_CLOEXEC =>
        {
            PendingSyscall::Dup {
                source: args[0] as i32,
                destination: None,
                close_on_exec: args[1] as i32 == libc::F_DUPFD_CLOEXEC,
            }
        }
        libc::SYS_fcntl if args[1] as i32 == libc::F_SETFD => PendingSyscall::SetCloseOnExec {
            fd: args[0] as i32,
            enabled: args[2] as i32 & libc::FD_CLOEXEC != 0,
        },
        libc::SYS_fcntl => PendingSyscall::None,
        libc::SYS_close => PendingSyscall::Close { fd: args[0] as i32 },
        libc::SYS_read | libc::SYS_readv | libc::SYS_pread64 => {
            PendingSyscall::Read { fd: args[0] as i32 }
        }
        libc::SYS_write | libc::SYS_writev | libc::SYS_pwrite64 => {
            PendingSyscall::Write { fd: args[0] as i32 }
        }
        libc::SYS_rename => rename_pending(
            resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
            resolve_path(pid, state, libc::AT_FDCWD, args[1])?,
        ),
        libc::SYS_renameat | libc::SYS_renameat2 => rename_pending(
            resolve_path(pid, state, args[0] as i32, args[1])?,
            resolve_path(pid, state, args[2] as i32, args[3])?,
        ),
        libc::SYS_unlink => delete_pending(resolve_path(pid, state, libc::AT_FDCWD, args[0])?),
        libc::SYS_unlinkat => delete_pending(resolve_path(pid, state, args[0] as i32, args[1])?),
        libc::SYS_socket | libc::SYS_socketpair => PendingSyscall::Network {
            kind: NetworkOperation::Socket,
        },
        libc::SYS_connect | libc::SYS_bind | libc::SYS_listen => PendingSyscall::Network {
            kind: NetworkOperation::Write("socket control"),
        },
        libc::SYS_sendto | libc::SYS_sendmsg | libc::SYS_sendmmsg => PendingSyscall::Network {
            kind: NetworkOperation::Write("socket send"),
        },
        libc::SYS_recvfrom
        | libc::SYS_recvmsg
        | libc::SYS_recvmmsg
        | libc::SYS_accept
        | libc::SYS_accept4 => PendingSyscall::Network {
            kind: NetworkOperation::Read("socket receive"),
        },
        libc::SYS_clock_gettime | libc::SYS_gettimeofday | libc::SYS_time => {
            let kind = if number == libc::SYS_clock_gettime {
                match args[0] as i32 {
                    libc::CLOCK_REALTIME => ClockKind::Realtime,
                    libc::CLOCK_MONOTONIC => ClockKind::Monotonic,
                    other => ClockKind::Other(other),
                }
            } else {
                ClockKind::Realtime
            };
            PendingSyscall::Clock { kind }
        }
        libc::SYS_getrandom => PendingSyscall::Random,
        libc::SYS_mmap => {
            let length = args[1];
            let prot = args[2];
            let flags = args[3];
            let fd = args[4] as i64;
            let anonymous = flags & libc::MAP_ANONYMOUS as u64 != 0 || fd < 0;
            if anonymous {
                PendingSyscall::None
            } else {
                PendingSyscall::Mmap {
                    length,
                    prot,
                    flags,
                }
            }
        }
        libc::SYS_mprotect => PendingSyscall::Mprotect {
            address: args[0],
            length: args[1],
            prot: args[2],
        },
        libc::SYS_munmap => PendingSyscall::Munmap {
            address: args[0],
            length: args[1],
        },
        libc::SYS_mremap => PendingSyscall::Mremap {
            address: args[0],
            old_length: args[1],
        },
        libc::SYS_uname => PendingSyscall::KernelState {
            kind: KernelStateRead::Hostname,
        },
        libc::SYS_prlimit64
            if args[0] == 0
                && args[1] == libc::RLIMIT_STACK as u64
                && args[2] == 0
                && args[3] != 0 =>
        {
            // glibc queries the inherited stack limit during startup. RuntimeIdentity guards the
            // same values before reuse. Limit changes and all other prlimit calls remain effects.
            PendingSyscall::None
        }
        libc::SYS_sysinfo => system_information("sysinfo"),
        libc::SYS_sched_getaffinity => system_information("sched_getaffinity"),
        libc::SYS_prlimit64 => system_information("prlimit64"),
        libc::SYS_getpid => process_identity("getpid"),
        libc::SYS_getppid => process_identity("getppid"),
        libc::SYS_gettid => process_identity("gettid"),
        libc::SYS_getpgrp => process_identity("getpgrp"),
        libc::SYS_getpgid => process_identity("getpgid"),
        libc::SYS_getsid => process_identity("getsid"),
        libc::SYS_getuid | libc::SYS_geteuid | libc::SYS_getgid | libc::SYS_getegid => {
            PendingSyscall::KernelState {
                kind: KernelStateRead::Identity,
            }
        }
        libc::SYS_kill | libc::SYS_tkill | libc::SYS_tgkill => PendingSyscall::Signal {
            target: args[0] as i64,
            signal: if number == libc::SYS_tgkill {
                args[2] as i32
            } else {
                args[1] as i32
            },
        },
        libc::SYS_ioctl if args[1] == libc::FIOCLEX => PendingSyscall::SetCloseOnExec {
            fd: args[0] as i32,
            enabled: true,
        },
        libc::SYS_ioctl if args[1] == libc::FIONCLEX => PendingSyscall::SetCloseOnExec {
            fd: args[0] as i32,
            enabled: false,
        },
        libc::SYS_ioctl if args[1] == libc::TCGETS => state
            .fds
            .get(&(args[0] as i32))
            .and_then(|fd| match fd {
                FdState::File(path) | FdState::InheritedFile(path) => {
                    Some(PendingSyscall::TerminalProbe { path: path.clone() })
                }
                FdState::Other if args[0] == 1 || args[0] == 2 => Some(PendingSyscall::None),
                FdState::Other if args[0] == 0 => Some(PendingSyscall::InheritedTerminalProbe),
                _ => None,
            })
            .unwrap_or_else(|| PendingSyscall::Unknown {
                number,
                detail: format!("TCGETS on unclassified fd {}", args[0]),
            }),
        libc::SYS_ioctl if args[0] == 1 || args[0] == 2 => PendingSyscall::None,
        _ if is_known_internal_syscall(number) => PendingSyscall::None,
        _ => PendingSyscall::Unknown {
            number,
            detail: format!(
                "unmodeled syscall {number} args [{:#x}, {:#x}, {:#x}, {:#x}, {:#x}, {:#x}]",
                args[0], args[1], args[2], args[3], args[4], args[5]
            ),
        },
    };
    Ok(pending)
}

fn system_information(syscall: &str) -> PendingSyscall {
    PendingSyscall::KernelState {
        kind: KernelStateRead::SystemInfo {
            syscall: syscall.into(),
        },
    }
}

fn process_identity(syscall: &str) -> PendingSyscall {
    PendingSyscall::KernelState {
        kind: KernelStateRead::ProcessIdentity {
            syscall: syscall.into(),
        },
    }
}

fn rename_pending(from: PathBuf, to: PathBuf) -> PendingSyscall {
    PendingSyscall::Rename {
        from_snapshot: path_snapshot(&from),
        to_snapshot: path_snapshot(&to),
        from,
        to,
    }
}

fn delete_pending(path: PathBuf) -> PendingSyscall {
    PendingSyscall::Delete {
        snapshot: path_snapshot(&path),
        path,
    }
}

fn path_snapshot(path: &Path) -> PathSnapshot {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return PathSnapshot::Absent,
        Err(_) => return PathSnapshot::Unavailable,
    };
    if metadata.file_type().is_symlink() {
        return PathSnapshot::Unavailable;
    }
    let fingerprint = match fingerprint(path) {
        Ok(fingerprint) => fingerprint,
        Err(_) => return PathSnapshot::Unavailable,
    };
    if metadata.is_file() {
        match hash_file(path) {
            Ok(hash) => PathSnapshot::File { hash, fingerprint },
            Err(_) => PathSnapshot::Unavailable,
        }
    } else {
        PathSnapshot::Metadata(fingerprint)
    }
}

fn record_snapshot(pid: Pid, path: PathBuf, snapshot: PathSnapshot, collector: &mut Collector) {
    match snapshot {
        PathSnapshot::File { hash, fingerprint } => collector.push(
            pid,
            Effect::Read(ReadEffect::File(FileRead {
                path,
                hash: Some(hash),
                fingerprint: Some(fingerprint),
            })),
        ),
        PathSnapshot::Metadata(fingerprint) => collector.push(
            pid,
            Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                path,
                fingerprint: Some(fingerprint),
            })),
        ),
        PathSnapshot::Absent => collector.push(
            pid,
            Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                path,
                fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
            })),
        ),
        PathSnapshot::Unavailable => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "filesystem precondition cannot be guarded: {}",
                    path.display()
                ),
            }),
        ),
    }
}

fn record_metadata(pid: Pid, path: PathBuf, collector: &mut Collector) {
    match fingerprint(&path) {
        Ok(value) => collector.push(
            pid,
            Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                fingerprint: Some(value),
                path,
            })),
        ),
        Err(error) => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "metadata dependency cannot be guarded: {} ({error})",
                    path.display()
                ),
            }),
        ),
    }
}

fn record_symlink_metadata(pid: Pid, path: PathBuf, collector: &mut Collector) {
    match symlink_fingerprint(&path) {
        Ok(value) => collector.push(
            pid,
            Effect::Read(ReadEffect::SymlinkMetadata(FileMetadataRead {
                fingerprint: Some(value),
                path,
            })),
        ),
        Err(error) => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "symlink metadata dependency cannot be guarded: {} ({error})",
                    path.display()
                ),
            }),
        ),
    }
}

fn open_pending(
    pid: Pid,
    state: &ProcessState,
    dirfd: i32,
    address: u64,
    flags: i32,
) -> Result<PendingSyscall, TraceError> {
    let path = resolve_path(pid, state, dirfd, address)?;
    Ok(PendingSyscall::Open {
        before_hash: path.is_file().then(|| hash_file(&path).ok()).flatten(),
        before_fingerprint: fingerprint(&path).ok(),
        path,
        flags,
    })
}

fn readlink_pending(
    pid: Pid,
    state: &ProcessState,
    dirfd: i32,
    address: u64,
    _number: i64,
) -> Result<PendingSyscall, TraceError> {
    let path = resolve_path(pid, state, dirfd, address)?;
    let process_executable = format!("/proc/{}/exe", pid.as_raw());
    let own_executable = path == Path::new("/proc/self/exe")
        || path == Path::new("/proc/thread-self/exe")
        || path == Path::new(&process_executable);
    Ok(if own_executable {
        PendingSyscall::None
    } else {
        PendingSyscall::ReadLink { path }
    })
}

fn complete_syscall(
    pid: Pid,
    state: &mut ProcessState,
    pending: PendingSyscall,
    result: i64,
    collector: &mut Collector,
) {
    match pending {
        PendingSyscall::Open {
            path,
            flags,
            before_hash,
            before_fingerprint,
        } => {
            let fd = result as i32;
            if is_random_device(&path) {
                state.fds.insert(fd, FdState::File(path.clone()));
                collector.push(
                    pid,
                    Effect::Read(ReadEffect::Random(RandomSource::Device(path))),
                );
            } else if is_proc_self(&path) {
                state.fds.insert(fd, FdState::File(path.clone()));
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_open),
                        detail: format!("process-relative procfs dependency: {}", path.display()),
                    }),
                );
            } else if path.starts_with("/proc") && before_hash.is_none() {
                state.fds.insert(fd, FdState::File(path.clone()));
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_open),
                        detail: format!(
                            "unhashable procfs dependency cannot be guarded: {}",
                            path.display()
                        ),
                    }),
                );
            } else if flags & (libc::O_WRONLY | libc::O_RDWR | libc::O_CREAT | libc::O_TRUNC) != 0 {
                state.fds.insert(fd, FdState::File(path.clone()));
                if flags & libc::O_TRUNC == 0 {
                    if let Some(hash) = before_hash {
                        collector.push(
                            pid,
                            Effect::Read(ReadEffect::File(FileRead {
                                path: path.clone(),
                                hash: Some(hash),
                                fingerprint: before_fingerprint.clone(),
                            })),
                        );
                    } else if before_fingerprint.is_none() && flags & libc::O_CREAT != 0 {
                        collector.push(
                            pid,
                            Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                                path: path.clone(),
                                fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
                            })),
                        );
                    }
                }
                collector.push(
                    pid,
                    Effect::Write(WriteEffect::File(FileWrite {
                        path,
                        operation: FileWriteKind::CreateOrModify,
                        allows_create: Some(flags & libc::O_CREAT != 0),
                    })),
                );
            } else if let Some(hash) = before_hash {
                state.fds.insert(fd, FdState::File(path.clone()));
                collector.push(
                    pid,
                    Effect::Read(ReadEffect::File(FileRead {
                        path,
                        hash: Some(hash),
                        fingerprint: before_fingerprint,
                    })),
                );
            } else if let Some(fingerprint) = before_fingerprint.filter(|_| path.is_dir()) {
                state.fds.insert(fd, FdState::File(path.clone()));
                collector.push(
                    pid,
                    Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                        path,
                        fingerprint: Some(fingerprint),
                    })),
                );
            } else {
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_open),
                        detail: format!("opened dependency cannot be guarded: {}", path.display()),
                    }),
                );
            }
        }
        PendingSyscall::Metadata { path } => {
            record_metadata(pid, path, collector);
        }
        PendingSyscall::SymlinkMetadata { path } => {
            record_symlink_metadata(pid, path, collector);
        }
        PendingSyscall::TerminalProbe { path } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(libc::SYS_ioctl),
                detail: format!(
                    "successful terminal-state query cannot be guarded: {}",
                    path.display()
                ),
            }),
        ),
        PendingSyscall::InheritedTerminalProbe => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(libc::SYS_ioctl),
                detail: "successful terminal-state query on inherited stdin cannot be guarded"
                    .into(),
            }),
        ),
        PendingSyscall::ReadLink { path } => match fs::read_link(&path) {
            Ok(target) => collector.push(
                pid,
                Effect::Read(ReadEffect::Symlink(SymlinkRead {
                    path,
                    target: Some(target),
                })),
            ),
            Err(error) => collector.push(
                pid,
                Effect::Unknown(UnknownEffect {
                    syscall: Some(libc::SYS_readlink),
                    detail: format!(
                        "successful readlink result cannot be inspected: {} ({error})",
                        path.display()
                    ),
                }),
            ),
        },
        PendingSyscall::Access { path } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(libc::SYS_access),
                detail: format!(
                    "successful access check cannot be guarded exactly: {}",
                    path.display()
                ),
            }),
        ),
        PendingSyscall::Chdir { path } => {
            state.cwd = path.clone();
            collector.push(pid, Effect::Control(ControlEffect::Chdir(path)));
        }
        PendingSyscall::ExecAttempt { .. } => {}
        PendingSyscall::CreateDirectory { path } => collector.push(
            pid,
            Effect::Write(WriteEffect::File(FileWrite {
                path,
                operation: FileWriteKind::CreateOrModify,
                allows_create: Some(true),
            })),
        ),
        PendingSyscall::Dup {
            source,
            destination,
            close_on_exec,
        } => {
            let destination = destination.unwrap_or(result as i32);
            if let Some(fd) = state.fds.get(&source).cloned() {
                state.fds.insert(destination, fd);
            }
            if close_on_exec {
                state.close_on_exec.insert(destination);
            } else {
                state.close_on_exec.remove(&destination);
            }
        }
        PendingSyscall::Close { fd } => {
            state.fds.remove(&fd);
            state.close_on_exec.remove(&fd);
        }
        PendingSyscall::SetCloseOnExec { fd, enabled } => {
            if enabled {
                state.close_on_exec.insert(fd);
            } else {
                state.close_on_exec.remove(&fd);
            }
        }
        PendingSyscall::Rename {
            from,
            to,
            from_snapshot,
            to_snapshot,
        } => {
            record_snapshot(pid, from.clone(), from_snapshot, collector);
            record_snapshot(pid, to.clone(), to_snapshot, collector);
            collector.push(
                pid,
                Effect::Write(WriteEffect::File(FileWrite {
                    path: from,
                    operation: FileWriteKind::Delete,
                    allows_create: None,
                })),
            );
            collector.push(
                pid,
                Effect::Write(WriteEffect::File(FileWrite {
                    path: to,
                    operation: FileWriteKind::RenameDestination,
                    allows_create: Some(true),
                })),
            );
        }
        PendingSyscall::Delete { path, snapshot } => {
            record_snapshot(pid, path.clone(), snapshot, collector);
            collector.push(
                pid,
                Effect::Write(WriteEffect::File(FileWrite {
                    path,
                    operation: FileWriteKind::Delete,
                    allows_create: None,
                })),
            );
        }
        PendingSyscall::Read { fd } => match state.fds.get(&fd).cloned() {
            Some(FdState::Network) => collector.push(
                pid,
                Effect::Read(ReadEffect::Network(NetworkRead {
                    operation: "read from socket".into(),
                })),
            ),
            Some(FdState::File(_)) => {}
            Some(FdState::InheritedFile(path)) if path == Path::new("/dev/null") => {}
            Some(FdState::InheritedFile(path)) => collector.push(
                pid,
                Effect::Unknown(UnknownEffect {
                    syscall: Some(libc::SYS_read),
                    detail: format!(
                        "read from inherited descriptor {fd} is not replayable: {}",
                        path.display()
                    ),
                }),
            ),
            _ => {
                let resolved = fs::read_link(format!("/proc/{}/fd/{fd}", pid.as_raw())).ok();
                if let Some(path) = resolved.filter(|path| path.is_absolute() && path.is_file()) {
                    if let Ok(hash) = hash_file(&path) {
                        let file_fingerprint = fingerprint(&path).ok();
                        state.fds.insert(fd, FdState::File(path.clone()));
                        collector.push(
                            pid,
                            Effect::Read(ReadEffect::File(FileRead {
                                path,
                                hash: Some(hash),
                                fingerprint: file_fingerprint,
                            })),
                        );
                    } else {
                        collector.push(
                            pid,
                            Effect::Unknown(UnknownEffect {
                                syscall: Some(libc::SYS_read),
                                detail: format!("read from unhashable fd {fd}"),
                            }),
                        );
                    }
                } else {
                    collector.push(
                        pid,
                        Effect::Unknown(UnknownEffect {
                            syscall: Some(libc::SYS_read),
                            detail: format!("read from unclassified fd {fd}"),
                        }),
                    );
                }
            }
        },
        PendingSyscall::Write { fd } => match state.fds.get(&fd) {
            Some(FdState::File(path)) => collector.push(
                pid,
                Effect::Write(WriteEffect::File(FileWrite {
                    path: path.clone(),
                    operation: FileWriteKind::CreateOrModify,
                    allows_create: None,
                })),
            ),
            Some(FdState::Network) => collector.push(
                pid,
                Effect::Write(WriteEffect::Network(NetworkWrite {
                    operation: "write to socket".into(),
                })),
            ),
            Some(FdState::Other) if fd == 1 || fd == 2 => {}
            _ => collector.push(
                pid,
                Effect::Write(WriteEffect::Ipc(IpcWrite {
                    operation: format!("write to unclassified fd {fd}"),
                })),
            ),
        },
        PendingSyscall::Network { kind } => match kind {
            NetworkOperation::Socket => {
                state.fds.insert(result as i32, FdState::Network);
            }
            NetworkOperation::Read(operation) => collector.push(
                pid,
                Effect::Read(ReadEffect::Network(NetworkRead {
                    operation: operation.into(),
                })),
            ),
            NetworkOperation::Write(operation) => collector.push(
                pid,
                Effect::Write(WriteEffect::Network(NetworkWrite {
                    operation: operation.into(),
                })),
            ),
        },
        PendingSyscall::Clock { kind } => {
            collector.push(pid, Effect::Read(ReadEffect::Clock(kind)));
        }
        PendingSyscall::Random => collector.push(
            pid,
            Effect::Read(ReadEffect::Random(RandomSource::GetRandom)),
        ),
        PendingSyscall::KernelState { kind } => {
            collector.push(pid, Effect::Read(ReadEffect::KernelState(kind)));
        }
        PendingSyscall::Signal { signal, target } => collector.push(
            pid,
            Effect::Control(ControlEffect::Signal(SignalEffect {
                signal,
                target_pid: target,
            })),
        ),
        PendingSyscall::Unknown { number, detail } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(number),
                detail: format!("unmodeled successful syscall {number}: {detail}"),
            }),
        ),
        PendingSyscall::Mmap {
            length,
            prot,
            flags,
            ..
        } => {
            let address = result as u64;
            if length > 0 {
                let shared = flags & libc::MAP_SHARED as u64 != 0;
                let writable = prot & libc::PROT_WRITE as u64 != 0;
                state.file_mappings.push(FileMapping {
                    start: address,
                    end: address.saturating_add(length),
                    shared,
                    writable,
                });
                if shared && writable {
                    collector.push(
                        pid,
                        Effect::Unknown(UnknownEffect {
                            syscall: Some(libc::SYS_mmap),
                            detail: "file-backed MAP_SHARED mapping is writable; stores through it are not captured outputs".into(),
                        }),
                    );
                }
            }
        }
        PendingSyscall::Mprotect {
            address,
            length,
            prot,
        } => {
            if mapping_prot_makes_shared_file_writable(
                &mut state.file_mappings,
                address,
                length,
                prot,
            ) {
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_mprotect),
                        detail: "mprotect made a shared file mapping writable; stores through it are not captured outputs".into(),
                    }),
                );
            }
        }
        PendingSyscall::Munmap { address, length } => {
            remove_mapping_range(&mut state.file_mappings, address, length);
        }
        PendingSyscall::Mremap {
            address,
            old_length,
        } => {
            if overlaps_file_mapping(&state.file_mappings, address, old_length) {
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_mremap),
                        detail: "mremap of a file-backed mapping is not a guarded effect".into(),
                    }),
                );
            }
            remove_mapping_range(&mut state.file_mappings, address, old_length);
        }
        PendingSyscall::None => {}
    }
}

fn complete_failed_syscall(
    pid: Pid,
    pending: PendingSyscall,
    errno: i64,
    collector: &mut Collector,
) {
    match pending {
        PendingSyscall::ReadLink { path } if errno == libc::EINVAL as i64 => collector.push(
            pid,
            Effect::Read(ReadEffect::Symlink(SymlinkRead { path, target: None })),
        ),
        PendingSyscall::ReadLink { path }
            if errno == libc::ENOENT as i64 || errno == libc::ENOTDIR as i64 =>
        {
            collector.push(
                pid,
                Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                    path,
                    fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
                })),
            );
        }
        PendingSyscall::SymlinkMetadata { path }
            if errno == libc::ENOENT as i64 || errno == libc::ENOTDIR as i64 =>
        {
            collector.push(
                pid,
                Effect::Read(ReadEffect::SymlinkMetadata(FileMetadataRead {
                    path,
                    fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
                })),
            );
        }
        PendingSyscall::TerminalProbe { path } => record_metadata(pid, path, collector),
        PendingSyscall::InheritedTerminalProbe => {}
        PendingSyscall::Open { path, .. }
        | PendingSyscall::Metadata { path }
        | PendingSyscall::SymlinkMetadata { path }
        | PendingSyscall::Access { path }
        | PendingSyscall::Chdir { path }
        | PendingSyscall::ExecAttempt { path }
            if errno == libc::ENOENT as i64 || errno == libc::ENOTDIR as i64 =>
        {
            collector.push(
                pid,
                Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                    path,
                    fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
                })),
            );
        }
        PendingSyscall::CreateDirectory { path } if errno == libc::EEXIST as i64 => {
            if let Ok(value) = fingerprint(&path) {
                collector.push(
                    pid,
                    Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                        path,
                        fingerprint: Some(value),
                    })),
                );
            } else {
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_mkdir),
                        detail: format!(
                            "existing directory cannot be guarded after mkdir failure: {}",
                            path.display()
                        ),
                    }),
                );
            }
        }
        PendingSyscall::Open { path, .. }
        | PendingSyscall::Metadata { path }
        | PendingSyscall::Access { path }
        | PendingSyscall::Chdir { path }
        | PendingSyscall::ExecAttempt { path }
        | PendingSyscall::Delete { path, .. }
        | PendingSyscall::CreateDirectory { path } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "failed filesystem effect is not guardable: {} (errno {errno})",
                    path.display()
                ),
            }),
        ),
        PendingSyscall::Rename { from, to, .. } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "failed rename is not guardable: {} to {} (errno {errno})",
                    from.display(),
                    to.display()
                ),
            }),
        ),
        PendingSyscall::Network { kind } => match kind {
            NetworkOperation::Socket => collector.push(
                pid,
                Effect::Read(ReadEffect::Network(NetworkRead {
                    operation: format!("failed socket creation (errno {errno})"),
                })),
            ),
            NetworkOperation::Read(operation) => collector.push(
                pid,
                Effect::Read(ReadEffect::Network(NetworkRead {
                    operation: format!("failed {operation} (errno {errno})"),
                })),
            ),
            NetworkOperation::Write(operation) => collector.push(
                pid,
                Effect::Write(WriteEffect::Network(NetworkWrite {
                    operation: format!("failed {operation} (errno {errno})"),
                })),
            ),
        },
        PendingSyscall::Clock { kind } => {
            collector.push(pid, Effect::Read(ReadEffect::Clock(kind)));
        }
        PendingSyscall::Random => collector.push(
            pid,
            Effect::Read(ReadEffect::Random(RandomSource::GetRandom)),
        ),
        PendingSyscall::KernelState { kind } => {
            collector.push(pid, Effect::Read(ReadEffect::KernelState(kind)));
        }
        PendingSyscall::Signal { signal, target } => collector.push(
            pid,
            Effect::Control(ControlEffect::Signal(SignalEffect {
                signal,
                target_pid: target,
            })),
        ),
        PendingSyscall::Read { fd } | PendingSyscall::Write { fd } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!("failed I/O on fd {fd} is not modeled (errno {errno})"),
            }),
        ),
        PendingSyscall::Dup { source, .. }
        | PendingSyscall::Close { fd: source }
        | PendingSyscall::SetCloseOnExec { fd: source, .. } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!("failed fd operation on {source} is not modeled (errno {errno})"),
            }),
        ),
        PendingSyscall::ReadLink { path } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(libc::SYS_readlink),
                detail: format!(
                    "failed readlink is not guardable: {} (errno {errno})",
                    path.display()
                ),
            }),
        ),
        PendingSyscall::Unknown { number, detail } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(number),
                detail: format!("unmodeled failed syscall {number} (errno {errno}): {detail}"),
            }),
        ),
        PendingSyscall::Mmap { .. }
        | PendingSyscall::Mprotect { .. }
        | PendingSyscall::Munmap { .. }
        | PendingSyscall::Mremap { .. }
        | PendingSyscall::None => {}
        _ => {}
    }
}

fn resolve_path(
    pid: Pid,
    state: &ProcessState,
    dirfd: i32,
    address: u64,
) -> Result<PathBuf, TraceError> {
    let raw = read_c_string(pid, address)?;
    let path = PathBuf::from(OsString::from_vec(raw));
    if path.is_absolute() {
        return Ok(normalize(path));
    }
    let base = if dirfd == libc::AT_FDCWD {
        state.cwd.clone()
    } else if let Some(FdState::File(path)) = state.fds.get(&dirfd) {
        path.clone()
    } else {
        fs::read_link(format!("/proc/{}/fd/{dirfd}", pid.as_raw())).map_err(|error| {
            TraceError::Ptrace(format!("cannot resolve dirfd {dirfd} for {pid}: {error}"))
        })?
    };
    Ok(normalize(base.join(path)))
}

fn normalize(path: PathBuf) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    normalized
}

fn read_c_string(pid: Pid, address: u64) -> Result<Vec<u8>, TraceError> {
    let mut bytes = Vec::new();
    let word_size = std::mem::size_of::<libc::c_long>();
    while bytes.len() < 64 * 1024 {
        let word = ptrace::read(pid, (address as usize + bytes.len()) as ptrace::AddressType)
            .map_err(ptrace_error)?;
        for byte in word.to_ne_bytes().into_iter().take(word_size) {
            if byte == 0 {
                return Ok(bytes);
            }
            bytes.push(byte);
        }
    }
    Err(TraceError::Ptrace(
        "unterminated path exceeds 64 KiB".into(),
    ))
}

fn read_word(pid: Pid, address: u64) -> Result<u64, TraceError> {
    ptrace::read(pid, address as ptrace::AddressType)
        .map(|word| word as u64)
        .map_err(ptrace_error)
}

fn is_proc_self(path: &Path) -> bool {
    path.starts_with("/proc/self") || path.starts_with("/proc/thread-self")
}

fn is_random_device(path: &Path) -> bool {
    path == Path::new("/dev/random") || path == Path::new("/dev/urandom")
}

fn inherited_fd_state(pid: Pid, fd: i32) -> FdState {
    let target = fs::read_link(format!("/proc/{}/fd/{fd}", pid.as_raw()));
    match target {
        Ok(path) if path.is_absolute() => FdState::InheritedFile(path),
        Ok(path) if path.to_string_lossy().starts_with("socket:") => FdState::Network,
        _ => FdState::Other,
    }
}

fn ensure_vdso_disarmed(
    pid: Pid,
    states: &mut HashMap<Pid, ProcessState>,
    collector: &mut Collector,
) {
    let Some(state) = states.get(&pid) else {
        return;
    };
    if state.vdso_disarmed {
        return;
    }
    let result = disarm_vdso_time(pid);
    if let Some(state) = states.get_mut(&pid) {
        state.vdso_disarmed = true;
    }
    if let Err(detail) = result {
        collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail,
            }),
        );
    }
}

const AT_NULL: u64 = 0;
const AT_SYSINFO_EHDR: u64 = 33;

fn disarm_vdso_time(pid: Pid) -> Result<(), String> {
    let auxv = clear_auxv_sysinfo(pid);
    let aux_cleared = matches!(auxv, Ok(AuxvSysinfo::Cleared));
    match vdso_mapping(pid)? {
        Some(mapping) => {
            let patched: Result<(), String> = (|| {
                let mut image = vec![0u8; mapping.len()];
                read_remote(pid, mapping.start, &mut image)?;
                let patches = vdso_time_patches(&image, mapping.start)?;
                for patch in patches {
                    write_remote(pid, patch.address, &patch.bytes)?;
                }
                Ok(())
            })();
            match patched {
                Ok(()) => Ok(()),
                Err(_) if aux_cleared => Ok(()),
                Err(detail) => Err(detail),
            }
        }
        None => match auxv {
            Ok(AuxvSysinfo::Cleared | AuxvSysinfo::Absent) => Ok(()),
            Ok(AuxvSysinfo::Unreadable) | Err(_) => Err(
                "could not inspect the auxiliary vector, so an invisible vDSO clock read cannot be ruled out"
                    .into(),
            ),
        },
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum AuxvSysinfo {
    Cleared,
    Absent,
    Unreadable,
}

struct VdsoMapping {
    start: u64,
    end: u64,
}

impl VdsoMapping {
    fn len(&self) -> usize {
        self.end.saturating_sub(self.start) as usize
    }
}

struct VdsoPatch {
    address: u64,
    bytes: [u8; 8],
}

fn vdso_mapping(pid: Pid) -> Result<Option<VdsoMapping>, String> {
    let maps = fs::read_to_string(format!("/proc/{}/maps", pid.as_raw()))
        .map_err(|error| format!("could not read process map to disarm vDSO time: {error}"))?;
    for line in maps.lines() {
        if !line.contains("[vdso]") {
            continue;
        }
        let range = line.split_whitespace().next().unwrap_or("");
        let (start, end) = range
            .split_once('-')
            .ok_or_else(|| format!("unreadable vDSO map entry: {line}"))?;
        let start = u64::from_str_radix(start, 16)
            .map_err(|_| format!("unreadable vDSO start: {start}"))?;
        let end =
            u64::from_str_radix(end, 16).map_err(|_| format!("unreadable vDSO end: {end}"))?;
        if end <= start || end - start > 1024 * 1024 {
            return Err(format!("implausible vDSO mapping {start:#x}-{end:#x}"));
        }
        return Ok(Some(VdsoMapping { start, end }));
    }
    Ok(None)
}

fn clear_auxv_sysinfo(pid: Pid) -> Result<AuxvSysinfo, String> {
    let regs =
        ptrace::getregs(pid).map_err(|error| format!("could not read entry registers: {error}"))?;
    let argc = read_u64(pid, regs.rsp)
        .map_err(|error| format!("could not read argc while disarming vDSO time: {error}"))?;
    if argc > 4096 {
        return Ok(AuxvSysinfo::Unreadable);
    }
    let mut addr = regs.rsp.saturating_add(8 * (argc + 2));
    let mut environment_terminated = false;
    for _ in 0..8192 {
        let word = read_u64(pid, addr).map_err(|error| {
            format!("could not walk environment while disarming vDSO time: {error}")
        })?;
        addr = addr.saturating_add(8);
        if word == AT_NULL {
            environment_terminated = true;
            break;
        }
    }
    if !environment_terminated {
        return Ok(AuxvSysinfo::Unreadable);
    }
    for _ in 0..256 {
        let key = read_u64(pid, addr).map_err(|error| {
            format!("could not read auxiliary vector while disarming vDSO time: {error}")
        })?;
        if key == AT_NULL {
            return Ok(AuxvSysinfo::Absent);
        }
        if key > 1024 {
            return Ok(AuxvSysinfo::Unreadable);
        }
        if key == AT_SYSINFO_EHDR {
            write_remote(pid, addr.saturating_add(8), &0u64.to_le_bytes())?;
            return Ok(AuxvSysinfo::Cleared);
        }
        addr = addr.saturating_add(16);
    }
    Ok(AuxvSysinfo::Unreadable)
}

fn vdso_time_patches(image: &[u8], map_start: u64) -> Result<Vec<VdsoPatch>, String> {
    let symbols = vdso_symbol_offsets(image)?;
    let mut patches = Vec::new();
    let mut saw_clock = false;
    let mut saw_gettimeofday = false;
    for (name, offset) in symbols {
        let Some(number) = vdso_time_syscall(&name) else {
            continue;
        };
        if name.contains("clock_gettime") {
            saw_clock = true;
        }
        if name.contains("gettimeofday") {
            saw_gettimeofday = true;
        }
        let address = map_start.saturating_add(offset);
        if address < map_start
            || address.saturating_add(8) > map_start.saturating_add(image.len() as u64)
        {
            return Err(format!("vDSO symbol {name} is outside the mapped image"));
        }
        patches.push(VdsoPatch {
            address,
            bytes: vdso_syscall_stub(number),
        });
    }
    if !saw_clock || !saw_gettimeofday {
        return Err(
            "vDSO image has no clock_gettime and gettimeofday entry points to redirect; refusing reuse"
                .into(),
        );
    }
    Ok(patches)
}

fn vdso_time_syscall(name: &str) -> Option<u32> {
    if name == "__vdso_clock_gettime" || name == "__kernel_clock_gettime" {
        Some(libc::SYS_clock_gettime as u32)
    } else if name == "__vdso_gettimeofday" || name == "__kernel_gettimeofday" {
        Some(libc::SYS_gettimeofday as u32)
    } else if name == "__vdso_time" || name == "__kernel_time" {
        Some(libc::SYS_time as u32)
    } else {
        None
    }
}

fn vdso_syscall_stub(number: u32) -> [u8; 8] {
    let mut bytes = [0u8; 8];
    bytes[0] = 0xb8;
    bytes[1..5].copy_from_slice(&number.to_le_bytes());
    bytes[5] = 0x0f;
    bytes[6] = 0x05;
    bytes[7] = 0xc3;
    bytes
}

fn vdso_symbol_offsets(image: &[u8]) -> Result<Vec<(String, u64)>, String> {
    if image.len() < 64 || &image[0..4] != b"\x7fELF" || image[4] != 2 {
        return Err("vDSO image is not a 64-bit ELF".into());
    }
    let phoff = read_elf_u64(image, 32)?;
    let phentsize = read_elf_u16(image, 54)? as usize;
    let phnum = read_elf_u16(image, 56)? as usize;
    let mut load_vaddr = 0u64;
    for index in 0..phnum {
        let off = phoff as usize + index * phentsize;
        if read_elf_u32(image, off)? != 1 {
            continue;
        }
        load_vaddr = read_elf_u64(image, off + 16)?;
        break;
    }
    let shoff = read_elf_u64(image, 40)? as usize;
    let shentsize = read_elf_u16(image, 58)? as usize;
    let shnum = read_elf_u16(image, 60)? as usize;
    if shentsize < 64 || shnum > 128 {
        return Err("vDSO section headers are not usable".into());
    }
    let mut dynsym = None;
    let mut sections = Vec::new();
    for index in 0..shnum {
        let off = shoff + index * shentsize;
        // sh_type is the second word. The first word is sh_name.
        let kind = read_elf_u32(image, off + 4)?;
        let offset = read_elf_u64(image, off + 24)? as usize;
        let size = read_elf_u64(image, off + 32)? as usize;
        let link = read_elf_u32(image, off + 40)? as usize;
        let entsize = read_elf_u64(image, off + 56)? as usize;
        sections.push((offset, size));
        if kind == 11 {
            dynsym = Some((offset, size, link, entsize));
        }
    }
    let (sym_off, sym_size, link, entsize) =
        dynsym.ok_or_else(|| "vDSO has no dynamic symbol table".to_string())?;
    if entsize < 24 || link >= sections.len() {
        return Err("vDSO symbol table is truncated".into());
    }
    let (str_off, str_size) = sections[link];
    let mut symbols = Vec::new();
    let mut cursor = sym_off;
    let end = sym_off.saturating_add(sym_size);
    while cursor + entsize <= end {
        let name_off = read_elf_u32(image, cursor)? as usize;
        let value = read_elf_u64(image, cursor + 8)?;
        let size = read_elf_u64(image, cursor + 16)?;
        if name_off < str_size {
            let start = str_off + name_off;
            if let Some(relative) = image.get(start..str_off + str_size) {
                let name_len = relative.iter().position(|byte| *byte == 0).unwrap_or(0);
                if let Ok(name) = std::str::from_utf8(&relative[..name_len]) {
                    if vdso_time_syscall(name).is_some() && (size == 0 || size >= 8) {
                        let offset = value.wrapping_sub(load_vaddr);
                        symbols.push((name.to_string(), offset));
                    }
                }
            }
        }
        cursor += entsize;
    }
    Ok(symbols)
}

fn read_elf_u16(image: &[u8], offset: usize) -> Result<u16, String> {
    let bytes = image
        .get(offset..offset + 2)
        .ok_or_else(|| "truncated vDSO ELF".to_string())?;
    Ok(u16::from_le_bytes(bytes.try_into().unwrap()))
}

fn read_elf_u32(image: &[u8], offset: usize) -> Result<u32, String> {
    let bytes = image
        .get(offset..offset + 4)
        .ok_or_else(|| "truncated vDSO ELF".to_string())?;
    Ok(u32::from_le_bytes(bytes.try_into().unwrap()))
}

fn read_elf_u64(image: &[u8], offset: usize) -> Result<u64, String> {
    let bytes = image
        .get(offset..offset + 8)
        .ok_or_else(|| "truncated vDSO ELF".to_string())?;
    Ok(u64::from_le_bytes(bytes.try_into().unwrap()))
}

fn read_u64(pid: Pid, address: u64) -> Result<u64, String> {
    let mut bytes = [0u8; 8];
    read_remote(pid, address, &mut bytes)?;
    Ok(u64::from_le_bytes(bytes))
}

fn read_remote(pid: Pid, address: u64, buffer: &mut [u8]) -> Result<(), String> {
    let mut memory = fs::File::open(format!("/proc/{}/mem", pid.as_raw()))
        .map_err(|error| format!("could not open process memory: {error}"))?;
    memory
        .seek(SeekFrom::Start(address))
        .map_err(|error| format!("could not seek process memory: {error}"))?;
    memory
        .read_exact(buffer)
        .map_err(|error| format!("could not read process memory: {error}"))?;
    Ok(())
}

fn write_remote(pid: Pid, address: u64, bytes: &[u8]) -> Result<(), String> {
    let mut memory = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(format!("/proc/{}/mem", pid.as_raw()))
        .map_err(|error| format!("could not write process memory: {error}"))?;
    memory
        .seek(SeekFrom::Start(address))
        .map_err(|error| format!("could not seek process memory for write: {error}"))?;
    memory
        .write_all(bytes)
        .map_err(|error| format!("could not patch process memory: {error}"))?;
    Ok(())
}

fn overlaps_file_mapping(mappings: &[FileMapping], address: u64, length: u64) -> bool {
    let end = address.saturating_add(length);
    mappings
        .iter()
        .any(|mapping| mapping.start < end && address < mapping.end)
}

fn remove_mapping_range(mappings: &mut Vec<FileMapping>, address: u64, length: u64) {
    let end = address.saturating_add(length);
    let mut next = Vec::new();
    for mapping in mappings.drain(..) {
        if mapping.end <= address || mapping.start >= end {
            next.push(mapping);
            continue;
        }
        if mapping.start < address {
            next.push(FileMapping {
                end: address,
                ..mapping.clone()
            });
        }
        if mapping.end > end {
            next.push(FileMapping {
                start: end,
                ..mapping
            });
        }
    }
    *mappings = next;
}

fn mapping_prot_makes_shared_file_writable(
    mappings: &mut Vec<FileMapping>,
    address: u64,
    length: u64,
    prot: u64,
) -> bool {
    let end = address.saturating_add(length);
    let writable = prot & libc::PROT_WRITE as u64 != 0;
    let mut shared_write = false;
    let mut next = Vec::new();
    for mapping in mappings.drain(..) {
        if mapping.end <= address || mapping.start >= end {
            next.push(mapping);
            continue;
        }
        if mapping.shared && writable {
            shared_write = true;
        }
        if mapping.start < address {
            next.push(FileMapping {
                end: address,
                ..mapping.clone()
            });
        }
        let mid_start = mapping.start.max(address);
        let mid_end = mapping.end.min(end);
        if mid_start < mid_end {
            next.push(FileMapping {
                start: mid_start,
                end: mid_end,
                writable,
                shared: mapping.shared,
            });
        }
        if mapping.end > end {
            next.push(FileMapping {
                start: end,
                ..mapping
            });
        }
    }
    *mappings = next;
    shared_write
}

fn is_known_internal_syscall(number: i64) -> bool {
    matches!(
        number,
        libc::SYS_lseek
            | libc::SYS_fadvise64
            | libc::SYS_getdents64
            | libc::SYS_brk
            | libc::SYS_madvise
            | libc::SYS_futex
            | libc::SYS_arch_prctl
            | libc::SYS_set_tid_address
            | libc::SYS_set_robust_list
            | libc::SYS_rseq
            | libc::SYS_rt_sigaction
            | libc::SYS_rt_sigprocmask
            | libc::SYS_rt_sigreturn
            | libc::SYS_sigaltstack
            | libc::SYS_exit
            | libc::SYS_exit_group
            | libc::SYS_wait4
            | libc::SYS_waitid
            | libc::SYS_getcwd
            | libc::SYS_sched_yield
            | libc::SYS_restart_syscall
            | libc::SYS_clone
            | libc::SYS_clone3
            | libc::SYS_fork
            | libc::SYS_vfork
    )
}

fn pending_description(pending: &PendingSyscall) -> String {
    match pending {
        PendingSyscall::Open { path, .. }
        | PendingSyscall::Metadata { path }
        | PendingSyscall::SymlinkMetadata { path }
        | PendingSyscall::ReadLink { path }
        | PendingSyscall::TerminalProbe { path }
        | PendingSyscall::Access { path }
        | PendingSyscall::Chdir { path }
        | PendingSyscall::ExecAttempt { path }
        | PendingSyscall::CreateDirectory { path }
        | PendingSyscall::Delete { path, .. } => path.display().to_string(),
        PendingSyscall::Rename { from, to, .. } => {
            format!("rename {} to {}", from.display(), to.display())
        }
        PendingSyscall::Network { .. } => "network operation".into(),
        PendingSyscall::Unknown { number, detail } => format!("syscall {number}: {detail}"),
        PendingSyscall::Read { fd } => format!("read from fd {fd}"),
        PendingSyscall::Write { fd } => format!("write to fd {fd}"),
        PendingSyscall::Signal { signal, target } => {
            format!("signal {signal} to process {target}")
        }
        PendingSyscall::Clock { .. } => "clock read".into(),
        PendingSyscall::Random => "randomness read".into(),
        PendingSyscall::KernelState { kind } => format!("kernel state read: {kind:?}"),
        PendingSyscall::Mmap { .. } => "file-backed mmap".into(),
        PendingSyscall::Mprotect { .. } => "mprotect".into(),
        PendingSyscall::Munmap { .. } => "munmap".into(),
        PendingSyscall::Mremap { .. } => "mremap".into(),
        PendingSyscall::Dup { .. }
        | PendingSyscall::Close { .. }
        | PendingSyscall::SetCloseOnExec { .. }
        | PendingSyscall::InheritedTerminalProbe
        | PendingSyscall::None => "process-internal operation".into(),
    }
}

fn effect_target(effect: &Effect) -> String {
    match effect {
        Effect::Read(ReadEffect::File(value)) => value.path.display().to_string(),
        Effect::Read(ReadEffect::FileMetadata(value)) => value.path.display().to_string(),
        Effect::Read(ReadEffect::SymlinkMetadata(value)) => value.path.display().to_string(),
        Effect::Read(ReadEffect::Symlink(value)) => value.path.display().to_string(),
        Effect::Write(WriteEffect::File(value)) => value.path.display().to_string(),
        Effect::Control(ControlEffect::Exec(value)) => value.path.display().to_string(),
        Effect::Control(ControlEffect::Chdir(value)) => value.display().to_string(),
        Effect::Unknown(value) => value.detail.clone(),
        other => format!("{other:?}"),
    }
}

pub(super) fn probe_ptrace() -> Result<(), String> {
    use nix::unistd::{fork, ForkResult};
    // SAFETY: doctor calls this before TraceJIT creates other threads. The child only performs
    // async-signal-safe calls and exits with _exit.
    match unsafe { fork() }.map_err(|error| format!("could not fork ptrace probe: {error}"))? {
        ForkResult::Child => {
            if ptrace::traceme().is_err() {
                unsafe { libc::_exit(2) };
            }
            unsafe { libc::raise(libc::SIGSTOP) };
            unsafe { libc::_exit(0) };
        }
        ForkResult::Parent { child } => match waitpid(child, None) {
            Ok(WaitStatus::Stopped(_, _)) => {
                ptrace::detach(child, None)
                    .map_err(|error| format!("ptrace detach failed: {error}"))?;
                let _ = waitpid(child, None);
                Ok(())
            }
            Ok(WaitStatus::Exited(_, 2)) => Err(ptrace_denied_message()),
            Ok(status) => Err(format!("ptrace probe failed: {status:?}")),
            Err(error) => Err(format!("ptrace probe wait failed: {error}")),
        },
    }
}

fn ptrace_denied_message() -> String {
    match fs::read_to_string("/proc/sys/kernel/yama/ptrace_scope") {
        Ok(scope) => format!(
            "ptrace attach was denied (yama ptrace_scope={})",
            scope.trim()
        ),
        Err(_) => "ptrace attach was denied".into(),
    }
}

fn ptrace_error(error: Errno) -> TraceError {
    TraceError::Ptrace(error.to_string())
}

fn ptrace_operation(operation: &str, pid: Pid, error: Errno) -> TraceError {
    TraceError::Ptrace(format!("{operation} for pid {pid}: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shared_read_only() -> FileMapping {
        FileMapping {
            start: 0x1000,
            end: 0x2000,
            shared: true,
            writable: false,
        }
    }

    #[test]
    fn shared_mprotect_write_is_visible_to_the_guard() {
        let mut mappings = vec![shared_read_only()];
        assert!(mapping_prot_makes_shared_file_writable(
            &mut mappings,
            0x1000,
            0x1000,
            libc::PROT_WRITE as u64
        ));
        assert!(mappings.iter().any(|mapping| mapping.writable));
    }

    #[test]
    fn private_mprotect_write_is_not_a_shared_store() {
        let mut mappings = vec![FileMapping {
            start: 0x1000,
            end: 0x2000,
            shared: false,
            writable: false,
        }];
        assert!(!mapping_prot_makes_shared_file_writable(
            &mut mappings,
            0x1000,
            0x1000,
            libc::PROT_WRITE as u64
        ));
    }

    #[test]
    fn munmap_drops_only_the_covered_range() {
        let mut mappings = vec![shared_read_only()];
        remove_mapping_range(&mut mappings, 0x1000, 0x800);
        assert_eq!(mappings.len(), 1);
        assert_eq!(mappings[0].start, 0x1800);
        assert_eq!(mappings[0].end, 0x2000);
    }

    #[test]
    fn vdso_stub_is_mov_syscall_ret() {
        let stub = vdso_syscall_stub(228);
        assert_eq!(stub, [0xb8, 228, 0, 0, 0, 0x0f, 0x05, 0xc3]);
        assert_eq!(vdso_time_syscall("__vdso_clock_gettime"), Some(228));
        assert_eq!(vdso_time_syscall("__vdso_gettimeofday"), Some(96));
        assert_eq!(vdso_time_syscall("__vdso_time"), Some(201));
        assert_eq!(vdso_time_syscall("__vdso_getcpu"), None);
    }

    #[test]
    fn synthetic_vdso_time_symbols_are_patched_in_place() {
        let image = synthetic_vdso();
        let patches = vdso_time_patches(&image, 0x1000).unwrap();
        let addresses: Vec<_> = patches.iter().map(|patch| patch.address).collect();
        assert!(addresses.contains(&0x1200));
        assert!(addresses.contains(&0x1300));
        assert!(patches
            .iter()
            .all(|patch| patch.bytes[0] == 0xb8 && patch.bytes[7] == 0xc3));
    }

    fn synthetic_vdso() -> Vec<u8> {
        let mut image = vec![0u8; 0x400];
        image[0..4].copy_from_slice(b"\x7fELF");
        image[4] = 2;
        image[5] = 1;
        write_u16(&mut image, 16, 3);
        write_u16(&mut image, 18, 62);
        write_u32(&mut image, 20, 1);
        write_u64(&mut image, 32, 64);
        write_u64(&mut image, 40, 0x100);
        write_u16(&mut image, 52, 64);
        write_u16(&mut image, 54, 56);
        write_u16(&mut image, 56, 1);
        write_u16(&mut image, 58, 64);
        write_u16(&mut image, 60, 3);
        write_u32(&mut image, 64, 1);
        write_u32(&mut image, 68, 5);
        write_u64(&mut image, 64 + 32, 0x400);
        write_u64(&mut image, 64 + 40, 0x400);
        write_u64(&mut image, 64 + 48, 0x1000);
        let names = b"\0__vdso_clock_gettime\0__vdso_gettimeofday\0";
        image[0xc0..0xc0 + names.len()].copy_from_slice(names);
        write_symbol(&mut image, 0x78 + 24, 1, 0x200, 16);
        write_symbol(&mut image, 0x78 + 48, 22, 0x300, 16);
        write_shdr(&mut image, 0x100 + 64, 11, 0x78, 72, 2, 24);
        write_shdr(&mut image, 0x100 + 128, 3, 0xc0, names.len() as u64, 0, 0);
        image
    }

    fn write_symbol(image: &mut [u8], offset: usize, name: u32, value: u64, size: u64) {
        write_u32(image, offset, name);
        write_u64(image, offset + 8, value);
        write_u64(image, offset + 16, size);
    }

    fn write_shdr(
        image: &mut [u8],
        offset: usize,
        kind: u32,
        section_offset: u64,
        size: u64,
        link: u32,
        entsize: u64,
    ) {
        write_u32(image, offset + 4, kind);
        write_u64(image, offset + 24, section_offset);
        write_u64(image, offset + 32, size);
        write_u32(image, offset + 40, link);
        write_u64(image, offset + 56, entsize);
    }

    fn write_u16(image: &mut [u8], offset: usize, value: u16) {
        image[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
    }

    fn write_u32(image: &mut [u8], offset: usize, value: u32) {
        image[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }

    fn write_u64(image: &mut [u8], offset: usize, value: u64) {
        image[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
}

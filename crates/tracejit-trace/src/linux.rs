use super::{TraceError, TraceOutcome, TraceRequest};
use nix::errno::Errno;
use nix::sys::ptrace;
use nix::sys::signal::{kill, Signal};
use nix::sys::wait::{waitpid, WaitPidFlag, WaitStatus};
use nix::unistd::Pid;
use std::collections::{HashMap, HashSet};
use std::ffi::OsString;
use std::fs;
use std::io::Read;
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
    let mut root_exit = None;

    while !states.is_empty() {
        let status = match waitpid(Pid::from_raw(-1), Some(WaitPidFlag::__WALL)) {
            Ok(status) => status,
            Err(Errno::ECHILD) => break,
            Err(error) => return Err(ptrace_error(error)),
        };
        match status {
            WaitStatus::PtraceSyscall(pid) => {
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
                }
                ptrace::syscall(pid, None).map_err(ptrace_error)?;
            }
            WaitStatus::Stopped(pid, signal) => {
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

fn is_known_internal_syscall(number: i64) -> bool {
    matches!(
        number,
        libc::SYS_lseek
            | libc::SYS_fadvise64
            | libc::SYS_getdents64
            | libc::SYS_mmap
            | libc::SYS_mprotect
            | libc::SYS_munmap
            | libc::SYS_brk
            | libc::SYS_mremap
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

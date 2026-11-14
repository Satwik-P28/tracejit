use super::{Contract, TraceError, TraceOutcome, TraceRequest};
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
use std::os::unix::fs::{FileTypeExt, MetadataExt};
use std::os::unix::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tracejit_effects::{
    ClockKind, ControlEffect, ControlledEntropyRead, ControlledRuntimeObservation,
    ControlledRuntimeRead, DependencyEdge, DependencyKind, DirectoryEnumerationRead,
    DirectoryEnumerationRequest, DirectoryOpen, Effect, EffectRecord, ExecutionMetadata,
    FileMetadataRead, FileRead, FileWrite, FileWriteKind, FilesystemStatsRead,
    FilesystemStatsSource, InheritedStreamRead, IpcWrite, KernelStateRead, NetworkRead,
    NetworkWrite, ProcessExec, ProcessNode, ProcessSpawn, RandomSource, ReadEffect, SignalEffect,
    SymlinkRead, Trace, UnknownEffect, WriteEffect,
};
use tracejit_guards::{
    credential_identity, fingerprint, hash_file, namespace_identity, symlink_fingerprint,
};

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
    /// Directory enumerations in progress, keyed by descriptor.
    enumerations: HashMap<i32, EnumerationState>,
    /// Consumption of an inherited regular-file stdin description, when it is modelled.
    stdin_stream: Option<InheritedStreamState>,
    /// False after exec until vDSO time entry points are redirected to syscalls.
    vdso_disarmed: bool,
}

/// Records one directory's entry stream while the program reads it.
#[derive(Clone)]
struct EnumerationState {
    fingerprint: tracejit_effects::FileFingerprint,
    credential: Option<tracejit_effects::Hash>,
    mount_namespace: Option<tracejit_effects::NamespaceIdentity>,
    /// Bytes captured so far, to bound the cache record.
    bytes: usize,
    /// Index of the effect record this stream appends to.
    effect_index: Option<usize>,
    /// Set when the stream exceeded the capture bound or could not be recorded.
    refused: bool,
}

/// Tracks the shared open file description an inherited regular-file stdin names.
///
/// `start_offset` comes from `/proc/<pid>/fdinfo/0` before the program runs. `end_offset` is the
/// model's current position for that description: reads advance it by the bytes returned, and a
/// successful `lseek` with `SEEK_SET`/`SEEK_CUR`/`SEEK_END` sets it to the syscall's result.
/// `bytes_read` counts bytes the program actually observed; `pread` contributes to it without
/// moving the description. Reuse reproduces the final position, not the intervening history,
/// because only the final position is observable to the caller after the process exits.
#[derive(Clone)]
struct InheritedStreamState {
    path: PathBuf,
    hash: tracejit_effects::Hash,
    fingerprint: tracejit_effects::FileFingerprint,
    start_offset: u64,
    end_offset: u64,
    bytes_read: u64,
    effect_index: Option<usize>,
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
    /// An end of a pipe created inside the traced process tree, identified by the pipe rather
    /// than by the descriptor number so that `dup`, fork and exec preserve provenance.
    InternalPipe {
        pipe: u64,
        readable: bool,
        writable: bool,
    },
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
    /// A successful permission, ownership or timestamp change. It is an output mutation: replay
    /// must reproduce the post-state metadata, and a wall-clock timestamp request is refused
    /// because a cached value would differ from a native rerun.
    MetadataWrite {
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
        mode: i32,
        flags: i32,
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
    FsStats {
        path: PathBuf,
        buffer: u64,
        source: FilesystemStatsSource,
    },
    Enumerate {
        path: PathBuf,
        fd: i32,
        buffer: u64,
        requested: u64,
    },
    Read {
        fd: i32,
        /// Requested byte count, or `None` for a vectored call whose iovec was not inspected.
        count: Option<u64>,
        /// `pread64` reads at an explicit offset and does not move the shared description.
        positioned: bool,
    },
    /// A seek on the inherited regular-file stdin description. Only `SEEK_SET`, `SEEK_CUR` and
    /// `SEEK_END` on fd 0 itself reach this state; the dispatch refuses aliases and
    /// `SEEK_DATA`/`SEEK_HOLE`.
    Seek {
        fd: i32,
    },
    Write {
        fd: i32,
        count: Option<u64>,
    },
    Pipe {
        address: u64,
        close_on_exec: bool,
    },
    Network {
        kind: NetworkOperation,
    },
    Clock {
        kind: ClockKind,
    },
    Random,
    /// A runtime-internal entropy probe that the controlled-execution contract answers itself.
    ControlledRandom {
        contract: String,
        value: u64,
        buffer: u64,
        length: u32,
        flags: i32,
        library: PathBuf,
        library_hash: tracejit_effects::Hash,
        build_id: String,
        site_offset: u64,
        destination_offset: u64,
    },
    KernelState {
        kind: KernelStateRead,
    },
    /// An incidental runtime observation fixed by the compiler-runtime contract.
    ControlledRuntime {
        observation: ControlledRuntimeObservation,
        executable: PathBuf,
        executable_hash: tracejit_effects::Hash,
        build_id: String,
        buffer: u64,
        length: u32,
        value: u64,
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
    pipes: HashMap<u64, PipeRecord>,
    next_pipe: u64,
}

/// What the tracer observed crossing one internal pipe.
///
/// Reuse of a command that moved bytes through a pipe is permitted only when the reader's
/// observations cannot depend on how the kernel happened to packetise the stream. Three
/// conditions make that true, and each one is *detected* here rather than assumed:
///
/// - a single process wrote the pipe, so the write order is that process's program order;
/// - every read either received exactly what it asked for, or was the final data before
///   end-of-file, so the sequence of read results is fixed by the concatenated stream;
/// - no write was refused or truncated, so no reader exited early.
///
/// Any violation is recorded with the observation that triggered it and makes the execution
/// unguardable. The test suite exercises each rule.
#[derive(Default)]
struct PipeRecord {
    writers: HashSet<i32>,
    /// Sequence of a short read whose stream has not yet been shown to be complete.
    short_read: Option<u64>,
    unstable: Option<String>,
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

/// The pid a wait status belongs to, or `None` when the reported process is already gone.
fn reported_pid(status: &WaitStatus) -> Option<Pid> {
    match status {
        WaitStatus::Stopped(pid, _)
        | WaitStatus::PtraceEvent(pid, _, _)
        | WaitStatus::PtraceSyscall(pid)
        | WaitStatus::Continued(pid) => Some(*pid),
        WaitStatus::Exited(_, _) | WaitStatus::Signaled(_, _, _) | WaitStatus::StillAlive => None,
    }
}

/// Reads the parent this kernel attached the tracee on behalf of.
///
/// A thread's `/proc` parent is the parent of its whole thread group, so a non-leader thread is
/// reconciled from its group leader when that leader is already tracked. Returns `None` unless the
/// process is traced by this tracer, which keeps the reconciliation from adopting an unrelated
/// child of the tracer itself.
fn traced_parent(pid: Pid, states: &HashMap<Pid, ProcessState>) -> Option<Pid> {
    let status = fs::read_to_string(format!("/proc/{}/status", pid.as_raw())).ok()?;
    let (mut tracer, mut tgid, mut ppid) = (None, None, None);
    for line in status.lines() {
        let mut fields = line.split_whitespace();
        match (fields.next(), fields.next()) {
            (Some("TracerPid:"), Some(value)) => tracer = value.parse::<i32>().ok(),
            (Some("Tgid:"), Some(value)) => tgid = value.parse::<i32>().ok(),
            (Some("PPid:"), Some(value)) => ppid = value.parse::<i32>().ok(),
            _ => {}
        }
    }
    if tracer? != std::process::id() as i32 {
        return None;
    }
    let tgid = Pid::from_raw(tgid?);
    if tgid != pid && states.contains_key(&tgid) {
        return Some(tgid);
    }
    let ppid = Pid::from_raw(ppid?);
    states.contains_key(&ppid).then_some(ppid)
}

/// Registers a child that the kernel attached to this tracer but whose fork event has not been
/// processed yet. Registration is idempotent: a vfork child can reach its first stop before the
/// parent's `PTRACE_EVENT_VFORK`, and the event must not overwrite the post-exec state that the
/// child's own `PTRACE_EVENT_EXEC` already applied.
fn adopt_child(
    child: Pid,
    parent: Pid,
    states: &mut HashMap<Pid, ProcessState>,
    processes: &mut Vec<ProcessNode>,
    tracee_guard: &mut TraceeGuard,
    collector: &mut Collector,
) -> Result<(), TraceError> {
    if states.contains_key(&child) {
        return Ok(());
    }
    // A vfork child that exits without exec can be reaped before the parent's fork event is
    // processed. Installing a state for that pid would leave an entry that never receives another
    // wait status, so the loop would never observe an empty process set. Record the event and the
    // uncertainty instead; reuse is refused.
    if fs::metadata(format!("/proc/{}", child.as_raw())).is_err() {
        collector.push(
            parent,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "child {child} exited before its fork event was processed; no state was installed"
                ),
            }),
        );
        return Ok(());
    }
    let inherited = states
        .get(&parent)
        .cloned()
        .ok_or_else(|| TraceError::Ptrace(format!("missing parent state for {parent}")))?;
    if !tracee_guard.pids.contains(&child) {
        tracee_guard.pids.push(child);
    }
    states.insert(
        child,
        ProcessState {
            // The child resumes on the exit side of the creating syscall; the first reported
            // boundary varies, so synchronize from the entry-stop return-register sentinel.
            entering: false,
            synchronize_on_next_syscall: true,
            pending: None,
            enumerations: HashMap::new(),
            // A child shares the open file description but not this model's consumption
            // accounting, so it must not silently read stdin.
            stdin_stream: None,
            ..inherited
        },
    );
    if !processes
        .iter()
        .any(|process| process.pid == child.as_raw() as u32)
    {
        processes.push(ProcessNode {
            pid: child.as_raw() as u32,
            parent_pid: Some(parent.as_raw() as u32),
            executable: None,
            exit_code: None,
        });
    }
    collector.push(
        parent,
        Effect::Control(ControlEffect::Spawn(ProcessSpawn {
            child_pid: child.as_raw() as u32,
        })),
    );
    Ok(())
}

impl Collector {
    fn open_pipe(&mut self) -> u64 {
        self.next_pipe += 1;
        self.pipes.insert(self.next_pipe, PipeRecord::default());
        self.next_pipe
    }

    fn pipe_read(&mut self, _pid: Pid, pipe: u64, count: Option<u64>, result: i64) {
        let Some(record) = self.pipes.get_mut(&pipe) else {
            return;
        };
        if record.unstable.is_some() {
            return;
        }
        let Some(count) = count else {
            record.unstable = Some(format!(
                "pipe {pipe}: a vectored read has no tracked request size, so the result depends on how the writer packetised the stream"
            ));
            return;
        };
        let read = result as u64;
        if read == 0 {
            // End of file: everything the writer produced has been consumed.
            record.short_read = None;
            return;
        }
        if read < count {
            record.short_read = Some(self.sequence);
        }
    }

    fn pipe_write(&mut self, pid: Pid, pipe: u64, count: Option<u64>, result: i64) {
        let Some(record) = self.pipes.get_mut(&pipe) else {
            return;
        };
        if record.unstable.is_some() {
            return;
        }
        if record.short_read.is_some() {
            record.unstable = Some(format!(
                "pipe {pipe}: a read returned less than it requested and more data followed, so the reader's observations depend on scheduling"
            ));
            return;
        }
        let Some(count) = count else {
            record.unstable = Some(format!(
                "pipe {pipe}: a vectored write has no tracked size, so a partial transfer cannot be ruled out"
            ));
            return;
        };
        if (result as u64) < count {
            record.unstable = Some(format!(
                "pipe {pipe}: a write was only partially accepted, so the split depends on the reader's progress"
            ));
            return;
        }
        record.writers.insert(pid.as_raw());
        if record.writers.len() > 1 {
            record.unstable = Some(format!(
                "pipe {pipe}: more than one process wrote to it, so byte order depends on scheduling"
            ));
        }
    }

    fn flush_pipes(&mut self) {
        let mut unstable = self
            .pipes
            .iter()
            .filter_map(|(pipe, record)| record.unstable.clone().map(|reason| (*pipe, reason)))
            .collect::<Vec<_>>();
        unstable.sort_by_key(|(pipe, _)| *pipe);
        for (_, reason) in unstable {
            self.sequence += 1;
            self.effects.push(EffectRecord {
                sequence: self.sequence,
                pid: 0,
                effect: Effect::Unknown(UnknownEffect {
                    syscall: None,
                    detail: reason,
                }),
            });
        }
    }

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
    // Exec the path the caller named whenever it still resolves to the executable that was
    // resolved for the identity. Preserving argv[0] alone is not enough for a script: the kernel
    // hands the interpreter the path that was passed to execve, so exec'ing the canonical target
    // leaves `$0` absolute where a direct `./script` invocation left it relative. A name without
    // a separator cannot be execed as a path at all, so PATH-name invocations keep the resolved
    // path and rely on the preserved argv[0].
    let executable_path = request
        .argv
        .first()
        .filter(|argument| argument.to_string_lossy().contains('/'))
        .and_then(|argument| {
            let named = Path::new(argument);
            let absolute = if named.is_absolute() {
                named.to_path_buf()
            } else {
                request.cwd.join(named)
            };
            (fs::canonicalize(&absolute).ok()? == request.executable).then(|| named.to_path_buf())
        })
        .unwrap_or_else(|| request.executable.clone());
    // The lookup key was built from a hash taken before tracing started. If the path now resolves
    // to a different file, this run's profile would be filed under the identity of an executable
    // that did not produce it, which is the one way this design could record a result under the
    // wrong identity. Re-check immediately before exec and fail closed instead. This narrows the
    // window to the gap between this check and `execve`; it does not close it, because the kernel
    // resolves the path again when it execs.
    if let Some(expected) = request.expected_executable_hash {
        let actual = hash_file(&executable_path).map_err(|error| {
            TraceError::ExecutableChanged(format!(
                "could not re-verify {} before execution: {error}",
                executable_path.display()
            ))
        })?;
        if actual != expected {
            return Err(TraceError::ExecutableChanged(format!(
                "{} changed between identity construction and execution",
                executable_path.display()
            )));
        }
    }
    let mut command = Command::new(&executable_path);
    // Keep the caller's argv[0] byte-for-byte. `resolve_executable` canonicalizes symlinks, and
    // the kernel-visible argv[0] is observable: CPython derives its installation prefix, and
    // therefore its module search path, from argv[0], so rewriting it to the canonical target
    // makes a traced execution resolve a different installation than a direct execution of the
    // same command line.
    if let Some(program) = request.argv.first() {
        command.arg0(program);
    }
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

    let initial_fds = initial_descriptor_table(root_pid).map_err(|error| {
        TraceError::Ptrace(format!(
            "could not enumerate the target descriptor table: {error}"
        ))
    })?;
    // Descriptors above stderr are inherited state, not effects created by this execution. The
    // stdin offset model does not cover their offsets, flags or shared open descriptions, so no
    // record containing one may become reusable. Core refuses these invocations before lookup;
    // this effect is a second line of defence for any trace path that reaches here.
    let extra_inherited_fds = initial_fds
        .keys()
        .copied()
        .filter(|fd| *fd > 2)
        .collect::<Vec<_>>();
    let stdin_alias = stdin_descriptor_alias(root_pid);
    let stdin_refusal = stdin_alias.map(|fd| {
        format!(
            "inherited stdin shares its open file description with descriptor {fd}; the shared offset is not modelled"
        )
    });
    let stdin_stream = if stdin_refusal.is_some() {
        None
    } else {
        initial_inherited_stream(root_pid)
    };
    let mut states = HashMap::from([(
        root_pid,
        ProcessState {
            cwd: request.cwd.clone(),
            fds: initial_fds,
            close_on_exec: HashSet::new(),
            entering: true,
            synchronize_on_next_syscall: false,
            pending: None,
            file_mappings: Vec::new(),
            enumerations: HashMap::new(),
            stdin_stream,
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
        pipes: HashMap::new(),
        next_pipe: 0,
    };
    for fd in extra_inherited_fds {
        collector.push(
            root_pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: format!(
                    "inherited descriptor {fd} beyond stdin is not modelled; its identity, offset, flags and shared open description cannot be guarded"
                ),
            }),
        );
    }
    if let Some(detail) = stdin_refusal {
        collector.push(
            root_pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail,
            }),
        );
    }
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
        // The kernel reports a child to the tracer before the child can run, but it does not
        // promise that the parent's fork event is dequeued before the child's own first stop.
        // vfork makes the race concrete: the parent only stops once the child execs or exits, so
        // the child's SIGSTOP and even its PTRACE_EVENT_EXEC can arrive first. Reconcile that
        // tracee from /proc instead of failing with a missing state.
        if let Some(pid) = reported_pid(&status) {
            if !states.contains_key(&pid) {
                match traced_parent(pid, &states) {
                    Some(parent) => adopt_child(
                        pid,
                        parent,
                        &mut states,
                        &mut processes,
                        &mut tracee_guard,
                        &mut collector,
                    )?,
                    // Reparenting, CLONE_PARENT and a TID change across exec can leave no tracked
                    // /proc parent. Aborting would turn a normal command into a traced failure, so
                    // reconstruct conservatively from a known process and record that reuse is
                    // refused: an incomplete state must never be silently treated as complete.
                    None => {
                        if let Some(parent) = states.keys().next().copied() {
                            adopt_child(
                                pid,
                                parent,
                                &mut states,
                                &mut processes,
                                &mut tracee_guard,
                                &mut collector,
                            )?;
                            collector.push(
                                pid,
                                Effect::Unknown(UnknownEffect {
                                    syscall: None,
                                    detail: format!(
                                        "process {pid} has no tracked parent; inherited state was reconstructed conservatively and reuse is refused"
                                    ),
                                }),
                            );
                        }
                    }
                }
            }
        }
        match status {
            WaitStatus::PtraceSyscall(pid) => {
                ensure_vdso_disarmed(pid, &mut states, &mut collector);
                handle_syscall(
                    pid,
                    &mut states,
                    &mut collector,
                    request.sandbox.is_some(),
                    request.contract,
                )?;
                ptrace::syscall(pid, None)
                    .map_err(|error| ptrace_operation("resume after syscall", pid, error))?;
            }
            WaitStatus::PtraceEvent(pid, Signal::SIGTRAP, event)
                if event == libc::PTRACE_EVENT_FORK
                    || event == libc::PTRACE_EVENT_VFORK
                    || event == libc::PTRACE_EVENT_CLONE =>
            {
                let child_pid = Pid::from_raw(ptrace::getevent(pid).map_err(ptrace_error)? as i32);
                adopt_child(
                    child_pid,
                    pid,
                    &mut states,
                    &mut processes,
                    &mut tracee_guard,
                    &mut collector,
                )?;
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
                let state = states.get_mut(&pid).ok_or_else(|| {
                    TraceError::Ptrace(format!("missing process state for {pid}"))
                })?;
                let closed = state.close_on_exec.drain().collect::<Vec<_>>();
                for fd in closed {
                    state.fds.remove(&fd);
                }
                state.entering = false;
                state.synchronize_on_next_syscall = true;
                state.pending = None;
                state.file_mappings.clear();
                state.vdso_disarmed = false;
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
    // Pipe determinism is a property of the whole transfer, so it can only be judged once every
    // process has exited. An unstable pattern becomes an unknown effect, which refuses reuse.
    collector.flush_pipes();
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
    contract: Option<Contract>,
) -> Result<(), TraceError> {
    let registers =
        ptrace::getregs(pid).map_err(|error| ptrace_operation("read registers", pid, error))?;
    let state = match states.get_mut(&pid) {
        Some(state) => state,
        None => {
            let proc_status = fs::read_to_string(format!("/proc/{}/status", pid.as_raw()))
                .unwrap_or_else(|error| format!("<{error}>"));
            let fields = proc_status
                .lines()
                .filter(|line| {
                    line.starts_with("Name:")
                        || line.starts_with("Tgid:")
                        || line.starts_with("PPid:")
                        || line.starts_with("TracerPid:")
                        || line.starts_with("State:")
                })
                .collect::<Vec<_>>()
                .join(" ");
            let tracked = states.keys().map(|key| key.as_raw()).collect::<Vec<_>>();
            return Err(TraceError::Ptrace(format!(
                "missing process state for {pid}; proc=[{fields}]; tracked={tracked:?}"
            )));
        }
    };
    if state.synchronize_on_next_syscall {
        state.entering = registers.rax as i64 == -(libc::ENOSYS as i64);
        state.synchronize_on_next_syscall = false;
    }
    if state.entering {
        // A process that moved the shared description outside the modelled operations, for
        // example an external observer, is detected before the process disappears.
        if registers.orig_rax as i64 == libc::SYS_exit_group {
            verify_stdin_position(pid, state, collector);
        }
        let pending = decode_entry(pid, state, &registers, contract)?;
        // The contract supplies the bytes, so the kernel must not produce a different value. An
        // invalid syscall number makes the kernel return ENOSYS; the exit stop below replaces
        // the return register and writes the contract bytes as if the call had succeeded.
        if matches!(pending, PendingSyscall::ControlledRandom { .. }) {
            let mut injected = registers;
            injected.orig_rax = u64::MAX;
            ptrace::setregs(pid, injected)
                .map_err(|error| ptrace_operation("inject controlled entropy", pid, error))?;
        }
        state.pending = Some(pending);
        state.entering = false;
    } else {
        let pending = state.pending.take().unwrap_or(PendingSyscall::None);
        if let PendingSyscall::ControlledRandom {
            contract,
            value,
            buffer,
            length,
            flags,
            library,
            library_hash,
            build_id,
            site_offset,
            destination_offset,
        } = pending
        {
            write_process_bytes(pid, buffer, &value.to_ne_bytes())?;
            let mut resumed = ptrace::getregs(pid)
                .map_err(|error| ptrace_operation("read registers", pid, error))?;
            resumed.rax = u64::from(length);
            ptrace::setregs(pid, resumed)
                .map_err(|error| ptrace_operation("finish controlled entropy", pid, error))?;
            collector.push(
                pid,
                Effect::Read(ReadEffect::ControlledEntropy(ControlledEntropyRead {
                    library,
                    library_hash,
                    build_id,
                    site_offset,
                    destination_offset,
                    module_offset: site_offset,
                    length,
                    flags,
                    value,
                    contract,
                })),
            );
            state.entering = true;
            return Ok(());
        }
        if let PendingSyscall::ControlledRuntime {
            observation,
            executable,
            executable_hash,
            build_id,
            buffer,
            length,
            value,
        } = pending
        {
            let payload = controlled_runtime_payload(observation, value, length)?;
            write_process_bytes(pid, buffer, &payload).map_err(|error| {
                TraceError::Ptrace(format!(
                    "{} buffer {buffer:#x} (length {length}): {error}",
                    observation.name()
                ))
            })?;
            let mut resumed = ptrace::getregs(pid)
                .map_err(|error| ptrace_operation("read registers", pid, error))?;
            resumed.rax = 0;
            ptrace::setregs(pid, resumed)
                .map_err(|error| ptrace_operation("finish controlled observation", pid, error))?;
            collector.push(
                pid,
                Effect::Read(ReadEffect::ControlledRuntime(ControlledRuntimeRead {
                    observation,
                    executable,
                    executable_hash,
                    build_id,
                    length,
                    value,
                    contract: Contract::CompilerRuntimeV1.id().to_string(),
                })),
            );
            state.entering = true;
            return Ok(());
        }
        let result = registers.rax as i64;
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
    contract: Option<Contract>,
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
        libc::SYS_open => {
            open_pending(pid, state, libc::AT_FDCWD, args[0], args[1] as i32, number)?
        }
        libc::SYS_openat => {
            open_pending(pid, state, args[0] as i32, args[1], args[2] as i32, number)?
        }
        libc::SYS_openat2 => {
            let flags = read_word(pid, args[2])? as i32;
            open_pending(pid, state, args[0] as i32, args[1], flags, number)?
        }
        // `creat(path, mode)` is `open(path, O_CREAT|O_WRONLY|O_TRUNC)`. Leaving it unmodelled
        // meant every later `fstat` on the new descriptor was unclassified too, which refused
        // `tar` and every other tool that creates an output file.
        libc::SYS_creat => open_pending(
            pid,
            state,
            libc::AT_FDCWD,
            args[0],
            libc::O_CREAT | libc::O_WRONLY | libc::O_TRUNC,
            number,
        )?,
        libc::SYS_ftruncate => resolution_for_fd(state, args[0] as i32)
            .map(|path| PendingSyscall::MetadataWrite { path })
            .unwrap_or_else(|| PendingSyscall::Unknown {
                number,
                detail: format!("truncate on unclassified fd {}", args[0]),
            }),
        libc::SYS_truncate => PendingSyscall::MetadataWrite {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_fchmod | libc::SYS_fchown => {
            resolution_for_fd(state, args[0] as i32)
                .map(|path| PendingSyscall::MetadataWrite { path })
                .unwrap_or_else(|| PendingSyscall::Unknown {
                    number,
                    detail: format!("metadata change on unclassified fd {}", args[0]),
                })
        }
        libc::SYS_chmod | libc::SYS_chown => PendingSyscall::MetadataWrite {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_fchmodat | libc::SYS_fchownat => PendingSyscall::MetadataWrite {
            path: resolve_path(pid, state, args[0] as i32, args[1])?,
        },
        libc::SYS_utimensat => {
            let path = if args[1] == 0 {
                resolution_for_fd(state, args[0] as i32)
            } else {
                Some(resolve_path(pid, state, args[0] as i32, args[1])?)
            };
            match (path, utimensat_uses_wall_clock(pid, args[2])) {
                (Some(path), false) => PendingSyscall::MetadataWrite { path },
                (Some(_), true) => PendingSyscall::Unknown {
                    number,
                    detail: "utimensat timestamps come from the wall clock".into(),
                },
                (None, _) => PendingSyscall::Unknown {
                    number,
                    detail: format!("utimensat on unclassified fd {}", args[0]),
                },
            }
        }
        libc::SYS_stat => PendingSyscall::Metadata {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
        },
        libc::SYS_access => {
            access_pending(pid, state, libc::AT_FDCWD, args[0], args[1] as i32, 0, number)?
        }
        libc::SYS_faccessat => {
            access_pending(pid, state, args[0] as i32, args[1], args[2] as i32, 0, number)?
        }
        libc::SYS_faccessat2 => access_pending(
            pid,
            state,
            args[0] as i32,
            args[1],
            args[2] as i32,
            args[3] as i32,
            number,
        )?,
        libc::SYS_fstat => state
            .fds
            .get(&(args[0] as i32))
            .and_then(|fd| match fd {
                FdState::File(path) | FdState::InheritedFile(path) => {
                    Some(PendingSyscall::Metadata { path: path.clone() })
                }
                FdState::InternalPipe { .. } => Some(PendingSyscall::Unknown {
                    number,
                    detail: format!(
                        "fstat on pipe descriptor {} reports buffered byte counts, which depend on scheduling",
                        args[0]
                    ),
                }),
                FdState::Other if args[0] <= 2 => Some(PendingSyscall::None),
                _ => None,
            })
            .unwrap_or_else(|| PendingSyscall::Unknown {
                number,
                detail: format!("fstat on unclassified fd {}", args[0]),
            }),
        // A directory enumeration is recorded as the exact byte stream the kernel returned. It
        // is only admitted when the descriptor is at position zero, so a rewind or a seek that
        // this model does not track cannot silently change which entries the program saw.
        libc::SYS_getdents64 => match state.fds.get(&(args[0] as i32)) {
            Some(FdState::File(path)) if path.is_dir() => {
                let fd = args[0] as i32;
                let first = !state.enumerations.contains_key(&fd);
                if first && fd_position(pid, fd) != Some(0) {
                    PendingSyscall::Unknown {
                        number,
                        detail: format!(
                            "directory enumeration of {} did not start at offset zero",
                            path.display()
                        ),
                    }
                } else {
                    PendingSyscall::Enumerate {
                        path: path.clone(),
                        fd,
                        buffer: args[1],
                        requested: args[2],
                    }
                }
            }
            _ => PendingSyscall::Unknown {
                number,
                detail: format!("getdents64 on unclassified fd {}", args[0]),
            },
        },
        libc::SYS_statfs => PendingSyscall::FsStats {
            path: resolve_path(pid, state, libc::AT_FDCWD, args[0])?,
            buffer: args[1],
            source: FilesystemStatsSource::Path,
        },
        libc::SYS_fstatfs => state
            .fds
            .get(&(args[0] as i32))
            .and_then(|fd| match fd {
                FdState::File(path) | FdState::InheritedFile(path) => Some(PendingSyscall::FsStats {
                    path: path.clone(),
                    buffer: args[1],
                    source: FilesystemStatsSource::Descriptor,
                }),
                _ => None,
            })
            .unwrap_or_else(|| PendingSyscall::Unknown {
                number,
                detail: format!("fstatfs on unclassified fd {}", args[0]),
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
        // x86-64 `read(fd, buffer, count)` and `pread64(fd, buffer, count, offset)` carry the
        // length in the third argument; the second is the buffer address. They differ in the
        // effect on the shared open file description, which the inherited-stdin model tracks.
        libc::SYS_read => PendingSyscall::Read {
            fd: args[0] as i32,
            count: Some(args[2]),
            positioned: false,
        },
        libc::SYS_pread64 => PendingSyscall::Read {
            fd: args[0] as i32,
            count: Some(args[2]),
            positioned: true,
        },
        libc::SYS_readv => PendingSyscall::Read {
            fd: args[0] as i32,
            // The iovec is not inspected, so the requested length is unknown.
            count: None,
            positioned: false,
        },
        libc::SYS_write | libc::SYS_pwrite64 => PendingSyscall::Write {
            fd: args[0] as i32,
            count: Some(args[2]),
        },
        libc::SYS_writev => PendingSyscall::Write {
            fd: args[0] as i32,
            count: None,
        },
        libc::SYS_pipe | libc::SYS_pipe2 => PendingSyscall::Pipe {
            address: args[0],
            close_on_exec: number == libc::SYS_pipe2 && args[1] as i32 & libc::O_CLOEXEC != 0,
        },
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
        libc::SYS_clock_gettime | libc::SYS_gettimeofday => {
            let kind = if number == libc::SYS_clock_gettime {
                match args[0] as i32 {
                    libc::CLOCK_REALTIME => ClockKind::Realtime,
                    libc::CLOCK_MONOTONIC => ClockKind::Monotonic,
                    other => ClockKind::Other(other),
                }
            } else {
                ClockKind::Realtime
            };
            let observation = match &kind {
                ClockKind::Realtime => Some(ControlledRuntimeObservation::ClockRealtime),
                ClockKind::Monotonic => Some(ControlledRuntimeObservation::ClockMonotonic),
                ClockKind::Other(_) => None,
            };
            match (contract, observation) {
                (Some(Contract::CompilerRuntimeV1), Some(observation)) => {
                    match compiler_observation(pid, observation) {
                        Some((executable, executable_hash, build_id)) => {
                            PendingSyscall::ControlledRuntime {
                                observation,
                                executable,
                                executable_hash,
                                build_id,
                                buffer: if number == libc::SYS_clock_gettime {
                                    args[1]
                                } else {
                                    args[0]
                                },
                                length: observation.length(),
                                value: observation.value(),
                            }
                        }
                        None => PendingSyscall::Clock { kind },
                    }
                }
                _ => PendingSyscall::Clock { kind },
            }
        }
        libc::SYS_time => PendingSyscall::Clock {
            kind: ClockKind::Realtime,
        },
        // Native mode keeps `getrandom` nondeterministic. Under the allocator-entropy contract
        // only the runtime's own internal probe is answered by the tracer; an application buffer,
        // a different length or different flags still makes the execution ineligible.
        libc::SYS_getrandom => {
            let buffer = args[0];
            let length = args[1];
            let flags = args[2] as i32;
            match contract {
                Some(_) if length == 8 && flags == 1 => {
                    // The probe is admitted by the allocator-entropy contract's own audited
                    // call site; a broader contract activates it but does not redefine it.
                    let contract_id = Contract::AllocatorEntropyV1.id().to_string();
                    match allocator_entropy_site(pid, registers.rip, buffer) {
                        Some(site) => PendingSyscall::ControlledRandom {
                            contract: contract_id,
                            value: tracejit_effects::ALLOCATOR_ENTROPY_VALUE,
                            buffer,
                            length: length as u32,
                            flags,
                            library: site.library,
                            library_hash: site.library_hash,
                            build_id: site.build_id,
                            site_offset: site.site_offset,
                            destination_offset: site.destination_offset,
                        },
                        None => PendingSyscall::Random,
                    }
                }
                _ => PendingSyscall::Random,
            }
        }
        libc::SYS_mmap => {
            let length = args[1];
            let prot = args[2];
            let flags = args[3];
            let fd = args[4] as i64;
            let anonymous = flags & libc::MAP_ANONYMOUS as u64 != 0 || fd < 0;
            let shared = flags & libc::MAP_SHARED as u64 != 0;
            // Anonymous MAP_SHARED is shared memory across fork/clone with no file effect
            // stream. Treating it as process-internal would miss cross-process mutation.
            if anonymous && shared {
                PendingSyscall::Unknown {
                    number,
                    detail: "anonymous MAP_SHARED mapping is untracked shared memory; stores and cross-fork visibility are not captured outputs".into(),
                }
            } else if anonymous {
                PendingSyscall::None
            } else {
                PendingSyscall::Mmap {
                    length,
                    prot,
                    flags,
                }
            }
        }
        // Hard-link creation aliases an inode under a new pathname. Restoration is
        // pathname-visible (CAS rename), so successful link/linkat cannot be replayed as
        // native inode sharing. Fail closed rather than recording a false output model.
        libc::SYS_link | libc::SYS_linkat => PendingSyscall::Unknown {
            number,
            detail: "hard-link creation is not a pathname-equivalent output effect".into(),
        },
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
        // Under the compiler contract, resource-limit queries and the driver's own stack-limit
        // raise are process-local configuration of an audited binary; the inherited limits are
        // part of `RuntimeIdentity`, so a different limit is a different cache identity.
        libc::SYS_prlimit64
            if contract == Some(Contract::CompilerRuntimeV1)
                && audited_toolchain(pid).is_some() =>
        {
            PendingSyscall::None
        }
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
        libc::SYS_getrusage
            if contract == Some(Contract::CompilerRuntimeV1)
                && args[0] == libc::RUSAGE_SELF as u64
                && args[1] != 0 =>
        {
            match compiler_observation(pid, ControlledRuntimeObservation::GetrusageSelf) {
                Some((executable, executable_hash, build_id)) => {
                    PendingSyscall::ControlledRuntime {
                        observation: ControlledRuntimeObservation::GetrusageSelf,
                        executable,
                        executable_hash,
                        build_id,
                        buffer: args[1],
                        length: ControlledRuntimeObservation::GetrusageSelf.length(),
                        value: ControlledRuntimeObservation::GetrusageSelf.value(),
                    }
                }
                None => PendingSyscall::Unknown {
                    number,
                    detail: "getrusage outside the audited compiler profile".into(),
                },
            }
        }
        libc::SYS_sysinfo => match contract {
            Some(Contract::CompilerRuntimeV1) => {
                match compiler_observation(pid, ControlledRuntimeObservation::SysinfoMemory) {
                    Some((executable, executable_hash, build_id)) => {
                        PendingSyscall::ControlledRuntime {
                            observation: ControlledRuntimeObservation::SysinfoMemory,
                            executable,
                            executable_hash,
                            build_id,
                            buffer: args[0],
                            length: ControlledRuntimeObservation::SysinfoMemory.length(),
                            value: ControlledRuntimeObservation::SysinfoMemory.value(),
                        }
                    }
                    None => system_information("sysinfo"),
                }
            }
            _ => system_information("sysinfo"),
        },
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
        // A directory seek changes which entries a later `getdents64` observes, and no directory
        // stream model tracks a mid-stream seek, so it stays refused.
        libc::SYS_lseek => match state.fds.get(&(args[0] as i32)) {
            Some(FdState::File(path)) if path.is_dir() => PendingSyscall::Unknown {
                number,
                detail: format!(
                    "lseek on directory descriptor {} is not modelled",
                    args[0]
                ),
            },
            Some(FdState::InheritedFile(path)) if path.is_dir() => PendingSyscall::Unknown {
                number,
                detail: format!(
                    "lseek on inherited directory descriptor {} is not modelled",
                    args[0]
                ),
            },
            Some(FdState::InheritedFile(path))
                if state
                    .stdin_stream
                    .as_ref()
                    .is_some_and(|stream| stream.path == *path) =>
            {
                let fd = args[0] as i32;
                let whence = args[2] as i32;
                // The caller-visible description is fd 0. A duplicate moves the same offset, but
                // the model tracks one position per stream, so an alias is refused rather than
                // guessed. `SEEK_DATA`/`SEEK_HOLE` answer about allocation layout, which the
                // content hash does not capture, so they are refused too.
                if fd != 0 {
                    PendingSyscall::Unknown {
                        number,
                        detail: format!(
                            "lseek on inherited descriptor {fd}, an alias of stdin, is not modelled"
                        ),
                    }
                } else if !matches!(whence, libc::SEEK_SET | libc::SEEK_CUR | libc::SEEK_END) {
                    PendingSyscall::Unknown {
                        number,
                        detail: format!(
                            "lseek whence {whence} on inherited descriptor 0 is not modelled"
                        ),
                    }
                } else {
                    PendingSyscall::Seek { fd }
                }
            }
            // A forked child shares the open file description but not this model's consumption
            // accounting, and an inherited alias can move the same description. Both are refused
            // rather than treated as a process-internal seek.
            Some(FdState::InheritedFile(path))
                if path == Path::new("/dev/null")
                    && is_null_device_fd(pid, args[0] as i32) =>
            {
                PendingSyscall::None
            }
            Some(FdState::InheritedFile(path)) => PendingSyscall::Unknown {
                number,
                detail: format!(
                    "lseek on inherited descriptor {} whose open file description ({}) is not modelled",
                    args[0],
                    path.display()
                ),
            },
            // Seeks on every other descriptor keep the pre-existing treatment: they are
            // process-internal and no read model depends on their offset.
            _ => PendingSyscall::None,
        },
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

/// Returns true only when the inherited descriptor currently names the kernel null device.
///
/// The pathname alone is not enough: a bind mount or substituted node can make `/dev/null`
/// resolve to a regular file, and an inherited descriptor can be replaced. `fstat` through
/// `/proc/<pid>/fd/<fd>` inspects the actual open object. Any failure is a refusal, not an
/// assumption that the descriptor is null.
fn is_null_device_fd(pid: Pid, fd: i32) -> bool {
    let path = format!("/proc/{}/fd/{}", pid.as_raw(), fd);
    let Ok(metadata) = fs::metadata(path) else {
        return false;
    };
    metadata.file_type().is_char_device() && metadata.rdev() == libc::makedev(1, 3) as u64
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
                audited_toolchain: audited_toolchain(pid).is_some(),
            })),
        ),
        PathSnapshot::Absent => collector.push(
            pid,
            Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                path,
                fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
                audited_toolchain: audited_toolchain(pid).is_some(),
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

/// Structured provenance for recorded dependencies, enabled with `TRACEJIT_DIAG_DEPS=1`.
///
/// The kind of a dependency is not implied by the syscall that produced it: an `open` of a
/// directory yields a directory-open dependency, while `stat`, `fstat` and `newfstatat` all yield
/// the same metadata dependency. Printing the recording site, thread, path and resulting effect
/// together makes that mapping observable instead of something to be inferred from syscall order.
/// Diagnostics go to stderr so they never contaminate a traced command's stdout.
fn diag_dependency(tid: Pid, site: &str, path: &Path, detail: &str) {
    if std::env::var_os("TRACEJIT_DIAG_DEPS").is_none() {
        return;
    }
    let path = path
        .display()
        .to_string()
        .replace('\\', "\\\\")
        .replace('"', "\\\"");
    let detail = detail.replace('"', "\\\"");
    eprintln!(
        "{{\"event\":\"dependency\",\"tid\":{},\"site\":\"{}\",\"path\":\"{}\",\"detail\":\"{}\"}}",
        tid.as_raw(),
        site,
        path,
        detail
    );
}

fn record_metadata(pid: Pid, path: PathBuf, collector: &mut Collector) {
    match fingerprint(&path) {
        Ok(value) => collector.push(
            pid,
            Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                fingerprint: Some(value),
                path,
                audited_toolchain: audited_toolchain(pid).is_some(),
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
                audited_toolchain: audited_toolchain(pid).is_some(),
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

/// Records a permission probe, or refuses it when it does not name a path.
///
/// `AT_EMPTY_PATH` asks about the descriptor's inode, so re-evaluating a path would answer a
/// different question than the program asked. An empty name without that flag is an `ENOENT` probe
/// that the absence metadata guard already covers. Both are refused here rather than approximated.
fn access_pending(
    pid: Pid,
    state: &ProcessState,
    dirfd: i32,
    address: u64,
    mode: i32,
    flags: i32,
    number: i64,
) -> Result<PendingSyscall, TraceError> {
    let named = !read_c_string(pid, address)?.is_empty();
    if !named || flags & libc::AT_EMPTY_PATH != 0 {
        return Ok(PendingSyscall::Unknown {
            number,
            detail:
                "access check resolves through a descriptor, not a name, so it cannot be replayed"
                    .into(),
        });
    }
    Ok(PendingSyscall::Access {
        path: resolve_path(pid, state, dirfd, address)?,
        mode,
        flags,
    })
}

fn open_pending(
    pid: Pid,
    state: &ProcessState,
    dirfd: i32,
    address: u64,
    flags: i32,
    number: i64,
) -> Result<PendingSyscall, TraceError> {
    let path = resolve_path(pid, state, dirfd, address)?;
    diag_dependency(
        pid,
        "tracejit-trace::open_pending",
        &path,
        &format!("syscall={number} flags={flags:#x} dirfd={dirfd}"),
    );
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

fn forget_descriptor(state: &mut ProcessState, fd: i32) {
    state.fds.remove(&fd);
    state.close_on_exec.remove(&fd);
    // An enumeration record is about one open file description. Reusing the descriptor number
    // must not append a new directory's stream to the previous record: the guard would replay a
    // concatenation that no single descriptor ever produced.
    state.enumerations.remove(&fd);
}

fn record_pipe(
    state: &mut ProcessState,
    read_fd: i32,
    write_fd: i32,
    close_on_exec: bool,
    collector: &mut Collector,
) {
    let pipe = collector.open_pipe();
    forget_descriptor(state, read_fd);
    forget_descriptor(state, write_fd);
    state.fds.insert(
        read_fd,
        FdState::InternalPipe {
            pipe,
            readable: true,
            writable: false,
        },
    );
    state.fds.insert(
        write_fd,
        FdState::InternalPipe {
            pipe,
            readable: false,
            writable: true,
        },
    );
    if close_on_exec {
        state.close_on_exec.insert(read_fd);
        state.close_on_exec.insert(write_fd);
    }
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
            state.enumerations.remove(&fd);
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
                                audited_toolchain: audited_toolchain(pid).is_some(),
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
                // A directory opened without being read is a name-resolution base, not a
                // metadata observation: an open cannot report its timestamps, size or link
                // count. Recording it as a full metadata read made every create or delete in
                // the directory invalidate the entry, including the command's own output.
                state.fds.insert(fd, FdState::File(path.clone()));
                diag_dependency(
                    pid,
                    "tracejit-trace::complete_syscall",
                    &path,
                    &format!("fd={fd} effect=DirectoryOpened flags={flags:#x}"),
                );
                collector.push(
                    pid,
                    Effect::Read(ReadEffect::DirectoryOpened(DirectoryOpen {
                        path: path.clone(),
                        fingerprint,
                        flags,
                        credential: credential_identity(pid.as_raw() as u32),
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
        PendingSyscall::Access { path, mode, flags } => collector.push(
            pid,
            Effect::Read(ReadEffect::Access(tracejit_effects::AccessCheck {
                path,
                mode,
                flags,
                errno: None,
                credential: credential_identity(pid.as_raw() as u32),
            })),
        ),
        PendingSyscall::Pipe {
            address,
            close_on_exec,
        } => match read_word(pid, address) {
            Ok(word) => {
                // `pipe` writes two adjacent `int`s; the first occupies the low half of the word.
                let read_fd = (word & 0xffff_ffff) as u32 as i32;
                let write_fd = (word >> 32) as u32 as i32;
                record_pipe(state, read_fd, write_fd, close_on_exec, collector);
            }
            Err(_) => collector.push(
                pid,
                Effect::Unknown(UnknownEffect {
                    syscall: Some(libc::SYS_pipe2),
                    detail: "pipe descriptor pair could not be read from the traced process".into(),
                }),
            ),
        },
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
        PendingSyscall::MetadataWrite { path } => collector.push(
            pid,
            Effect::Write(WriteEffect::File(FileWrite {
                path,
                operation: FileWriteKind::CreateOrModify,
                allows_create: Some(false),
            })),
        ),
        PendingSyscall::Dup {
            source,
            destination,
            close_on_exec,
        } => {
            let destination = destination.unwrap_or(result as i32);
            // dup2(fd, fd) is a successful Linux no-op and keeps FD_CLOEXEC. dup3(fd, fd)
            // fails with EINVAL, so only dup2 reaches this path. Forgetting this destination
            // would erase the fd classification, CLOEXEC bit and enumeration record.
            if destination == source {
                return;
            }
            // A duplicate shares the directory offset but not a separately recorded stream.
            // Refuse to extend either record rather than guess which descriptor consumed which
            // bytes; a later getdents64 on a non-zero offset is refused by the trace.
            state.enumerations.remove(&source);
            forget_descriptor(state, destination);
            if let Some(fd) = state.fds.get(&source).cloned() {
                state.fds.insert(destination, fd);
            }
            if close_on_exec {
                state.close_on_exec.insert(destination);
            } else {
                state.close_on_exec.remove(&destination);
            }
        }
        PendingSyscall::Close { fd } => forget_descriptor(state, fd),
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
        PendingSyscall::FsStats {
            path,
            buffer,
            source,
        } => {
            let mut raw = [0_u8; 120];
            match read_remote(pid, buffer, &mut raw) {
                Ok(()) => {
                    let mut words = [0_i64; 15];
                    for (index, chunk) in raw.chunks_exact(8).enumerate() {
                        let mut word = [0_u8; 8];
                        word.copy_from_slice(chunk);
                        words[index] = i64::from_ne_bytes(word);
                    }
                    match fingerprint(&path) {
                        Ok(expected) => collector.push(
                            pid,
                            Effect::Read(ReadEffect::FilesystemStats(FilesystemStatsRead {
                                path,
                                source,
                                stats: Some(statfs_from_words(&words)),
                                errno: None,
                                fingerprint: Some(expected),
                                credential: credential_identity(pid.as_raw() as u32),
                                mount_namespace: namespace_identity(pid.as_raw() as u32),
                            })),
                        ),
                        Err(error) => collector.push(
                            pid,
                            Effect::Unknown(UnknownEffect {
                                syscall: Some(libc::SYS_statfs),
                                detail: format!(
                                    "filesystem-stat result cannot be bound to a path: {} ({error})",
                                    path.display()
                                ),
                            }),
                        ),
                    }
                }
                Err(detail) => collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_statfs),
                        detail: format!("filesystem-stat result could not be read: {detail}"),
                    }),
                ),
            }
        }
        PendingSyscall::Enumerate {
            path,
            fd,
            buffer,
            requested,
        } => {
            let length = result as usize;
            if length > requested as usize {
                collector.push(
                    pid,
                    Effect::Unknown(UnknownEffect {
                        syscall: Some(libc::SYS_getdents64),
                        detail: format!(
                            "getdents64 returned {length} bytes for a {requested}-byte buffer"
                        ),
                    }),
                );
            } else {
                let mut bytes = vec![0_u8; length];
                match read_remote(pid, buffer, &mut bytes) {
                    Ok(()) => {
                        let request = DirectoryEnumerationRequest {
                            requested,
                            returned: bytes,
                        };
                        let entry =
                            state
                                .enumerations
                                .entry(fd)
                                .or_insert_with(|| EnumerationState {
                                    fingerprint: fingerprint(&path)
                                        .unwrap_or(tracejit_effects::FileFingerprint::absent()),
                                    credential: credential_identity(pid.as_raw() as u32),
                                    mount_namespace: namespace_identity(pid.as_raw() as u32),
                                    bytes: 0,
                                    effect_index: None,
                                    refused: false,
                                });
                        let size = request.returned.len();
                        if !entry.refused && entry.bytes + size > MAX_ENUMERATION_BYTES {
                            entry.refused = true;
                            collector.push(
                                pid,
                                Effect::Unknown(UnknownEffect {
                                    syscall: Some(libc::SYS_getdents64),
                                    detail: format!(
                                        "directory enumeration of {} is too large to guard",
                                        path.display()
                                    ),
                                }),
                            );
                        } else if !entry.refused {
                            entry.bytes += size;
                            match entry.effect_index {
                                Some(index) => {
                                    if let Some(EffectRecord {
                                        effect: Effect::Read(ReadEffect::DirectoryEnumerated(read)),
                                        ..
                                    }) = collector.effects.get_mut(index)
                                    {
                                        read.requests.push(request);
                                    }
                                }
                                None => {
                                    let first = DirectoryEnumerationRead {
                                        path: path.clone(),
                                        requests: vec![request],
                                        fingerprint: Some(entry.fingerprint.clone()),
                                        credential: entry.credential,
                                        mount_namespace: entry.mount_namespace,
                                    };
                                    collector.push(
                                        pid,
                                        Effect::Read(ReadEffect::DirectoryEnumerated(first)),
                                    );
                                    entry.effect_index = collector.effects.len().checked_sub(1);
                                }
                            }
                        }
                    }
                    Err(detail) => collector.push(
                        pid,
                        Effect::Unknown(UnknownEffect {
                            syscall: Some(libc::SYS_getdents64),
                            detail: format!(
                                "directory enumeration bytes could not be read: {detail}"
                            ),
                        }),
                    ),
                }
            }
        }
        PendingSyscall::Read {
            fd,
            count,
            positioned,
        } => match state.fds.get(&fd).cloned() {
            Some(FdState::Network) => collector.push(
                pid,
                Effect::Read(ReadEffect::Network(NetworkRead {
                    operation: "read from socket".into(),
                })),
            ),
            Some(FdState::File(_)) => {}
            // Bytes from a pipe created inside this execution are a function of inputs that are
            // already guarded, so the read itself is not a dependency. Whether the transfer is
            // packetisation independent is tracked per pipe and enforced at the end of the trace.
            Some(FdState::InternalPipe {
                pipe,
                readable: true,
                ..
            }) => collector.pipe_read(pid, pipe, count, result),
            Some(FdState::InternalPipe { pipe, .. }) => collector.push(
                pid,
                Effect::Unknown(UnknownEffect {
                    syscall: Some(libc::SYS_read),
                    detail: format!("read from the write end of internal pipe {pipe}"),
                }),
            ),
            Some(FdState::InheritedFile(path))
                if path == Path::new("/dev/null") && is_null_device_fd(pid, fd) => {}
            // A read from an inherited regular file is guarded as its content plus the offset
            // contract of the shared open file description. The effect is pushed on the first
            // read so its sequence stays before any later write, then updated in place.
            Some(FdState::InheritedFile(path))
                if fd == 0
                    && state
                        .stdin_stream
                        .as_ref()
                        .is_some_and(|stream| stream.path == path) =>
            {
                let consumed = result as u64;
                if let Some(stream) = state.stdin_stream.as_mut() {
                    stream.bytes_read = stream.bytes_read.saturating_add(consumed);
                    // `pread` reads at an explicit offset and leaves the shared description
                    // where it was; only an ordinary read advances the model's position.
                    if !positioned {
                        stream.end_offset = stream.end_offset.saturating_add(consumed);
                    }
                }
                record_inherited_stream_effect(state, collector, pid, path.clone());
                verify_stdin_position(pid, state, collector);
            }
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
        // A successful seek moves the shared open file description. The final position is the
        // caller-visible effect; reproducing it is what makes a cache hit equivalent to running
        // the program. The bytes the program would read after the seek depend on the same guarded
        // content and initial position, so cached stdout remains valid.
        PendingSyscall::Seek { fd } => {
            if fd == 0 && result >= 0 {
                if let Some(stream) = state.stdin_stream.as_mut() {
                    stream.end_offset = result as u64;
                }
                let path = state
                    .stdin_stream
                    .as_ref()
                    .map(|stream| stream.path.clone());
                if let Some(path) = path {
                    record_inherited_stream_effect(state, collector, pid, path);
                }
                verify_stdin_position(pid, state, collector);
            }
        }
        PendingSyscall::Write { fd, count } => match state.fds.get(&fd) {
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
            Some(FdState::InternalPipe {
                pipe,
                writable: true,
                ..
            }) => collector.pipe_write(pid, *pipe, count, result),
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
                forget_descriptor(state, result as i32);
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
        PendingSyscall::ControlledRandom { .. } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(libc::SYS_getrandom),
                detail: "controlled entropy was not completed by the tracer".into(),
            }),
        ),
        PendingSyscall::ControlledRuntime { .. } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: None,
                detail: "controlled runtime observation was not completed by the tracer".into(),
            }),
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

/// Writes the current offset contract into the execution's single inherited-stream effect.
///
/// One effect per stream is necessary rather than one per read: the effect layer deduplicates by
/// path while keeping the first record, so a per-read record would replay the first read's end
/// position instead of the final one. `bytes_read` is diagnostic; the guard uses the start and
/// final positions plus the content hash.
fn record_inherited_stream_effect(
    state: &mut ProcessState,
    collector: &mut Collector,
    pid: Pid,
    path: PathBuf,
) {
    let Some(stream) = state.stdin_stream.as_mut() else {
        return;
    };
    let start_offset = stream.start_offset;
    let end_offset = stream.end_offset;
    let bytes_read = stream.bytes_read;
    let index = stream.effect_index;
    let hash = stream.hash;
    let fingerprint = stream.fingerprint.clone();
    match index {
        Some(index) => {
            if let Some(EffectRecord {
                effect: Effect::Read(ReadEffect::InheritedStream(read)),
                ..
            }) = collector.effects.get_mut(index)
            {
                read.end_offset = end_offset;
                read.bytes_read = bytes_read;
            }
        }
        None => {
            collector.push(
                pid,
                Effect::Read(ReadEffect::InheritedStream(InheritedStreamRead {
                    path,
                    hash: Some(hash),
                    fingerprint: Some(fingerprint),
                    start_offset,
                    end_offset,
                    bytes_read,
                })),
            );
            if let Some(stream) = state.stdin_stream.as_mut() {
                stream.effect_index = collector.effects.len().checked_sub(1);
            }
        }
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
                    audited_toolchain: audited_toolchain(pid).is_some(),
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
                    audited_toolchain: audited_toolchain(pid).is_some(),
                })),
            );
        }
        PendingSyscall::TerminalProbe { path } => record_metadata(pid, path, collector),
        PendingSyscall::InheritedTerminalProbe => {}
        PendingSyscall::Open { path, .. }
        | PendingSyscall::Metadata { path }
        | PendingSyscall::SymlinkMetadata { path }
        | PendingSyscall::Access { path, .. }
        | PendingSyscall::Chdir { path }
        | PendingSyscall::ExecAttempt { path }
            if errno == libc::ENOENT as i64 || errno == libc::ENOTDIR as i64 =>
        {
            collector.push(
                pid,
                Effect::Read(ReadEffect::FileMetadata(FileMetadataRead {
                    path,
                    fingerprint: Some(tracejit_effects::FileFingerprint::absent()),
                    audited_toolchain: audited_toolchain(pid).is_some(),
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
                        audited_toolchain: audited_toolchain(pid).is_some(),
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
        PendingSyscall::Access { path, mode, flags } => collector.push(
            pid,
            Effect::Read(ReadEffect::Access(tracejit_effects::AccessCheck {
                path,
                mode,
                flags,
                errno: Some(errno as i32),
                credential: credential_identity(pid.as_raw() as u32),
            })),
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
        PendingSyscall::FsStats { path, source, .. } => collector.push(
            pid,
            Effect::Read(ReadEffect::FilesystemStats(FilesystemStatsRead {
                fingerprint: fingerprint(&path).ok(),
                path,
                source,
                stats: None,
                errno: Some(errno as i32),
                credential: credential_identity(pid.as_raw() as u32),
                mount_namespace: namespace_identity(pid.as_raw() as u32),
            })),
        ),
        PendingSyscall::Enumerate { path, .. } => collector.push(
            pid,
            Effect::Unknown(UnknownEffect {
                syscall: Some(libc::SYS_getdents64),
                detail: format!(
                    "directory enumeration of {} failed with errno {errno}",
                    path.display()
                ),
            }),
        ),
        // A failed seek leaves the description exactly where it was. The program observed the
        // errno, and that observation is already reflected in the cached output; there is no
        // caller-visible offset change to reproduce.
        PendingSyscall::Seek { .. } => {}
        PendingSyscall::Read { fd, .. } | PendingSyscall::Write { fd, .. } => collector.push(
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

/// The runtime-internal call site a controlled-entropy contract may answer.
struct EntropySite {
    library: PathBuf,
    library_hash: tracejit_effects::Hash,
    build_id: String,
    site_offset: u64,
    destination_offset: u64,
}

struct AddressMapping {
    start: u64,
    end: u64,
    offset: u64,
    permissions: String,
    path: PathBuf,
}

/// Decides whether a `getrandom(8, GRND_NONBLOCK)` call is the runtime's own allocator probe.
///
/// The contract's whole justification is that the value never reaches an application buffer. That
/// is checked mechanically, not assumed: the instruction pointer and the destination must lie in
/// the *same* shared library, the destination must be in that library's private writable data, and
/// the issuing module must not be the program itself (where runtime and application code share one
/// address space and the check could not tell them apart).
fn allocator_entropy_site(pid: Pid, ip: u64, buffer: u64) -> Option<EntropySite> {
    fn refuse() -> Option<EntropySite> {
        None
    }
    let Some(maps) = fs::read_to_string(format!("/proc/{}/maps", pid.as_raw())).ok() else {
        return refuse();
    };
    let mut mappings = Vec::new();
    for line in maps.lines() {
        let mut fields = line.splitn(6, ' ');
        let (Some(range), Some(permissions), Some(offset), Some(_device), Some(_inode)) = (
            fields.next(),
            fields.next(),
            fields.next(),
            fields.next(),
            fields.next(),
        ) else {
            return refuse();
        };
        let Ok(offset) = u64::from_str_radix(offset, 16) else {
            return refuse();
        };
        let path = PathBuf::from(fields.next().unwrap_or_default().trim_start());
        let Some((start, end)) = range.split_once('-') else {
            return refuse();
        };
        let (Ok(start), Ok(end)) = (u64::from_str_radix(start, 16), u64::from_str_radix(end, 16))
        else {
            return refuse();
        };
        mappings.push(AddressMapping {
            start,
            end,
            offset,
            permissions: permissions.to_string(),
            path,
        });
    }
    let Some(code) = mappings
        .iter()
        .find(|mapping| ip >= mapping.start && ip < mapping.end)
    else {
        return refuse();
    };
    if !code.permissions.starts_with("r-x") || !code.path.is_absolute() {
        return refuse();
    }
    let Ok(executable) = fs::read_link(format!("/proc/{}/exe", pid.as_raw())) else {
        return refuse();
    };
    if code.path == executable {
        return refuse();
    }
    let Some(data) = mappings
        .iter()
        .find(|mapping| buffer >= mapping.start && buffer < mapping.end)
    else {
        return refuse();
    };
    if !data.permissions.starts_with("rw") || data.permissions.contains('s') {
        return refuse();
    }
    let Some(base) = code.start.checked_sub(code.offset) else {
        return refuse();
    };
    let Some(site_offset) = ip.checked_sub(base) else {
        return refuse();
    };
    let Some(destination_offset) = buffer.checked_sub(base) else {
        return refuse();
    };
    // Beyond being in the library's writable segment, the address must be the offset the audited
    // build uses for its allocator key. The loader maps the tail of that segment (`.bss`, where
    // glibc keeps its tcache key) anonymously, so a pathname comparison is not enough; the ELF
    // layout and the audited offset together are.
    match library_writable_data_contains(&code.path, destination_offset) {
        Some(true) => {}
        Some(false) => return refuse(),
        None => return refuse(),
    }
    // The call site profile is the admission rule: one exact runtime build, one exact instruction
    // offset, one exact destination offset, and the audited instruction bytes. A different library
    // that happens to request eight non-blocking bytes into its own data does not match, and an
    // unknown build of the same library is refused rather than assumed equivalent.
    let Some(build_id) = tracejit_effects::elf_build_id(&code.path) else {
        return refuse();
    };
    let Some(profile) = tracejit_effects::allocator_entropy_profile(&build_id) else {
        return refuse();
    };
    if site_offset != profile.site_offset || destination_offset != profile.destination_offset {
        return refuse();
    }
    let Ok(library_bytes) = fs::read(&code.path) else {
        return refuse();
    };
    // The signature covers the `syscall` instruction and what follows it; the reported stop is
    // two bytes past the instruction.
    let signature_start = profile.site_offset.saturating_sub(2) as usize;
    if library_bytes.get(signature_start..signature_start + profile.site_signature.len())
        != Some(profile.site_signature)
    {
        return refuse();
    }
    let Ok(library_hash) = hash_file(&code.path) else {
        return refuse();
    };
    Some(EntropySite {
        library: code.path.clone(),
        library_hash,
        build_id,
        site_offset,
        destination_offset,
    })
}

/// Whether `offset` falls inside a `PT_LOAD` segment that the library maps writable.
///
/// `offset` is relative to the library's load base, which is the same coordinate space as the ELF
/// program headers' virtual addresses.
fn library_writable_data_contains(library: &Path, offset: u64) -> Option<bool> {
    let bytes = fs::read(library).ok()?;
    if bytes.len() < 64 || &bytes[..4] != b"\x7fELF" || bytes[4] != 2 || bytes[5] != 1 {
        return None;
    }
    let read_u16 = |at: usize| -> Option<u16> {
        bytes
            .get(at..at + 2)
            .map(|slice| u16::from_le_bytes([slice[0], slice[1]]))
    };
    let read_u32 = |at: usize| -> Option<u32> {
        bytes
            .get(at..at + 4)
            .map(|slice| u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
    };
    let read_u64 = |at: usize| -> Option<u64> {
        bytes.get(at..at + 8).map(|slice| {
            u64::from_le_bytes([
                slice[0], slice[1], slice[2], slice[3], slice[4], slice[5], slice[6], slice[7],
            ])
        })
    };
    let program_offset = read_u64(0x20)? as usize;
    let entry_size = read_u16(0x36)? as usize;
    let entry_count = read_u16(0x38)? as usize;
    let mut found = false;
    for index in 0..entry_count {
        let at = program_offset.checked_add(index.checked_mul(entry_size)?)?;
        let kind = read_u32(at)?;
        let flags = read_u32(at + 4)?;
        let virtual_address = read_u64(at + 16)?;
        let memory_size = read_u64(at + 40)?;
        if kind == 1 && flags & 0x2 != 0 {
            found = true;
            if offset >= virtual_address && offset < virtual_address.saturating_add(memory_size) {
                return Some(true);
            }
        }
    }
    Some(!found)
}

/// Writes into the tracee's address space without assuming word-sized alignment.
fn controlled_runtime_payload(
    observation: ControlledRuntimeObservation,
    value: u64,
    length: u32,
) -> Result<Vec<u8>, TraceError> {
    match observation {
        ControlledRuntimeObservation::GetrusageSelf
        | ControlledRuntimeObservation::ClockMonotonic
        | ControlledRuntimeObservation::ClockRealtime => Ok(vec![0_u8; length as usize]),
        ControlledRuntimeObservation::SysinfoMemory => {
            // SAFETY: an all-zero `struct sysinfo` is valid; every field is an integer. The
            // contract fixes the fields `cc1` consults and leaves the rest zero.
            let mut info: libc::sysinfo = unsafe { std::mem::zeroed() };
            info.totalram = value as libc::c_ulong;
            info.freeram = tracejit_effects::COMPILER_RUNTIME_SYSINFO_FREERAM as libc::c_ulong;
            info.procs = 1;
            info.mem_unit = 1;
            // SAFETY: `info` is a live local with no padding read here; the slice covers exactly
            // its initialized bytes and is copied before `info` goes out of scope.
            let bytes = unsafe {
                std::slice::from_raw_parts(
                    (&info as *const libc::sysinfo).cast::<u8>(),
                    std::mem::size_of::<libc::sysinfo>(),
                )
            };
            if bytes.len() != length as usize {
                return Err(TraceError::Ptrace(format!(
                    "sysinfo payload is {} bytes, contract records {length}",
                    bytes.len()
                )));
            }
            Ok(bytes.to_vec())
        }
    }
}

/// Returns the audited identity of a process executable, or `None` to fail closed.
fn compiler_observation(
    pid: Pid,
    observation: ControlledRuntimeObservation,
) -> Option<(PathBuf, tracejit_effects::Hash, String)> {
    let executable = fs::read_link(format!("/proc/{}/exe", pid.as_raw())).ok()?;
    let build_id = cached_build_id(&executable)?;
    let profile = tracejit_effects::compiler_runtime_profile(&executable, &build_id)?;
    if !profile.allows(observation) {
        return None;
    }
    let executable_hash = cached_executable_hash(&executable)?;
    Some((executable, executable_hash, build_id))
}

fn audited_toolchain(pid: Pid) -> Option<(PathBuf, String)> {
    let executable = fs::read_link(format!("/proc/{}/exe", pid.as_raw())).ok()?;
    let build_id = cached_build_id(&executable)?;
    tracejit_effects::compiler_runtime_profile(&executable, &build_id)?;
    Some((executable, build_id))
}

/// Reads each binary's GNU build ID once per trace instead of once per observation.
fn cached_build_id(path: &Path) -> Option<String> {
    static IDS: std::sync::OnceLock<Mutex<HashMap<PathBuf, Option<String>>>> =
        std::sync::OnceLock::new();
    let ids = IDS.get_or_init(|| Mutex::new(HashMap::new()));
    if let Some(id) = ids.lock().ok()?.get(path) {
        return id.clone();
    }
    let id = tracejit_effects::elf_build_id(path);
    ids.lock().ok()?.insert(path.to_path_buf(), id.clone());
    id
}

/// Hashes each compiler binary once per trace; the guard re-hashes it at every reuse.
fn cached_executable_hash(path: &Path) -> Option<tracejit_effects::Hash> {
    static HASHES: std::sync::OnceLock<Mutex<HashMap<PathBuf, tracejit_effects::Hash>>> =
        std::sync::OnceLock::new();
    let hashes = HASHES.get_or_init(|| Mutex::new(HashMap::new()));
    if let Some(hash) = hashes.lock().ok()?.get(path).copied() {
        return Some(hash);
    }
    let hash = hash_file(path).ok()?;
    hashes.lock().ok()?.insert(path.to_path_buf(), hash);
    Some(hash)
}

fn write_process_bytes(pid: Pid, address: u64, bytes: &[u8]) -> Result<(), TraceError> {
    let local = libc::iovec {
        iov_base: bytes.as_ptr() as *mut libc::c_void,
        iov_len: bytes.len(),
    };
    let remote = libc::iovec {
        iov_base: address as *mut libc::c_void,
        iov_len: bytes.len(),
    };
    // SAFETY: `bytes` is a live local slice and the remote address is the buffer the tracee
    // passed to `getrandom`, inside its own address space.
    let written = unsafe { libc::process_vm_writev(pid.as_raw(), &local, 1, &remote, 1, 0) };
    if written == bytes.len() as isize {
        return Ok(());
    }
    for (index, chunk) in bytes.chunks(std::mem::size_of::<u64>()).enumerate() {
        let mut word = [0_u8; 8];
        word[..chunk.len()].copy_from_slice(chunk);
        ptrace::write(
            pid,
            (address as usize + index * 8) as ptrace::AddressType,
            u64::from_ne_bytes(word) as libc::c_long,
        )
        .map_err(ptrace_error)?;
    }
    Ok(())
}

fn resolution_for_fd(state: &ProcessState, fd: i32) -> Option<PathBuf> {
    match state.fds.get(&fd) {
        Some(FdState::File(path)) | Some(FdState::InheritedFile(path)) => Some(path.clone()),
        _ => None,
    }
}

/// A short or failed read is treated as uninspectable, so the caller refuses rather than guesses.
fn read_tracee_bytes(pid: Pid, address: u64, length: usize) -> Option<Vec<u8>> {
    if address == 0 {
        return None;
    }
    let mut buffer = vec![0u8; length];
    let local = libc::iovec {
        iov_base: buffer.as_mut_ptr().cast(),
        iov_len: length,
    };
    let remote = libc::iovec {
        iov_base: address as *mut libc::c_void,
        iov_len: length,
    };
    let read = unsafe { libc::process_vm_readv(pid.as_raw(), &local, 1, &remote, 1, 0) };
    if read == length as isize {
        Some(buffer)
    } else {
        None
    }
}

/// A null times pointer means "now", and `UTIME_NOW` in either field does the same.
fn utimensat_uses_wall_clock(pid: Pid, times: u64) -> bool {
    let Some(bytes) = read_tracee_bytes(pid, times, 32) else {
        return true;
    };
    (0..2).any(|index| {
        let offset = index * 16 + 8;
        let nsec = i64::from_ne_bytes(bytes[offset..offset + 8].try_into().expect("timespec"));
        nsec == libc::UTIME_NOW
    })
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

/// Removes `.` components and keeps the pathname otherwise verbatim, `..` included.
///
/// The dependency record must keep the pathname the process actually passed to the kernel. Two
/// things then fall out of replaying that pathname instead of a rewrite of it:
///
/// - `a/symlink/../b` is not `a/b` when `symlink` is a link: the kernel follows the link first and
///   resolves `..` afterwards. Substituting the canonical target (`be94f38`) discards the symlink
///   components, so repointing the link is invisible to the guard and the cache replays bytes a
///   native run would no longer read. That is a false hit, and the regression tests
///   `a_repointed_symlink_before_dotdot_is_never_a_cache_hit` and its chain variant keep it out.
/// - The observed target is still pinned exactly, and more strongly than by its name: every read
///   dependency carries the target's content hash and a fingerprint with device and inode.
///
/// Keeping the pathname is therefore what preserves the resolution evidence: the guard asks the
/// kernel the same question the program asked, so every condition that made the pathname resolve
/// to the recorded inode is re-evaluated. Only `.` is removed, because the kernel ignores it.
fn normalize(path: PathBuf) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
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
        // Linux appends " (deleted)" when the directory entry is gone but the open file
        // description remains. That string is not a resolvable pathname, so treating it as
        // InheritedFile would invent a path identity the kernel does not use on replay.
        Ok(path) if path.is_absolute() && path_is_live_pathname(&path) => {
            FdState::InheritedFile(path)
        }
        Ok(path) if path.to_string_lossy().starts_with("socket:") => FdState::Network,
        _ => FdState::Other,
    }
}

/// `/proc/<pid>/fd/<n>` pathnames that still name a directory entry.
fn path_is_live_pathname(path: &Path) -> bool {
    !path.as_os_str().as_encoded_bytes().ends_with(b" (deleted)")
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

/// Upper bound on the entry bytes kept in one cache record.
///
/// A record has to stay replayable and reasonably sized; a directory larger than this refuses
/// the execution instead of silently keeping a prefix of the stream.
const MAX_ENUMERATION_BYTES: usize = 1 << 20;

/// Parses the kernel's 120-byte `struct statfs` layout on x86_64.
fn statfs_from_words(words: &[i64; 15]) -> tracejit_effects::FilesystemStats {
    tracejit_effects::FilesystemStats {
        f_type: words[0],
        f_bsize: words[1],
        f_blocks: words[2] as u64,
        f_bfree: words[3] as u64,
        f_bavail: words[4] as u64,
        f_files: words[5] as u64,
        f_ffree: words[6] as u64,
        f_fsid: [words[7] as u32 as i32, (words[7] >> 32) as u32 as i32],
        f_namelen: words[8],
        f_frsize: words[9],
        f_flags: words[10],
        f_spare: [words[11], words[12], words[13], words[14]],
    }
}

/// Reads the file position a descriptor currently holds from `/proc/<pid>/fdinfo`.
fn fd_position(pid: Pid, fd: i32) -> Option<u64> {
    let info = fs::read_to_string(format!("/proc/{}/fdinfo/{fd}", pid.as_raw())).ok()?;
    info.lines()
        .find_map(|line| line.strip_prefix("pos:")?.trim().parse().ok())
}

/// Captures the contract of an inherited regular-file stdin before the program runs.
///
/// Only a regular file whose descriptor target is still reachable at the same path is admitted.
/// Pipes, sockets, terminals and unknown descriptors keep the conservative refusal.
/// Classifies every inherited descriptor from /proc, not only fds 0..2.
///
/// An inherited regular file on any descriptor is `InheritedFile`, and a read from one is refused
/// unless its offset contract is modelled. Only stdin is modelled, so classifying all descriptors
/// makes an inherited file on fd 3 fail closed instead of being treated as an ordinary open read.
fn initial_descriptor_table(pid: Pid) -> std::io::Result<HashMap<i32, FdState>> {
    let mut fds = HashMap::new();
    // An incomplete table cannot establish that no extra descriptor was inherited. Return the
    // error instead of silently modelling only stdin/stdout/stderr.
    for entry in fs::read_dir(format!("/proc/{}/fd", pid.as_raw()))? {
        let entry = entry?;
        if let Some(fd) = entry
            .file_name()
            .to_str()
            .and_then(|name| name.parse::<i32>().ok())
        {
            if fd >= 0 {
                fds.insert(fd, inherited_fd_state(pid, fd));
            }
        }
    }
    for fd in 0..=2 {
        fds.entry(fd).or_insert_with(|| inherited_fd_state(pid, fd));
    }
    Ok(fds)
}

/// Finds another descriptor of the same process that refers to the same open file description as
/// stdin. `kcmp` is unavailable on this kernel, so equal device, inode and position are used as the
/// conservative signature: an independent open at exactly the same position is refused too.
fn stdin_descriptor_alias(pid: Pid) -> Option<i32> {
    use std::os::unix::fs::MetadataExt;
    let stdin = fs::metadata(format!("/proc/{}/fd/0", pid.as_raw())).ok()?;
    if !stdin.is_file() {
        return None;
    }
    let position = fd_position(pid, 0)?;
    let entries = fs::read_dir(format!("/proc/{}/fd", pid.as_raw())).ok()?;
    let mut candidates = entries
        .flatten()
        .filter_map(|entry| {
            let fd = entry.file_name().to_str()?.parse::<i32>().ok()?;
            (fd > 0).then(|| (fd, entry.path()))
        })
        .collect::<Vec<_>>();
    candidates.sort_by_key(|(fd, _)| *fd);
    candidates.into_iter().find_map(|(fd, path)| {
        let metadata = fs::metadata(&path).ok()?;
        (metadata.is_file()
            && metadata.dev() == stdin.dev()
            && metadata.ino() == stdin.ino()
            && fd_position(pid, fd) == Some(position))
        .then_some(fd)
    })
}

/// Compares the kernel's position for the shared description with the model's prediction. A
/// mismatch means something moved the description outside the operations being replayed (another
/// process or an alias this run did not observe), so the stream is withdrawn and reuse is refused.
fn verify_stdin_position(pid: Pid, state: &mut ProcessState, collector: &mut Collector) {
    let Some(stream) = state.stdin_stream.as_ref() else {
        return;
    };
    let expected = stream.end_offset;
    // A process may close stdin before exiting, which does not move the description. Absence of
    // the descriptor is therefore not a mismatch; a present descriptor whose offset differs is.
    let Some(observed) = fd_position(pid, 0) else {
        return;
    };
    if observed == expected {
        return;
    }
    let detail = format!(
        "inherited stdin position is {observed:?} but the model expected {expected}; the shared open file description moved outside the modelled reads and seeks"
    );
    state.stdin_stream = None;
    collector.push(
        pid,
        Effect::Unknown(UnknownEffect {
            syscall: None,
            detail,
        }),
    );
}

fn initial_inherited_stream(pid: Pid) -> Option<InheritedStreamState> {
    let link = format!("/proc/{}/fd/0", pid.as_raw());
    let path = fs::read_link(&link).ok()?;
    if !path.is_absolute() || path == Path::new("/dev/null") {
        return None;
    }
    let metadata = fs::metadata(&link).ok()?;
    if !metadata.is_file() {
        return None;
    }
    let expected = fingerprint(Path::new(&link)).ok()?;
    // The path must still name the inode the descriptor refers to, otherwise a replay by path
    // would hash a different file than the one the program will read.
    let named = fingerprint(&path).ok()?;
    if named.device != expected.device || named.inode != expected.inode {
        return None;
    }
    let hash = hash_file(Path::new(&link)).ok()?;
    let start_offset = fd_position(pid, 0)?;
    Some(InheritedStreamState {
        path,
        hash,
        fingerprint: expected,
        start_offset,
        end_offset: start_offset,
        bytes_read: 0,
        effect_index: None,
    })
}

fn is_known_internal_syscall(number: i64) -> bool {
    matches!(
        number,
        libc::SYS_lseek
            | libc::SYS_fadvise64
            | libc::SYS_brk
            | libc::SYS_umask
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
        | PendingSyscall::Access { path, .. }
        | PendingSyscall::Chdir { path }
        | PendingSyscall::ExecAttempt { path }
        | PendingSyscall::CreateDirectory { path }
        | PendingSyscall::MetadataWrite { path }
        | PendingSyscall::Delete { path, .. } => path.display().to_string(),
        PendingSyscall::Rename { from, to, .. } => {
            format!("rename {} to {}", from.display(), to.display())
        }
        PendingSyscall::Network { .. } => "network operation".into(),
        PendingSyscall::Unknown { number, detail } => format!("syscall {number}: {detail}"),
        PendingSyscall::Read { fd, .. } => format!("read from fd {fd}"),
        PendingSyscall::Seek { fd } => format!("seek on fd {fd}"),
        PendingSyscall::Write { fd, .. } => format!("write to fd {fd}"),
        PendingSyscall::Pipe { .. } => "pipe creation".into(),
        PendingSyscall::Signal { signal, target } => {
            format!("signal {signal} to process {target}")
        }
        PendingSyscall::Clock { .. } => "clock read".into(),
        PendingSyscall::Random => "randomness read".into(),
        PendingSyscall::ControlledRandom { .. } => "controlled allocator entropy".into(),
        PendingSyscall::ControlledRuntime { .. } => "controlled runtime observation".into(),
        PendingSyscall::KernelState { kind } => format!("kernel state read: {kind:?}"),
        PendingSyscall::Mmap { .. } => "file-backed mmap".into(),
        PendingSyscall::Mprotect { .. } => "mprotect".into(),
        PendingSyscall::Munmap { .. } => "munmap".into(),
        PendingSyscall::Mremap { .. } => "mremap".into(),
        PendingSyscall::FsStats { path, .. } => {
            format!("filesystem statistics for {}", path.display())
        }
        PendingSyscall::Enumerate { path, .. } => {
            format!("directory enumeration of {}", path.display())
        }
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

    fn collector() -> Collector {
        Collector {
            sequence: 0,
            effects: Vec::new(),
            dependencies: Vec::new(),
            pipes: HashMap::new(),
            next_pipe: 0,
        }
    }

    #[test]
    fn reusing_a_descriptor_forgets_its_directory_enumeration() {
        let mut state = ProcessState {
            cwd: PathBuf::from("/"),
            fds: HashMap::new(),
            close_on_exec: HashSet::new(),
            entering: false,
            synchronize_on_next_syscall: false,
            pending: None,
            file_mappings: Vec::new(),
            enumerations: HashMap::new(),
            stdin_stream: None,
            vdso_disarmed: false,
        };
        state.fds.insert(7, FdState::File(PathBuf::from("/tmp")));
        state.close_on_exec.insert(7);
        state.enumerations.insert(
            7,
            EnumerationState {
                fingerprint: tracejit_effects::FileFingerprint::absent(),
                credential: None,
                mount_namespace: None,
                bytes: 48,
                effect_index: Some(3),
                refused: false,
            },
        );
        forget_descriptor(&mut state, 7);
        assert!(!state.fds.contains_key(&7));
        assert!(!state.close_on_exec.contains(&7));
        assert!(!state.enumerations.contains_key(&7));
    }

    #[test]
    fn descriptor_reuse_through_close_open_socket_and_pipe_forgets_enumeration() {
        let pid = Pid::from_raw(1);
        let make_state = || {
            let mut state = ProcessState {
                cwd: PathBuf::from("/"),
                fds: HashMap::new(),
                close_on_exec: HashSet::new(),
                entering: false,
                synchronize_on_next_syscall: false,
                pending: None,
                file_mappings: Vec::new(),
                enumerations: HashMap::new(),
                stdin_stream: None,
                vdso_disarmed: false,
            };
            state.fds.insert(7, FdState::File(PathBuf::from("/tmp")));
            state.enumerations.insert(
                7,
                EnumerationState {
                    fingerprint: tracejit_effects::FileFingerprint::absent(),
                    credential: None,
                    mount_namespace: None,
                    bytes: 48,
                    effect_index: Some(3),
                    refused: false,
                },
            );
            state
        };

        let mut close = make_state();
        complete_syscall(
            pid,
            &mut close,
            PendingSyscall::Close { fd: 7 },
            0,
            &mut collector(),
        );
        assert!(!close.enumerations.contains_key(&7));

        let mut open = make_state();
        complete_syscall(
            pid,
            &mut open,
            PendingSyscall::Open {
                path: PathBuf::from("/tmp/file"),
                flags: libc::O_RDONLY,
                before_hash: None,
                before_fingerprint: None,
            },
            7,
            &mut collector(),
        );
        assert!(!open.enumerations.contains_key(&7));

        let mut socket = make_state();
        complete_syscall(
            pid,
            &mut socket,
            PendingSyscall::Network {
                kind: NetworkOperation::Socket,
            },
            7,
            &mut collector(),
        );
        assert!(!socket.enumerations.contains_key(&7));

        let mut pipe = make_state();
        record_pipe(&mut pipe, 7, 8, false, &mut collector());
        assert!(!pipe.enumerations.contains_key(&7));
        assert!(!pipe.enumerations.contains_key(&8));
        assert!(matches!(
            pipe.fds.get(&7),
            Some(FdState::InternalPipe { .. })
        ));
        assert!(matches!(
            pipe.fds.get(&8),
            Some(FdState::InternalPipe { .. })
        ));
    }

    #[test]
    fn dup2_same_descriptor_preserves_file_directory_pipe_and_cloexec_state() {
        let pid = Pid::from_raw(1);

        let mut file = ProcessState {
            cwd: PathBuf::from("/"),
            fds: HashMap::new(),
            close_on_exec: HashSet::new(),
            entering: false,
            synchronize_on_next_syscall: false,
            pending: None,
            file_mappings: Vec::new(),
            enumerations: HashMap::new(),
            stdin_stream: None,
            vdso_disarmed: false,
        };
        file.fds
            .insert(7, FdState::File(PathBuf::from("/tmp/file")));
        file.close_on_exec.insert(7);
        complete_syscall(
            pid,
            &mut file,
            PendingSyscall::Dup {
                source: 7,
                destination: Some(7),
                close_on_exec: false,
            },
            7,
            &mut collector(),
        );
        assert!(matches!(
            file.fds.get(&7),
            Some(FdState::File(path)) if path == Path::new("/tmp/file")
        ));
        assert!(file.close_on_exec.contains(&7));

        let mut directory = ProcessState {
            cwd: PathBuf::from("/"),
            fds: HashMap::new(),
            close_on_exec: HashSet::new(),
            entering: false,
            synchronize_on_next_syscall: false,
            pending: None,
            file_mappings: Vec::new(),
            enumerations: HashMap::new(),
            stdin_stream: None,
            vdso_disarmed: false,
        };
        directory
            .fds
            .insert(7, FdState::File(PathBuf::from("/tmp")));
        directory.enumerations.insert(
            7,
            EnumerationState {
                fingerprint: tracejit_effects::FileFingerprint::absent(),
                credential: None,
                mount_namespace: None,
                bytes: 48,
                effect_index: Some(3),
                refused: false,
            },
        );
        complete_syscall(
            pid,
            &mut directory,
            PendingSyscall::Dup {
                source: 7,
                destination: Some(7),
                close_on_exec: false,
            },
            7,
            &mut collector(),
        );
        assert!(directory.fds.contains_key(&7));
        assert_eq!(directory.enumerations.get(&7).unwrap().bytes, 48);

        let mut pipe = ProcessState {
            cwd: PathBuf::from("/"),
            fds: HashMap::new(),
            close_on_exec: HashSet::new(),
            entering: false,
            synchronize_on_next_syscall: false,
            pending: None,
            file_mappings: Vec::new(),
            enumerations: HashMap::new(),
            stdin_stream: None,
            vdso_disarmed: false,
        };
        pipe.fds.insert(
            7,
            FdState::InternalPipe {
                pipe: 3,
                readable: true,
                writable: false,
            },
        );
        complete_syscall(
            pid,
            &mut pipe,
            PendingSyscall::Dup {
                source: 7,
                destination: Some(7),
                close_on_exec: false,
            },
            7,
            &mut collector(),
        );
        assert!(matches!(
            pipe.fds.get(&7),
            Some(FdState::InternalPipe {
                pipe: 3,
                readable: true,
                writable: false
            })
        ));
    }

    #[test]
    fn ordinary_duplicates_still_replace_destination_and_reset_cloexec() {
        let pid = Pid::from_raw(1);
        for (label, destination, result, close_on_exec) in [
            ("dup", None, 9, false),
            ("dup2", Some(8), 8, false),
            ("dup3", Some(8), 8, true),
            ("fcntl", None, 9, true),
        ] {
            let mut state = ProcessState {
                cwd: PathBuf::from("/"),
                fds: HashMap::new(),
                close_on_exec: HashSet::new(),
                entering: false,
                synchronize_on_next_syscall: false,
                pending: None,
                file_mappings: Vec::new(),
                enumerations: HashMap::new(),
                stdin_stream: None,
                vdso_disarmed: false,
            };
            state.fds.insert(7, FdState::File(PathBuf::from("/source")));
            let reused = destination.unwrap_or(result as i32);
            state
                .fds
                .insert(reused, FdState::File(PathBuf::from("/destination")));
            state.close_on_exec.insert(reused);
            state.enumerations.insert(
                7,
                EnumerationState {
                    fingerprint: tracejit_effects::FileFingerprint::absent(),
                    credential: None,
                    mount_namespace: None,
                    bytes: 16,
                    effect_index: None,
                    refused: false,
                },
            );
            state.enumerations.insert(
                reused,
                EnumerationState {
                    fingerprint: tracejit_effects::FileFingerprint::absent(),
                    credential: None,
                    mount_namespace: None,
                    bytes: 16,
                    effect_index: None,
                    refused: false,
                },
            );
            complete_syscall(
                pid,
                &mut state,
                PendingSyscall::Dup {
                    source: 7,
                    destination,
                    close_on_exec,
                },
                result,
                &mut collector(),
            );
            assert!(
                matches!(
                    state.fds.get(&reused),
                    Some(FdState::File(path)) if path == Path::new("/source")
                ),
                "{label}: destination was not replaced"
            );
            assert_eq!(
                state.close_on_exec.contains(&reused),
                close_on_exec,
                "{label}: destination CLOEXEC"
            );
            assert!(
                !state.enumerations.contains_key(&7),
                "{label}: source enumeration survived the duplicate"
            );
            assert!(
                !state.enumerations.contains_key(&reused),
                "{label}: destination enumeration survived the duplicate"
            );
        }
    }

    #[test]
    fn normalize_keeps_parent_components_so_links_resolve_like_the_kernel() {
        // `..` after a symlink is resolved by the kernel from the link target, so collapsing it
        // lexically would record a different file than the one the process read.
        assert_eq!(
            normalize(PathBuf::from("/a/link/../b")),
            PathBuf::from("/a/link/../b")
        );
        assert_eq!(normalize(PathBuf::from("/a/./b")), PathBuf::from("/a/b"));
    }

    #[test]
    fn a_scheduler_stable_pipe_transfer_is_not_an_effect() {
        let mut collector = collector();
        let pipe = collector.open_pipe();
        let pid = Pid::from_raw(1);
        collector.pipe_write(pid, pipe, Some(9), 9);
        collector.pipe_read(pid, pipe, Some(64), 9);
        collector.flush_pipes();
        assert!(collector.effects.is_empty());
    }

    #[test]
    fn a_short_read_followed_by_more_data_refuses_reuse() {
        let mut collector = collector();
        let pipe = collector.open_pipe();
        let pid = Pid::from_raw(1);
        collector.pipe_read(pid, pipe, Some(64), 4);
        collector.pipe_write(pid, pipe, Some(4), 4);
        collector.flush_pipes();
        assert_eq!(collector.effects.len(), 1);
        assert!(matches!(collector.effects[0].effect, Effect::Unknown(_)));
    }

    #[test]
    fn a_short_read_before_end_of_file_stays_stable() {
        let mut collector = collector();
        let pipe = collector.open_pipe();
        let pid = Pid::from_raw(1);
        collector.pipe_read(pid, pipe, Some(64), 9);
        collector.pipe_read(pid, pipe, Some(64), 0);
        collector.flush_pipes();
        assert!(collector.effects.is_empty());
    }

    #[test]
    fn two_writers_make_byte_order_scheduling_dependent() {
        let mut collector = collector();
        let pipe = collector.open_pipe();
        collector.pipe_write(Pid::from_raw(1), pipe, Some(1), 1);
        collector.pipe_write(Pid::from_raw(2), pipe, Some(1), 1);
        collector.flush_pipes();
        assert_eq!(collector.effects.len(), 1);
    }

    #[test]
    fn a_partial_write_refuses_reuse() {
        let mut collector = collector();
        let pipe = collector.open_pipe();
        collector.pipe_write(Pid::from_raw(1), pipe, Some(8), 3);
        collector.flush_pipes();
        assert_eq!(collector.effects.len(), 1);
    }

    #[test]
    fn an_untracked_vectored_transfer_refuses_reuse() {
        let mut collector = collector();
        let pipe = collector.open_pipe();
        collector.pipe_write(Pid::from_raw(1), pipe, None, 4);
        collector.flush_pipes();
        assert_eq!(collector.effects.len(), 1);
    }

    fn shared_read_only() -> FileMapping {
        FileMapping {
            start: 0x1000,
            end: 0x2000,
            shared: true,
            writable: false,
        }
    }

    #[test]
    fn deleted_proc_fd_pathname_is_not_treated_as_a_live_path() {
        assert!(!path_is_live_pathname(Path::new("/tmp/input (deleted)")));
        assert!(path_is_live_pathname(Path::new("/tmp/input")));
        assert!(path_is_live_pathname(Path::new("/tmp/input(deleted)")));
    }

    #[test]
    fn anonymous_shared_mmap_flags_are_refused() {
        let flags = libc::MAP_SHARED as u64 | libc::MAP_ANONYMOUS as u64;
        assert!(flags & libc::MAP_SHARED as u64 != 0);
        assert!(flags & libc::MAP_ANONYMOUS as u64 != 0);
        // Private anonymous mappings remain process-internal; only the shared bit is refused.
        let private = libc::MAP_PRIVATE as u64 | libc::MAP_ANONYMOUS as u64;
        assert_eq!(private & libc::MAP_SHARED as u64, 0);
    }

    /// The identity hash is sampled before tracing. If the path no longer matches it, the tracer
    /// must refuse rather than file the run's profile under an identity that did not produce it.
    #[test]
    fn refuses_to_trace_an_executable_that_no_longer_matches_its_identity() {
        let executable = std::env::current_exe().unwrap();
        let request = TraceRequest {
            executable: executable.clone(),
            argv: vec![executable.clone().into_os_string()],
            cwd: std::env::current_dir().unwrap(),
            environment: std::collections::BTreeMap::new(),
            expected_executable_hash: Some(tracejit_effects::Hash::new([0xab; 32])),
            sandbox: None,
            contract: None,
        };
        match trace_command(request) {
            Err(TraceError::ExecutableChanged(_)) => {}
            other => panic!("expected the tracer to refuse, got {other:?}"),
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

#[cfg(test)]
mod phase3d_tests {
    use super::*;
    use std::os::unix::io::AsRawFd;

    #[test]
    fn null_device_identity_is_not_path_only() {
        let null = fs::File::open("/dev/null").unwrap();
        assert!(is_null_device_fd(Pid::this(), null.as_raw_fd()));
        let regular = fs::File::open("/etc/hosts").unwrap();
        assert!(!is_null_device_fd(Pid::this(), regular.as_raw_fd()));
        assert!(
            !is_null_device_fd(Pid::this(), 1_000_000),
            "an uninspectable descriptor must fail closed"
        );
    }
}

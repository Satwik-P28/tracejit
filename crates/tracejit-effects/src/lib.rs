use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fmt::{Display, Formatter};
use std::path::PathBuf;
use std::str::FromStr;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct Hash([u8; 32]);

impl Hash {
    pub const fn new(bytes: [u8; 32]) -> Self {
        Self(bytes)
    }

    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

impl Display for Hash {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        for byte in self.0 {
            write!(f, "{byte:02x}")?;
        }
        Ok(())
    }
}

#[derive(Debug, thiserror::Error)]
#[error("invalid BLAKE3 hash")]
pub struct ParseHashError;

impl FromStr for Hash {
    type Err = ParseHashError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        if value.len() != 64 {
            return Err(ParseHashError);
        }
        let mut bytes = [0_u8; 32];
        for (index, byte) in bytes.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
                .map_err(|_| ParseHashError)?;
        }
        Ok(Self(bytes))
    }
}

impl From<blake3::Hash> for Hash {
    fn from(value: blake3::Hash) -> Self {
        Self(*value.as_bytes())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum DeterminismClass {
    Proven,
    Guarded,
    EmpiricallyStable,
    Unknown,
    Nondeterministic,
}

impl DeterminismClass {
    pub const fn cache_eligible(self) -> bool {
        matches!(self, Self::Proven | Self::Guarded)
    }
}

impl Display for DeterminismClass {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        let value = match self {
            Self::Proven => "PROVEN",
            Self::Guarded => "GUARDED",
            Self::EmpiricallyStable => "EMPIRICALLY_STABLE",
            Self::Unknown => "UNKNOWN",
            Self::Nondeterministic => "NONDETERMINISTIC",
        };
        f.write_str(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Effect {
    Read(ReadEffect),
    Write(WriteEffect),
    Control(ControlEffect),
    Unknown(UnknownEffect),
}

impl Effect {
    pub fn properties(&self) -> EffectProperties {
        match self {
            Self::Read(ReadEffect::File(_))
            | Self::Read(ReadEffect::FileMetadata(_))
            | Self::Read(ReadEffect::DirectoryOpened(_))
            | Self::Read(ReadEffect::DirectoryEnumerated(_))
            | Self::Read(ReadEffect::FilesystemStats(_))
            | Self::Read(ReadEffect::InheritedStream(_))
            | Self::Read(ReadEffect::SymlinkMetadata(_))
            | Self::Read(ReadEffect::Symlink(_))
            | Self::Read(ReadEffect::Access(_))
            | Self::Read(ReadEffect::Environment(_))
            | Self::Read(ReadEffect::WorkingDirectory)
            | Self::Read(ReadEffect::KernelState(KernelStateRead::Hostname))
            | Self::Read(ReadEffect::KernelState(KernelStateRead::Identity)) => EffectProperties {
                observable: true,
                reversible: true,
                guardable: true,
                cache_key_relevant: true,
            },
            Self::Read(ReadEffect::ControlledEntropy(_)) => EffectProperties {
                observable: false,
                reversible: true,
                guardable: true,
                cache_key_relevant: true,
            },
            Self::Read(ReadEffect::Clock(_))
            | Self::Read(ReadEffect::Random(_))
            | Self::Read(ReadEffect::Network(_))
            | Self::Read(ReadEffect::KernelState(KernelStateRead::SystemInfo { .. }))
            | Self::Read(ReadEffect::KernelState(KernelStateRead::ProcessIdentity { .. })) => {
                EffectProperties {
                    observable: true,
                    reversible: false,
                    guardable: false,
                    cache_key_relevant: true,
                }
            }
            Self::Read(ReadEffect::KernelState(KernelStateRead::Proc(_))) => EffectProperties {
                observable: true,
                reversible: true,
                guardable: true,
                cache_key_relevant: true,
            },
            // Internal pipe traffic is a function of inputs that are already guarded, so it is
            // not a cache-key input of its own. The tracer refuses the execution when the
            // observed transfer was packetisation dependent.
            Self::Read(ReadEffect::Ipc(_)) => EffectProperties {
                observable: false,
                reversible: true,
                guardable: true,
                cache_key_relevant: false,
            },
            Self::Write(WriteEffect::File(_)) => EffectProperties {
                observable: true,
                reversible: true,
                guardable: false,
                cache_key_relevant: false,
            },
            Self::Control(ControlEffect::Spawn(_))
            | Self::Control(ControlEffect::Exec(_))
            | Self::Control(ControlEffect::Chdir(_)) => EffectProperties {
                observable: true,
                reversible: true,
                guardable: true,
                cache_key_relevant: true,
            },
            Self::Write(WriteEffect::Network(_))
            | Self::Write(WriteEffect::Ipc(_))
            | Self::Control(ControlEffect::Signal(_))
            | Self::Unknown(_) => EffectProperties {
                observable: true,
                reversible: false,
                guardable: false,
                cache_key_relevant: true,
            },
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EffectProperties {
    pub observable: bool,
    pub reversible: bool,
    pub guardable: bool,
    pub cache_key_relevant: bool,
}

/// The only controlled-execution contract this version implements.
pub const ALLOCATOR_ENTROPY_CONTRACT: &str = "tracejit.allocator-entropy.v1";

/// Bytes supplied for allocator-internal entropy under that contract.
///
/// The value is fixed so that a trace recorded under the contract can be reproduced exactly. It
/// never leaves the runtime's own allocator state: the tracer admits a call only when the
/// destination is a private writable mapping of the shared library that issued it.
pub const ALLOCATOR_ENTROPY_VALUE: u64 = 0x9e37_79b9_7f4a_7c15;

/// An audited runtime call site the allocator-entropy contract may answer.
///
/// A profile is not a pattern: it names one exact build and the exact offsets and instruction
/// bytes of its allocator probe. Any other library, build or call site is refused, even if its
/// memory layout looks similar.
#[derive(Clone, Copy, Debug)]
pub struct AllocatorEntropyProfile {
    /// GNU build ID of the runtime library, hex encoded (as `readelf -n` prints it).
    pub build_id: &'static str,
    /// Offset at which the tracer reports the syscall stop, relative to the library's load base.
    /// On x86-64 this is the byte after the two-byte `syscall` instruction.
    pub site_offset: u64,
    /// Offset of the runtime's `tcache_key` in its writable data, relative to the load base.
    pub destination_offset: u64,
    /// The audited bytes ending at `site_offset`, i.e. the `syscall` instruction and the
    /// instructions immediately after it.
    pub site_signature: &'static [u8],
}

/// The audited profiles. Only these builds are admitted.
///
/// The entry below was audited on Ubuntu 24.04 glibc 2.39: the `syscall` is at `libc+0xa9e87`,
/// execution resumes at `libc+0xa9e89`, the destination is `libc+0x20b178`, and the caller is
/// `ptmalloc_init` through `tcache_key_initialize`.
pub const ALLOCATOR_ENTROPY_PROFILES: &[AllocatorEntropyProfile] = &[AllocatorEntropyProfile {
    build_id: "a4a7992a8e66555c8141ab2a08a8465ff6e0ea65",
    site_offset: 0xa9e89,
    destination_offset: 0x20b178,
    site_signature: &[0x0f, 0x05, 0x48, 0x8d, 0x5d, 0xd0, 0x48, 0x83, 0xf8, 0x08],
}];

pub fn allocator_entropy_profile(build_id: &str) -> Option<&'static AllocatorEntropyProfile> {
    ALLOCATOR_ENTROPY_PROFILES
        .iter()
        .find(|profile| profile.build_id == build_id)
}

/// Reads the GNU build ID note of an ELF64 little-endian shared object.
///
/// The build ID is the identity a profile is keyed by. It is deliberately not derived from a
/// pathname or a mapping name: the same library can be mapped under many names, and a different
/// library can be mapped under the same one.
pub fn elf_build_id(path: &std::path::Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    if bytes.len() < 64 || &bytes[..4] != b"\x7fELF" || bytes[4] != 2 || bytes[5] != 1 {
        return None;
    }
    let u16_at = |at: usize| {
        bytes
            .get(at..at + 2)
            .map(|slice| u16::from_le_bytes([slice[0], slice[1]]))
    };
    let u32_at = |at: usize| {
        bytes
            .get(at..at + 4)
            .map(|slice| u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
    };
    let u64_at = |at: usize| -> Option<u64> {
        bytes.get(at..at + 8).map(|slice| {
            u64::from_le_bytes([
                slice[0], slice[1], slice[2], slice[3], slice[4], slice[5], slice[6], slice[7],
            ])
        })
    };
    let program_offset = u64_at(0x20)? as usize;
    let entry_size = u16_at(0x36)? as usize;
    let entry_count = u16_at(0x38)? as usize;
    for index in 0..entry_count {
        let at = program_offset.checked_add(index.checked_mul(entry_size)?)?;
        if u32_at(at)? != 4 {
            continue;
        }
        let offset = u64_at(at + 8)? as usize;
        let size = u64_at(at + 32)? as usize;
        let note = bytes.get(offset..offset.checked_add(size)?)?;
        let mut cursor = 0usize;
        while cursor + 12 <= note.len() {
            let word = |base: usize| -> Option<u32> {
                note.get(base..base + 4)
                    .map(|slice| u32::from_le_bytes([slice[0], slice[1], slice[2], slice[3]]))
            };
            let namesz = word(cursor)? as usize;
            let descsz = word(cursor + 4)? as usize;
            let kind = word(cursor + 8)?;
            let name_start = cursor + 12;
            let name_end = name_start.checked_add(namesz)?;
            let desc_start = name_end.checked_add((4 - namesz % 4) % 4)?;
            let desc_end = desc_start.checked_add(descsz)?;
            if kind == 3 && note.get(name_start..name_end)?.starts_with(b"GNU") {
                let mut hex = String::with_capacity(descsz * 2);
                for byte in note.get(desc_start..desc_end)? {
                    hex.push_str(&format!("{byte:02x}"));
                }
                return Some(hex);
            }
            cursor = desc_end.checked_add((4 - descsz % 4) % 4)?;
        }
    }
    None
}

/// One `getrandom` result the controlled-execution contract supplied instead of the kernel.
///
/// The record pins the runtime library by content hash and the call site by module offset, so a
/// changed libc invalidates the entry. `observable` is false in the strict sense: the bytes are
/// written into the runtime's own allocator state, not into a caller buffer.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ControlledEntropyRead {
    pub library: PathBuf,
    pub library_hash: Hash,
    /// Audited runtime build this call site belongs to. Empty on records written before the
    /// call-site profile existed; those records are refused rather than reinterpreted.
    #[serde(default)]
    pub build_id: String,
    /// Offset of the `syscall` instruction, relative to the library's load base.
    #[serde(default)]
    pub site_offset: u64,
    /// Offset of the runtime's allocator key, relative to the library's load base.
    #[serde(default)]
    pub destination_offset: u64,
    #[serde(default)]
    pub module_offset: u64,
    pub length: u32,
    pub flags: i32,
    pub value: u64,
    pub contract: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ReadEffect {
    File(FileRead),
    FileMetadata(FileMetadataRead),
    DirectoryOpened(DirectoryOpen),
    DirectoryEnumerated(DirectoryEnumerationRead),
    FilesystemStats(FilesystemStatsRead),
    InheritedStream(InheritedStreamRead),
    SymlinkMetadata(FileMetadataRead),
    Symlink(SymlinkRead),
    Access(AccessCheck),
    Ipc(IpcRead),
    Environment(EnvironmentRead),
    WorkingDirectory,
    Clock(ClockKind),
    Random(RandomSource),
    ControlledEntropy(ControlledEntropyRead),
    Network(NetworkRead),
    KernelState(KernelStateRead),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum WriteEffect {
    File(FileWrite),
    Network(NetworkWrite),
    Ipc(IpcWrite),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ControlEffect {
    Spawn(ProcessSpawn),
    Exec(ProcessExec),
    Chdir(PathBuf),
    Signal(SignalEffect),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FileFingerprint {
    pub device: u64,
    pub inode: u64,
    pub size: u64,
    pub blocks: u64,
    pub block_size: u64,
    pub accessed_ns: i128,
    pub modified_ns: i128,
    pub changed_ns: i128,
    pub mode: u32,
    pub link_count: u64,
    pub uid: u32,
    pub gid: u32,
    pub device_id: u64,
}

impl FileFingerprint {
    pub const fn absent() -> Self {
        Self {
            device: u64::MAX,
            inode: u64::MAX,
            size: u64::MAX,
            blocks: u64::MAX,
            block_size: u64::MAX,
            accessed_ns: i128::MIN,
            modified_ns: i128::MIN,
            changed_ns: i128::MIN,
            mode: u32::MAX,
            link_count: u64::MAX,
            uid: u32::MAX,
            gid: u32::MAX,
            device_id: u64::MAX,
        }
    }

    pub const fn is_absent(&self) -> bool {
        self.device == u64::MAX
            && self.inode == u64::MAX
            && self.size == u64::MAX
            && self.blocks == u64::MAX
            && self.block_size == u64::MAX
            && self.accessed_ns == i128::MIN
            && self.modified_ns == i128::MIN
            && self.changed_ns == i128::MIN
            && self.mode == u32::MAX
            && self.link_count == u64::MAX
            && self.uid == u32::MAX
            && self.gid == u32::MAX
            && self.device_id == u64::MAX
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FileRead {
    pub path: PathBuf,
    pub hash: Option<Hash>,
    pub fingerprint: Option<FileFingerprint>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FileMetadataRead {
    pub path: PathBuf,
    pub fingerprint: Option<FileFingerprint>,
}

/// A directory the process opened without observing its metadata or its entries.
///
/// This is the observation a name-resolution base makes: `gzip` opens the input's parent directory
/// and then opens the basename relative to that descriptor. What such an open depends on is that the
/// path still names the same directory, with the permissions that let the recorded process open it.
/// It cannot observe the directory's timestamps, size, block count or link count, so recording a
/// full [`FileFingerprint`] here turned every create or delete in the directory — including the
/// command's own output — into an invalidation of an otherwise reusable execution.
///
/// A program that genuinely inspects directory metadata issues `stat`/`fstat`/`newfstatat`, which
/// are recorded separately as [`FileMetadataRead`] and still compare timestamps. A program that
/// enumerates the directory is refused, because entry sets are not modelled.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DirectoryOpen {
    pub path: PathBuf,
    pub fingerprint: FileFingerprint,
    /// The open flags the program used. Validation reproduces the same access mode instead of
    /// assuming read permission: an `O_PATH` open needs only search permission on the path.
    #[serde(default)]
    pub flags: i32,
    /// Digest of the process credential set that performed the open.
    #[serde(default)]
    pub credential: Option<Hash>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SymlinkRead {
    pub path: PathBuf,
    pub target: Option<PathBuf>,
}

/// The exact bytes one `getdents64` call returned, with the buffer size that was requested.
///
/// Replaying a directory enumeration means asking the kernel for the same number of bytes at
/// the same stream position and requiring the same bytes back. Recording only a sorted set of
/// names would discard the order, the per-call boundaries, `d_off` cookies, `d_type`, `d_ino`
/// and the point at which a short read returned, all of which the program can observe.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DirectoryEnumerationRequest {
    pub requested: u64,
    pub returned: Vec<u8>,
}

/// A directory enumeration the program performed, as a replayable byte-stream contract.
///
/// The tracer refuses the execution when the directory descriptor was not positioned at zero
/// when enumeration began, when the directory was seeked or duplicated in a way this model does
/// not track, or when the recorded stream is too large to keep in a cache record.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DirectoryEnumerationRead {
    pub path: PathBuf,
    pub requests: Vec<DirectoryEnumerationRequest>,
    pub fingerprint: Option<FileFingerprint>,
    #[serde(default)]
    pub credential: Option<Hash>,
    #[serde(default)]
    pub mount_namespace: Option<NamespaceIdentity>,
}

/// The exact result of a `statfs`/`fstatfs` query.
///
/// Every field is kept, including the capacity fields that move as the filesystem is used. A
/// program may read any of them; pretending `f_bfree` is uninteresting would be an assumption
/// about the program, not a guard.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FilesystemStats {
    pub f_type: i64,
    pub f_bsize: i64,
    pub f_blocks: u64,
    pub f_bfree: u64,
    pub f_bavail: u64,
    pub f_files: u64,
    pub f_ffree: u64,
    pub f_fsid: [i32; 2],
    pub f_namelen: i64,
    pub f_frsize: i64,
    pub f_flags: i64,
    pub f_spare: [i64; 4],
}

/// Which syscall produced a [`FilesystemStats`] observation.
///
/// `statfs` names a path and `fstatfs` names a descriptor; replaying one as the other would
/// answer a slightly different question, so the guard reproduces the recorded call shape.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum FilesystemStatsSource {
    Path,
    Descriptor,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FilesystemStatsRead {
    pub path: PathBuf,
    pub source: FilesystemStatsSource,
    /// `None` when the kernel refused the query; `errno` then holds what the program observed.
    pub stats: Option<FilesystemStats>,
    pub errno: Option<i32>,
    /// Identity of the object the path resolved to when the query ran.
    pub fingerprint: Option<FileFingerprint>,
    #[serde(default)]
    pub credential: Option<Hash>,
    #[serde(default)]
    pub mount_namespace: Option<NamespaceIdentity>,
}

/// Identity of a mount namespace, taken from `/proc/<pid>/ns/mnt`.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NamespaceIdentity {
    pub device: u64,
    pub inode: u64,
}

/// A read from an inherited regular-file descriptor, with the offset contract it carries.
///
/// The bytes are the descriptor target's content, which is guarded like any other file. The
/// offsets are not content: a reuse that did not consume the same bytes would leave the shared
/// open file description at a different position than a direct execution, which the caller can
/// observe afterwards. Reuse therefore requires the recorded start offset and reproduces the
/// recorded end offset.
///
/// `end_offset` is the final position, not necessarily the sum of the bytes read: a successful
/// `lseek` with `SEEK_SET`, `SEEK_CUR` or `SEEK_END` repositions the description, and `pread`
/// leaves it unchanged. Only the final position is caller-visible after the process exits, so the
/// model records that rather than the seek history.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InheritedStreamRead {
    pub path: PathBuf,
    pub hash: Option<Hash>,
    pub fingerprint: Option<FileFingerprint>,
    pub start_offset: u64,
    pub end_offset: u64,
    pub bytes_read: u64,
}

/// A recorded permission check, stored verbatim so it can be re-evaluated instead of
/// approximated.
///
/// `access(2)` reports only success or an `errno`, and that answer depends on the caller's real
/// or effective credentials, every directory traversed on the way, POSIX ACLs, and mount
/// options. No content or metadata fingerprint reproduces it exactly, so the call itself is
/// kept and replayed as a predicate: reuse is allowed only when the kernel gives the same
/// answer now. The call has no side effects (it does not update `atime`), which is what makes
/// re-evaluation a valid guard rather than a second execution.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AccessCheck {
    pub path: PathBuf,
    pub mode: i32,
    /// `AT_EACCESS` and `AT_SYMLINK_NOFOLLOW` are semantically significant and are preserved.
    pub flags: i32,
    /// `None` when the check succeeded, otherwise the exact `errno` the program observed.
    pub errno: Option<i32>,
    /// Digest of the caller's security identity when the check ran.
    ///
    /// Re-evaluating the call answers a question about *those* credentials. Asking it as a
    /// different user, group set or capability set can return the recorded answer for the wrong
    /// reason: root bypasses discretionary checks, so a revoked ACL looks unchanged to a replayed
    /// check running as root while a fresh run of the dropped-privilege program would now be
    /// denied. The guard therefore requires the replaying process to hold the same identity, and
    /// refuses otherwise instead of trusting the coincidence.
    #[serde(default)]
    pub credential: Option<Hash>,
}

/// Bytes read from a pipe whose producer is part of the same traced execution.
///
/// Such a read is not a dependency on external state: the bytes are a function of inputs that are
/// already guarded. It is recorded for diagnostics, and the pipe's packetisation assumptions are
/// checked separately by the tracer, which refuses the execution when the observed transfer
/// pattern was schedule dependent.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct IpcRead {
    pub pipe: u64,
    pub description: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EnvironmentRead {
    pub key: OsString,
    pub value: Option<OsString>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ClockKind {
    Realtime,
    Monotonic,
    Other(i32),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum RandomSource {
    GetRandom,
    Device(PathBuf),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NetworkRead {
    pub operation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum KernelStateRead {
    Proc(PathBuf),
    Hostname,
    Identity,
    SystemInfo { syscall: String },
    ProcessIdentity { syscall: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FileWrite {
    pub path: PathBuf,
    pub operation: FileWriteKind,
    pub allows_create: Option<bool>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum FileWriteKind {
    CreateOrModify,
    RenameDestination,
    Delete,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NetworkWrite {
    pub operation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct IpcWrite {
    pub operation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProcessSpawn {
    pub child_pid: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProcessExec {
    pub path: PathBuf,
    pub hash: Option<Hash>,
    pub fingerprint: Option<FileFingerprint>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SignalEffect {
    pub signal: i32,
    pub target_pid: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct UnknownEffect {
    pub syscall: Option<i64>,
    pub detail: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct EffectRecord {
    pub sequence: u64,
    pub pid: u32,
    pub effect: Effect,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExecutionMetadata {
    pub command: Vec<OsString>,
    pub started_unix_ms: u128,
    pub runtime_ns: u128,
    pub exit_code: i32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProcessNode {
    pub pid: u32,
    pub parent_pid: Option<u32>,
    pub executable: Option<PathBuf>,
    pub exit_code: Option<i32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum DependencyKind {
    Reads,
    Writes,
    SpawnedBy,
    ExecutedBy,
    DependsOn,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DependencyEdge {
    pub from: String,
    pub to: String,
    pub kind: DependencyKind,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Trace {
    pub execution: ExecutionMetadata,
    pub processes: Vec<ProcessNode>,
    pub effects: Vec<EffectRecord>,
    pub dependencies: Vec<DependencyEdge>,
}

impl Default for Trace {
    fn default() -> Self {
        Self {
            execution: ExecutionMetadata {
                command: Vec::new(),
                started_unix_ms: 0,
                runtime_ns: 0,
                exit_code: 0,
            },
            processes: Vec::new(),
            effects: Vec::new(),
            dependencies: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum InputDependency {
    Executable {
        path: PathBuf,
        expected_hash: Hash,
        fingerprint: Option<FileFingerprint>,
    },
    File {
        path: PathBuf,
        expected_hash: Hash,
        fingerprint: Option<FileFingerprint>,
    },
    Metadata {
        path: PathBuf,
        fingerprint: FileFingerprint,
    },
    /// A directory that was opened, without any of its metadata being observed.
    DirectoryOpened {
        path: PathBuf,
        fingerprint: FileFingerprint,
        #[serde(default)]
        flags: i32,
        #[serde(default)]
        credential: Option<Hash>,
    },
    /// A directory whose entries were read, as an exact replayable byte stream.
    DirectoryEnumerated {
        path: PathBuf,
        requests: Vec<DirectoryEnumerationRequest>,
        fingerprint: Option<FileFingerprint>,
        credential: Option<Hash>,
        mount_namespace: Option<NamespaceIdentity>,
    },
    /// A `statfs`/`fstatfs` observation, replayed as the same kernel query.
    FilesystemStats {
        path: PathBuf,
        source: FilesystemStatsSource,
        stats: Option<FilesystemStats>,
        errno: Option<i32>,
        fingerprint: Option<FileFingerprint>,
        credential: Option<Hash>,
        mount_namespace: Option<NamespaceIdentity>,
    },
    /// An inherited regular-file descriptor read, with its offset contract.
    InheritedStream {
        path: PathBuf,
        expected_hash: Option<Hash>,
        fingerprint: Option<FileFingerprint>,
        start_offset: u64,
        end_offset: u64,
        bytes_read: u64,
    },
    SymlinkMetadata {
        path: PathBuf,
        fingerprint: FileFingerprint,
    },
    Symlink {
        path: PathBuf,
        target: Option<PathBuf>,
    },
    Access {
        path: PathBuf,
        mode: i32,
        flags: i32,
        errno: Option<i32>,
        #[serde(default)]
        credential: Option<Hash>,
    },
    /// Runtime-internal entropy that a controlled-execution contract fixed.
    ControlledEntropy {
        library: PathBuf,
        library_hash: Hash,
        #[serde(default)]
        build_id: String,
        #[serde(default)]
        site_offset: u64,
        #[serde(default)]
        destination_offset: u64,
        #[serde(default)]
        module_offset: u64,
        length: u32,
        flags: i32,
        value: u64,
        contract: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FileDescriptorIdentity {
    pub target: PathBuf,
    pub fingerprint: Option<FileFingerprint>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RuntimeIdentity {
    pub os: String,
    pub architecture: String,
    pub kernel_release: String,
    pub kernel_version: String,
    pub hostname: String,
    pub domain_name: String,
    pub uid: u32,
    pub euid: u32,
    pub gid: u32,
    pub egid: u32,
    pub stack_limit_soft: u64,
    pub stack_limit_hard: u64,
    pub stdin: FileDescriptorIdentity,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExecutionIdentity {
    pub executable_hash: Hash,
    pub argv: Vec<OsString>,
    pub cwd: PathBuf,
    #[serde(with = "os_map")]
    pub environment: BTreeMap<OsString, OsString>,
    pub input_dependencies: Vec<InputDependency>,
    pub runtime_identity: RuntimeIdentity,
}

mod os_map {
    use serde::{Deserialize, Deserializer, Serialize, Serializer};
    use std::collections::BTreeMap;
    use std::ffi::OsString;

    pub fn serialize<S>(
        values: &BTreeMap<OsString, OsString>,
        serializer: S,
    ) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        values.iter().collect::<Vec<_>>().serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<BTreeMap<OsString, OsString>, D::Error>
    where
        D: Deserializer<'de>,
    {
        Vec::<(OsString, OsString)>::deserialize(deserializer)
            .map(|values| values.into_iter().collect())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Classification {
    pub class: DeterminismClass,
    pub reasons: Vec<String>,
}

pub fn reconstruct_dependencies(effects: &[EffectRecord]) -> Vec<InputDependency> {
    let first_writes = effects
        .iter()
        .filter_map(|record| match &record.effect {
            Effect::Write(WriteEffect::File(write)) => Some((write.path.clone(), record.sequence)),
            _ => None,
        })
        .fold(
            BTreeMap::<PathBuf, u64>::new(),
            |mut values, (path, sequence)| {
                values
                    .entry(path)
                    .and_modify(|existing| *existing = (*existing).min(sequence))
                    .or_insert(sequence);
                values
            },
        );
    let mut files = BTreeMap::new();
    let mut executables = BTreeMap::new();
    let mut metadata = BTreeMap::new();
    let mut directory_opens = BTreeMap::new();
    let mut directory_enumerations = Vec::<DirectoryEnumerationRead>::new();
    let mut filesystem_stats = Vec::<FilesystemStatsRead>::new();
    let mut inherited_streams = BTreeMap::<PathBuf, InheritedStreamRead>::new();
    let mut symlink_metadata = BTreeMap::new();
    let mut symlinks = BTreeMap::new();
    let mut access = BTreeMap::<(PathBuf, i32, i32), (Option<i32>, Option<Hash>)>::new();
    let mut controlled_entropy = Vec::<ControlledEntropyRead>::new();
    for record in effects {
        match &record.effect {
            Effect::Read(ReadEffect::File(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                if let Some(hash) = read.hash {
                    files
                        .entry(read.path.clone())
                        .or_insert((hash, read.fingerprint.clone()));
                }
            }
            Effect::Read(ReadEffect::FileMetadata(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                if let Some(fingerprint) = &read.fingerprint {
                    metadata
                        .entry(read.path.clone())
                        .or_insert(fingerprint.clone());
                }
            }
            Effect::Read(ReadEffect::DirectoryOpened(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                directory_opens.entry(read.path.clone()).or_insert((
                    read.fingerprint.clone(),
                    read.flags,
                    read.credential,
                ));
            }
            Effect::Read(ReadEffect::DirectoryEnumerated(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                // Each distinct stream is a separate observation. Two enumerations of the same
                // directory can legitimately start at different times, so keeping only the first
                // would leave the second unguarded.
                if !directory_enumerations.contains(read) {
                    directory_enumerations.push(read.clone());
                }
            }
            Effect::Read(ReadEffect::FilesystemStats(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                // Two identical queries collapse into one guard; two *different* observations
                // of the same path both stay, because a replay has to reproduce each one.
                if !filesystem_stats.contains(read) {
                    filesystem_stats.push(read.clone());
                }
            }
            Effect::Read(ReadEffect::InheritedStream(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                inherited_streams
                    .entry(read.path.clone())
                    .or_insert_with(|| read.clone());
            }
            Effect::Read(ReadEffect::SymlinkMetadata(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                if let Some(fingerprint) = &read.fingerprint {
                    symlink_metadata
                        .entry(read.path.clone())
                        .or_insert(fingerprint.clone());
                }
            }
            Effect::Read(ReadEffect::Symlink(read))
                if precedes_first_write(&first_writes, &read.path, record.sequence) =>
            {
                symlinks
                    .entry(read.path.clone())
                    .or_insert(read.target.clone());
            }
            Effect::Read(ReadEffect::Access(check))
                if precedes_first_write(&first_writes, &check.path, record.sequence) =>
            {
                access
                    .entry((check.path.clone(), check.mode, check.flags))
                    .or_insert((check.errno, check.credential));
            }
            Effect::Read(ReadEffect::ControlledEntropy(read)) => {
                // Each distinct call site is a separate observation; two calls from the same site
                // with the same shape collapse into one guard.
                if !controlled_entropy.contains(read) {
                    controlled_entropy.push(read.clone());
                }
            }
            Effect::Control(ControlEffect::Exec(exec)) => {
                if let Some(hash) = exec.hash {
                    executables
                        .entry(exec.path.clone())
                        .or_insert((hash, exec.fingerprint.clone()));
                }
            }
            _ => {}
        }
    }
    for path in executables.keys() {
        files.remove(path);
    }
    let mut dependencies = files
        .into_iter()
        .map(
            |(path, (expected_hash, fingerprint))| InputDependency::File {
                path,
                expected_hash,
                fingerprint,
            },
        )
        .collect::<Vec<_>>();
    dependencies.extend(
        executables
            .into_iter()
            .map(
                |(path, (expected_hash, fingerprint))| InputDependency::Executable {
                    path,
                    expected_hash,
                    fingerprint,
                },
            ),
    );
    dependencies.extend(
        metadata
            .into_iter()
            .map(|(path, fingerprint)| InputDependency::Metadata { path, fingerprint }),
    );
    dependencies.extend(directory_opens.into_iter().map(
        |(path, (fingerprint, flags, credential))| InputDependency::DirectoryOpened {
            path,
            fingerprint,
            flags,
            credential,
        },
    ));
    dependencies.extend(directory_enumerations.into_iter().map(|read| {
        InputDependency::DirectoryEnumerated {
            path: read.path,
            requests: read.requests,
            fingerprint: read.fingerprint,
            credential: read.credential,
            mount_namespace: read.mount_namespace,
        }
    }));
    dependencies.extend(filesystem_stats.into_iter().map(|read| {
        InputDependency::FilesystemStats {
            path: read.path,
            source: read.source,
            stats: read.stats,
            errno: read.errno,
            fingerprint: read.fingerprint,
            credential: read.credential,
            mount_namespace: read.mount_namespace,
        }
    }));
    dependencies.extend(inherited_streams.into_iter().map(|(path, read)| {
        InputDependency::InheritedStream {
            path,
            expected_hash: read.hash,
            fingerprint: read.fingerprint,
            start_offset: read.start_offset,
            end_offset: read.end_offset,
            bytes_read: read.bytes_read,
        }
    }));
    dependencies.extend(
        symlink_metadata
            .into_iter()
            .map(|(path, fingerprint)| InputDependency::SymlinkMetadata { path, fingerprint }),
    );
    dependencies.extend(
        symlinks
            .into_iter()
            .map(|(path, target)| InputDependency::Symlink { path, target }),
    );
    dependencies.extend(
        access
            .into_iter()
            .map(
                |((path, mode, flags), (errno, credential))| InputDependency::Access {
                    path,
                    mode,
                    flags,
                    errno,
                    credential,
                },
            ),
    );
    dependencies.extend(controlled_entropy.into_iter().map(|read| {
        InputDependency::ControlledEntropy {
            library: read.library,
            library_hash: read.library_hash,
            build_id: read.build_id,
            site_offset: read.site_offset,
            destination_offset: read.destination_offset,
            module_offset: read.module_offset,
            length: read.length,
            flags: read.flags,
            value: read.value,
            contract: read.contract,
        }
    }));
    dependencies
}

fn push_unique(reasons: &mut Vec<String>, reason: String) {
    if !reasons.contains(&reason) {
        reasons.push(reason);
    }
}

fn clock_name(kind: ClockKind) -> String {
    match kind {
        ClockKind::Realtime => "realtime".into(),
        ClockKind::Monotonic => "monotonic".into(),
        ClockKind::Other(id) => format!("clock {id}"),
    }
}

fn random_name(source: &RandomSource) -> String {
    match source {
        RandomSource::GetRandom => "getrandom".into(),
        RandomSource::Device(path) => path.display().to_string(),
    }
}

fn precedes_first_write(
    first_writes: &BTreeMap<PathBuf, u64>,
    path: &std::path::Path,
    read_sequence: u64,
) -> bool {
    match first_writes.get(path) {
        Some(write_sequence) => read_sequence < *write_sequence,
        None => true,
    }
}

pub fn classify(effects: &[EffectRecord]) -> Classification {
    let mut unknown = Vec::new();
    let mut nondeterministic = Vec::new();
    for record in effects {
        match &record.effect {
            Effect::Unknown(effect) => unknown.push(effect.detail.clone()),
            Effect::Read(ReadEffect::Clock(kind)) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process read system clock: {}", clock_name(*kind)),
                );
            }
            Effect::Read(ReadEffect::Random(source)) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process read randomness via {}", random_name(source)),
                );
            }
            Effect::Read(ReadEffect::Network(effect)) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process read network: {}", effect.operation),
                );
            }
            Effect::Read(ReadEffect::KernelState(KernelStateRead::SystemInfo { syscall })) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process read system information via {syscall}"),
                );
            }
            Effect::Read(ReadEffect::KernelState(KernelStateRead::ProcessIdentity { syscall })) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process read process identity via {syscall}"),
                );
            }
            Effect::Write(WriteEffect::Network(effect)) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process wrote network: {}", effect.operation),
                );
            }
            Effect::Write(WriteEffect::Ipc(effect)) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process wrote IPC: {}", effect.operation),
                );
            }
            Effect::Control(ControlEffect::Signal(effect)) => {
                push_unique(
                    &mut nondeterministic,
                    format!("process sent signal {}", effect.signal),
                );
            }
            _ => {}
        }
    }
    if !unknown.is_empty() {
        return Classification {
            class: DeterminismClass::Unknown,
            reasons: unknown,
        };
    }
    if !nondeterministic.is_empty() {
        return Classification {
            class: DeterminismClass::Nondeterministic,
            reasons: nondeterministic,
        };
    }
    Classification {
        class: DeterminismClass::Guarded,
        reasons: vec!["all observed dependencies are guardable or captured outputs".into()],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_round_trip() {
        let hash = Hash::from(blake3::hash(b"tracejit"));
        assert_eq!(hash.to_string().parse::<Hash>().unwrap(), hash);
    }

    #[test]
    fn refusal_reasons_name_the_observed_syscall() {
        let effects = vec![
            EffectRecord {
                sequence: 0,
                pid: 1,
                effect: Effect::Read(ReadEffect::KernelState(KernelStateRead::ProcessIdentity {
                    syscall: "getpid".into(),
                })),
            },
            EffectRecord {
                sequence: 1,
                pid: 1,
                effect: Effect::Read(ReadEffect::KernelState(KernelStateRead::ProcessIdentity {
                    syscall: "getpid".into(),
                })),
            },
            EffectRecord {
                sequence: 2,
                pid: 1,
                effect: Effect::Read(ReadEffect::Random(RandomSource::GetRandom)),
            },
        ];
        let classification = classify(&effects);
        assert_eq!(classification.class, DeterminismClass::Nondeterministic);
        assert_eq!(
            classification.reasons,
            vec![
                "process read process identity via getpid".to_string(),
                "process read randomness via getrandom".to_string(),
            ]
        );
    }

    #[test]
    fn unknown_takes_precedence_over_nondeterminism() {
        let effects = vec![
            EffectRecord {
                sequence: 0,
                pid: 1,
                effect: Effect::Read(ReadEffect::Random(RandomSource::GetRandom)),
            },
            EffectRecord {
                sequence: 1,
                pid: 1,
                effect: Effect::Unknown(UnknownEffect {
                    syscall: Some(16),
                    detail: "ioctl".into(),
                }),
            },
        ];
        assert_eq!(classify(&effects).class, DeterminismClass::Unknown);
    }

    #[test]
    fn serialization_round_trip() {
        let effect = Effect::Read(ReadEffect::WorkingDirectory);
        let encoded = serde_json::to_vec(&effect).unwrap();
        assert_eq!(serde_json::from_slice::<Effect>(&encoded).unwrap(), effect);
    }

    #[test]
    fn execution_identity_environment_round_trips_as_ordered_entries() {
        let identity = ExecutionIdentity {
            executable_hash: Hash::from(blake3::hash(b"binary")),
            argv: vec![OsString::from("command")],
            cwd: PathBuf::from("/work"),
            environment: BTreeMap::from([
                (OsString::from("A"), OsString::from("1")),
                (OsString::from("B"), OsString::from("2")),
            ]),
            input_dependencies: Vec::new(),
            runtime_identity: RuntimeIdentity {
                os: "Linux".into(),
                architecture: "x86_64".into(),
                kernel_release: "test".into(),
                kernel_version: "test-version".into(),
                hostname: "test".into(),
                domain_name: "test-domain".into(),
                uid: 1000,
                euid: 1000,
                gid: 1000,
                egid: 1000,
                stack_limit_soft: 8 * 1024 * 1024,
                stack_limit_hard: u64::MAX,
                stdin: FileDescriptorIdentity {
                    target: PathBuf::from("/dev/null"),
                    fingerprint: None,
                },
            },
        };
        let encoded = serde_json::to_vec(&identity).unwrap();
        assert_eq!(
            serde_json::from_slice::<ExecutionIdentity>(&encoded).unwrap(),
            identity
        );
    }
}

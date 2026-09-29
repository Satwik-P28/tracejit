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
            | Self::Read(ReadEffect::SymlinkMetadata(_))
            | Self::Read(ReadEffect::Symlink(_))
            | Self::Read(ReadEffect::Environment(_))
            | Self::Read(ReadEffect::WorkingDirectory)
            | Self::Read(ReadEffect::KernelState(KernelStateRead::Hostname))
            | Self::Read(ReadEffect::KernelState(KernelStateRead::Identity)) => EffectProperties {
                observable: true,
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

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ReadEffect {
    File(FileRead),
    FileMetadata(FileMetadataRead),
    SymlinkMetadata(FileMetadataRead),
    Symlink(SymlinkRead),
    Environment(EnvironmentRead),
    WorkingDirectory,
    Clock(ClockKind),
    Random(RandomSource),
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

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SymlinkRead {
    pub path: PathBuf,
    pub target: Option<PathBuf>,
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
    SymlinkMetadata {
        path: PathBuf,
        fingerprint: FileFingerprint,
    },
    Symlink {
        path: PathBuf,
        target: Option<PathBuf>,
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
    let mut symlink_metadata = BTreeMap::new();
    let mut symlinks = BTreeMap::new();
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

use serde::{Deserialize, Serialize};
use std::ffi::{CStr, OsString};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use tracejit_effects::{
    DirectoryEnumerationRequest, ExecutionIdentity, FileDescriptorIdentity, FileFingerprint,
    FilesystemStats, FilesystemStatsSource, Hash, InputDependency, NamespaceIdentity,
    RuntimeIdentity,
};

#[derive(Debug, thiserror::Error)]
pub enum GuardError {
    #[error("could not read {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("canonical serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("could not inspect runtime identity: {0}")]
    Runtime(String),
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub enum GuardMode {
    Fast,
    #[default]
    Strict,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Guard {
    ExecutableHash {
        path: PathBuf,
        expected: Hash,
    },
    FileHash {
        path: PathBuf,
        expected: Hash,
    },
    FileMetadata {
        path: PathBuf,
        expected: FileFingerprint,
    },
    /// A directory that was opened, not inspected.
    ///
    /// Validation reproduces the observation instead of comparing a fingerprint: the path must
    /// still name the same directory (device, inode, mode and ownership), and this process must
    /// still be able to open it. Timestamps are deliberately not compared, because an `open` of a
    /// directory cannot report them; a program that reads them issues a `stat`, which produces a
    /// [`Guard::FileMetadata`] that does compare them.
    DirectoryOpened {
        path: PathBuf,
        expected: FileFingerprint,
        /// Access mode of the recorded open, so an `O_PATH` open is not replayed as a read.
        #[serde(default)]
        flags: i32,
        /// Credential set that performed the recorded open.
        #[serde(default)]
        credential: Option<Hash>,
    },
    /// A directory enumeration replayed byte for byte.
    DirectoryEnumerated {
        path: PathBuf,
        requests: Vec<DirectoryEnumerationRequest>,
        expected: FileFingerprint,
        credential: Option<Hash>,
        mount_namespace: Option<NamespaceIdentity>,
    },
    /// A `statfs`/`fstatfs` observation replayed as the same kernel query.
    FilesystemStats {
        path: PathBuf,
        source: FilesystemStatsSource,
        expected: Option<FilesystemStats>,
        errno: Option<i32>,
        fingerprint: Option<FileFingerprint>,
        credential: Option<Hash>,
        mount_namespace: Option<NamespaceIdentity>,
    },
    /// An inherited regular-file descriptor read and the offset it must consume.
    InheritedStream {
        path: PathBuf,
        expected_hash: Option<Hash>,
        fingerprint: Option<FileFingerprint>,
        start_offset: u64,
        end_offset: u64,
    },
    SymlinkTarget {
        path: PathBuf,
        expected: Option<PathBuf>,
    },
    SymlinkMetadata {
        path: PathBuf,
        expected: FileFingerprint,
    },
    /// A recorded permission check, replayed rather than approximated.
    ///
    /// The answer depends on credentials, path traversal, ACLs and mount options, none of which a
    /// content or metadata fingerprint reproduces, so validation asks the kernel again and
    /// requires the same success/`errno` answer.
    AccessCheck {
        path: PathBuf,
        mode: i32,
        flags: i32,
        expected: Option<i32>,
        /// Identity the recorded answer belongs to; a replay under different credentials is
        /// refused rather than trusted.
        #[serde(default)]
        credential: Option<Hash>,
    },
    EnvironmentValue {
        key: OsString,
        expected: Option<OsString>,
    },
    WorkingDirectory {
        expected: PathBuf,
    },
    RuntimeIdentity {
        expected: RuntimeIdentity,
    },
    NoUnexpectedEffects,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GuardFailure {
    pub guard: Box<Guard>,
    pub reason: String,
    pub expected: String,
    pub actual: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GuardReport {
    pub checked: usize,
    pub passed: usize,
    pub failure: Option<GuardFailure>,
}

pub fn hash_reader(mut reader: impl Read) -> Result<Hash, io::Error> {
    let mut hasher = blake3::Hasher::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(Hash::from(hasher.finalize()))
}

pub fn hash_file(path: &Path) -> Result<Hash, GuardError> {
    let file = File::open(path).map_err(|source| GuardError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    hash_reader(file).map_err(|source| GuardError::Io {
        path: path.to_path_buf(),
        source,
    })
}

pub fn canonical_hash<T: Serialize>(value: &T) -> Result<Hash, GuardError> {
    let bytes = serde_json::to_vec(value)?;
    Ok(Hash::from(blake3::hash(&bytes)))
}

#[cfg(unix)]
pub fn fingerprint(path: &Path) -> Result<FileFingerprint, GuardError> {
    let metadata = fs::metadata(path).map_err(|source| GuardError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    fingerprint_from_metadata(metadata)
}

#[cfg(unix)]
pub fn symlink_fingerprint(path: &Path) -> Result<FileFingerprint, GuardError> {
    let metadata = fs::symlink_metadata(path).map_err(|source| GuardError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    fingerprint_from_metadata(metadata)
}

#[cfg(unix)]
fn fingerprint_from_metadata(metadata: fs::Metadata) -> Result<FileFingerprint, GuardError> {
    use std::os::unix::fs::MetadataExt;

    let modified_ns =
        i128::from(metadata.mtime()) * 1_000_000_000_i128 + i128::from(metadata.mtime_nsec());
    let accessed_ns =
        i128::from(metadata.atime()) * 1_000_000_000_i128 + i128::from(metadata.atime_nsec());
    let changed_ns =
        i128::from(metadata.ctime()) * 1_000_000_000_i128 + i128::from(metadata.ctime_nsec());
    Ok(FileFingerprint {
        device: metadata.dev(),
        inode: metadata.ino(),
        size: metadata.size(),
        blocks: metadata.blocks(),
        block_size: metadata.blksize(),
        accessed_ns,
        modified_ns,
        changed_ns,
        mode: metadata.mode(),
        link_count: metadata.nlink(),
        uid: metadata.uid(),
        gid: metadata.gid(),
        device_id: metadata.rdev(),
    })
}

#[cfg(not(unix))]
pub fn fingerprint(path: &Path) -> Result<FileFingerprint, GuardError> {
    let metadata = fs::metadata(path).map_err(|source| GuardError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    let modified_ns = metadata
        .modified()
        .ok()
        .and_then(|value| value.duration_since(std::time::UNIX_EPOCH).ok())
        .map_or(0, |value| value.as_nanos() as i128);
    Ok(FileFingerprint {
        device: 0,
        inode: 0,
        size: metadata.len(),
        blocks: 0,
        block_size: 0,
        accessed_ns: 0,
        modified_ns,
        changed_ns: 0,
        mode: u32::from(metadata.permissions().readonly()),
        link_count: 0,
        uid: 0,
        gid: 0,
        device_id: 0,
    })
}

#[cfg(not(unix))]
pub fn symlink_fingerprint(path: &Path) -> Result<FileFingerprint, GuardError> {
    fingerprint(path)
}

pub fn current_runtime_identity() -> Result<RuntimeIdentity, GuardError> {
    #[cfg(unix)]
    {
        let mut info = std::mem::MaybeUninit::<libc::utsname>::zeroed();
        // SAFETY: uname initializes the provided utsname on success. We check its return value.
        if unsafe { libc::uname(info.as_mut_ptr()) } != 0 {
            return Err(GuardError::Runtime(io::Error::last_os_error().to_string()));
        }
        // SAFETY: the successful uname call above initialized every field.
        let info = unsafe { info.assume_init() };
        let field = |value: &[libc::c_char]| {
            // SAFETY: utsname fields are fixed-size, NUL-terminated arrays on supported Unix systems.
            unsafe { CStr::from_ptr(value.as_ptr()) }
                .to_string_lossy()
                .into_owned()
        };
        #[cfg(target_os = "linux")]
        let domain_name = field(&info.domainname);
        #[cfg(not(target_os = "linux"))]
        let domain_name = String::new();
        let mut stack_limit = std::mem::MaybeUninit::<libc::rlimit>::uninit();
        // SAFETY: getrlimit initializes stack_limit on success. The inherited stack limits are
        // part of the runtime behavior and must match before a cached result can be reused.
        if unsafe { libc::getrlimit(libc::RLIMIT_STACK, stack_limit.as_mut_ptr()) } != 0 {
            return Err(GuardError::Runtime(io::Error::last_os_error().to_string()));
        }
        // SAFETY: the successful getrlimit call above initialized both fields.
        let stack_limit = unsafe { stack_limit.assume_init() };
        #[cfg(target_os = "linux")]
        let stdin_link = Path::new("/proc/self/fd/0");
        #[cfg(not(target_os = "linux"))]
        let stdin_link = Path::new("/dev/fd/0");
        let stdin_target = fs::read_link(stdin_link)
            .map_err(|error| GuardError::Runtime(format!("could not inspect stdin: {error}")))?;
        let stdin_fingerprint = fingerprint(stdin_link).ok();
        Ok(RuntimeIdentity {
            os: field(&info.sysname),
            architecture: field(&info.machine),
            kernel_release: field(&info.release),
            kernel_version: field(&info.version),
            hostname: field(&info.nodename),
            domain_name,
            // SAFETY: these calls have no preconditions and do not dereference memory.
            uid: unsafe { libc::getuid() },
            // SAFETY: these calls have no preconditions and do not dereference memory.
            euid: unsafe { libc::geteuid() },
            // SAFETY: these calls have no preconditions and do not dereference memory.
            gid: unsafe { libc::getgid() },
            // SAFETY: these calls have no preconditions and do not dereference memory.
            egid: unsafe { libc::getegid() },
            stack_limit_soft: stack_limit.rlim_cur,
            stack_limit_hard: stack_limit.rlim_max,
            stdin: FileDescriptorIdentity {
                target: stdin_target,
                fingerprint: stdin_fingerprint,
            },
        })
    }
    #[cfg(not(unix))]
    {
        Err(GuardError::Runtime(
            "runtime identity is unsupported on this platform".into(),
        ))
    }
}

impl Guard {
    pub fn validate(&self, mode: GuardMode) -> Result<(), GuardFailure> {
        match self {
            Self::ExecutableHash { path, expected } => {
                validate_executable(path).map_err(|actual| GuardFailure {
                    guard: Box::new(self.clone()),
                    reason: "executable permission changed".into(),
                    expected: "executable access".into(),
                    actual,
                })?;
                let actual = hash_file(path).map_err(|error| GuardFailure {
                    guard: Box::new(self.clone()),
                    reason: "executable could not be hashed".into(),
                    expected: expected.to_string(),
                    actual: error.to_string(),
                })?;
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "executable content changed".into(),
                        expected: expected.to_string(),
                        actual: actual.to_string(),
                    })
                }
            }
            Self::FileHash { path, expected } => {
                let actual = hash_file(path).map_err(|error| GuardFailure {
                    guard: Box::new(self.clone()),
                    reason: "file could not be hashed".into(),
                    expected: expected.to_string(),
                    actual: error.to_string(),
                })?;
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "file content changed".into(),
                        expected: expected.to_string(),
                        actual: actual.to_string(),
                    })
                }
            }
            Self::FileMetadata { path, expected } => {
                let actual = match fingerprint(path) {
                    Ok(actual) => actual,
                    Err(GuardError::Io { source, .. })
                        if expected.is_absent() && source.kind() == io::ErrorKind::NotFound =>
                    {
                        return Ok(());
                    }
                    Err(error) => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "file metadata unavailable".into(),
                            expected: format!("{expected:?}"),
                            actual: error.to_string(),
                        });
                    }
                };
                if &actual == expected {
                    Ok(())
                } else if mode == GuardMode::Strict && path.is_file() {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "metadata changed; no content hash was recorded".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    })
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "file metadata changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    })
                }
            }
            Self::DirectoryOpened {
                path,
                expected,
                flags,
                credential,
            } => {
                let current = credential_identity(0);
                if credential.is_none() || current.as_ref() != credential.as_ref() {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "directory-open credentials changed".into(),
                        expected: describe_credential(credential.as_ref()),
                        actual: describe_credential(current.as_ref()),
                    });
                }
                let actual = match fingerprint(path) {
                    Ok(actual) => actual,
                    Err(error) => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "directory is unavailable".into(),
                            expected: format!("{expected:?}"),
                            actual: error.to_string(),
                        });
                    }
                };
                if actual.mode & libc::S_IFMT != libc::S_IFDIR {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "path is no longer a directory".into(),
                        expected: "directory".into(),
                        actual: format!("mode {:#o}", actual.mode),
                    });
                }
                // Identity and the bits that decide whether the open can succeed. Size, blocks,
                // link count and timestamps are excluded on purpose: creating or deleting an entry
                // changes all of them without changing anything an open can observe.
                if actual.device != expected.device
                    || actual.inode != expected.inode
                    || actual.mode != expected.mode
                    || actual.uid != expected.uid
                    || actual.gid != expected.gid
                {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "directory identity or permissions changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    });
                }
                // Replay the observable itself: the recorded execution opened this directory, and
                // a fresh run would have to do the same. This is what covers permission and ACL
                // changes that mode bits do not fully express.
                if let Err(error) = probe_directory_open(path, *flags) {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "directory can no longer be opened".into(),
                        expected: "open succeeds".into(),
                        actual: error,
                    });
                }
                Ok(())
            }
            Self::DirectoryEnumerated {
                path,
                requests,
                expected,
                credential,
                mount_namespace,
            } => {
                validate_credential_and_namespace(
                    self,
                    credential.as_ref(),
                    mount_namespace.as_ref(),
                )?;
                let actual = match fingerprint(path) {
                    Ok(actual) => actual,
                    Err(error) => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "enumerated directory is unavailable".into(),
                            expected: format!("{expected:?}"),
                            actual: error.to_string(),
                        });
                    }
                };
                if actual.device != expected.device || actual.inode != expected.inode {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "enumerated directory identity changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    });
                }
                if actual.mode & libc::S_IFMT != libc::S_IFDIR {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "path is no longer a directory".into(),
                        expected: "directory".into(),
                        actual: format!("mode {:#o}", actual.mode),
                    });
                }
                let observed = replay_directory_enumeration(path, requests).map_err(|reason| {
                    GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "directory enumeration could not be replayed".into(),
                        expected: "the recorded entry stream".into(),
                        actual: reason,
                    }
                })?;
                if let Some(difference) = observed {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "directory entry stream changed".into(),
                        expected: format!(
                            "call {}: {} bytes starting {:02x?}",
                            difference.index,
                            difference.recorded.len(),
                            &difference.recorded[..difference.recorded.len().min(32)]
                        ),
                        actual: format!(
                            "{} bytes starting {:02x?}",
                            difference.current.len(),
                            &difference.current[..difference.current.len().min(32)]
                        ),
                    });
                }
                Ok(())
            }
            Self::FilesystemStats {
                path,
                source,
                expected,
                errno,
                fingerprint: expected_fingerprint,
                credential,
                mount_namespace,
            } => {
                validate_credential_and_namespace(
                    self,
                    credential.as_ref(),
                    mount_namespace.as_ref(),
                )?;
                if let Some(expected_fingerprint) = expected_fingerprint {
                    let actual = match fingerprint(path) {
                        Ok(actual) => actual,
                        Err(error) => {
                            return Err(GuardFailure {
                                guard: Box::new(self.clone()),
                                reason: "filesystem-stat path is unavailable".into(),
                                expected: format!("{expected_fingerprint:?}"),
                                actual: error.to_string(),
                            });
                        }
                    };
                    if actual.device != expected_fingerprint.device
                        || actual.inode != expected_fingerprint.inode
                    {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "filesystem-stat path resolved to a different object".into(),
                            expected: format!("{expected_fingerprint:?}"),
                            actual: format!("{actual:?}"),
                        });
                    }
                }
                let (actual, actual_errno) =
                    statfs_query(path, *source).map_err(|reason| GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "filesystem statistics could not be re-queried".into(),
                        expected: describe_statfs(*expected, *errno),
                        actual: reason,
                    })?;
                if &actual != expected || &actual_errno != errno {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "filesystem statistics changed".into(),
                        expected: describe_statfs(*expected, *errno),
                        actual: describe_statfs(actual, actual_errno),
                    });
                }
                Ok(())
            }
            Self::InheritedStream {
                path,
                expected_hash,
                fingerprint: expected_fingerprint,
                start_offset,
                end_offset: _,
            } => {
                let target = fs::read_link("/proc/self/fd/0").map_err(|error| GuardFailure {
                    guard: Box::new(self.clone()),
                    reason: "inherited stdin is unavailable".into(),
                    expected: path.display().to_string(),
                    actual: error.to_string(),
                })?;
                if &target != path {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "inherited stdin names a different file".into(),
                        expected: path.display().to_string(),
                        actual: target.display().to_string(),
                    });
                }
                let actual_fingerprint =
                    fingerprint(Path::new("/proc/self/fd/0")).map_err(|error| GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "inherited stdin metadata is unavailable".into(),
                        expected: format!("{expected_fingerprint:?}"),
                        actual: error.to_string(),
                    })?;
                if actual_fingerprint.mode & libc::S_IFMT != libc::S_IFREG {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "inherited stdin is no longer a regular file".into(),
                        expected: "regular file".into(),
                        actual: format!("mode {:#o}", actual_fingerprint.mode),
                    });
                }
                match expected_fingerprint {
                    Some(expected_fingerprint)
                        if actual_fingerprint.device == expected_fingerprint.device
                            && actual_fingerprint.inode == expected_fingerprint.inode => {}
                    Some(expected_fingerprint) => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "inherited stdin is a different file".into(),
                            expected: format!("{expected_fingerprint:?}"),
                            actual: format!("{actual_fingerprint:?}"),
                        });
                    }
                    None => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "inherited stdin identity was not recorded".into(),
                            expected: "a recorded identity".into(),
                            actual: "none".into(),
                        });
                    }
                }
                match expected_hash {
                    Some(expected_hash) => {
                        let actual = hash_file(path).map_err(|error| GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "inherited stdin could not be hashed".into(),
                            expected: expected_hash.to_string(),
                            actual: error.to_string(),
                        })?;
                        if &actual != expected_hash {
                            return Err(GuardFailure {
                                guard: Box::new(self.clone()),
                                reason: "inherited stdin content changed".into(),
                                expected: expected_hash.to_string(),
                                actual: actual.to_string(),
                            });
                        }
                    }
                    None => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "inherited stdin content was not recorded".into(),
                            expected: "a recorded hash".into(),
                            actual: "none".into(),
                        });
                    }
                }
                // The shared open file description must still be at the position the recorded
                // execution started from; otherwise a fresh run would read different bytes.
                // SAFETY: lseek only inspects the descriptor's offset here.
                let offset = unsafe { libc::lseek(0, 0, libc::SEEK_CUR) };
                if offset < 0 || offset as u64 != *start_offset {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "inherited stdin offset changed".into(),
                        expected: start_offset.to_string(),
                        actual: offset.to_string(),
                    });
                }
                Ok(())
            }
            Self::SymlinkTarget { path, expected } => {
                let actual = match fs::read_link(path) {
                    Ok(target) => Some(target),
                    Err(error) if error.kind() == io::ErrorKind::InvalidInput => None,
                    Err(error) => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "symlink state unavailable".into(),
                            expected: format!("{expected:?}"),
                            actual: error.to_string(),
                        });
                    }
                };
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "symlink target changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    })
                }
            }
            Self::SymlinkMetadata { path, expected } => {
                let actual = match symlink_fingerprint(path) {
                    Ok(actual) => actual,
                    Err(GuardError::Io { source, .. })
                        if expected.is_absent() && source.kind() == io::ErrorKind::NotFound =>
                    {
                        return Ok(());
                    }
                    Err(error) => {
                        return Err(GuardFailure {
                            guard: Box::new(self.clone()),
                            reason: "symlink metadata unavailable".into(),
                            expected: format!("{expected:?}"),
                            actual: error.to_string(),
                        });
                    }
                };
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "symlink metadata changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    })
                }
            }
            Self::EnvironmentValue { key, expected } => {
                let actual = std::env::var_os(key);
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "environment value changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    })
                }
            }
            Self::WorkingDirectory { expected } => {
                let actual = std::env::current_dir().map_err(|error| GuardFailure {
                    guard: Box::new(self.clone()),
                    reason: "working directory unavailable".into(),
                    expected: expected.display().to_string(),
                    actual: error.to_string(),
                })?;
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "working directory changed".into(),
                        expected: expected.display().to_string(),
                        actual: actual.display().to_string(),
                    })
                }
            }
            Self::RuntimeIdentity { expected } => {
                let actual = current_runtime_identity().map_err(|error| GuardFailure {
                    guard: Box::new(self.clone()),
                    reason: "runtime identity unavailable".into(),
                    expected: format!("{expected:?}"),
                    actual: error.to_string(),
                })?;
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "runtime identity changed".into(),
                        expected: format!("{expected:?}"),
                        actual: format!("{actual:?}"),
                    })
                }
            }
            Self::AccessCheck {
                path,
                mode,
                flags,
                expected,
                credential,
            } => {
                let current = credential_identity(0);
                if credential.is_none() || credential.as_ref() != current.as_ref() {
                    return Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "access check credentials changed".into(),
                        expected: describe_credential(credential.as_ref()),
                        actual: describe_credential(current.as_ref()),
                    });
                }
                let actual =
                    evaluate_access(path, *mode, *flags).map_err(|reason| GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "access check could not be re-evaluated".into(),
                        expected: describe_access(*expected),
                        actual: reason,
                    })?;
                if &actual == expected {
                    Ok(())
                } else {
                    Err(GuardFailure {
                        guard: Box::new(self.clone()),
                        reason: "access check result changed".into(),
                        expected: describe_access(*expected),
                        actual: describe_access(actual),
                    })
                }
            }
            Self::NoUnexpectedEffects => Ok(()),
        }
    }
}

fn validate_credential_and_namespace(
    guard: &Guard,
    credential: Option<&Hash>,
    namespace: Option<&NamespaceIdentity>,
) -> Result<(), GuardFailure> {
    let current = credential_identity(0);
    if credential.is_none() || current.as_ref() != credential {
        return Err(GuardFailure {
            guard: Box::new(guard.clone()),
            reason: "replay credentials changed".into(),
            expected: describe_credential(credential),
            actual: describe_credential(current.as_ref()),
        });
    }
    let current_namespace = namespace_identity(0);
    if namespace.is_none() || current_namespace.as_ref() != namespace {
        return Err(GuardFailure {
            guard: Box::new(guard.clone()),
            reason: "mount namespace changed".into(),
            expected: format!("{namespace:?}"),
            actual: format!("{current_namespace:?}"),
        });
    }
    Ok(())
}

fn describe_statfs(stats: Option<FilesystemStats>, errno: Option<i32>) -> String {
    match (stats, errno) {
        (Some(stats), _) => format!(
            "type={} bsize={} blocks={} bfree={} bavail={} files={} ffree={} namelen={} frsize={} flags={:#x}",
            stats.f_type,
            stats.f_bsize,
            stats.f_blocks,
            stats.f_bfree,
            stats.f_bavail,
            stats.f_files,
            stats.f_ffree,
            stats.f_namelen,
            stats.f_frsize,
            stats.f_flags
        ),
        (None, Some(errno)) => format!("failed with errno {errno}"),
        (None, None) => "unrecorded".into(),
    }
}

/// Identity of the mount namespace a process is in, from `/proc/<pid>/ns/mnt`.
///
/// The same path can name different mounts in different namespaces, so a replay of a pathname
/// query is only meaningful inside the namespace the recording ran in. `pid == 0` is the
/// calling process.
pub fn namespace_identity(pid: u32) -> Option<NamespaceIdentity> {
    use std::os::unix::fs::MetadataExt;
    let directory = if pid == 0 {
        "self".to_owned()
    } else {
        pid.to_string()
    };
    let metadata = fs::metadata(format!("/proc/{directory}/ns/mnt")).ok()?;
    Some(NamespaceIdentity {
        device: metadata.dev(),
        inode: metadata.ino(),
    })
}

/// Repeats the recorded `statfs`/`fstatfs` query and returns what the kernel reports now.
///
/// Every field is compared by the caller. Capacity fields such as `f_bfree` and `f_ffree` move
/// with unrelated filesystem use, and that is exactly why they are kept: a program can read
/// them, so a value that moved is an observation that changed.
fn statfs_query(
    path: &Path,
    source: FilesystemStatsSource,
) -> Result<(Option<FilesystemStats>, Option<i32>), String> {
    use std::os::unix::ffi::OsStrExt;

    let path_bytes = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| "path contains a NUL byte".to_owned())?;
    let mut buffer = [0_i64; 15];
    // SAFETY: `buffer` is 120 bytes, the size of `struct statfs` on x86_64, and the kernel only
    // writes to it. The path string is NUL-terminated and outlives the call.
    let answer = unsafe {
        match source {
            FilesystemStatsSource::Path => {
                libc::syscall(libc::SYS_statfs, path_bytes.as_ptr(), buffer.as_mut_ptr())
            }
            FilesystemStatsSource::Descriptor => {
                let fd = libc::open(path_bytes.as_ptr(), libc::O_PATH | libc::O_CLOEXEC);
                if fd < 0 {
                    return Ok((
                        None,
                        Some(
                            io::Error::last_os_error()
                                .raw_os_error()
                                .unwrap_or(libc::EACCES),
                        ),
                    ));
                }
                let answer = libc::syscall(libc::SYS_fstatfs, fd, buffer.as_mut_ptr());
                let error = io::Error::last_os_error().raw_os_error();
                libc::close(fd);
                if answer != 0 {
                    return Ok((None, Some(error.unwrap_or(libc::EIO))));
                }
                return Ok((Some(statfs_from_words(&buffer)), None));
            }
        }
    };
    if answer != 0 {
        return Ok((
            None,
            Some(
                io::Error::last_os_error()
                    .raw_os_error()
                    .unwrap_or(libc::EIO),
            ),
        ));
    }
    Ok((Some(statfs_from_words(&buffer)), None))
}

/// `struct statfs` on x86_64: seven 8-byte fields, a two-`int` fsid, three more 8-byte fields,
/// then five 8-byte words that cover `f_flags` and `f_spare[4]`.
fn statfs_from_words(words: &[i64; 15]) -> FilesystemStats {
    FilesystemStats {
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

/// Repeats the recorded open with the same access mode.
///
/// A recorded `O_PATH` open needs search permission only, so replaying it as `O_RDONLY` would
/// deoptimize a record that a fresh run would still satisfy. Adding `O_DIRECTORY` is safe
/// because the caller has already required the path to still be a directory.
fn probe_directory_open(path: &Path, flags: i32) -> Result<(), String> {
    use std::os::unix::ffi::OsStrExt;

    let path_bytes = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| "path contains a NUL byte".to_owned())?;
    let access = if flags & libc::O_PATH != 0 {
        libc::O_PATH
    } else {
        libc::O_RDONLY
    };
    // SAFETY: path_bytes is a valid NUL-terminated string.
    let fd = unsafe {
        libc::open(
            path_bytes.as_ptr(),
            access | libc::O_DIRECTORY | libc::O_CLOEXEC,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error().to_string());
    }
    // SAFETY: fd was opened above and is not used afterwards.
    unsafe { libc::close(fd) };
    Ok(())
}

/// The first recorded entry buffer that a replay did not reproduce.
struct EnumerationDifference {
    index: usize,
    recorded: Vec<u8>,
    current: Vec<u8>,
}

/// Replays every recorded `getdents64` call and requires byte-identical results.
///
/// The directory is opened fresh and read from position zero, which is the only starting point
/// the tracer admits. A difference in entry order, `d_off`, `d_type`, `d_ino`, name bytes or the
/// call boundaries is an observed difference, so it deoptimizes instead of being normalised
/// away.
fn replay_directory_enumeration(
    path: &Path,
    requests: &[DirectoryEnumerationRequest],
) -> Result<Option<EnumerationDifference>, String> {
    use std::os::unix::ffi::OsStrExt;

    let path_bytes = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| "path contains a NUL byte".to_owned())?;
    // SAFETY: path_bytes is a valid NUL-terminated string.
    let fd = unsafe {
        libc::open(
            path_bytes.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error().to_string());
    }
    for (index, request) in requests.iter().enumerate() {
        let mut buffer = vec![0_u8; request.requested.max(1) as usize];
        // SAFETY: the buffer is valid for `requested` bytes and fd is an open directory.
        let read = unsafe {
            libc::syscall(
                libc::SYS_getdents64,
                fd,
                buffer.as_mut_ptr(),
                request.requested,
            )
        };
        if read < 0 {
            let error = io::Error::last_os_error().to_string();
            // SAFETY: fd was opened above and is not used afterwards.
            unsafe { libc::close(fd) };
            return Err(error);
        }
        buffer.truncate(read as usize);
        if buffer != request.returned {
            // SAFETY: fd was opened above and is not used afterwards.
            unsafe { libc::close(fd) };
            return Ok(Some(EnumerationDifference {
                index,
                recorded: request.returned.clone(),
                current: buffer,
            }));
        }
    }
    // SAFETY: fd was opened above and is not used afterwards.
    unsafe { libc::close(fd) };
    Ok(None)
}

/// Applies the side effects a reuse must reproduce on an inherited stream.
///
/// Only called after every guard has passed and cached output has been verified. A cached
/// execution that consumed bytes advanced the shared open file description; a reuse that did not
/// would leave the caller's descriptor in a different position than a direct run.
pub fn apply_inherited_stream_offsets(guards: &[Guard]) -> Result<(), String> {
    for guard in guards {
        if let Guard::InheritedStream {
            end_offset,
            start_offset,
            ..
        } = guard
        {
            // SAFETY: lseek only changes the descriptor's offset.
            let result = unsafe { libc::lseek(0, *end_offset as i64, libc::SEEK_SET) };
            if result < 0 || result as u64 != *end_offset {
                return Err(format!(
                    "could not advance inherited stdin from {start_offset} to {end_offset}: {}",
                    io::Error::last_os_error()
                ));
            }
        }
    }
    Ok(())
}

#[cfg(unix)]
fn validate_executable(path: &Path) -> Result<(), String> {
    use std::os::unix::ffi::OsStrExt;

    let path = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| "path contains a NUL byte".to_owned())?;
    // SAFETY: path is a valid NUL-terminated string and access does not retain it.
    if unsafe { libc::access(path.as_ptr(), libc::X_OK) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error().to_string())
    }
}

#[cfg(not(unix))]
fn validate_executable(path: &Path) -> Result<(), String> {
    path.is_file()
        .then_some(())
        .ok_or_else(|| "executable is not a file".into())
}

#[cfg(unix)]
fn evaluate_access(path: &Path, mode: i32, flags: i32) -> Result<Option<i32>, String> {
    use std::os::unix::ffi::OsStrExt;

    let path_bytes = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| "path contains a NUL byte".to_owned())?;
    #[cfg(target_os = "linux")]
    {
        // SAFETY: path_bytes is a valid NUL-terminated string; faccessat2 does not retain it.
        let answer = unsafe {
            libc::syscall(
                libc::SYS_faccessat2,
                libc::AT_FDCWD,
                path_bytes.as_ptr(),
                mode,
                flags,
            )
        };
        if answer != -1 {
            return Ok(None);
        }
        let error = io::Error::last_os_error();
        if error.raw_os_error() == Some(libc::ENOSYS) && flags == 0 {
            // Kernels before 5.8 lack faccessat2. Plain access(2) has exactly the real-credential
            // semantics the tracer recorded for flags == 0, so the fallback is equivalent.
            // SAFETY: path_bytes is a valid NUL-terminated string.
            if unsafe { libc::access(path_bytes.as_ptr(), mode) } != -1 {
                return Ok(None);
            }
            return Ok(Some(
                io::Error::last_os_error()
                    .raw_os_error()
                    .unwrap_or(libc::EACCES),
            ));
        }
        Ok(Some(error.raw_os_error().unwrap_or(libc::EACCES)))
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (mode, flags);
        Err("access checks are only replayed on Linux".into())
    }
}

/// Digest of a process's security-relevant identity: real, effective and saved ids, the
/// supplementary group set, and the capability sets that override discretionary access checks.
///
/// `pid == 0` means the calling process. `None` means the identity could not be read, which the
/// guard treats as a refusal.
pub fn credential_identity(pid: u32) -> Option<Hash> {
    let directory = if pid == 0 {
        "self".to_owned()
    } else {
        pid.to_string()
    };
    let status = std::fs::read_to_string(format!("/proc/{directory}/status")).ok()?;
    let mut hasher = blake3::Hasher::new();
    let mut found = 0_usize;
    for key in [
        "Uid:", "Gid:", "Groups:", "CapInh:", "CapPrm:", "CapEff:", "CapAmb:",
    ] {
        let line = status.lines().find(|line| line.starts_with(key))?;
        hasher.update(line.trim_end().as_bytes());
        hasher.update(b"\n");
        found += 1;
    }
    (found == 7).then(|| Hash::from(hasher.finalize()))
}

fn describe_credential(credential: Option<&Hash>) -> String {
    match credential {
        Some(value) => {
            let rendered = value.to_string();
            format!("identity {}", rendered.chars().take(16).collect::<String>())
        }
        None => "identity unavailable".to_owned(),
    }
}

fn describe_access(result: Option<i32>) -> String {
    match result {
        None => "permitted".into(),
        Some(errno) => format!("denied with errno {errno}"),
    }
}

pub fn validate_all(guards: &[Guard], mode: GuardMode) -> GuardReport {
    let mut index = 0;
    let mut passed = 0;
    while index < guards.len() {
        if let Guard::FileMetadata { path, expected } = &guards[index] {
            if let Some(hash_path) = guards.get(index + 1).and_then(content_hash_path) {
                if path == hash_path {
                    match guards[index].validate(mode) {
                        Ok(()) if mode == GuardMode::Fast => {
                            passed += 2;
                            index += 2;
                            continue;
                        }
                        Ok(()) => {
                            passed += 1;
                            index += 1;
                            continue;
                        }
                        Err(_metadata_failure)
                            if metadata_change_allows_hash_fallback(path, expected) =>
                        {
                            match guards[index + 1].validate(mode) {
                                Ok(()) => {
                                    passed += 2;
                                    index += 2;
                                    continue;
                                }
                                Err(hash_failure) => {
                                    return GuardReport {
                                        checked: index + 2,
                                        passed,
                                        failure: Some(hash_failure),
                                    };
                                }
                            }
                        }
                        Err(failure) => {
                            return GuardReport {
                                checked: index + 1,
                                passed,
                                failure: Some(failure),
                            };
                        }
                    }
                }
            }
        }
        match guards[index].validate(mode) {
            Ok(()) => passed += 1,
            Err(failure) => {
                return GuardReport {
                    checked: index + 1,
                    passed,
                    failure: Some(failure),
                };
            }
        }
        index += 1;
    }
    GuardReport {
        checked: guards.len(),
        passed,
        failure: None,
    }
}

fn metadata_change_allows_hash_fallback(path: &Path, expected: &FileFingerprint) -> bool {
    if expected.is_absent() {
        return false;
    }
    fingerprint(path).is_ok_and(|actual| {
        actual.mode == expected.mode && actual.uid == expected.uid && actual.gid == expected.gid
    })
}

fn content_hash_path(guard: &Guard) -> Option<&Path> {
    match guard {
        Guard::ExecutableHash { path, .. } | Guard::FileHash { path, .. } => Some(path),
        _ => None,
    }
}

pub fn compile_guards(executable: PathBuf, identity: &ExecutionIdentity) -> Vec<Guard> {
    let executable_metadata = fingerprint(&executable).ok();
    let mut guards = Vec::new();
    if let Some(expected) = executable_metadata {
        guards.push(Guard::FileMetadata {
            path: executable.clone(),
            expected,
        });
    }
    guards.extend([
        Guard::ExecutableHash {
            path: executable,
            expected: identity.executable_hash,
        },
        Guard::WorkingDirectory {
            expected: identity.cwd.clone(),
        },
        Guard::RuntimeIdentity {
            expected: identity.runtime_identity.clone(),
        },
    ]);
    guards.extend(
        identity
            .environment
            .iter()
            .map(|(key, value)| Guard::EnvironmentValue {
                key: key.clone(),
                expected: Some(value.clone()),
            }),
    );
    for dependency in &identity.input_dependencies {
        match dependency {
            InputDependency::Executable {
                path,
                expected_hash,
                fingerprint,
            } => {
                if let Some(expected) = fingerprint {
                    guards.push(Guard::FileMetadata {
                        path: path.clone(),
                        expected: expected.clone(),
                    });
                }
                guards.push(Guard::ExecutableHash {
                    path: path.clone(),
                    expected: *expected_hash,
                });
            }
            InputDependency::File {
                path,
                expected_hash,
                fingerprint,
            } => {
                if let Some(expected) = fingerprint {
                    guards.push(Guard::FileMetadata {
                        path: path.clone(),
                        expected: expected.clone(),
                    });
                }
                guards.push(Guard::FileHash {
                    path: path.clone(),
                    expected: *expected_hash,
                });
            }
            InputDependency::Metadata { path, fingerprint } => guards.push(Guard::FileMetadata {
                path: path.clone(),
                expected: fingerprint.clone(),
            }),
            InputDependency::DirectoryOpened {
                path,
                fingerprint,
                flags,
                credential,
            } => guards.push(Guard::DirectoryOpened {
                path: path.clone(),
                expected: fingerprint.clone(),
                flags: *flags,
                credential: *credential,
            }),
            InputDependency::DirectoryEnumerated {
                path,
                requests,
                fingerprint,
                credential,
                mount_namespace,
            } => guards.push(Guard::DirectoryEnumerated {
                path: path.clone(),
                requests: requests.clone(),
                expected: fingerprint.clone().unwrap_or_else(FileFingerprint::absent),
                credential: *credential,
                mount_namespace: *mount_namespace,
            }),
            InputDependency::FilesystemStats {
                path,
                source,
                stats,
                errno,
                fingerprint,
                credential,
                mount_namespace,
            } => guards.push(Guard::FilesystemStats {
                path: path.clone(),
                source: *source,
                expected: *stats,
                errno: *errno,
                fingerprint: fingerprint.clone(),
                credential: *credential,
                mount_namespace: *mount_namespace,
            }),
            InputDependency::InheritedStream {
                path,
                expected_hash,
                fingerprint,
                start_offset,
                end_offset,
                bytes_read: _,
            } => guards.push(Guard::InheritedStream {
                path: path.clone(),
                expected_hash: *expected_hash,
                fingerprint: fingerprint.clone(),
                start_offset: *start_offset,
                end_offset: *end_offset,
            }),
            InputDependency::SymlinkMetadata { path, fingerprint } => {
                guards.push(Guard::SymlinkMetadata {
                    path: path.clone(),
                    expected: fingerprint.clone(),
                });
            }
            InputDependency::Symlink { path, target } => guards.push(Guard::SymlinkTarget {
                path: path.clone(),
                expected: target.clone(),
            }),
            InputDependency::Access {
                path,
                mode,
                flags,
                errno,
                credential,
            } => guards.push(Guard::AccessCheck {
                path: path.clone(),
                mode: *mode,
                flags: *flags,
                expected: *errno,
                credential: *credential,
            }),
        }
    }
    guards.push(Guard::NoUnexpectedEffects);
    guards
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[cfg(unix)]
    #[test]
    fn an_access_check_without_a_recorded_identity_is_refused() {
        // A record written before identities were captured cannot be replayed soundly, so it must
        // deoptimize rather than be trusted.
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("probe");
        fs::write(&path, b"present").unwrap();
        let guard = Guard::AccessCheck {
            path,
            mode: libc::F_OK,
            flags: 0,
            expected: None,
            credential: None,
        };
        let failure = guard.validate(GuardMode::Strict).unwrap_err();
        assert!(failure.reason.contains("credentials"), "{failure:?}");
    }

    #[cfg(unix)]
    #[test]
    fn an_access_check_replays_only_for_the_recorded_identity() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("probe");
        fs::write(&path, b"present").unwrap();
        let guard = Guard::AccessCheck {
            path: path.clone(),
            mode: libc::F_OK,
            flags: 0,
            expected: None,
            credential: credential_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::remove_file(&path).unwrap();
        let failure = guard.validate(GuardMode::Strict).unwrap_err();
        assert!(
            failure.reason.contains("access check result changed"),
            "{failure:?}"
        );
    }

    #[test]
    fn canonical_hash_is_stable_for_sorted_maps() {
        let left = std::collections::BTreeMap::from([("a", 1), ("b", 2)]);
        let right = std::collections::BTreeMap::from([("b", 2), ("a", 1)]);
        assert_eq!(
            canonical_hash(&left).unwrap(),
            canonical_hash(&right).unwrap()
        );
    }

    #[test]
    fn file_hash_guard_detects_change() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("input");
        let mut file = File::create(&path).unwrap();
        file.write_all(b"before").unwrap();
        let guard = Guard::FileHash {
            path: path.clone(),
            expected: hash_file(&path).unwrap(),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::write(&path, b"after").unwrap();
        assert!(guard.validate(GuardMode::Strict).is_err());
    }

    #[test]
    fn guard_report_stops_at_first_failure() {
        let guards = vec![
            Guard::NoUnexpectedEffects,
            Guard::WorkingDirectory {
                expected: PathBuf::from("/not/the/current/directory"),
            },
            Guard::NoUnexpectedEffects,
        ];
        let report = validate_all(&guards, GuardMode::Strict);
        assert_eq!(report.checked, 2);
        assert_eq!(report.passed, 1);
        assert!(report.failure.is_some());
    }

    #[test]
    fn absence_metadata_guard_detects_creation() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("optional-input");
        let guard = Guard::FileMetadata {
            path: path.clone(),
            expected: FileFingerprint::absent(),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::write(&path, b"now present").unwrap();
        assert!(guard.validate(GuardMode::Strict).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn symlink_metadata_guard_detects_target_replacement() {
        let directory = tempfile::tempdir().unwrap();
        let first = directory.path().join("first");
        let second = directory.path().join("second");
        let link = directory.path().join("link");
        fs::write(&first, b"same").unwrap();
        fs::write(&second, b"same").unwrap();
        std::os::unix::fs::symlink(&first, &link).unwrap();
        let guard = Guard::SymlinkMetadata {
            path: link.clone(),
            expected: symlink_fingerprint(&link).unwrap(),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::remove_file(&link).unwrap();
        std::os::unix::fs::symlink(&second, &link).unwrap();
        assert!(guard.validate(GuardMode::Strict).is_err());
    }

    #[test]
    fn fast_mode_accepts_unchanged_metadata_without_hashing() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("input");
        fs::write(&path, b"content").unwrap();
        let guards = vec![
            Guard::FileMetadata {
                path: path.clone(),
                expected: fingerprint(&path).unwrap(),
            },
            Guard::FileHash {
                path,
                expected: Hash::from(blake3::hash(b"deliberately different")),
            },
        ];
        let report = validate_all(&guards, GuardMode::Fast);
        assert_eq!(report.passed, 2);
        assert!(report.failure.is_none());
    }

    #[test]
    fn strict_mode_hashes_after_safe_metadata_change() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("input");
        let replacement = directory.path().join("replacement");
        fs::write(&path, b"same content").unwrap();
        let expected_metadata = fingerprint(&path).unwrap();
        let expected_hash = hash_file(&path).unwrap();
        fs::write(&replacement, b"same content").unwrap();
        fs::rename(replacement, &path).unwrap();
        let guards = vec![
            Guard::FileMetadata {
                path: path.clone(),
                expected: expected_metadata,
            },
            Guard::FileHash {
                path,
                expected: expected_hash,
            },
        ];
        let report = validate_all(&guards, GuardMode::Strict);
        assert_eq!(report.passed, 2);
        assert!(report.failure.is_none());
    }

    #[test]
    fn directory_open_guard_ignores_entries_created_beside_an_input() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        fs::create_dir(&directory).unwrap();
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected: fingerprint(&directory).unwrap(),
            flags: 0,
            credential: credential_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        // Every one of these mutates mtime, ctime, size, or link count. An open observes none of
        // them, so none of them may invalidate the entry.
        fs::write(directory.join("sibling"), b"data").unwrap();
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::remove_file(directory.join("sibling")).unwrap();
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::create_dir(directory.join("child")).unwrap();
        assert!(guard.validate(GuardMode::Strict).is_ok());
    }

    #[test]
    fn directory_open_guard_ignores_timestamps_size_and_link_count() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        fs::create_dir(&directory).unwrap();
        let mut expected = fingerprint(&directory).unwrap();
        expected.accessed_ns += 1_000_000_000;
        expected.modified_ns += 1_000_000_000;
        expected.changed_ns += 1_000_000_000;
        expected.size += 4096;
        expected.blocks += 8;
        expected.link_count += 1;
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected,
            flags: 0,
            credential: credential_identity(0),
        };
        // None of these are observable through an open, so none may invalidate reuse.
        assert!(guard.validate(GuardMode::Strict).is_ok());
    }

    #[test]
    fn directory_open_guard_detects_permission_change() {
        use std::os::unix::fs::PermissionsExt;

        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        fs::create_dir(&directory).unwrap();
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected: fingerprint(&directory).unwrap(),
            flags: 0,
            credential: credential_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o500)).unwrap();
        assert_eq!(
            guard.validate(GuardMode::Strict).unwrap_err().reason,
            "directory identity or permissions changed"
        );
    }

    #[test]
    fn directory_open_guard_detects_removal() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        fs::create_dir(&directory).unwrap();
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected: fingerprint(&directory).unwrap(),
            flags: 0,
            credential: credential_identity(0),
        };
        fs::remove_dir(&directory).unwrap();
        assert_eq!(
            guard.validate(GuardMode::Strict).unwrap_err().reason,
            "directory is unavailable"
        );
    }

    /// Replacement is tested with both directories alive at once so the replacement cannot land on
    /// the just-freed inode: a filesystem is free to reuse it, which would make this test flaky
    /// rather than wrong.
    #[test]
    fn directory_open_guard_detects_replacement() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        let replacement = root.path().join("replacement");
        fs::create_dir(&directory).unwrap();
        fs::create_dir(&replacement).unwrap();
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected: fingerprint(&directory).unwrap(),
            flags: 0,
            credential: credential_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::remove_dir(&directory).unwrap();
        fs::rename(&replacement, &directory).unwrap();
        assert_eq!(
            guard.validate(GuardMode::Strict).unwrap_err().reason,
            "directory identity or permissions changed"
        );
    }

    #[test]
    fn directory_open_guard_detects_a_type_change() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        fs::create_dir(&directory).unwrap();
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected: fingerprint(&directory).unwrap(),
            flags: 0,
            credential: credential_identity(0),
        };
        fs::remove_dir(&directory).unwrap();
        fs::write(&directory, b"a file where a directory was").unwrap();
        assert_eq!(
            guard.validate(GuardMode::Strict).unwrap_err().reason,
            "path is no longer a directory"
        );
    }

    /// The reduced comparison must not leak into genuine directory metadata reads.
    #[test]
    fn explicit_directory_metadata_guard_still_compares_timestamps() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("work");
        fs::create_dir(&directory).unwrap();
        assert!(Guard::DirectoryOpened {
            path: directory.clone(),
            expected: fingerprint(&directory).unwrap(),
            flags: 0,
            credential: credential_identity(0),
        }
        .validate(GuardMode::Strict)
        .is_ok());
        // The expected fingerprint is synthesized so the assertion depends on the comparison
        // itself, not on how quickly this filesystem publishes an entry-creation timestamp to a
        // later `stat` in the same process (measured: it can lag by tens of milliseconds here).
        let mut changed = fingerprint(&directory).unwrap();
        changed.modified_ns += 1_000_000_000;
        changed.changed_ns += 1_000_000_000;
        let guard = Guard::FileMetadata {
            path: directory.clone(),
            expected: changed,
        };
        assert_eq!(
            guard.validate(GuardMode::Strict).unwrap_err().reason,
            "file metadata changed"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn access_guard_replays_the_kernel_answer() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("probe");
        fs::write(&path, b"x").unwrap();
        let guard = Guard::AccessCheck {
            path: path.clone(),
            mode: libc::F_OK,
            flags: 0,
            expected: None,
            credential: credential_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::remove_file(&path).unwrap();
        let failure = guard.validate(GuardMode::Strict).unwrap_err();
        assert_eq!(failure.reason, "access check result changed");
        assert!(failure.actual.contains(&libc::ENOENT.to_string()));
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn access_guard_keeps_a_recorded_denial_that_still_holds() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("absent");
        let guard = Guard::AccessCheck {
            path,
            mode: libc::F_OK,
            flags: 0,
            expected: Some(libc::ENOENT),
            credential: credential_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn content_hash_does_not_override_permission_change() {
        use std::os::unix::fs::PermissionsExt;

        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("input");
        fs::write(&path, b"same content").unwrap();
        let expected_metadata = fingerprint(&path).unwrap();
        let expected_hash = hash_file(&path).unwrap();
        let changed_mode = expected_metadata.mode ^ 0o100;
        fs::set_permissions(&path, fs::Permissions::from_mode(changed_mode)).unwrap();
        let guards = vec![
            Guard::FileMetadata {
                path: path.clone(),
                expected: expected_metadata,
            },
            Guard::FileHash {
                path,
                expected: expected_hash,
            },
        ];
        assert!(validate_all(&guards, GuardMode::Strict).failure.is_some());
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn filesystem_stat_guard_replays_every_field_and_detects_capacity_change() {
        // `/proc` is a pseudo-filesystem whose statfs answer is constant, so the assertion is
        // about the comparison and not about how busy the host is.
        let path = Path::new("/proc");
        let (stats, errno) = statfs_query(path, FilesystemStatsSource::Path).unwrap();
        let stats = stats.expect("statfs on /proc succeeds");
        assert!(errno.is_none());
        let guard = Guard::FilesystemStats {
            path: path.to_path_buf(),
            source: FilesystemStatsSource::Path,
            expected: Some(stats),
            errno: None,
            fingerprint: Some(fingerprint(path).unwrap()),
            credential: credential_identity(0),
            mount_namespace: namespace_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        // A capacity field is exactly the kind of value a program can read, so a change to it
        // must deoptimize instead of being treated as noise.
        let mut moved = stats;
        moved.f_bfree = moved.f_bfree.wrapping_sub(1);
        let moved_guard = Guard::FilesystemStats {
            path: path.to_path_buf(),
            source: FilesystemStatsSource::Path,
            expected: Some(moved),
            errno: None,
            fingerprint: Some(fingerprint(path).unwrap()),
            credential: credential_identity(0),
            mount_namespace: namespace_identity(0),
        };
        let failure = moved_guard.validate(GuardMode::Strict).unwrap_err();
        assert!(
            failure.reason.contains("filesystem statistics changed"),
            "{failure:?}"
        );
        // A descriptor-sourced query is replayed as a descriptor query, not as a pathname one.
        let descriptor = Guard::FilesystemStats {
            path: path.to_path_buf(),
            source: FilesystemStatsSource::Descriptor,
            expected: Some(stats),
            errno: None,
            fingerprint: Some(fingerprint(path).unwrap()),
            credential: credential_identity(0),
            mount_namespace: namespace_identity(0),
        };
        assert!(descriptor.validate(GuardMode::Strict).is_ok());
    }

    #[cfg(target_os = "linux")]
    fn enumerate(path: &Path) -> Vec<DirectoryEnumerationRequest> {
        use std::os::unix::ffi::OsStrExt;

        let name = std::ffi::CString::new(path.as_os_str().as_bytes()).unwrap();
        // SAFETY: name is a valid NUL-terminated string.
        let fd = unsafe {
            libc::open(
                name.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC,
            )
        };
        assert!(fd >= 0);
        let mut requests = Vec::new();
        loop {
            let requested = 4096_u64;
            let mut buffer = vec![0_u8; requested as usize];
            // SAFETY: buffer is valid for `requested` bytes and fd is an open directory.
            let read =
                unsafe { libc::syscall(libc::SYS_getdents64, fd, buffer.as_mut_ptr(), requested) };
            assert!(read >= 0);
            buffer.truncate(read as usize);
            let eof = buffer.is_empty();
            requests.push(DirectoryEnumerationRequest {
                requested,
                returned: buffer,
            });
            if eof {
                break;
            }
        }
        // SAFETY: fd was opened above and is not used afterwards.
        unsafe { libc::close(fd) };
        requests
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn directory_enumeration_guard_replays_the_exact_entry_stream() {
        let directory = tempfile::tempdir().unwrap();
        fs::write(directory.path().join("a"), b"a").unwrap();
        fs::write(directory.path().join("b"), b"b").unwrap();
        let requests = enumerate(directory.path());
        assert!(!requests.is_empty());
        let guard = Guard::DirectoryEnumerated {
            path: directory.path().to_path_buf(),
            requests,
            expected: fingerprint(directory.path()).unwrap(),
            credential: credential_identity(0),
            mount_namespace: namespace_identity(0),
        };
        assert!(guard.validate(GuardMode::Strict).is_ok());
        // A new entry changes the byte stream, including its order and cookies.
        fs::write(directory.path().join("c"), b"c").unwrap();
        let failure = guard.validate(GuardMode::Strict).unwrap_err();
        assert!(
            failure.reason.contains("entry stream changed"),
            "{failure:?}"
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn inherited_stream_guard_refuses_stdin_that_is_not_the_recorded_file() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("input.txt");
        fs::write(&path, b"payload").unwrap();
        let guard = Guard::InheritedStream {
            path: path.clone(),
            expected_hash: Some(hash_file(&path).unwrap()),
            fingerprint: Some(fingerprint(&path).unwrap()),
            start_offset: 0,
            end_offset: 7,
        };
        // The test harness stdin is not this file, so the guard must fail closed rather than
        // reuse output computed from different bytes.
        let failure = guard.validate(GuardMode::Strict).unwrap_err();
        assert!(failure.reason.contains("inherited stdin"), "{failure:?}");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn directory_open_guard_replays_o_path_without_read_permission() {
        use std::os::unix::fs::PermissionsExt;

        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("search-only");
        fs::create_dir(&directory).unwrap();
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o100)).unwrap();
        let expected = fingerprint(&directory).unwrap();
        let guard = Guard::DirectoryOpened {
            path: directory.clone(),
            expected,
            flags: libc::O_PATH,
            credential: credential_identity(0),
        };
        // `O_PATH` needs search permission only. Replaying it as a read would deoptimize a
        // record that a fresh `O_PATH` open still satisfies.
        assert!(guard.validate(GuardMode::Strict).is_ok());
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn directory_open_guard_requires_the_recorded_credentials() {
        let root = tempfile::tempdir().unwrap();
        let guard = Guard::DirectoryOpened {
            path: root.path().to_path_buf(),
            expected: fingerprint(root.path()).unwrap(),
            flags: 0,
            credential: None,
        };
        let failure = guard.validate(GuardMode::Strict).unwrap_err();
        assert!(failure.reason.contains("credentials"), "{failure:?}");
    }
}

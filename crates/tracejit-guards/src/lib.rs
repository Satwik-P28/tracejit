use serde::{Deserialize, Serialize};
use std::ffi::{CStr, OsString};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use tracejit_effects::{
    ExecutionIdentity, FileFingerprint, Hash, InputDependency, RuntimeIdentity,
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
    SymlinkTarget {
        path: PathBuf,
        expected: Option<PathBuf>,
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
    use std::os::unix::fs::MetadataExt;

    let metadata = fs::metadata(path).map_err(|source| GuardError::Io {
        path: path.to_path_buf(),
        source,
    })?;
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
            Self::NoUnexpectedEffects => Ok(()),
        }
    }
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
            InputDependency::Symlink { path, target } => guards.push(Guard::SymlinkTarget {
                path: path.clone(),
                expected: target.clone(),
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
}

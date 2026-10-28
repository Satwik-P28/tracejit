use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::cell::Cell;
use std::fs::{self, File};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use tempfile::{NamedTempFile, TempPath};
use tracejit_effects::{DeterminismClass, EffectRecord, ExecutionIdentity, Hash, Trace};
use tracejit_guards::{hash_reader, Guard, GuardFailure};

#[derive(Debug, thiserror::Error)]
pub enum CacheError {
    #[error("cache I/O failed at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("cache database failed: {0}")]
    Database(#[from] rusqlite::Error),
    #[error("cache metadata is corrupt: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("CAS object {hash} is corrupt")]
    CorruptObject { hash: Hash },
    #[error("output path has no parent: {0}")]
    InvalidOutputPath(PathBuf),
    #[error("cached output precondition failed at {path}: {reason}")]
    OutputPrecondition { path: PathBuf, reason: String },
    #[error("refusing to use unsafe cache root {path}: {reason}")]
    UnsafeRoot { path: PathBuf, reason: String },
    #[error("output restoration failed after mutating the workspace: {reason}")]
    RestorationRollback { reason: String },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum OutputKind {
    File,
    Deleted,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct OutputArtifact {
    pub path: PathBuf,
    pub kind: OutputKind,
    pub content: Option<Hash>,
    pub unix_mode: Option<u32>,
    pub allows_create: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum CacheDecision {
    Executed,
    Reused,
    Deoptimized,
    Ineligible,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DecisionRecord {
    pub decision: CacheDecision,
    pub reason: String,
    pub guard_failure: Option<GuardFailure>,
    pub decided_unix_ms: u128,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct StoredExecution {
    pub id: String,
    pub lookup_key: Hash,
    pub command: Vec<std::ffi::OsString>,
    pub executable: PathBuf,
    pub identity: ExecutionIdentity,
    pub classification: DeterminismClass,
    pub classification_reasons: Vec<String>,
    pub effects: Vec<EffectRecord>,
    pub guards: Vec<Guard>,
    pub outputs: Vec<OutputArtifact>,
    pub stdout: Hash,
    pub stderr: Hash,
    pub exit_code: i32,
    pub baseline_runtime_ns: u128,
    #[serde(default)]
    pub process_count: usize,
    /// Kept for in-memory reports. The cache stores `process_count` instead of this duplicate.
    #[serde(default, skip_serializing)]
    pub trace: Trace,
    pub last_decision: DecisionRecord,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CacheStats {
    pub executions: u64,
    pub objects: u64,
    pub object_bytes: u64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct OpenTimings {
    pub prepare_ns: u64,
    pub sqlite_open_ns: u64,
    pub schema_ns: u64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct QueryTimings {
    pub query_ns: u64,
    pub decode_ns: u64,
}

pub struct Cache {
    root: PathBuf,
    objects: PathBuf,
    executions: PathBuf,
    connection: Connection,
    pub open_timings: OpenTimings,
    last_query: Cell<QueryTimings>,
}

impl Cache {
    pub fn open(root: impl Into<PathBuf>) -> Result<Self, CacheError> {
        let root = root.into();
        let started = Instant::now();
        prepare_root(&root)?;
        let objects = root.join("objects");
        let executions = root.join("executions");
        create_dir_all(&objects)?;
        create_dir_all(&executions)?;
        let prepare_ns = u64_nanos(started);
        let database = root.join("db.sqlite3");
        let started = Instant::now();
        let connection = Connection::open(&database)?;
        let sqlite_open_ns = u64_nanos(started);
        let started = Instant::now();
        connection.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA busy_timeout=10000;
             PRAGMA synchronous=FULL;
             CREATE TABLE IF NOT EXISTS executions (
                 lookup_key TEXT PRIMARY KEY NOT NULL,
                 execution_id TEXT NOT NULL,
                 record_json BLOB NOT NULL,
                 updated_unix_ms TEXT NOT NULL
             );",
        )?;
        let schema_ns = u64_nanos(started);
        Ok(Self {
            root,
            objects,
            executions,
            connection,
            open_timings: OpenTimings {
                prepare_ns,
                sqlite_open_ns,
                schema_ns,
            },
            last_query: Cell::new(QueryTimings::default()),
        })
    }

    pub fn last_query(&self) -> QueryTimings {
        self.last_query.get()
    }

    pub fn default_root() -> PathBuf {
        if let Some(root) = std::env::var_os("TRACEJIT_CACHE_DIR") {
            return PathBuf::from(root);
        }
        std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".cache/tracejit")
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Stores `bytes` under their BLAKE3 hash and returns it.
    ///
    /// Reading an object always rehashes it, so an object that does not match its own name
    /// can never be served. Writing one is therefore allowed to *repair* that name instead
    /// of refusing forever: the bytes written here are exactly the bytes whose BLAKE3 digest
    /// is the destination name. The replacement is a temporary file plus rename, so a
    /// concurrent reader sees either the old object or the new one, never a partial one.
    pub fn put_bytes(&self, bytes: &[u8]) -> Result<Hash, CacheError> {
        let hash = Hash::from(blake3::hash(bytes));
        let destination = self.objects.join(hash.to_string());
        if destination.exists() && self.verify_object(hash).is_ok() {
            return Ok(hash);
        }
        let mut temporary = NamedTempFile::new_in(&self.objects)
            .map_err(|source| io_error(&self.objects, source))?;
        temporary
            .write_all(bytes)
            .and_then(|()| temporary.as_file().sync_all())
            .map_err(|source| io_error(temporary.path(), source))?;
        match temporary.persist_noclobber(&destination) {
            Ok(_) => {}
            Err(error) if error.error.kind() == io::ErrorKind::AlreadyExists => {
                // Either another process stored the same object first, or the existing name
                // holds content that does not match it. Only the second case is repaired.
                if self.verify_object(hash).is_err() {
                    error
                        .file
                        .persist(&destination)
                        .map_err(|error| io_error(&destination, error.error))?;
                }
            }
            Err(error) => return Err(io_error(&destination, error.error)),
        }
        Ok(hash)
    }

    pub fn get_bytes(&self, hash: Hash) -> Result<Vec<u8>, CacheError> {
        let path = self.objects.join(hash.to_string());
        let bytes = fs::read(&path).map_err(|source| io_error(&path, source))?;
        if Hash::from(blake3::hash(&bytes)) != hash {
            return Err(CacheError::CorruptObject { hash });
        }
        Ok(bytes)
    }

    pub fn put_execution(&mut self, record: &StoredExecution) -> Result<(), CacheError> {
        let json = serde_json::to_vec(record)?;
        let record_path = self.executions.join(format!("{}.json", record.id));
        atomic_write(&record_path, &json)?;
        let transaction = self.connection.transaction()?;
        transaction.execute(
            "INSERT INTO executions (lookup_key, execution_id, record_json, updated_unix_ms)
             VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(lookup_key) DO UPDATE SET
               execution_id=excluded.execution_id,
               record_json=excluded.record_json,
               updated_unix_ms=excluded.updated_unix_ms",
            params![
                record.lookup_key.to_string(),
                record.id,
                json,
                now_unix_ms().to_string()
            ],
        )?;
        transaction.commit()?;
        Ok(())
    }

    pub fn find(&self, lookup_key: Hash) -> Result<Option<StoredExecution>, CacheError> {
        let started = Instant::now();
        let json: Option<Vec<u8>> = self
            .connection
            .query_row(
                "SELECT record_json FROM executions WHERE lookup_key = ?1",
                [lookup_key.to_string()],
                |row| row.get(0),
            )
            .optional()?;
        let query_ns = u64_nanos(started);
        let started = Instant::now();
        let record = json
            .map(|bytes| serde_json::from_slice(&bytes).map_err(CacheError::from))
            .transpose()?;
        self.last_query.set(QueryTimings {
            query_ns,
            decode_ns: u64_nanos(started),
        });
        Ok(record)
    }

    pub fn find_by_id(&self, id: &str) -> Result<Option<StoredExecution>, CacheError> {
        let json: Option<Vec<u8>> = self
            .connection
            .query_row(
                "SELECT record_json FROM executions WHERE execution_id = ?1",
                [id],
                |row| row.get(0),
            )
            .optional()?;
        json.map(|bytes| serde_json::from_slice(&bytes).map_err(CacheError::from))
            .transpose()
    }

    pub fn latest(&self) -> Result<Option<StoredExecution>, CacheError> {
        let json: Option<Vec<u8>> = self
            .connection
            .query_row(
                "SELECT record_json FROM executions ORDER BY CAST(updated_unix_ms AS INTEGER) DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        json.map(|bytes| serde_json::from_slice(&bytes).map_err(CacheError::from))
            .transpose()
    }

    /// Restores every captured output.
    ///
    /// This is deliberately *not* a single atomic multi-file transaction. It runs in
    /// phases so that nothing is mutated until every destination precondition, every
    /// content-addressed object, and every rollback backup is ready:
    ///
    /// 1. validate every destination precondition;
    /// 2. verify every CAS object and write it to a temporary file in the destination
    ///    directory;
    /// 3. hard-link each destination that already exists to a temporary backup name in
    ///    the same directory;
    /// 4. rename each staged file over its destination, or remove a deleted path.
    ///
    /// A failure in phase 4 rolls the already-applied outputs back from those backups
    /// before returning, so the caller observes either the fully restored workspace or
    /// the one it started with. A hard kill between two renames can still leave a mixed
    /// workspace and stray staging or backup files; there is no recovery journal.
    pub fn restore_outputs(&self, outputs: &[OutputArtifact]) -> Result<(), CacheError> {
        for output in outputs {
            validate_output_precondition(output)?;
        }
        let mut staged = Vec::with_capacity(outputs.len());
        for output in outputs {
            staged.push(self.stage_output(output)?);
        }
        let mut backups = Vec::with_capacity(outputs.len());
        for output in outputs {
            backups.push(match fs::symlink_metadata(&output.path) {
                Ok(_) => Some(backup_destination(&output.path)?),
                Err(error) if error.kind() == io::ErrorKind::NotFound => None,
                Err(source) => return Err(io_error(&output.path, source)),
            });
        }
        let mut applied: Vec<AppliedOutput> = Vec::new();
        for ((output, staged), backup) in outputs.iter().zip(staged).zip(backups) {
            if fault::should_fail(&output.path) {
                let error = CacheError::OutputPrecondition {
                    path: output.path.clone(),
                    reason: "injected restoration failure".into(),
                };
                return Err(rollback_restoration(&applied, error));
            }
            match apply_output(output, staged, backup) {
                Ok(Some(entry)) => applied.push(entry),
                Ok(None) => {}
                Err(error) => return Err(rollback_restoration(&applied, error)),
            }
        }
        Ok(())
    }

    /// Verifies one cached output and stages it without touching the destination.
    fn stage_output(&self, output: &OutputArtifact) -> Result<StagedOutput, CacheError> {
        let parent = output
            .path
            .parent()
            .ok_or_else(|| CacheError::InvalidOutputPath(output.path.clone()))?;
        match output.kind {
            OutputKind::Deleted => Ok(StagedOutput::Absence),
            OutputKind::File => {
                let hash = output
                    .content
                    .ok_or_else(|| CacheError::InvalidOutputPath(output.path.clone()))?;
                // get_bytes rehashes the object, so corruption is detected before any
                // destination is touched.
                let bytes = self.get_bytes(hash)?;
                let mut temporary =
                    NamedTempFile::new_in(parent).map_err(|source| io_error(parent, source))?;
                temporary
                    .write_all(&bytes)
                    .and_then(|()| temporary.as_file().sync_all())
                    .map_err(|source| io_error(temporary.path(), source))?;
                #[cfg(unix)]
                if let Some(mode) = output.unix_mode {
                    use std::os::unix::fs::PermissionsExt;
                    temporary
                        .as_file()
                        .set_permissions(fs::Permissions::from_mode(mode))
                        .map_err(|source| io_error(temporary.path(), source))?;
                }
                Ok(StagedOutput::Content(temporary))
            }
        }
    }

    pub fn stats(&self) -> Result<CacheStats, CacheError> {
        let executions =
            self.connection
                .query_row("SELECT COUNT(*) FROM executions", [], |row| row.get(0))?;
        let mut objects = 0_u64;
        let mut object_bytes = 0_u64;
        for entry in
            fs::read_dir(&self.objects).map_err(|source| io_error(&self.objects, source))?
        {
            let entry = entry.map_err(|source| io_error(&self.objects, source))?;
            if entry
                .file_type()
                .map_err(|source| io_error(entry.path(), source))?
                .is_file()
            {
                objects += 1;
                object_bytes += entry
                    .metadata()
                    .map_err(|source| io_error(entry.path(), source))?
                    .len();
            }
        }
        Ok(CacheStats {
            executions,
            objects,
            object_bytes,
        })
    }

    pub fn clear(self) -> Result<(), CacheError> {
        drop(self.connection);
        let marker = self.root.join(".tracejit-cache-v1");
        if !marker.is_file() {
            return Err(CacheError::UnsafeRoot {
                path: self.root,
                reason: "cache ownership marker is missing".into(),
            });
        }
        for directory in [&self.objects, &self.executions] {
            if directory.exists() {
                fs::remove_dir_all(directory).map_err(|source| io_error(directory, source))?;
            }
        }
        for name in [
            "db.sqlite3",
            "db.sqlite3-wal",
            "db.sqlite3-shm",
            "db.sqlite3-journal",
            ".tracejit-cache-v1",
        ] {
            let path = self.root.join(name);
            match fs::remove_file(&path) {
                Ok(()) => {}
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(source) => return Err(io_error(&path, source)),
            }
        }
        match fs::remove_dir(&self.root) {
            Ok(()) => {}
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::DirectoryNotEmpty | io::ErrorKind::NotFound
                ) => {}
            Err(source) => return Err(io_error(&self.root, source)),
        }
        Ok(())
    }

    fn verify_object(&self, hash: Hash) -> Result<(), CacheError> {
        let path = self.objects.join(hash.to_string());
        let file = File::open(&path).map_err(|source| io_error(&path, source))?;
        let actual = hash_reader(file).map_err(|source| io_error(&path, source))?;
        if actual != hash {
            return Err(CacheError::CorruptObject { hash });
        }
        Ok(())
    }
}

fn prepare_root(root: &Path) -> Result<(), CacheError> {
    if let Ok(metadata) = fs::symlink_metadata(root) {
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(CacheError::UnsafeRoot {
                path: root.to_path_buf(),
                reason: "root must be a real directory, not a symlink or file".into(),
            });
        }
    } else {
        create_dir_all(root)?;
    }
    let marker = root.join(".tracejit-cache-v1");
    if marker.is_file() {
        return Ok(());
    }
    let allowed = [
        "objects",
        "executions",
        "db.sqlite3",
        "db.sqlite3-wal",
        "db.sqlite3-shm",
        "db.sqlite3-journal",
    ];
    for entry in fs::read_dir(root).map_err(|source| io_error(root, source))? {
        let entry = entry.map_err(|source| io_error(root, source))?;
        if !allowed.iter().any(|name| entry.file_name() == *name) {
            return Err(CacheError::UnsafeRoot {
                path: root.to_path_buf(),
                reason: format!("unexpected existing entry: {}", entry.path().display()),
            });
        }
    }
    fs::write(&marker, b"TraceJIT cache v1\n").map_err(|source| io_error(&marker, source))
}

pub fn output_from_path(
    cache: &Cache,
    path: &Path,
    deleted: bool,
    allows_create: bool,
) -> Result<OutputArtifact, CacheError> {
    if deleted || !path.exists() {
        return Ok(OutputArtifact {
            path: path.to_path_buf(),
            kind: OutputKind::Deleted,
            content: None,
            unix_mode: None,
            allows_create: false,
        });
    }
    let bytes = fs::read(path).map_err(|source| io_error(path, source))?;
    let content = cache.put_bytes(&bytes)?;
    #[cfg(unix)]
    let unix_mode = {
        use std::os::unix::fs::PermissionsExt;
        Some(
            fs::metadata(path)
                .map_err(|source| io_error(path, source))?
                .permissions()
                .mode(),
        )
    };
    #[cfg(not(unix))]
    let unix_mode = None;
    Ok(OutputArtifact {
        path: path.to_path_buf(),
        kind: OutputKind::File,
        content: Some(content),
        unix_mode,
        allows_create,
    })
}

fn validate_output_precondition(output: &OutputArtifact) -> Result<(), CacheError> {
    let parent = output
        .path
        .parent()
        .ok_or_else(|| CacheError::InvalidOutputPath(output.path.clone()))?;
    validate_output_parent(output, parent)?;
    if output.kind == OutputKind::Deleted {
        // The traced run removed this path. Re-creating that state is only safe while
        // the path is still absent, or is still a single-link regular file, so a path
        // replaced by a directory or a symlink after tracing fails closed instead of
        // being unlinked.
        return match fs::symlink_metadata(&output.path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
            Err(source) => Err(io_error(&output.path, source)),
            Ok(metadata) if metadata.file_type().is_file() && link_count(&metadata) == 1 => Ok(()),
            Ok(_) => Err(CacheError::OutputPrecondition {
                path: output.path.clone(),
                reason: "the path to delete is no longer the regular file the traced run removed"
                    .into(),
            }),
        };
    }
    let metadata = match fs::symlink_metadata(&output.path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound && output.allows_create => {
            return Ok(())
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Err(CacheError::OutputPrecondition {
                path: output.path.clone(),
                reason: "the original writable open required an existing file".into(),
            })
        }
        Err(source) => return Err(io_error(&output.path, source)),
    };
    if !metadata.file_type().is_file() {
        return Err(CacheError::OutputPrecondition {
            path: output.path.clone(),
            reason: "the current output is not a regular file".into(),
        });
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 {
            return Err(CacheError::OutputPrecondition {
                path: output.path.clone(),
                reason: "the current output has multiple hard links".into(),
            });
        }
    }
    fs::OpenOptions::new()
        .write(true)
        .open(&output.path)
        .map(|_| ())
        .map_err(|error| CacheError::OutputPrecondition {
            path: output.path.clone(),
            reason: format!("the original writable open would fail: {error}"),
        })
}

enum StagedOutput {
    /// New content, fully written and synced in the destination directory.
    Content(NamedTempFile),
    /// The cached result is that the path does not exist.
    Absence,
}

enum AppliedOutput {
    /// The destination did not exist before this restoration.
    Created(PathBuf),
    /// The destination existed; `backup` holds a hard link to its previous state.
    Replaced(PathBuf, TempPath),
}

impl AppliedOutput {
    fn path(&self) -> &Path {
        match self {
            Self::Created(path) | Self::Replaced(path, _) => path,
        }
    }
}

/// Applies one prepared output mutation, returning `None` when there is nothing to undo.
fn apply_output(
    output: &OutputArtifact,
    staged: StagedOutput,
    backup: Option<TempPath>,
) -> Result<Option<AppliedOutput>, CacheError> {
    match (staged, backup) {
        (StagedOutput::Content(temporary), backup) => {
            // rename(2) replaces the directory entry itself, so a symlink substituted
            // between validation and this call is replaced rather than followed.
            temporary
                .persist(&output.path)
                .map_err(|error| io_error(&output.path, error.error))?;
            Ok(Some(match backup {
                Some(backup) => AppliedOutput::Replaced(output.path.clone(), backup),
                None => AppliedOutput::Created(output.path.clone()),
            }))
        }
        (StagedOutput::Absence, None) => match fs::remove_file(&output.path) {
            Ok(()) => Ok(None),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(source) => Err(io_error(&output.path, source)),
        },
        (StagedOutput::Absence, Some(backup)) => {
            fs::remove_file(&output.path).map_err(|source| io_error(&output.path, source))?;
            Ok(Some(AppliedOutput::Replaced(output.path.clone(), backup)))
        }
    }
}

/// Undoes the applied outputs in reverse order and returns `error`, or an error that also
/// names every failure to roll back.
fn rollback_restoration(applied: &[AppliedOutput], error: CacheError) -> CacheError {
    let mut failures = Vec::new();
    for entry in applied.iter().rev() {
        let result = match entry {
            AppliedOutput::Created(path) => match fs::remove_file(path) {
                Ok(()) => Ok(()),
                Err(source) if source.kind() == io::ErrorKind::NotFound => Ok(()),
                Err(source) => Err(source),
            },
            AppliedOutput::Replaced(path, backup) => fs::rename(backup, path),
        };
        if let Err(source) = result {
            failures.push(format!("{}: {source}", entry.path().display()));
        }
    }
    if failures.is_empty() {
        error
    } else {
        CacheError::RestorationRollback {
            reason: format!("{error}; rollback also failed for {}", failures.join("; ")),
        }
    }
}

/// Hard-links the current destination to a temporary name in the same directory.
///
/// A link is used instead of a copy so rollback is cheap and preserves the previous
/// inode, mode, ownership, and timestamps. The returned `TempPath` removes the link when
/// it is dropped, so a successful restoration leaves no backup behind.
fn backup_destination(path: &Path) -> Result<TempPath, CacheError> {
    let parent = path
        .parent()
        .ok_or_else(|| CacheError::InvalidOutputPath(path.to_path_buf()))?;
    let reserved: TempPath = NamedTempFile::new_in(parent)
        .map_err(|source| io_error(parent, source))?
        .into_temp_path();
    let reserved_path: &Path = &reserved;
    fs::remove_file(reserved_path).map_err(|source| io_error(reserved_path, source))?;
    fs::hard_link(path, reserved_path).map_err(|source| io_error(reserved_path, source))?;
    Ok(reserved)
}

fn link_count(metadata: &fs::Metadata) -> u64 {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        metadata.nlink()
    }
    #[cfg(not(unix))]
    {
        let _ = metadata;
        1
    }
}

/// Deterministic restoration-failure injection, compiled out of normal builds.
#[cfg(test)]
mod fault {
    use std::cell::RefCell;
    use std::path::{Path, PathBuf};

    thread_local! {
        static FAIL_PATH: RefCell<Option<PathBuf>> = const { RefCell::new(None) };
    }

    pub fn arm(path: PathBuf) {
        FAIL_PATH.with(|slot| *slot.borrow_mut() = Some(path));
    }

    pub fn disarm() {
        FAIL_PATH.with(|slot| *slot.borrow_mut() = None);
    }

    pub fn should_fail(path: &Path) -> bool {
        FAIL_PATH.with(|slot| slot.borrow().as_deref() == Some(path))
    }
}

#[cfg(not(test))]
mod fault {
    use std::path::Path;

    pub fn should_fail(_path: &Path) -> bool {
        false
    }
}

#[cfg(target_os = "linux")]
fn validate_output_parent(output: &OutputArtifact, parent: &Path) -> Result<(), CacheError> {
    for ancestor in parent.ancestors() {
        let metadata =
            fs::symlink_metadata(ancestor).map_err(|error| CacheError::OutputPrecondition {
                path: output.path.clone(),
                reason: format!(
                    "output ancestor {} is unavailable: {error}",
                    ancestor.display()
                ),
            })?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(CacheError::OutputPrecondition {
                path: output.path.clone(),
                reason: format!(
                    "output ancestor {} is not a real directory",
                    ancestor.display()
                ),
            });
        }
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn validate_output_parent(output: &OutputArtifact, parent: &Path) -> Result<(), CacheError> {
    let metadata =
        fs::symlink_metadata(parent).map_err(|error| CacheError::OutputPrecondition {
            path: output.path.clone(),
            reason: format!("output parent is unavailable: {error}"),
        })?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(CacheError::OutputPrecondition {
            path: output.path.clone(),
            reason: "output parent is not a real directory".into(),
        });
    }
    Ok(())
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), CacheError> {
    let parent = path
        .parent()
        .ok_or_else(|| CacheError::InvalidOutputPath(path.to_path_buf()))?;
    create_dir_all(parent)?;
    let mut temporary = NamedTempFile::new_in(parent).map_err(|source| io_error(parent, source))?;
    temporary
        .write_all(bytes)
        .and_then(|()| temporary.as_file().sync_all())
        .map_err(|source| io_error(temporary.path(), source))?;
    temporary
        .persist(path)
        .map_err(|error| io_error(path, error.error))?;
    Ok(())
}

fn create_dir_all(path: &Path) -> Result<(), CacheError> {
    fs::create_dir_all(path).map_err(|source| io_error(path, source))
}

fn io_error(path: impl AsRef<Path>, source: io::Error) -> CacheError {
    CacheError::Io {
        path: path.as_ref().to_path_buf(),
        source,
    }
}

fn u64_nanos(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

pub fn now_unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cas_deduplicates_and_detects_corruption() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path()).unwrap();
        let first = cache.put_bytes(b"same").unwrap();
        let second = cache.put_bytes(b"same").unwrap();
        assert_eq!(first, second);
        assert_eq!(cache.stats().unwrap().objects, 1);
        fs::write(
            directory.path().join("objects").join(first.to_string()),
            b"bad",
        )
        .unwrap();
        assert!(matches!(
            cache.get_bytes(first),
            Err(CacheError::CorruptObject { .. })
        ));
    }

    #[test]
    fn output_restoration_is_content_checked() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let output = directory.path().join("output.txt");
        fs::write(&output, b"expected").unwrap();
        let artifact = output_from_path(&cache, &output, false, false).unwrap();
        fs::write(&output, b"changed").unwrap();
        cache.restore_outputs(&[artifact]).unwrap();
        assert_eq!(fs::read(&output).unwrap(), b"expected");
    }

    #[test]
    fn restoration_respects_create_precondition() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let output = directory.path().join("output.txt");
        fs::write(&output, b"expected").unwrap();
        let cannot_create = output_from_path(&cache, &output, false, false).unwrap();
        let can_create = output_from_path(&cache, &output, false, true).unwrap();
        fs::remove_file(&output).unwrap();
        assert!(matches!(
            cache.restore_outputs(&[cannot_create]),
            Err(CacheError::OutputPrecondition { .. })
        ));
        cache.restore_outputs(&[can_create]).unwrap();
        assert_eq!(fs::read(&output).unwrap(), b"expected");
    }

    #[cfg(unix)]
    #[test]
    fn restoration_rejects_symlink_substitution() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let output = directory.path().join("output.txt");
        let target = directory.path().join("target.txt");
        fs::write(&output, b"expected").unwrap();
        fs::write(&target, b"target").unwrap();
        let artifact = output_from_path(&cache, &output, false, true).unwrap();
        fs::remove_file(&output).unwrap();
        std::os::unix::fs::symlink(&target, &output).unwrap();
        assert!(matches!(
            cache.restore_outputs(&[artifact]),
            Err(CacheError::OutputPrecondition { .. })
        ));
        assert_eq!(fs::read(&target).unwrap(), b"target");
    }

    fn captured_outputs(cache: &Cache, paths: &[(&Path, bool)]) -> Vec<OutputArtifact> {
        paths
            .iter()
            .map(|(path, deleted)| output_from_path(cache, path, *deleted, true).unwrap())
            .collect()
    }

    fn temporary_files(directory: &Path) -> usize {
        fs::read_dir(directory)
            .unwrap()
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.file_name().to_string_lossy().starts_with(".tmp"))
            .count()
    }

    #[test]
    fn restores_multiple_outputs_over_existing_content() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let first = directory.path().join("a.txt");
        let second = directory.path().join("b.txt");
        fs::write(&first, b"cached-a").unwrap();
        fs::write(&second, b"cached-b").unwrap();
        let artifacts = captured_outputs(&cache, &[(&first, false), (&second, false)]);
        fs::write(&first, b"user-a").unwrap();
        fs::write(&second, b"user-b").unwrap();
        cache.restore_outputs(&artifacts).unwrap();
        assert_eq!(fs::read(&first).unwrap(), b"cached-a");
        assert_eq!(fs::read(&second).unwrap(), b"cached-b");
        assert_eq!(temporary_files(directory.path()), 0);
    }

    #[test]
    fn failure_during_a_later_replacement_rolls_the_first_one_back() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let first = directory.path().join("a.txt");
        let second = directory.path().join("b.txt");
        fs::write(&first, b"cached-a").unwrap();
        fs::write(&second, b"cached-b").unwrap();
        let artifacts = captured_outputs(&cache, &[(&first, false), (&second, false)]);
        fs::write(&first, b"user-a").unwrap();
        fs::write(&second, b"user-b").unwrap();
        fault::arm(second.clone());
        let error = cache.restore_outputs(&artifacts).unwrap_err();
        fault::disarm();
        assert!(matches!(error, CacheError::OutputPrecondition { .. }));
        // The failed restoration left the workspace exactly as the caller had it.
        assert_eq!(fs::read(&first).unwrap(), b"user-a");
        assert_eq!(fs::read(&second).unwrap(), b"user-b");
        assert_eq!(temporary_files(directory.path()), 0);
    }

    #[test]
    fn mixed_file_and_deletion_restoration_rolls_both_back() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let created = directory.path().join("created.txt");
        let deleted = directory.path().join("deleted.txt");
        let failing = directory.path().join("failing.txt");
        fs::write(&created, b"cached-created").unwrap();
        fs::write(&deleted, b"cached-deleted").unwrap();
        fs::write(&failing, b"cached-failing").unwrap();
        let artifacts = vec![
            output_from_path(&cache, &created, false, true).unwrap(),
            output_from_path(&cache, &deleted, true, false).unwrap(),
            output_from_path(&cache, &failing, false, true).unwrap(),
        ];
        fs::remove_file(&created).unwrap();
        fs::write(&deleted, b"user-deleted").unwrap();
        fs::write(&failing, b"user-failing").unwrap();
        fault::arm(failing.clone());
        assert!(cache.restore_outputs(&artifacts).is_err());
        fault::disarm();
        // The re-created file was removed again and the deleted file was put back.
        assert!(!created.exists());
        assert_eq!(fs::read(&deleted).unwrap(), b"user-deleted");
        assert_eq!(fs::read(&failing).unwrap(), b"user-failing");
        assert_eq!(temporary_files(directory.path()), 0);
    }

    #[test]
    fn a_corrupt_object_fails_before_any_destination_is_touched() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let first = directory.path().join("a.txt");
        let second = directory.path().join("b.txt");
        fs::write(&first, b"cached-a").unwrap();
        fs::write(&second, b"cached-b").unwrap();
        let artifacts = captured_outputs(&cache, &[(&first, false), (&second, false)]);
        let corrupted = artifacts[1].content.unwrap();
        fs::write(
            directory
                .path()
                .join("cache")
                .join("objects")
                .join(corrupted.to_string()),
            b"tampered",
        )
        .unwrap();
        fs::write(&first, b"user-a").unwrap();
        fs::write(&second, b"user-b").unwrap();
        assert!(matches!(
            cache.restore_outputs(&artifacts),
            Err(CacheError::CorruptObject { .. })
        ));
        assert_eq!(fs::read(&first).unwrap(), b"user-a");
        assert_eq!(fs::read(&second).unwrap(), b"user-b");
    }

    #[test]
    fn a_symlink_substituted_before_the_swap_cannot_redirect_the_write() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let output = directory.path().join("output.txt");
        let victim = directory.path().join("victim.txt");
        fs::write(&output, b"cached").unwrap();
        fs::write(&victim, b"victim").unwrap();
        let artifact = output_from_path(&cache, &output, false, true).unwrap();
        let staged = cache.stage_output(&artifact).unwrap();
        // The substitution happens after validation and staging, immediately before the
        // swap. rename(2) replaces the link itself instead of following it.
        fs::remove_file(&output).unwrap();
        std::os::unix::fs::symlink(&victim, &output).unwrap();
        apply_output(&artifact, staged, None).unwrap().unwrap();
        assert_eq!(fs::read(&victim).unwrap(), b"victim");
        assert_eq!(fs::read(&output).unwrap(), b"cached");
        assert!(!fs::symlink_metadata(&output)
            .unwrap()
            .file_type()
            .is_symlink());
    }

    #[test]
    fn deleting_a_path_replaced_by_a_directory_fails_closed() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let path = directory.path().join("gone.txt");
        fs::write(&path, b"gone").unwrap();
        let artifact = output_from_path(&cache, &path, true, false).unwrap();
        fs::remove_file(&path).unwrap();
        fs::create_dir(&path).unwrap();
        assert!(matches!(
            cache.restore_outputs(&[artifact]),
            Err(CacheError::OutputPrecondition { .. })
        ));
        assert!(
            path.is_dir(),
            "the replacement directory must be left alone"
        );
    }

    #[test]
    fn a_second_attempt_after_a_failed_restoration_recovers() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let first = directory.path().join("a.txt");
        let second = directory.path().join("b.txt");
        fs::write(&first, b"cached-a").unwrap();
        fs::write(&second, b"cached-b").unwrap();
        let artifacts = captured_outputs(&cache, &[(&first, false), (&second, false)]);
        fs::write(&first, b"user-a").unwrap();
        fs::write(&second, b"user-b").unwrap();
        fault::arm(second.clone());
        assert!(cache.restore_outputs(&artifacts).is_err());
        fault::disarm();
        cache.restore_outputs(&artifacts).unwrap();
        assert_eq!(fs::read(&first).unwrap(), b"cached-a");
        assert_eq!(fs::read(&second).unwrap(), b"cached-b");
        assert_eq!(temporary_files(directory.path()), 0);
    }

    #[test]
    fn a_malformed_record_fails_closed_instead_of_reusing() {
        let directory = tempfile::tempdir().unwrap();
        let cache = Cache::open(directory.path().join("cache")).unwrap();
        let key = Hash::from(blake3::hash(b"lookup key"));
        cache
            .connection
            .execute(
                "INSERT INTO executions (lookup_key, execution_id, record_json, updated_unix_ms)
                 VALUES (?1, ?2, ?3, ?4)",
                params![key.to_string(), "truncated", b"{\"id\":".to_vec(), "1"],
            )
            .unwrap();
        assert!(matches!(cache.find(key), Err(CacheError::Serialization(_))));
    }

    #[test]
    fn cache_root_refuses_existing_unrelated_content() {
        let directory = tempfile::tempdir().unwrap();
        fs::write(directory.path().join("keep.txt"), b"user data").unwrap();
        assert!(matches!(
            Cache::open(directory.path()),
            Err(CacheError::UnsafeRoot { .. })
        ));
        assert_eq!(
            fs::read(directory.path().join("keep.txt")).unwrap(),
            b"user data"
        );
    }

    #[test]
    fn clear_removes_only_owned_cache_entries() {
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path().join("cache");
        let cache = Cache::open(&root).unwrap();
        fs::write(root.join("unrelated.txt"), b"keep").unwrap();
        cache.clear().unwrap();
        assert_eq!(fs::read(root.join("unrelated.txt")).unwrap(), b"keep");
    }
}

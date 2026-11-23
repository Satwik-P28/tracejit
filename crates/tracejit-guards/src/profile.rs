//! Opt-in guard-cost instrumentation.
//!
//! Phase X needs to know where warm-hit validation time goes: how many guards of each kind are
//! interpreted, how many `stat`/`open`/`read`/`readlink`/access observations they issue, how many
//! bytes are hashed, and how the two validation passes (initial candidate check and the
//! pre-restore recheck) compare. `strace` cannot answer this: TraceJIT's own `ptrace` session
//! conflicts with an external tracer, so a traced `run` no longer reproduces the reuse path it is
//! supposed to measure.
//!
//! The instrumentation is off unless `TRACEJIT_GUARD_PROFILE=1`. When off, every counter update is
//! a predictable branch on a `OnceLock`; when on, counters are relaxed atomics and the timers are
//! `Instant::now()` pairs around the operations being attributed. The measured overhead of the
//! enabled mode is reported in `docs/PHASE_X_REPORT.md` rather than assumed to be zero.
//!
//! Categories are inclusive per operation and do not nest: `content_ns` is the time inside
//! `hash_reader` (read syscalls plus BLAKE3), `open_ns` is the time inside `File::open`,
//! `stat_ns` covers `stat`/`lstat`/`fstat` provenance reads, and `other_ns` is the remainder of the
//! pass. Every observation is counted at the helper the validator actually calls, so the numbers
//! describe the shipped validation path and not a model of it.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

/// Guard kinds in report order. The index is the slot used by the counters.
pub const KIND_NAMES: [&str; 17] = [
    "ExecutableHash",
    "FileHash",
    "FileMetadata",
    "DirectoryOpened",
    "OutputPrestate",
    "DirectoryEnumerated",
    "FilesystemStats",
    "InheritedStream",
    "ControlledEntropy",
    "ControlledRuntime",
    "SymlinkTarget",
    "SymlinkMetadata",
    "AccessCheck",
    "EnvironmentValue",
    "WorkingDirectory",
    "RuntimeIdentity",
    "NoUnexpectedEffects",
];

/// One full `validate_all` pass.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct PassStats {
    pub guards: u64,
    /// Guards that returned `Ok` before the pass ended.
    pub passed: u64,
    pub total_ns: u64,
    pub stat_calls: u64,
    pub stat_ns: u64,
    pub open_calls: u64,
    pub open_ns: u64,
    pub content_calls: u64,
    pub content_ns: u64,
    pub read_syscalls: u64,
    pub bytes_hashed: u64,
    pub readlink_calls: u64,
    pub readlink_ns: u64,
    pub access_calls: u64,
    pub access_ns: u64,
    pub directory_probes: u64,
    pub env_calls: u64,
    /// How many guards the pass examined when it failed (record order).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub first_failure_checked: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub first_failure_kind: Option<String>,
}

impl PassStats {
    /// Pass time not attributed to a measured kernel or hashing operation.
    pub fn other_ns(&self) -> u64 {
        self.total_ns.saturating_sub(
            self.stat_ns
                .saturating_add(self.open_ns)
                .saturating_add(self.content_ns)
                .saturating_add(self.readlink_ns)
                .saturating_add(self.access_ns),
        )
    }
}

/// Aggregate observation of every validation pass in this process.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct GuardProfile {
    pub passes: Vec<PassStats>,
    /// Guards interpreted per kind across all passes.
    pub guards_by_kind: BTreeMap<String, u64>,
    /// Distinct paths named per kind across all passes.
    pub unique_paths_by_kind: BTreeMap<String, u64>,
    pub peak_rss_kb: u64,
}

#[derive(Clone, Copy)]
pub(crate) enum Slot {
    Stat,
    Open,
    Content,
    Readlink,
    Access,
}

struct Counters {
    kind: [AtomicU64; KIND_NAMES.len()],
    stat_calls: AtomicU64,
    stat_ns: AtomicU64,
    open_calls: AtomicU64,
    open_ns: AtomicU64,
    content_calls: AtomicU64,
    content_ns: AtomicU64,
    read_syscalls: AtomicU64,
    bytes_hashed: AtomicU64,
    readlink_calls: AtomicU64,
    readlink_ns: AtomicU64,
    access_calls: AtomicU64,
    access_ns: AtomicU64,
    directory_probes: AtomicU64,
    env_calls: AtomicU64,
}

static COUNTERS: Counters = Counters {
    kind: [const { AtomicU64::new(0) }; KIND_NAMES.len()],
    stat_calls: AtomicU64::new(0),
    stat_ns: AtomicU64::new(0),
    open_calls: AtomicU64::new(0),
    open_ns: AtomicU64::new(0),
    content_calls: AtomicU64::new(0),
    content_ns: AtomicU64::new(0),
    read_syscalls: AtomicU64::new(0),
    bytes_hashed: AtomicU64::new(0),
    readlink_calls: AtomicU64::new(0),
    readlink_ns: AtomicU64::new(0),
    access_calls: AtomicU64::new(0),
    access_ns: AtomicU64::new(0),
    directory_probes: AtomicU64::new(0),
    env_calls: AtomicU64::new(0),
};

static ENABLED: OnceLock<bool> = OnceLock::new();

/// Whether per-guard cost collection is on.
pub fn enabled() -> bool {
    *ENABLED.get_or_init(|| {
        std::env::var_os("TRACEJIT_GUARD_PROFILE").is_some_and(|value| value == "1")
    })
}

/// Record which guard kind an interpretation step belongs to.
pub(crate) fn count_kind(slot: usize) {
    if enabled() {
        COUNTERS.kind[slot].fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_stat() {
    if enabled() {
        COUNTERS.stat_calls.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_open() {
    if enabled() {
        COUNTERS.open_calls.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_content() {
    if enabled() {
        COUNTERS.content_calls.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_read() {
    if enabled() {
        COUNTERS.read_syscalls.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_bytes(bytes: u64) {
    if enabled() {
        COUNTERS.bytes_hashed.fetch_add(bytes, Ordering::Relaxed);
    }
}

pub(crate) fn count_readlink() {
    if enabled() {
        COUNTERS.readlink_calls.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_access() {
    if enabled() {
        COUNTERS.access_calls.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_directory_probe() {
    if enabled() {
        COUNTERS.directory_probes.fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn count_env() {
    if enabled() {
        COUNTERS.env_calls.fetch_add(1, Ordering::Relaxed);
    }
}

/// Times one operation into its slot while it runs. A no-op when profiling is off.
pub(crate) struct Scoped(Option<(Instant, Slot)>);

impl Scoped {
    pub(crate) fn start(slot: Slot) -> Self {
        if enabled() {
            Self(Some((Instant::now(), slot)))
        } else {
            Self(None)
        }
    }
}

impl Drop for Scoped {
    fn drop(&mut self) {
        let Some((started, slot)) = self.0 else {
            return;
        };
        let elapsed = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        let counter = match slot {
            Slot::Stat => &COUNTERS.stat_ns,
            Slot::Open => &COUNTERS.open_ns,
            Slot::Content => &COUNTERS.content_ns,
            Slot::Readlink => &COUNTERS.readlink_ns,
            Slot::Access => &COUNTERS.access_ns,
        };
        counter.fetch_add(elapsed, Ordering::Relaxed);
    }
}

#[derive(Clone, Copy)]
struct Snapshot {
    at: Instant,
    stat_calls: u64,
    stat_ns: u64,
    open_calls: u64,
    open_ns: u64,
    content_calls: u64,
    content_ns: u64,
    read_syscalls: u64,
    bytes_hashed: u64,
    readlink_calls: u64,
    readlink_ns: u64,
    access_calls: u64,
    access_ns: u64,
    directory_probes: u64,
    env_calls: u64,
}

fn snapshot() -> Snapshot {
    Snapshot {
        at: Instant::now(),
        stat_calls: COUNTERS.stat_calls.load(Ordering::Relaxed),
        stat_ns: COUNTERS.stat_ns.load(Ordering::Relaxed),
        open_calls: COUNTERS.open_calls.load(Ordering::Relaxed),
        open_ns: COUNTERS.open_ns.load(Ordering::Relaxed),
        content_calls: COUNTERS.content_calls.load(Ordering::Relaxed),
        content_ns: COUNTERS.content_ns.load(Ordering::Relaxed),
        read_syscalls: COUNTERS.read_syscalls.load(Ordering::Relaxed),
        bytes_hashed: COUNTERS.bytes_hashed.load(Ordering::Relaxed),
        readlink_calls: COUNTERS.readlink_calls.load(Ordering::Relaxed),
        readlink_ns: COUNTERS.readlink_ns.load(Ordering::Relaxed),
        access_calls: COUNTERS.access_calls.load(Ordering::Relaxed),
        access_ns: COUNTERS.access_ns.load(Ordering::Relaxed),
        directory_probes: COUNTERS.directory_probes.load(Ordering::Relaxed),
        env_calls: COUNTERS.env_calls.load(Ordering::Relaxed),
    }
}

/// Live state of a pass being measured.
pub(crate) struct PassScope {
    start: Snapshot,
}

impl PassScope {
    pub(crate) fn start() -> Option<Self> {
        enabled().then(|| Self { start: snapshot() })
    }

    /// Finish the pass. `first_failure` is the examined guard count and kind of the failure.
    pub(crate) fn finish(self, guards: u64, passed: u64, first_failure: Option<(u64, usize)>) {
        let end = snapshot();
        let stats = PassStats {
            guards,
            passed,
            total_ns: u64::try_from(end.at.duration_since(self.start.at).as_nanos())
                .unwrap_or(u64::MAX),
            // Saturating deltas: `take()` resets the counters, so a caller that reports while a
            // pass is still in flight must record zero rather than underflow.
            stat_calls: delta(end.stat_calls, self.start.stat_calls),
            stat_ns: delta(end.stat_ns, self.start.stat_ns),
            open_calls: delta(end.open_calls, self.start.open_calls),
            open_ns: delta(end.open_ns, self.start.open_ns),
            content_calls: delta(end.content_calls, self.start.content_calls),
            content_ns: delta(end.content_ns, self.start.content_ns),
            read_syscalls: delta(end.read_syscalls, self.start.read_syscalls),
            bytes_hashed: delta(end.bytes_hashed, self.start.bytes_hashed),
            readlink_calls: delta(end.readlink_calls, self.start.readlink_calls),
            readlink_ns: delta(end.readlink_ns, self.start.readlink_ns),
            access_calls: delta(end.access_calls, self.start.access_calls),
            access_ns: delta(end.access_ns, self.start.access_ns),
            directory_probes: delta(end.directory_probes, self.start.directory_probes),
            env_calls: delta(end.env_calls, self.start.env_calls),
            first_failure_checked: first_failure.map(|(checked, _)| checked),
            first_failure_kind: first_failure.map(|(_, kind)| KIND_NAMES[kind].to_owned()),
        };
        if let Ok(mut passes) = passes().lock() {
            passes.push(stats);
        }
    }
}

fn delta(end: u64, start: u64) -> u64 {
    end.saturating_sub(start)
}

fn passes() -> &'static Mutex<Vec<PassStats>> {
    static PASSES: OnceLock<Mutex<Vec<PassStats>>> = OnceLock::new();
    PASSES.get_or_init(|| Mutex::new(Vec::new()))
}

fn observed_paths() -> &'static Mutex<BTreeMap<&'static str, BTreeSet<std::path::PathBuf>>> {
    static PATHS: OnceLock<Mutex<BTreeMap<&'static str, BTreeSet<std::path::PathBuf>>>> =
        OnceLock::new();
    PATHS.get_or_init(|| Mutex::new(BTreeMap::new()))
}

/// Record that a guard of `kind` observed `path`.
pub(crate) fn observe_path(kind: usize, path: &Path) {
    if !enabled() {
        return;
    }
    if let Ok(mut paths) = observed_paths().lock() {
        paths
            .entry(KIND_NAMES[kind])
            .or_default()
            .insert(path.to_path_buf());
    }
}

fn peak_rss_kb() -> u64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status
                .lines()
                .find(|line| line.starts_with("VmHWM:"))
                .and_then(|line| line.split_whitespace().nth(1))
                .and_then(|value| value.parse().ok())
        })
        .unwrap_or(0)
}

/// Take the measured profile, resetting the collectors. Returns `None` when profiling is off.
pub fn take() -> Option<GuardProfile> {
    if !enabled() {
        return None;
    }
    let passes = passes()
        .lock()
        .map(|mut passes| std::mem::take(&mut *passes))
        .unwrap_or_default();
    let mut guards_by_kind = BTreeMap::new();
    for (index, name) in KIND_NAMES.iter().enumerate() {
        let count = COUNTERS.kind[index].swap(0, Ordering::Relaxed);
        if count > 0 {
            guards_by_kind.insert((*name).to_owned(), count);
        }
    }
    // Reset the scalar counters in the same step that reports them, so a second `take()` in one
    // process measures its own window instead of repeating the first.
    for counter in [
        &COUNTERS.stat_calls,
        &COUNTERS.stat_ns,
        &COUNTERS.open_calls,
        &COUNTERS.open_ns,
        &COUNTERS.content_calls,
        &COUNTERS.content_ns,
        &COUNTERS.read_syscalls,
        &COUNTERS.bytes_hashed,
        &COUNTERS.readlink_calls,
        &COUNTERS.readlink_ns,
        &COUNTERS.access_calls,
        &COUNTERS.access_ns,
        &COUNTERS.directory_probes,
        &COUNTERS.env_calls,
    ] {
        counter.store(0, Ordering::Relaxed);
    }
    let unique_paths_by_kind = observed_paths()
        .lock()
        .map(|mut paths| {
            let observed = paths
                .iter()
                .filter(|(_, paths)| !paths.is_empty())
                .map(|(kind, paths)| ((*kind).to_owned(), paths.len() as u64))
                .collect::<BTreeMap<_, _>>();
            paths.clear();
            observed
        })
        .unwrap_or_default();
    Some(GuardProfile {
        passes,
        guards_by_kind,
        unique_paths_by_kind,
        peak_rss_kb: peak_rss_kb(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profiling_is_off_by_default() {
        assert!(!enabled() || std::env::var_os("TRACEJIT_GUARD_PROFILE").is_some());
    }

    #[test]
    fn other_time_never_underflows() {
        let stats = PassStats {
            total_ns: 10,
            stat_ns: 6,
            open_ns: 5,
            ..PassStats::default()
        };
        assert_eq!(stats.other_ns(), 0);
    }
}

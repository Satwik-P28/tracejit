# Phase 1 reliability audit

Audit of the TraceJIT tree at `f90b4db15ec066373101692996c822e2c51c67cf`
(`test: smoke-check the published v0.1.1 binary`, the branch point for this
phase). Every finding below was obtained by reading the implementation and, where
marked **VERIFIED**, by executing a reproduction on Linux x86_64.

Labels: **VERIFIED** (executed or direct code evidence), **INFERENCE**
(conclusion supported by evidence but not directly exercised), **UNVERIFIED**
(hypothesis that was not reproduced).

Measured host for this audit:

| Item | Value |
| --- | --- |
| Distribution | Ubuntu 24.04.5 LTS |
| Kernel | 6.1.102, x86_64, 2 vCPU, 3915 MB RAM |
| Filesystem | Ubuntu rootfs (`overlay`, see the benchmark report) |
| Rust | `rustc`/`cargo` from `stable` via `rustup` |
| Python | 3.12.3 |
| ptrace | available (`tracejit doctor` reports `ptrace yes`) |
| seccomp | available (`Seccomp: 0` before use; `prctl(PR_GET_NO_NEW_PRIVS)` works) |
| Landlock | **absent** (`landlock_create_ruleset` returns `ENOSYS`, errno 38) |

Consequence of the last row: this host cannot produce `PROVEN`. Every sandbox
assertion in `crates/tracejit-cli/tests/linux_integration.rs` and
`crates/tracejit-sandbox` printed its explicit skip reason, and none of the
findings below depend on `PROVEN`. That is a capability limitation of the audit
host, not a defect; it is reported again in the correctness matrix.

## Method

1. Read every crate, the fixture driver, `cases.json`, both benchmark harnesses,
   the workflow definitions, and `ARCHITECTURE.md`/`SAFETY.md`/`SPEC.md`.
2. Trace the cache-hit path and the miss path by hand and list every point where
   a failure is not recovered or a mutation is not reversible.
3. Reproduce each candidate defect with the pre-fix binary
   (`sha256 f1beed6be9d70d97…`, built from the audit commit) before changing
   anything.
4. Fix, then re-run the same reproduction against the fixed binary.

## Verified defects

### D1 — Partial multi-output restoration (HIGH, fixed)

**Location** `crates/tracejit-cache/src/lib.rs`, `Cache::restore_outputs`.

**Behavior before the fix.** The function validated every destination
precondition, loaded and verified every content-addressed object, and *then*
mutated outputs one at a time. Any failure from the second output onward left the
earlier outputs already replaced from the cache, while the function returned an
error and the caller re-traced from that mixed state.

**Reproduction** `benchmarks/realworld/repro/partial_restore.sh` builds a
two-output workspace (`a.txt` and `sub/b.txt`), obtains a verified cache hit,
restores the caller's content in both files, makes `sub/` read-only
(`chmod 0555`), and runs once more. The read-only directory passes the per-output
precondition (the file itself is still writable) and fails when a replacement is
staged there.

```
# pre-fix binary
third run exit status : 1
a.txt                 : input one          <- replaced from cache
sub/b.txt             : user content
RESULT partial restoration: a.txt was replaced from the cache before the failure

# fixed binary
third run exit status : 1
a.txt                 : user content
sub/b.txt             : user content
RESULT no partial mutation: a.txt still holds the caller's content
```

**Fix.** Restoration now runs in four phases: validate every precondition;
verify every CAS object and stage it to a temporary file in the destination
directory; hard-link every destination that already exists to a temporary backup
name in the same directory; only then swap each staged file into place or remove
a deleted path. A failure during the swap rolls the applied outputs back from
those backups, in reverse order, and the returned error names any rollback that
also failed (`CacheError::RestorationRollback`). Backups are hard links, not
copies, so the hit path pays one extra `link(2)` per output and no extra data
copy.

**Residual limitation (documented, not fixed).** This is *not* an atomic
multi-file transaction. The commit phase is a sequence of `rename(2)` calls. A
hard kill (SIGKILL, power loss, kernel panic) between two renames still leaves a
mixed workspace plus stray staging or `.tmp*` backup files in the destination
directories. There is no recovery journal and no work is done on the next run to
detect that state. Rollback covers in-process failures only.

### D2 — A corrupt CAS object could never be repaired, so the command became permanently unrunnable (MEDIUM, fixed)

**Location** `crates/tracejit-cache/src/lib.rs`, `Cache::put_bytes`, together
with the hit path in `crates/tracejit-core/src/lib.rs`, `run`.

**Behavior before the fix.** Two defects compounded:

1. The hit path propagated any `CacheError` from `restore_outputs`/`get_bytes`
   with `?`, so a corrupt object aborted the command instead of re-tracing. The
   only recovery was `tracejit cache clear`.
2. `put_bytes` refused to overwrite an object whose stored bytes did not match
   its name: both the early `destination.exists()` branch and the
   `AlreadyExists` branch called `verify_object` and returned `CorruptObject`.
   Even a re-trace therefore could not rewrite the poisoned hash — the object
   stayed corrupt forever and every later run for that key failed.

**Reproduction.** The new integration test
`a_corrupted_cached_output_fails_closed` tampers with the CAS object that holds a
captured output and then runs the command. Against the intermediate tree (hit
path repaired but `put_bytes` unchanged) the test failed on its first assertion:
the run exited non-zero instead of re-tracing and repairing.

**Fix.** `put_bytes` now repairs a mismatched object by writing the bytes whose
BLAKE3 digest *is* the destination name, using a temporary file plus rename so a
concurrent reader sees either the old object or the new one, never a partial one.
The hit path treats `CacheError::CorruptObject` as a deopt: nothing has been
mutated or exposed at that point, so the execution is re-traced and the record is
rewritten. Strict hashing is unchanged — `get_bytes` still rehashes on every read
and fails closed on any mismatch.

### D3 — A malformed metadata record made the command permanently fail (MEDIUM, fixed)

**Location** `crates/tracejit-core/src/lib.rs`, `run` (candidate lookup).

**Behavior before the fix.** `Cache::find` decodes `record_json` with
`serde_json`. A truncated or otherwise malformed record returned
`CacheError::Serialization`, which `run` propagated with `?`. The command failed
until the cache was cleared, even though nothing unsafe was involved.

**Reproduction** `crates/tracejit-cache`, unit test
`a_malformed_record_fails_closed_instead_of_reusing`, inserts a row whose
`record_json` is the truncated `{"id":` and asserts that `find` reports
`CacheError::Serialization`. Code inspection confirms the pre-fix `run`
propagated that error.

**Fix.** `run` now treats a decode failure as a miss and prepends the reason
(`stored metadata record could not be decoded (...); the execution was
retraced`) to the decision reason, so the execution is re-traced and the record
is rewritten. No cached byte is exposed either way, so this does not weaken the
fail-closed rule. `explain` still surfaces the decode failure for the record it
is asked about.

### D4 — A deleted output's precondition did not reject a directory or symlink replacement (LOW, fixed)

**Location** `crates/tracejit-cache/src/lib.rs`,
`validate_output_precondition`, `OutputKind::Deleted` branch.

**Behavior before the fix.** A `Deleted` artifact validated only its parent
directory. If another process replaced the path with a directory or a symlink
between tracing and restoration, the restore attempted `remove_file`, which
either failed (`EISDIR`) or removed a symlink the user had created.

**Fix.** A `Deleted` artifact now requires the path to be absent, or to still be
a single-link regular file. Regression test
`deleting_a_path_replaced_by_a_directory_fails_closed` asserts the replacement
directory is left alone.

### D5 — Benchmark results were overwritten and workloads ran in the repository (MEDIUM, methodology, fixed)

**Location** `benchmarks/harness/benchmark.py`, `benchmarks/harness/break_even.py`.

**Behavior before the fix.**

- Both harnesses always wrote `latest.json`/`latest.md` (and
  `break-even.json`/`break-even.md`) into the chosen output directory. A run at a
  new commit silently replaced the previous commit's numbers, which conflicts
  with "do not overwrite historical benchmark results".
- `break_even.py` wrote every sweep output and the calibration file into
  `benchmarks/workloads/sweep/output/`, i.e. inside the repository tree. The files
  are covered by `.gitignore`, so they were invisible to `git status`, but a
  benchmark was still using the repository as scratch space.
- Neither harness reported run-to-run noise next to its medians, and neither
  reported whether the run had mutated the repository.

**Fix.** `write_results`/`write_results`-equivalent helpers now write the rolling
`latest.*` report *and* an immutable `commit-<sha>[-dirty]/` copy. Both harnesses
take a snapshot of `git status --porcelain --untracked-files=all` at start and
report any path that appeared during the run as
`repository_changes_during_run`. `break_even.py` writes all workload output to a
`--scratch-dir` (a fresh temporary directory by default). Both report
`relative_standard_deviation` per condition and record `working_tree_dirty`.

### D6 — Traced execution rewrote `argv[0]`, so the traced process could resolve a different runtime installation than a direct execution (HIGH, fixed)

**Location** `crates/tracejit-core/src/lib.rs`, `resolve_executable` (which ends
with `fs::canonicalize`) together with `crates/tracejit-trace/src/linux.rs`,
`trace_command` (`Command::new(&request.executable)` writes the canonical path
into both the exec argument and `argv[0]`).

**Behavior before the fix.** `resolve_executable` canonicalizes symlinks, so a
command whose program path is a symlink is executed as its canonical target with
`argv[0]` rewritten to that target. `argv[0]` is observable to the traced
program, and at least one widely used runtime derives its installation prefix
from it: CPython picks `sys.prefix` and therefore its module search path from
`argv[0]`. The consequence is that **a traced execution was not the execution the
caller asked for**: it could import a different set of packages, or fail to
import one at all, than a direct execution of the identical command line.

This is not a false cache hit — classification and guards are built from the run
that actually happened. It is worse in a different way: the execution TraceJIT
records, hashes, and later replays is a *different program configuration* than
the user's command names, and every dependency, guard, and output in the record
comes from that other configuration.

**Reproduction** (Linux x86_64, this host):

```console
$ /opt/freestyle/python/bin/python3 -c 'import sys; print(sys.executable, sys.prefix)'
/opt/freestyle/python/bin/python3 /opt/freestyle/python

$ tracejit run --json -- /opt/freestyle/python/bin/python3 -c 'import sys; print(sys.executable, sys.prefix)'
/usr/bin/python3.12 /usr            # pre-fix: the canonical target, not the requested program
```

The same defect is visible end to end on a real workload. Python's
site-packages for the requested installation contains Pillow; the canonical
target's does not:

```console
# direct
exit 0  output sha256 9051d93b033ab24a…  (identical to traced output after the fix)

# pre-fix binary, traced
exit 1  ModuleNotFoundError: No module named 'PIL'
        outputs 0, writes 0

# fixed binary, traced
exit 0  output sha256 9051d93b033ab24a…  identical stdout, 2 writes, 406 dependencies
```

The pre-fix trace recorded **zero** file writes and **zero** outputs for a
program that writes one file. That ineligibility was an artifact of running the
wrong interpreter, not a property of the workload.

**Fix.** `trace_command` now sets `argv[0]` back to the program string the caller
supplied, using `std::os::unix::process::CommandExt::arg0`, while still executing
the resolved path:

```rust
if let Some(program) = request.argv.first() {
    command.arg0(program);
}
```

The resolved path is still what is exec'd, and it is still what is hashed for
the lookup key, so identity stability across symlink spellings is unchanged.

**Regression test**
`traced_execution_preserves_the_caller_supplied_argv0` in
`crates/tracejit-cli/tests/linux_integration.rs` symlinks `/bin/sh` into a
scratch directory and compares that shell's own view of `$0` (which *is*
`argv[0]`) between direct and traced execution. It fails against the pre-fix
binary and passes after the fix.

**Residual limitation.** Only `argv[0]` is restored. The exec'd inode is still
the canonical target, so a program that identifies itself through
`/proc/self/exe` still sees the link target — which is what the kernel reports for
a direct execution of a symlink as well, so the two now agree.

### D7 — Concurrent first-time cache initialization aborted the command with a false "unsafe cache root" (MEDIUM-HIGH, fixed)

**Location** `crates/tracejit-cache/src/lib.rs`, `prepare_root`.

**Behavior before the fix.** `prepare_root` accepts a root that already carries the
ownership marker, and otherwise enumerates the root and refuses any entry that is
not `objects`, `executions` or a SQLite file. `.tracejit-cache-v1` was **not** in
that allowed set, and the marker check runs *before* the enumeration, so two
processes starting against one fresh cache root could interleave as: A checks the
marker (absent) → B creates the root and writes the marker → A enumerates, finds
`.tracejit-cache-v1`, and returns
`UnsafeRoot { reason: "unexpected existing entry: <root>/.tracejit-cache-v1" }`.

**Severity** MEDIUM-HIGH. It fails *closed* — nothing wrong is reused and no
cached byte is exposed — but it fails **the command**, so a parallel build can
abort with a cache-directory error that has nothing to do with the workload.

**Reproduction** Captured during the Phase 1 validation gate:

```console
$ cargo test -p tracejit-cli --test linux_integration -- --test-threads=1
test concurrent_identical_runs_neither_fail_nor_reuse_unsafely ...
thread 'concurrent_identical_runs_neither_fail_nor_reuse_unsafely' panicked at
  crates/tracejit-cli/tests/linux_integration.rs:586:9:
a concurrent run failed:
tracejit: refusing to use unsafe cache root /tmp/.tmpfYSWcX/cache: unexpected existing entry: /tmp/.tmpfYSWcX/cache/.tracejit-cache-v1
```

The window is narrow: 144 further concurrent cold starts (12 rounds × 12
processes) did not reproduce it, and the test passed on two immediate re-runs.
That is why it is recorded with the captured output rather than as a stable
reproduction.

**Fix.** The marker is our own file, so it is never "unrelated content":
`.tracejit-cache-v1` is now in the allowed set, and a marker that appears between
the check and the enumeration is adopted without being written to — the second
part also refuses to follow a symlink planted at that path. Coverage:
`a_marker_written_by_a_peer_is_not_unrelated_content` (deterministic, exercises
the exact branch) and `concurrent_first_initialization_never_refuses_its_own_marker`
(8 racers × 50 fresh roots, asserting that no racer reports the false refusal).

**Residual.** The enumeration is still a snapshot of the directory. A malicious
writer that inserts a foreign entry between the marker check and the write is
still only detected on the next run; that is the S3 hardening item below, not a
privilege boundary, because an attacker with write access to the cache root
already controls its contents.

## Suspected defects that were not reproduced

### S1 — SQLite writer contention (cross-process not reproduced; same-process confirmed and out of the product path)

The cache opens SQLite with WAL and `synchronous=FULL` and, before this Phase,
no `busy_timeout`, so a second writer was expected to fail with `SQLITE_BUSY`.

**Cross-process: not reproduced.** Probes at 8 and 32 concurrent cold `run`
invocations of the same command against a single fresh cache produced **zero**
non-zero exits and **zero** errors, on both the pre-fix and the fixed binary;
during Phase 1 another 144 concurrent cold starts reproduced nothing either.
`PRAGMA busy_timeout=10000` is retained as hardening, not as a fix for an
observed cross-process failure.

**Same-process: reproduced, and expected.** The new unit test
`concurrent_first_initialization_never_refuses_its_own_marker` opens eight
connections from one process and does observe
`cache database failed: database is locked` (round 4 of 50 on this host). That is
SQLite's documented behaviour — it does **not** invoke the busy handler when the
conflicting lock is held by another connection in the **same process**, to avoid
deadlock. The CLI opens exactly one connection per process, so this is not a
product code path, and no code change was made for it: the guess that reordering
`journal_mode=WAL` after `busy_timeout` would fix it is wrong for the same-process
case, and making the test tolerate the error would hide the distinction. The test
asserts only what the design guarantees (no false `unsafe cache root`), and the
cross-process guarantee is asserted by
`concurrent_identical_runs_neither_fail_nor_reuse_unsafely`.

**If the cache is ever embedded** with several connections in one process, this
becomes a real gap and needs a process-wide serializer or a retry loop around the
WAL conversion.

### S2 — Time-of-check/time-of-use between guard validation and restoration (documented, not fixed)

`SAFETY.md` already states that guards cannot freeze the filesystem between
validation and restoration, and that `PROVEN` does not stop another process from
mutating an input. This audit confirms the code matches that statement: guards
run, then outputs are restored, with no attempt to re-validate. Closing it needs
file-descriptor-relative confinement or a workspace-level protocol, which is a
Phase 2-or-later architectural change. Phase 1 adds no claim to the contrary.

### S3 — `prepare_root` validates the cache root but not its subdirectories (UNVERIFIED)

`Cache::open` refuses a symlinked or non-directory root, and `clear` requires the
ownership marker. It does not check whether `<root>/objects` or
`<root>/executions` has been replaced with a symlink to another directory, and
`create_dir_all` succeeds through such a link. Exploiting this requires write
access to the cache root, at which point the attacker already controls the cache
directory contents, so it is not treated as a privilege boundary. Not fixed;
recorded as a hardening candidate.

### S4 — Hard-link based rollback on filesystems without hard links (INFERENCE)

`backup_destination` runs before the first mutation, so a filesystem that refuses
`link(2)` makes the whole restoration fail closed with an error and no output is
touched. That ordering is visible in the code and is the reason the backup phase
precedes the commit phase, but it was not exercised on a hard-link-free
filesystem during this audit.

## Structural observations (not defects)

- **Directory outputs force `UNKNOWN`.** `store_outcome` marks a non-regular
  output as `DeterminismClass::Unknown`, so any command that creates a directory
  becomes ineligible. This is fail-closed and intended; it is also a
  compatibility cost and is quantified in
  [PHASE1_COMPATIBILITY_REPORT.md](PHASE1_COMPATIBILITY_REPORT.md).
- **The lookup key contains the whole inherited environment.** Any environment
  change is therefore a full miss rather than a guarded dependency failure. That
  is the documented V1 design (`ARCHITECTURE.md`), and it is why
  `metadata_symlink_and_environment_changes_miss` observes `MISS` rather than
  `DEOPT` for an environment change.
- **`Guard::NoUnexpectedEffects` validates nothing.** It is a marker; the real
  rejection is classification. `SAFETY.md` says so and the code agrees.
- **`fast` guard mode skips the content hash when the entire fingerprint
  matches.** The fingerprint includes `ctime`, which userspace cannot set, so a
  same-size rewrite with a restored `mtime` is still caught. Asserted by
  `fast_guard_mode_still_deoptimizes_on_a_content_change`; the claim that no
  userspace actor can restore `ctime` is host-filesystem specific and remains an
  inference for exotic filesystems.

## Residual limitations carried into Phase 2

1. Restoration is recoverable but not crash-atomic (D1).
2. No repair or detection of a mixed workspace left by a hard kill; stray
   `.tmp*` staging or backup files are not swept.
3. Cache integrity failures are recovered by re-tracing, which costs a full
   re-execution; there is no quarantine of the affected record.
4. Directory and special-file outputs remain non-reusable.
5. `PROVEN` could not be exercised on the audit host (no Landlock).
6. Same-process multi-connection cache use is not serialized (S1); the supported
   model is one process, one cache connection, which is what the CLI does.

## Reproducing this audit

```bash
cargo build --workspace --release
cargo test --workspace
sh benchmarks/realworld/repro/partial_restore.sh ./target/release/tracejit
python3 benchmarks/realworld/census.py --runs 5 --warmups 1 --output-dir /tmp/phase1
```

The reproduction script exits non-zero when a partial restoration is observed.

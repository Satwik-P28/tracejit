# Output restoration semantics

This document answers one question precisely: what does TraceJIT promise about
the *metadata* of the files it restores, and is the current behaviour defensible
once a downstream build system reads that metadata?

## 1. What is promised today

`SAFETY.md` says restoration may fail closed (`Restoration failure also stops
reuse`), that outputs are validated before any destination is mutated, and that
TraceJIT does not claim inode-preserving restore. It says nothing about
timestamps. The observable-equivalence surface the benchmark oracle scores is
exit status, stdout, stderr, path set, file type, content, permission bits,
symlink targets and hard-link grouping - with timestamps, ownership and inode
numbers explicitly **advisory**.

The implementation is more specific than either statement. In
`crates/tracejit-cache/src/lib.rs`, `stage_output` replays, per regular-file
output: ownership (`chown`, before mode, so setuid bits are not cleared), mode,
and both `unix_accessed_ns` and `unix_modified_ns` via `FileTimes`. A file
artifact that is missing either timestamp fails closed as an invalid artifact
(`legacy_or_incomplete_file_artifacts_fail_closed`).

So: **restoring the recorded mtime is an implementation choice, not a documented
promise.** It is also observable, which is why it matters. The rest of this
document decides whether to keep it, and what to tell users.

## 2. The stale-archive counterexample, reproduced

Phase AB reported that a restored object could be older than an archive built
later, so `make` would skip the archive update. That is reproduced deterministically
on two independent upstream projects by `benchmarks/phase_ac/stale_archive.py`.

The experiment uses the realistic cache shape a compiler cache serves: one
translation unit compiled with two different flag sets over an unchanged source
tree, the archive rebuilt after each, then the object deleted and the first flag
set compiled again. A source *rewrite* would change `ctime` and correctly
deoptimise the hit, so it is not the reachable shape.

| Step | Traced arm | Native arm |
|---|---|---|
| compile, flags A | cold, cached (record R) | gcc |
| `ar rcs lib…a obj` | archive holds A-object | archive holds A-object |
| compile, flags B | cold, cached (second record) | gcc |
| `ar rcs lib…a obj` | archive holds B-object, newer | archive holds B-object, newer |
| delete object | - | - |
| compile, flags A | **`Reused`** (R), object restored with A-object bytes and R's mtime | gcc, object stamped *now* |
| `make` (archive: object) | **`make: 'liblua.a' is up to date.`** - `ar` not run | `ar rcs liblua.a lapi.o` - `ar` runs |
| archive member vs object | **differs** (first differing byte 40) | identical |
| object bytes vs native | identical | - |

Same outcome on zlib 1.3.1 (`libz.a`, `deflate.o`). Evidence:
`benchmarks/results/phaseac/stale_archive.json`; the harness exits non-zero if
this documented behaviour ever changes.

Interpretation, stated carefully:

* the restored **content** is exactly the native content, so this is not a
  content or replay defect;
* the restored **mtime** is exactly the mtime the original execution produced,
  which is what the current contract-free replay means by "reproduce the
  observation";
* the archive is stale only because GNU make's decision rule compares mtimes,
  and the restored object is older than an archive that was built after it;
* a tool that stamps fresh times (ccache, sccache, a native recompile) makes the
  archive update, at the cost of not reproducing the recorded metadata.

## 3. Is timestamp-exact restoration observable? Yes - measured

`benchmarks/phase_ac/metadata_observation.py` compiles a fixture that copies its
input to `out.txt` and prints `stat("out.txt").st_mtime`. Under
`allocator-entropy-v1` the warm run is a genuine HIT:

```
cold_decision                  Executed
warm_reused                    true
warm_match                     true          (oracle: full observation equal)
warm_stdout                    1795557277    (replayed)
restored_mtime_s               1795557277
stdout_names_restored_mtime    true
```

The replayed stdout names the restored file's timestamp, so the observation and
the workspace agree. Simulating policy B on the same hit (restore content, stamp
a fresh mtime - here by touching the file after the reuse):

```
stdout_still_says   1795557277
file_now_says       1795557279
divergence_s        2
```

That is the argument against a silent switch to fresh timestamps: TraceJIT
replays cached stdout, so a program that printed its output's mtime would then
describe a workspace state that no longer exists. The oracle in the corpus would
not catch it, because it treats timestamps as advisory - which is exactly why
this decision must not be made inside the restore path.

## 4. The policies, evaluated

| | Policy | Effect on make/ar | Effect on metadata observers | Crash / concurrency | Verdict |
|---|---|---|---|---|---|
| **A** | Preserve recorded metadata exactly (current) | Archive can stay stale when the restored object is older than a later archive | Correct: replayed stdout still names the restored mtime | Unchanged from today (intent, staging, rollback) | **Keep as the default** |
| **B** | Restore content, stamp fresh mtime | Fixes the stale archive for `make`/`ar` | **Breaks** every program whose output depends on its output's metadata (measured above); replayed stdout becomes a lie | Unchanged | Reject silently; it trades a documented limitation for an undocumented inconsistency |
| **C** | Restore content, declare downstream invalidation | Needs every consumer to honour the declaration | Correct if honoured | Adds a protocol nobody consumes today | Reject for now: no consumer exists, and an unhonoured declaration is worse than a documented limitation |
| **D** | Validate the dependency graph before choosing metadata | Correct in principle | Correct | Requires parsing every build system's DAG; unsound when the DAG is unknown or generated | Reject: cannot be made sound for arbitrary commands, and TraceJIT does not know the build graph |
| **E** | Explicit build-integration mode with separate semantics | Would let a user opt into fresh mtimes | Opt-in, so no silent break | A second restore semantics to test | **Reject for V0.3**; documented as the only defensible route if demand appears (see §6) |

Why A is the right default rather than a compromise: TraceJIT's contract is
*fail-closed whole-command reuse with recorded observations*. The recorded
observation of a command includes the metadata its output had. Choosing to
fabricate a different mtime would mean the restored state is not the state that
was observed, which is a semantic change disguised as a build-system fix. The
stale archive is a real limitation of that choice, and it is now measured,
documented and pinned.

## 5. The limitation and the tested workaround

**Limitation.** When a build system decides whether to run an archiving or
copying step by comparing mtimes, a restored output can appear older than a
dependent artifact that was produced later. The dependent step may then be
skipped, leaving an archive or bundle that does not match its members. TraceJIT
does not modify build systems and does not inspect their dependency graphs.

**Tested workaround** (verified in the same experiment, native arm): make the
restored outputs newer than their dependents before the build-system decision, or
invalidate the dependent step explicitly:

* `touch` the restored outputs after a run whose results you are about to feed to
  `make`/`ar` (`make` then re-archives, exactly as the native arm did);
* or force the dependent step (`make -B liblua.a`, `ar rcs` directly);
* or place TraceJIT in front of the *whole build* rather than in front of the
  compiler, so the archive is part of the same cached observation - this is the
  Phase AB whole-build result, where `make` itself is the cached command.

The third option is the only one that keeps the recorded observation intact; the
first two deliberately trade metadata fidelity for downstream freshness, and that
trade is now the user's explicit choice, not a hidden default.

## 6. What would justify a new mode

Only a demonstrated workload where (a) users cannot use whole-build caching,
(b) the stale-dependency step is expensive or silently wrong in practice, and
(c) the semantics can be selected explicitly per command. None of the Phase AC
evidence meets (a)-(c): the non-compiler workloads that reuse
(`NON_COMPILER_WORKLOAD_STUDY.md`) have no downstream mtime-driven step, and the
compiler case already has whole-build reuse. Adding a mode now would be
complexity without a user.

## 7. Regressions added

* `benchmarks/phase_ac/stale_archive.py --expect documented` - exits non-zero
  unless a warm HIT still restores the recorded mtime, `make` still skips `ar`,
  the archive still keeps the other object, and the native control still
  refreshes it. Runs on Lua 5.4.6 and zlib 1.3.1.
* `benchmarks/phase_ac/metadata_observation.py` - a HIT whose stdout names the
  restored mtime must remain consistent, and the policy-B simulation must remain
  contradictory. Both numbers are recorded, not asserted from memory.
* `crates/tracejit-cache`: `metadata_replay_round_trips_mode_owner_and_times`
  already pins exact mtime/atime/mode/owner replay; `legacy_or_incomplete_file_artifacts_fail_closed`
  pins the refusal of a record without timestamps.

## 8. Documentation correction

`SAFETY.md` did not state that output timestamps are restored exactly. Since the
behaviour is observable and now load-bearing for the stale-archive finding, the
limitations section of `docs/LIMITATIONS.md` and `SAFETY.md` should name it. This
phase adds the statement to `docs/LIMITATIONS.md`; no behavioural change was made
to the product.

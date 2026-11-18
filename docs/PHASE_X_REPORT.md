# Phase X report: guard-validation cost and verified dependency coalescing

Baseline `main`: `c7201126094e120d8079d94b0a6620786eddb2b3` (merge of Phase W1, PR #40).
Research branch: `research/phase-x`.

**Verdict.** One production change passed every gate: a cache candidate is now validated
**once**, immediately before any output is restored, instead of twice. Measured paired warm-hit
latency on the compiler workload fell from **116.7 ms to 67.3 ms (1.73×)**; the 27-invocation
rebuild session went **9.44 s → 8.67 s** and the 48-invocation session **12.53 s → 9.94 s**, with
identical cache decisions and byte-identical objects. Every proposed dependency-coalescing
experiment was rejected, including one that looked like another 1.5×: phase X found a
counterexample in which it would have produced an unsound HIT, and the case is now a permanent
regression test.

Nothing in this phase weakens a guard. The remaining 43.5 ms of validation is the contract's own
price: one read and one BLAKE3 hash of every byte the recorded command consumed.

---

## 1. Baseline and method

* Baseline binary: `cargo build --release -p tracejit-cli` at `c720112`, kept at
  `/tmp/tj-baseline` for paired comparison.
* Measurement harnesses (all new, all reproducible):
  * `benchmarks/phase_x/profile.py` — trace a workload, then measure warm hits with
    `TRACEJIT_PHASE_TIMING=1` and `TRACEJIT_GUARD_PROFILE=1`, and dump the stored record with
    `tracejit explain --json`.
  * `benchmarks/phase_x/ab.py` — paired interleaved A/B latency: each arm has its own cache, and
    measured rounds alternate between arms so machine drift hits every arm equally.
  * `benchmarks/phase_x/redundancy.py` — dependency-redundancy analysis over a stored guard list.
  * `benchmarks/phase_x/workloads.py` — non-compiler and intentionally unprofitable workloads.
  * `benchmarks/phase_w/session.py` (existing) — 27- and 48-invocation rebuild sessions.
* Workload: three translation units behind one shared header, `cc -O2 -c`, traced under
  `--contract compiler-runtime-v1` (the same workload Phase W used, functions-per-unit 220).
* Every measured invocation's cache decision is recorded. A retrace inside a measured round is
  reported as a warning and never counted as a hit.
* One methodological note that cost a wrong measurement: `TRACEJIT_PHASE_TIMING*` and
  `TRACEJIT_GUARD_PROFILE` participate in the recorded environment identity, so a warm-up run
  without them does not warm the identity a measured run looks up. The harness now warms with
  exactly the environment it measures.

`strace` cannot be used here: TraceJIT's own `ptrace` session conflicts with an external tracer, so
a traced `run` no longer reproduces the reuse path. All syscall counts below come from in-process
instrumentation at the helper the validator actually calls.

---

## 2. Guard-cost breakdown

Compiler workload, 393-guard record (`/usr/include` headers, the driver, `cc1`, `as`, shared
libraries). Medians over 18 warm runs, `TRACEJIT_GUARD_PROFILE=1`.

### 2.1 Baseline: two validation passes per hit

| pass | guards | total | hashing | stat | open | other | bytes hashed | stat calls | read syscalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| candidate check | 389 | 56.1 ms | 51.4 ms | 0.67 ms | 0.37 ms | 3.8 ms | 107,160,458 | 250 | 1737 |
| pre-restore recheck | 389 | 49.7 ms | 46.2 ms | 0.62 ms | 0.33 ms | 2.7 ms | 107,160,458 | 250 | 1737 |

Both passes are the same work: `guard_validation_ns` in the phase record only ever measured the
first, which is why the historical "≈45 ms in guard validation" understated the total cost by
about half. `guard_recheck_ns` was added to `PhaseTimings` to make the second pass visible.

### 2.2 Candidate: one validation pass per hit

| guards | total | hashing | stat | open | readlink | access | other | bytes hashed | stat calls | read syscalls |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 393 | 43.5 ms | 39.5 ms | 0.52 ms | 0.27 ms | 0.11 ms | 0.10 ms | 3.0 ms | 107,160,458 | 254 | 1737 |

Guard kinds interpreted per pass (`TRACEJIT_GUARD_PROFILE`): `FileMetadata` 234,
`SymlinkTarget` 60, `DirectoryOpened` 19, `EnvironmentValue` 13, `AccessCheck` 5,
`ControlledRuntime` 4, `OutputPrestate` 2, `ControlledEntropy` 1, `RuntimeIdentity` 1,
`WorkingDirectory` 1, `NoUnexpectedEffects` 1. Distinct paths: `FileMetadata` 184,
`SymlinkTarget` 60, `DirectoryOpened` 19, `AccessCheck` 4, `ControlledRuntime` 3,
`OutputPrestate` 2.

**91 % of validation is content hashing.** Metadata work is 1.2 %: 254 `stat`/`fstat` calls cost
0.52 ms in total. That single number decides Experiment C below.

### 2.3 Remaining warm-hit budget (candidate)

| phase | median |
| --- | ---: |
| process startup (exec + dynamic linking + static init) | 8.3 ms |
| identity preparation | 0.55 ms |
| cache open + schema + lookup query | 2.6 ms |
| candidate decode | 2.4 ms |
| guard validation (single pass) | 43.5 ms |
| CAS restore of the staged output | 4.8 ms |
| stdio replay, present, decision persist | 0.05 ms |

Warm-hit latency is `runtime_ns` plus interpreter start-up: a language runtime (the Python `etl`
workload below) pays its own start-up outside TraceJIT's control, which is why the same change is
worth 1.73× on `cc` and 1.11× on `etl`.

---

## 3. Dependency-redundancy analysis

From `benchmarks/results/phasex/redundancy-baseline.json` and the stored compiler record
`benchmarks/results/phasex/record-compiler.json.gz` (388 and 393 guards depending on the unit and
its input state; the structure is the same):

1. **Repeated metadata for the same path.** 230 `FileMetadata` guards name 180 distinct paths, and
   **51 of them are byte-identical duplicates** (same path, same expected fingerprint, because the
   header was both `stat`ed and opened in the same instant). `validate_all` already collapses an
   adjacent `FileMetadata`+content pair onto one open (52 pairs in this record); the remaining 51
   duplicates cost 51 extra `stat` calls, about 0.1 ms.
2. **Repeated content for the same path.** 57 content guards hash only 52 distinct paths:
   `cc1` is hashed **3×** (once as `ExecutableHash`, twice for `ControlledRuntime` observations),
   `gcc-13` **3×**, `as` **2×**. A pass therefore reads **107.2 MB for 43.4 MB of distinct
   content** (2.47×). This is the interesting redundancy, and section 5 explains why it stays.
   One residual duplicate is a path alias: `/lib/x86_64-linux-gnu/libc.so.6` (a `FileHash`) and
   `/usr/lib/x86_64-linux-gnu/libc.so.6` (`ControlledEntropy`) are the same file under two names;
   path-keyed work cannot merge them without resolving symlinks, which the record deliberately does
   not do.
3. **Executable identity** is recorded once per exec (`ExecutableHash`), and `files`/`executables`
   are already disjoint in `reconstruct_dependencies`, so there is no file/executable double hash.
4. **Directory opens, symlinks, access checks and environment values** already collapse per path
   or per `(path, mode, flags)` in `reconstruct_dependencies`. Nothing left to deduplicate there.

---

## 4. Accepted experiment A: one pre-restore validation pass

### 4.1 What changed

`run()` used to validate a candidate twice: once before the stdout/stderr CAS objects were loaded
and again immediately before `restore_outputs`. The first pass existed to avoid reading CAS objects
on a miss. For a hit it was pure duplicate work.

The stream objects are now loaded and verified first (as plain locals, never exposed), the
inherited-stream offsets are checked, and then **exactly one** guard pass runs immediately before
the restore. The typestate is unchanged: `GuardsPassed::admit` still gates `with_verified_streams`,
so cached bytes cannot be attached to an exposable token unless that pass succeeded.

### 4.2 Why this is not a weaker contract

The guarantee is "no cached output is restored unless a validation pass observed every input
immediately beforehand". The surviving pass is the former recheck, at the same position, observing
the same inputs. The removed pass covered `t1..t2` where `t2` is the surviving pass's own instant;
anything it could catch, the surviving pass also catches, because it observes inputs *later*. The
residual window — a mutation after the last observation, during the restore itself — is unchanged
and remains the documented V1 limitation. The change removes duplicated observation, not
observation.

Cost on the miss path: a candidate that fails its guards now pays for reading its stdout/stderr
objects first. On this workload those objects are empty; on an output-heavy command this is a
bounded read on a path that is about to re-execute the command.

### 4.3 Measurement

| metric | baseline | candidate | ratio |
| --- | ---: | ---: | ---: |
| paired warm-hit median (24 runs each, interleaved) | 116.7 ms | 67.3 ms | **1.73×** |
| paired p95 | 139.2 ms | 78.3 ms | 1.78× |
| guards interpreted per hit | 778 | 393 | 1.98× |
| `stat`/`fstat` calls per hit | 500 | 254 | 1.97× |
| `open` calls per hit | 114 | 57 | 2.00× |
| `read` syscalls per hit | 3474 | 1737 | 2.00× |
| `readlink` calls per hit | 120 | 60 | 2.00× |
| directory-open probes per hit | 38 | 19 | 2.00× |
| bytes hashed per hit | 214,320,916 | 107,160,458 | 2.00× |
| validation time per hit | 105.9 ms | 43.5 ms | 2.43× |
| 27-invocation rebuild session | 9.439 s | 8.666 s | 1.089× |
| 48-invocation rebuild session | 12.528 s | 9.936 s | 1.261× |

Sessions: identical decisions in both arms (27 invocations: 18 hits / 6 deopts / 3 misses;
48 invocations: 39 hits / 6 deopts / 3 misses) and `objects_match_native = true` in both.

### 4.4 Regressions

* `toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit` still passes: the test hook fires
  immediately before the single pass, the pass fails, and the run retraces instead of restoring.
  Its doc comment now says what it proves.
* `crates/tracejit-guards/src/phase_x_tests.rs` (new): a same-size rewrite inside one timestamp
  tick is still detected; two content guards for one path are two independent observations; a
  guard fails at its own position in record order.

---

## 5. Rejected experiment B: shared content digests per pass

### 5.1 The idea and the measured upside

`ContentObservations` cached a digest per path for the length of one pass and reused it for later
guards after re-observing the path and requiring an identical `FileFingerprint` (device, inode,
size, blocks, mode, ownership, mtime, ctime; access time excluded because a read updates it).
This is the "temporary validation context" of the brief, with an explicit validity contract.

Measured, it worked: **107.2 MB → 43.4 MB** hashed per pass, validation **43.5 ms → 24.6 ms**,
warm hit 59.8 ms → 52.4 ms, and paired A/B against the pre-Phase-X baseline **2.06×** instead
of 1.73×. Five of the eight duplicate observations were eliminated (the rest are path aliases).

### 5.2 Why it was rejected

The regression `a_same_size_rewrite_in_the_same_timestamp_tick_is_still_detected` failed against
it. `ctime` has coarse granularity in practice: a same-size rewrite that lands inside one tick
leaves `mtime`, `ctime` and `size` byte-for-byte identical, so the fingerprint comparison cannot
see it. The duplicate guards in this record are up to ~25 ms apart in the guard list
(`libc.so.6`'s `FileHash` at index 22, its `ControlledEntropy` at 387), which is far wider than a
tick: the cached digest would be handed to the later guard and a changed compiler binary would
produce a HIT.

That is precisely the "preserved-timestamp" attack the brief lists as adversarial coverage, so the
proof is incomplete and the cache was removed. The counterexample stays as a permanent regression
that proves the strict path still re-reads.

This is not a shortcoming unique to TraceJIT. ccache documents the same hazard and refuses to
cache when an input's mtime or ctime is not older than the invocation, and it exposes
`include_file_ctime,include_file_mtime` as *sloppiness* options for users who want to opt out
(<https://ccache.dev/manual/4.10.html>). TraceJIT's `Fast` guard mode is the same kind of explicit,
opt-in relaxation; Phase X did not extend it and did not use it for any number published here.

The sound version of this idea — verify each path's content at the **last** guard that names it and
defer the earlier duplicates — was evaluated on paper only. It is not obviously weaker (the last
observation is at least as late as the last check the current code performs), but it changes
failure attribution to a later guard, and it would split the `FileMetadata`+content pair that
currently shares one open file description. That is a larger semantic change than this phase's
evidence justifies; it belongs in its own phase with its own counterexample hunt.

---

## 6. Experiment ledger

| # | Hypothesis | Evidence | Verdict |
| --- | --- | --- | --- |
| A | The initial candidate check and the pre-restore recheck are the same work; one pass suffices | 105.9 ms → 43.5 ms validation, 1.73× warm hit, sessions 1.09×/1.26×, all gates pass | **Accepted** |
| B | Share one content digest across guards of the same path in a pass | 107.2 MB → 43.4 MB, 1.5× further, but same-tick rewrite proves a false HIT is reachable | **Rejected** (counterexample kept as a test) |
| A2 | Drop the 51 exactly duplicated `FileMetadata` guards at record construction | 51 `stat` calls ≈ 0.1 ms of a 43.5 ms pass (0.2 %), below the paired noise floor | Rejected (unmeasurable; exact dedup is sound, so it remains available if a pathological record appears) |
| C | Batch metadata with `statx` through `io_uring` or a worker pool | Metadata is 0.52 ms of 43.5 ms (1.2 %); the ceiling on the whole idea is 0.5 ms, against a dependency, a thread pool, kernel-version handling and a new failure mode | **Rejected on measurement** |
| D | Compile an immutable dependency plan per record | Interpretation overhead is the unattributed 3.0 ms of the pass (credential reads, `uname`/`getrlimit`, environment lookups, the loop itself); 91 % of the pass is `read`+BLAKE3, which a plan cannot remove | **Rejected on measurement** |
| E | Persistent change tracking (`inotify`/`fanotify`) to skip re-validation | Queues overflow (`IN_Q_OVERFLOW`, `FAN_Q_OVERFLOW`) and drops are silent by design; rename records are not atomic and can be split across a watched/unwatched boundary; a missed event is a wrong HIT | **Research only**; an empty queue is never proof of unchanged content |
| — | Metadata-only recheck (compare fingerprints instead of re-hashing) | Would replace the section-5 counterexample's safety with the same coarse `ctime` assumption, in `Strict` mode | Rejected: that is `Fast` mode under another name |

---

## 7. Prior art, and what does not transfer

* **ccache direct mode.** The manifest stores include-file paths plus their hash sums at store
  time, and a hit re-hashes those files
  (<https://ccache.dev/manual/4.14.3.html>). Same conclusion as Phase X: content, not metadata,
  decides a hit. ccache additionally *refuses* to cache when an input timestamp is not older than
  the invocation, exactly to avoid the tick-sized race that killed experiment B, and documents
  `include_file_ctime,include_file_mtime` sloppiness as the opt-out
  (<https://ccache.dev/manual/4.10.html>). ccache also validates only the inputs the compiler
  reported via `-MD`, including letting `-MMD` *exclude* system headers — a narrower contract than
  TraceJIT's observation of what the process actually read, and not transferable.
* **sccache.** Hash keys include a BLAKE3 digest per file plus the compiler path and, for Rust, the
  sysroot shared libraries (<https://github.com/mozilla/sccache/blob/main/docs/Caching.md>). The
  interesting difference is scope: sccache models a compiler's known input set; TraceJIT records
  whatever the process touched, so it cannot assume a compiler-style dependency list exists.
* **Bazel** takes the opposite structural choice: actions declare their inputs, and the action
  cache is keyed by content digests of those declared inputs. Transferable lesson: content
  addressing is what makes coalescing cheap. Not transferable: Bazel *knows* the input set from the
  build description; TraceJIT must infer it from `ptrace`.
* **Ninja** tracks dependencies through depfiles and timestamps only — cheaper, and explicitly
  weaker than what TraceJIT promises; it is the baseline a compiler cache is compared against, not
  a correctness model to copy.
* **`statx`/`STATX_CTIME`.** `ctime` is updated by writing and by inode changes
  (<https://man7.org/linux/man-pages/man7/inode.7.html>), which is what makes a fingerprint useful
  at all — but the *granularity* is the filesystem's and the clock's, which is why no fingerprint
  can substitute for a read (section 5).
* **`io_uring`/batched metadata.** Pointless at 254 `stat` calls costing 0.52 ms (section 6C).
* **`inotify`/`fanotify`.** The man pages are explicit that a cache built on events can end up
  inconsistent with the filesystem and that overflow means dropped events
  (<https://man7.org/linux/man-pages/man7/inotify.7.html>,
  <https://man7.org/linux/man-pages/man7/fanotify.7.html>). This is why experiment E stays
  research-only.

---

## 8. Adversarial verification

Every item below is exercised by the suite that ran for this branch; the newly added ones are in
`crates/tracejit-guards/src/phase_x_tests.rs` and
`crates/tracejit-cli/tests/linux_integration.rs`.

| Attack | Coverage |
| --- | --- |
| Same-size modification | `same_size_content_change_with_original_mtime_deoptimizes`, `a_same_size_rewrite_in_the_same_timestamp_tick_is_still_detected` |
| Preserved timestamps (`utimensat`) | same two tests; the second runs inside one tick, the worst case |
| Restored contents (ABA) | full re-read per guard per pass; no digest survives a pass |
| Atomic rename replacement | inode changes, so a `FileMetadata` guard fails; `rename_over_existing` fixture |
| Hardlink alias writes | path-keyed guards: each name is observed, `read_then_replace`/`symlink_delete_recreate` fixtures |
| Symlink swaps | `SymlinkTarget`/`SymlinkMetadata` guards plus path replay semantics |
| Concurrent truncate/write | TOCTOU hook test; documented residual window unchanged |
| Executable replacement | `ExecutableHash` re-reads the binary every hit (this is 32 MB of the 107 MB) |
| Permission changes | `OutputPrestate`, `DirectoryOpened`, `AccessCheck` guards replay the kernel answer |
| Directory replacement | `DirectoryOpened`/`DirectoryEnumerated` identity checks |
| Multiple cache candidates | candidate loop unchanged; each candidate validates once |
| Output corruption | CAS object verification before any destination is mutated |
| Interrupted restoration | `scripts/phase_k4_restore_fault.sh` (soft fail + hard kill) |
| Unknown syscalls | classification refuses reuse; census below |
| Previously recorded cache entries | `#[serde(default)]` fields keep old records strict; no schema bump |
| Phase W1 rename-source counterexample | `rename_source_bytes_are_an_input_even_when_the_source_is_recreated` |

---

## 9. Verification results

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace --no-fail-fast` | pass (34, 5, 1, 72, 6, 1, 1, 23, 29, 41, 4, 21 tests per target) |
| `cargo test -p tracejit-cli --test linux_integration -- --nocapture` | **72/72 pass** |
| `cargo build --workspace --release` | pass |
| `cargo audit` | no advisories (110 crates) |
| State-machine model check (`scripts/modelcheck/check_state_machines.py`) | `RESULT phase-k3-modelcheck PASS`, 0 violations |
| Restore fault injection (`scripts/phase_k4_restore_fault.sh`) | soft-fail PASS, hard-kill PASS |
| Differential fuzzing (`benchmarks/differential/fuzz.py --seed 29`) | `RESULT differential PASS`, 120 ok, **0 incorrect hits** |
| Real-world census (`benchmarks/realworld/census_v03.py`, held-out 20) | 20/20 executed, 0/20 reused, equivalence PASS — identical to the Phase U baseline (all refusals are genuine nondeterminism) |
| Version consistency | unchanged (`0.2.0-beta.1`); no release |

Descriptor-inheritance regressions are part of the 72-test integration suite
(`runner_inherited_descriptors_do_not_contaminate_runs_and_are_still_refused`); the Phase U2
child-local sweep is untouched.

### 9.1 CI

`.github/workflows/ci.yml` on branch `research/phase-x`: run **#253** on the production commit
`fac3f0d` completed **successfully** (fmt, clippy, workspace tests, release build, version
consistency, doctor, single-threaded Linux integration, census, demo).

One runner-side flake was observed: on the documentation-only follow-up `c378b68`, the `Tests`
step failed at default parallelism because `allocator_entropy_contract_reuses_a_glibc_tool` and
`inherited_stdin_reuse_is_stable_across_fresh_sessions` saw the allocator-entropy contract
classify a glibc tool `Nondeterministic` instead of `Guarded`. Both tests pass on this host
individually and in the full default-parallel suite (72/72), and the *same* code passed that
same step minutes earlier in #253, so this is the sensitivity to runner process pressure that
`PROJECT_STATE.md` already records for the default thread count — not a behaviour change. The
strict single-threaded `Linux integration` step never ran in that attempt because the earlier
step failed. The branch's final head was re-run and its status is reported with the PR.

---

## 10. Remaining bottlenecks

1. **Content hashing: 39.5 ms of 43.5 ms of validation, 107 MB read per hit.** Of that, about
   64 MB is the same compiler binaries read two or three times (section 3.2). Removing it needs a soundness proof
   that survived the counterexample in section 5; none did in this phase.
2. **Process start-up: 8.3 ms** — larger than the whole first-pass saving on trivial commands, and
   the floor under every hit (visible in the `true` workload: 8.5 ms for a 1 ms program).
3. **Candidate decode (2.4 ms) and lookup (2.6 ms).** Records carry their full effect list; a hit
   only needs the guard list, the outputs and the streams. Not attempted here: it is a cache-format
   change, outside the guard-validation scope of this phase.
4. **24 credential reads per hit** (`/proc/self/status` for 19 directory guards and 5 access
   checks), part of the 3.0 ms "other". A per-pass cache of the process's own identity is
   plausibly sound (validation is single-threaded) for about 1 ms; it was left for a later phase
   because it is the same class of change as experiment B and would need the same adversarial
   treatment.

---

## 11. Limitations of the evidence

* One machine, one filesystem (`ext4`, `relatime`), one kernel. Absolute latencies are not
  portable; the paired ratios are the claim.
* The compiler workload is synthetic (three units, one shared header) although it uses the real
  `cc`/`cc1`/`as` pipeline and `/usr/include`. Sessions use the same construction.
* `sort` on a small file never reuses (20/20 refusals), so the "unprofitable" data point is `true`
  (a hit that costs more than the program) plus the census, not a second real workload.
* Instrumentation overhead: unmeasurable when disabled (paired ratio 1.00 within spread); when
  enabled it costs **3.7 %** (61.0 ms → 63.3 ms median), so profile numbers are slightly
  pessimistic and always off for the headline latencies.
* The reordering changes *when* a corrupt stdout/stderr object is reported relative to a guard
  failure for the same candidate. Both produce a deopt with a reason; the reason chosen can differ
  when a candidate is both corrupt and stale.
* Warm-up and cache identity interact through the environment (section 1); a benchmark that warms
  without the measurement variables measures a different identity.

---

## 12. Reproducing

```bash
cargo build --release -p tracejit-cli

# guard-cost profile (two passes on the baseline, one on the candidate)
python3 benchmarks/phase_x/profile.py --tracejit target/release/tracejit \
    --workload repeat --rounds 6 --guard-profile \
    --output benchmarks/results/phasex/profile-final-guardprofile.json

# dependency redundancy over a stored record
python3 -c 'import json;print(json.dumps(json.load(open("benchmarks/results/phasex/profile-final-guardprofile.json"))["record"]))' > /tmp/record.json
python3 benchmarks/phase_x/redundancy.py --record /tmp/record.json

# paired interleaved A/B (baseline binary built from c720112)
python3 benchmarks/phase_x/ab.py --arm baseline=/tmp/tj-baseline \
    --arm final=target/release/tracejit --rounds 8 \
    --output benchmarks/results/phasex/ab-final.json

# non-compiler and unprofitable workloads
python3 benchmarks/phase_x/workloads.py --baseline /tmp/tj-baseline \
    --candidate target/release/tracejit --rounds 6 \
    --output benchmarks/results/phasex/workloads.json

# cumulative sessions
TRACEJIT_MAIN_BINARY=/tmp/tj-baseline python3 benchmarks/phase_w/session.py \
    --scenario edits --rounds 9 --edit-rounds 3,6 --tracejit target/release/tracejit \
    --arms tracejit-main,tracejit-fix --output benchmarks/results/phasex/session-27.json
TRACEJIT_MAIN_BINARY=/tmp/tj-baseline python3 benchmarks/phase_w/session.py \
    --scenario edits --rounds 16 --edit-rounds 7,12 --tracejit target/release/tracejit \
    --arms tracejit-main,tracejit-fix --output benchmarks/results/phasex/session-48.json
```

Raw evidence: `benchmarks/results/phasex/` (`ab-final.json`, `ab-share.json` for the rejected
experiment, `profile-*-guardprofile.json`, `redundancy-baseline.json`, `workloads.json`,
`session-27.json`, `session-48.json`, `fuzz-29.json`, `census-v03.json`). The profile files carry
the per-pass measurements and per-run samples but not the embedded record, whose effect list is
large; the compiler record is kept gzipped as `record-compiler.json.gz` (`zcat` it to feed
`redundancy.py --record`).

## 13. Files

* `crates/tracejit-core/src/lib.rs` — single pre-restore validation pass; `guard_recheck_ns` and
  `guard_profile` in `PhaseTimings`.
* `crates/tracejit-guards/src/profile.rs` (new) — opt-in per-kind/per-operation counters and
  timers, `TRACEJIT_GUARD_PROFILE=1`.
* `crates/tracejit-guards/src/lib.rs` — instrumentation at `hash_reader`, `hash_file`,
  `fingerprint`, the metadata/content pair, `readlink`, access, directory probes;
  `validate_all` wrapper that cannot change control flow.
* `crates/tracejit-guards/src/phase_x_tests.rs` (new) — the strictness regressions.
* `crates/tracejit-cli/src/main.rs` — attach the profile to the phase file.
* `crates/tracejit-cli/tests/linux_integration.rs` — docs for the TOCTOU test now describe the
  single pass.
* `benchmarks/phase_x/{profile,ab,redundancy,workloads}.py` (new), `benchmarks/results/phasex/`.
* `SAFETY.md`, `docs/LIMITATIONS.md` — the TOCTOU wording now matches one validation pass.

# Phase W: multi-state reuse, the two-deoptimisation penalty, and honest competition

Baseline: `main` = `cb4783f10bc4de0c8b7cf269121cfd83710730df` (PR #39). Research branch:
`research/phase-w`. Production binary before any change: `31898b97e5d8c427773930469d795a097de2d654b684017e55974bd2edcf2c64`
(byte-identical to `main`). All numbers below are measured on this host (Linux 6.1.102, x86_64,
8 vCPU, 15 GiB, ext4, `relatime`) against real `cc -O2 -c` translation units under the declared
`compiler-runtime-v1` contract. Raw data: `benchmarks/results/phasew/`.

## 1. The two-deoptimisation phenomenon, reproduced

`benchmarks/phase_w/transitions.py` records, for every invocation of a three-unit rebuild:
input state, output pre-state, cache decision and reason, the failing guard, every retained cache
record (decoded from SQLite with its guards and output artifacts), and the output post-state.
It hashes objects with `O_NOATIME` so the measurement does not itself invalidate a metadata guard.

With `main`, six rounds with header edits at rounds 2 and 4 (18 invocations) give
`3 Executed, 3 Reused, 12 Deoptimized`. Every round after an edit deoptimises; the record written
by the previous round is never reused. Phase V's 27-invocation session reproduces
`1.09×` (13.544 s vs 14.774 s native, 11 hits, 12 deopts), matching its report.

The failing guard is not the output pre-state class guard. It is a `FileHash` guard on the
**output object itself**, recorded with the content the object had *before* the compile:

```
guard 1007 Read  File { unit0.o, hash: 9d6a… }     <- tracer, not the program
guard 1008 Write File { unit0.o, operation: Delete }
guard 1009 Write File { unit0.o, operation: CreateOrModify }
```

`delete_pending`/`rename_pending` in `tracejit-trace` take a `path_snapshot` before the syscall and
`record_snapshot` pushes it as an ordinary `Read(File)` effect. Dependency reconstruction then keeps
that read because it precedes the first write to the path. The record therefore claims "I read
object bytes 9d6a…", when what actually happened is "those bytes were destroyed and replaced". The
next run cannot have them: the previous execution replaced them. One real input edit thus costs two
full executions:

1. edit invalidates the source hash → deopt → recompile (correct);
2. the fresh record still names the pre-delete object bytes → the object is now the new one → deopt
   again → recompile (this is the artefact).

`cc` produces exactly this pattern (`unlink` the old object, then create it), which is why the
penalty appeared only on the compile workload Phase V found profitable.

## 2. The fix: provenance for pre-state snapshots

`FileRead`/`FileMetadataRead` gain `#[serde(default)] prestate_snapshot`, set by `record_snapshot`
(a tracer observation) and false for every program read (records written earlier deserialize as
false and keep the strict behaviour). `reconstruct_dependencies` computes the **last** write
operation per path and drops a snapshot dependency only when the path ends the execution present
(its last write is `CreateOrModify`/`RenameDestination`): the execution destroyed those bytes and
then replaced them, so they cannot reach any observable effect, and the program's own reads of the
path remain separate effects. A path whose last write is `Delete` is emptied for good; the removed
bytes stay an exact input guard, unchanged.

Nothing else is relaxed: the output pre-state class guard, restore preconditions (regular file,
single link), object re-hashing, and every device/inode/permission/alias rule are untouched.

### Result

| session (3 units, 220 functions) | main | fixed | native |
| --- | --- | --- | --- |
| 27 invocations, edits at 3,6 | 13.544 s (11 hit / 12 deopt) | **9.239 s** (18 hit / 6 deopt) | 14.774 s |
| 48 invocations, edits at 7,12 | 14.872 s (33 hit / 12 deopt) | **11.548 s** (38 hit / 7 deopt) | 24.280 s |

27-invocation speedup against native: 1.09× → **1.60×** (1.47× against `main`). 48-invocation:
1.63× → 2.10×. Every arm's objects are byte-identical to a native build of the final sources.
The transition harness now shows exactly one deopt per edit per unit and immediate reuse after it.

## 3. Competition (same units, same schedules)

Nine- and sixteen-round cumulative sessions, all arms measured in the same process on the same
machine. `ccache 4.9.1`, `sccache 0.10.0`, GNU Make 4.3, ninja 1.12.1.

| scenario (27 invocations unless noted) | native | main | fixed | ccache | sccache | make | ninja |
| --- | --- | --- | --- | --- | --- | --- | --- |
| edits at 3,6 | 14.774 | 13.544 | 9.239 | **5.371** | 5.860 | 5.493 | 5.111 |
| repeat, no edits (48) | 24.181 | 6.620 | 6.762 | **1.916** | 1.912 | 1.540 | 1.567 |
| headers alternate A/B (30) | 9.115 | 16.208 | 17.933 | **2.460** | 2.892 | 8.486† | 10.276 |
| output deleted at 3,6 (30) | 9.852 | 6.929 | 6.309 | **1.505** | 1.407 | 1.594 | 1.629 |
| output corrupted at 3,6 (30) | 9.081 | 5.604 | 5.153 | **1.191** | 1.299 | 0.917† | 1.726 |
| flag change at 3,6 (30) | 9.141 | 6.842 | 6.024 | **2.057** | 2.261 | 0.925 | 0.934 |
| env var change at 3,6 (30) | 9.090 | 7.545 | 7.509 | **1.223** | 1.241 | 1.063 | 1.038 |

† produced objects that differ from a native build of the final sources: Make skipped a rebuild
because the target's mtime was newer (corruption) or the rewritten header kept the same second
(toggle). Ninja re-checks with depfiles and recovered the corruption case; Make did not. These are
real robustness differences between mtime scheduling and content caching, and they are reported as
such, not as speed.

**ccache and sccache win every compile-caching scenario, by 1.7× to 3.5× against the fixed
TraceJIT.** A driver-level hit costs TraceJIT 99–114 ms here versus ~35 ms for ccache, and ccache
never re-executes after an edit because it keys on preprocessed source instead of tracing. Make and
ninja skip whole commands for ~1 ms and are faster still whenever the build graph knows the
dependencies, but they cannot avoid a rebuild after a header edit and do not detect corrupted
outputs by content. TraceJIT remains the only arm that can memoise a *non-compiler* whole command
with validated inputs; on compile workloads its general contract is simply more expensive than a
compiler-specific cache. There is no measured basis for claiming TraceJIT beats ccache.

## 4. Multi-state records: what actually blocks revisiting a state

Records are already multi-state: the store keeps up to 8 candidates per identity
(`DEFAULT_MAX_CANDIDATES_PER_IDENTITY`), indexed by `execution_id`, and the walk validates newest
first. An A→B→A schedule produced five distinct records for five executions, each with the correct
source-hash guard — retention and candidate selection are not the problem.

Revisiting A still deoptimises, and the failing guard is not content:

```
round 2 (header back to A): FileMetadata common.h — "metadata changed; no content hash was recorded"
guards 41/42  FileMetadata(common.h) + FileHash(common.h)   <- pair, hash fallback exists
guard 144     FileMetadata(common.h)                        <- metadata-only, from gcc's own stat
```

`FileMetadata`+`FileHash` pairs may fall back to the content hash when only timestamps differ
(`metadata_change_allows_hash_fallback`). Guard 144 has no hash to fall back on: it is the
compiler's own `stat` of `common.h` while probing for a precompiled header (`common.h.gch`, also
guarded). gcc really does consult that metadata, so **the guard is correct**; an input that is
rewritten with identical bytes is a different observable state to this program. That is the
remaining, genuine reason a mutation costs a recompilation, and it is why "identically rewritten
sources always reuse" is not a safe contract change without modelling the compiler's PCH rule.
`docs/PHASE_W_REPORT.md` §7 lists it as the next contract question, not as a defect.

Consequently: the first deopt is required by the recorded contract; the second was an artefact of
record construction and is now gone; revisiting an older *state* is possible only when the program
did not stat the input's metadata, which the fixture-based
`alternating_inputs_reuse_a_retained_candidate` test covers and the compiler case cannot satisfy.

## 5. Rejected hypothesis: parallel guard validation

Profile of a warm hit on the 220-function unit: 99–114 ms total, `guard_validation_ns` 45 ms,
`cas_restore` 3.1 ms, SQLite query 2.2 ms, record decode 2.4 ms, process start 10.7 ms. The record
carries 408 guards and 45.7 MB of hashed content (`cc1` alone is 30.5 MB). A prototype that
pre-evaluated the 57 metadata+content units on 8 threads (same answers, same decision order, same
first-failure reporting) hashed that content in 15–17 ms instead of ~30 ms, but the sequential walk
over the remaining 354 metadata/symlink/access/runtime guards still cost 28–34 ms, so the measured
hit was unchanged (110.6 ms vs 111.7 ms median, n=7). Rejected and reverted: complexity without a
demonstrated end-to-end gain. Attacking the walk itself would mean re-working hundreds of guards
into batched stat/readlink calls; no evidence yet that it repays the review cost.

## 6. Verification

* `cargo fmt --all --check`, `cargo clippy --workspace --all-targets --all-features -- -D warnings`,
  `cargo audit`: clean.
* `cargo test --workspace --no-fail-fast`: every target passes, including 27 effects unit tests,
  36 guard tests, and **71/71** Linux integration tests. The child-local descriptor regressions from
  PR #39 are untouched and pass.
* `python3 scripts/modelcheck/check_state_machines.py`: PASS (reuse_hit, restore_crash,
  restore_intent, planted illegal state rejected).
* New adversarial tests: `superseded_delete_does_not_pin_the_next_run_to_the_old_bytes` (one input
  edit, one deopt, then a hit; an externally corrupted output is still restored) and
  `terminal_delete_still_requires_the_deleted_bytes` (a path deleted for good still deoptimises when
  its bytes differ). Three effects unit tests pin the dependency rule for superseded, terminal, and
  program reads.
* Every benchmark arm asserts object equality with a native build; the harness records decisions,
  cache bytes, and raw timings per arm.

## 7. Recommendation

Merge the superseded-delete change as a focused PR against `main` (three production source files:
the effect shape, the tracer's provenance flag, and the dependency rule; no SQLite schema change,
and old records keep the stricter behaviour). Do **not** merge the parallel
validation prototype and do not publish v0.3 on this evidence. Next work, in measured order:
(1) batch the metadata half of guard validation, which is now the dominant hit cost; (2) decide
whether a compiler stat of a header whose PCH is absent can be modelled as content-equivalent — that
is the only remaining path to reusing an earlier input state.

Reproduce:

```bash
python3 benchmarks/phase_w/transitions.py --rounds 6 --edit-rounds 2,4 --output /tmp/t.json
python3 benchmarks/phase_w/session.py --scenario edits --rounds 9 --edit-rounds 3,6 --output /tmp/s.json
```

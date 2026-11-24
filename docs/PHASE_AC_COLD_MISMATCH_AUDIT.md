# Phase AC: the `tar-create` cold mismatch on PR #44

## 1. What was reported

| Item | Value |
|---|---|
| Workflow | `Real-world benchmark v2` (`.github/workflows/benchmark-v2.yml`) |
| Run | [45430554122](https://github.com/Satwik-P28/tracejit/actions/runs/45430554122), attempt 1 |
| Head | `c187cc2c765b2fd5297a33c6407683e5ad555446` (`research/phase-ab`) |
| Failing job | `smoke` (job 138574336648), step 10, "Smoke benchmark (dev split, native + compiler contract)" |
| Failing step result | `failure`; check-run annotation: "Process completed with exit code 1" at `benchmark-v2.yml:267` |
| Other jobs | `correctness` succeeded; `full` and `competitive` skipped (PR event) |
| Reported row | `tar-create`, `cold_mismatch`, first seen under `compiler-runtime-v1` |

The job log itself is not retrievable from this environment: `gh` is not
authenticated and no token is available, and the jobs/annotations API is readable
anonymously but the log endpoint is not. Everything below is therefore derived
from the committed workflow, the anonymous job/annotation metadata, and a local
reproduction of that exact step - not from the log text.

The step that failed runs:

```
python3 benchmarks/realworld_v2/runner.py \
  --tracejit target/release/tracejit --mode both \
  --policies native,compiler-runtime-v1 --splits dev --reps-scale 0.25 \
  --output-dir "$AA_SCRATCH/smoke" --vendor "$AA_SCRATCH/vendor"
```

`cold_mismatch` is emitted at `runner.py` step 2: a **cold** traced execution
whose independent oracle observation differs from a native execution in the
native twin. Reproducing it needs only steps 0-2 of `qualify`, which is what
`benchmarks/phase_ac/tar_mismatch.py` implements.

## 2. Root cause

Not a TraceJIT defect and not a flaky runner. It is a **benchmark-fixture
defect**: the two twins were not identical in the one thing `tar` copies into
its output.

The shipped `qualify` built the twins with two separate preparation calls:

```python
corpus.prepare(native_ws, ctx, workload)
corpus.prepare(traced_ws, ctx, workload)
```

`corpus.prepare` is deterministic in the *bytes* it writes, but every write
stamps the current wall-clock time. The workload is

```
tar -cf bundle.tar corpus.txt corpus.bin
```

and the GNU tar header stores each member's modification time in seconds. Two
twins with identical content written at different times therefore produce two
*different but equally correct* archives. When both `prepare` calls land inside
the same wall-clock second the archives match; when they straddle a second
boundary they do not. That is the intermittency.

The pre-state gate could not see this. `oracle.compare_workspace_trees` compares
the covered contract fields - paths, type, mode, size, content digest, symlink
target, hard-link grouping - and reports timestamps as *advisory*. That is the
right rule for judging a reused decision (TraceJIT's observable contract does not
include input timestamps) and the wrong rule for proving that two twins start
equal. So the fixture divergence passed the pre-state check and surfaced three
steps later as an unexplained `cold_mismatch`.

Cause chain, each link measured:

1. the second `prepare` call writes the same bytes at a later time (`mtime`
   differs in 83 of 100 staggered trials, 51 of 60 in the traced experiment);
2. `tar` serialises the input `mtime` into both member headers;
3. the archive bytes differ, so the oracle reports a covered `entry` difference;
4. the harness reports `cold_mismatch`, which aborts the row before any reuse or
   timing evidence is collected.

## 3. Reproduction

`benchmarks/phase_ac/tar_mismatch.py --mode twins` reproduces the harness
sequence with a randomised stagger between the two `prepare` calls, then runs
the identical `tar` command natively in the native twin and cold under TraceJIT
in the traced twin, comparing both observed states with the shipped oracle.

`benchmarks/results/phaseac/tar_mismatch_twins.json` (60 trials, both policies,
120 compared runs):

```
cold_mismatches                 81 / 120   (67.5 %)
covered_fields_in_mismatch      {"entry": 81}
tar_header_fields_in_mismatch   {"mtime": 156, "block_sha256": 156}
input_mtime_unequal_trials      51 / 60
mismatch_when_mtimes_differ     51
mismatch_when_mtimes_equal      0
prestate_covered_mismatches     0
```

Read that as four independent facts:

* every mismatch is an `entry` difference on `bundle.tar`; nothing else in the
  workspace or on either stream ever differed;
* inside the archive, the **only** differing header field is `mtime`; name, mode,
  uid/gid, size, type, magic, uname/gname and member order are identical, and the
  payload blocks are identical;
* mismatch is perfectly predicted by unequal input mtimes (51 of 51) and never
  occurs when they are equal (0 of 9);
* the content-only pre-state check passes in every trial - it was structurally
  incapable of catching this.

`benchmarks/results/phaseac/tar_mismatch_native_only.json` is the same experiment
without TraceJIT (native twin versus native twin, 100 trials, 83 staggered): 83
trials had unequal input mtimes. This isolates the defect from any traced
execution entirely - the two native runs already disagree with each other.

Byte-level inspection of one failing pair: the archive `sha256` differs, the
member payloads are byte-identical, and the first differing byte is inside the
header `mtime` field. Forcing both twins to a single `mtime` before archiving
makes the archives identical (`fixed equal: True` in the two-directory probe).

A separate 100-trial native-only run (`tar_mismatch_native_only.json`) also shows
the shape the CI saw is *not* tied to a contract: native-versus-native twin
divergence is the same effect, so the fact that CI reported it under
`compiler-runtime-v1` only reflects which policy ran first into a second boundary.

## 4. Decision

The benchmark oracle and fixture had the defect; the product did not. Correcting
the comparison is therefore legitimate here - but not by silencing the check.
Three changes, in `benchmarks/realworld_v2/runner.py`:

1. **Prepare once, clone with metadata.** `prepare_twins()` calls
   `corpus.prepare` for the native twin and creates the traced twin with
   `shutil.copytree(..., symlinks=True)`, which preserves `mtime`, mode and
   ownership. The twins are now identical in every field a program can read,
   without normalising timestamps inside any workload - which would have
   destroyed the relative timing that `make-header-change` and
   `make-incremental-noop` depend on.
2. **Gate on metadata, not only content.** `prestate_metadata_differences()`
   compares kind, mode, size, `mtime_ns`, uid, gid and symlink target for every
   path before anything runs, and a mismatch stops the row as
   `prestate_metadata_mismatch`. This is a *harness* check and is deliberately
   separate from the oracle's contract, which still treats `mtime` as advisory.
3. **Make the validation contract complete.** `prestate_mismatch` (already
   emitted before this phase) and the new `prestate_metadata_mismatch` were
   missing from `validate.ACCEPTABLE` and from the results schema; both are now
   accepted, together with `hit_accounting_mismatch` and
   `cache_corruption_mismatch`, which the runner could also emit.

Nothing about eligibility, classification, guards, restoration or the wall-clock
comparison changed. A `cold_mismatch` is still a hard failure and is never
counted as a performance result.

## 5. Verification

* Fixed harness, same experiment, 100 trials, 200 compared runs
  (`tar_mismatch_clone.json`): **0 cold mismatches**, 0 unequal input mtimes,
  0 pre-state metadata differences.
* The real CI smoke step, run locally at this head with the fixed harness:

  ```
  python3 benchmarks/realworld_v2/runner.py --mode both \
    --policies native,compiler-runtime-v1 --splits dev --reps-scale 0.25
  ```

  exited 0 in 42 s; `validate.py` reports
  `OK: ... satisfies tracejit.realworld.results/v1`; 42 rows =
  10 reused / 30 refused / 2 tool-unavailable, **0 cold_mismatch, 0
  incorrect_hit**. `tar-create` is now `refused` under both policies (its
  `fcntl` on inherited fd 0 is unmodelled), with `prestate_metadata` equal.
  Evidence: `benchmarks/results/phaseac/smoke/results.json`.
* Permanent regression in `benchmarks/realworld_v2/test_harness.py`
  (`TwinsShareMetadata`): a one-second fixture skew must be *detected* by the
  metadata gate and must *change* a `tar` archive; a metadata-preserving clone
  must remove both. The test asserts the mechanism, not a timing coincidence.
* All 33 harness self-tests pass, including the new ones.

## 6. What this does and does not establish

Established: the CI failure is fully explained by fixture timestamps, reproduces
deterministically at 67.5 % under the same harness sequence, is absent when the
twins share metadata, and the corrected step passes locally end to end.

Not established here: that the CI job now passes. That requires a run on the new
head, which needs the branch push and the workflow (see `PHASE_AC_REPORT.md`).
The other `tar-create`-shaped workloads (`zip-create`, `tar-gzip`,
`zlib-gzip-tarball`) shared the same defect and are fixed by the same change;
they were not individually re-measured beyond the smoke split.

One residual, deliberately unchanged: the oracle still treats output timestamps
as out of contract. That is a separate question - what TraceJIT promises to
restore - and is analysed in `OUTPUT_RESTORE_SEMANTICS.md`.

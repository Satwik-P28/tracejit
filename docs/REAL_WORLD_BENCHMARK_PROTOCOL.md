# Real-world benchmark protocol, version 2 (Phase AA)

This document is the contract for `benchmarks/realworld_v2/`. It states what is
measured, how, what is deliberately not measured, and which comparison a reader
is not allowed to make from the artifacts. The protocol was fixed **before** any
result in `benchmarks/results/phaseaa/` existed, and no product behaviour was
changed in Phase AA.

## 1. Question

> For which ordinary Linux commands is whole-command reuse both semantically
> correct and net faster, compared with just running the command again?

Not "how large can a speedup be on a favourable command". A negative answer for a
family is a result and is reported as one.

## 2. Tiers: two orthogonal axes, never merged

The task's tier vocabulary mixes two different things, and conflating them is how
benchmark suites end up publishing an eligibility rate that means nothing. This
package keeps the axes separate.

**Axis 1 — workload setup (a property of the row):**

| Tier | Definition | Rows here |
| --- | --- | --- |
| A | Strict native. The command, its inputs, its invocation and its environment are unmodified. No contract, no adaptation. | 50 |
| C | Adapted workload. At least one declared change: an environment variable, a thread pin, an input shape, a wrapper script. Every adaptation is listed in `adaptations`. | 9 |
| D | Unsupported. TraceJIT refuses reuse. Kept as a negative result with its refusal reasons. | any refused row |

**Axis 2 — execution contract (a property of the invocation):**

| Policy | Flag | What it fixes |
| --- | --- | --- |
| `native` | none | nothing |
| `allocator-entropy-v1` | `--contract allocator-entropy-v1` | the audited glibc allocator entropy probe |
| `compiler-runtime-v1` | `--contract compiler-runtime-v1` | the audited GCC 13.3.0 toolchain's incidental runtime observations |

Tier B in the task vocabulary corresponds to the contract axis. A row therefore
carries both `environment_tier` and `policy`, and eligibility is reported as a
separate cell per `(tier, policy)` pair. **No table sums tier A with tier C, and
no table averages a native-policy row with a contract row.** Contract rows are
labelled "reproducible under contract", which is a weaker claim than "equivalent
to native execution".

## 3. Corpus

- 59 workload configurations in 12 families, declared in
  `benchmarks/realworld_v2/corpus.py` and frozen in `manifest.json`.
- 5 of the 59 need tools absent from this image (`cppcheck`, `shellcheck`,
  `ruff`, `zstd`, `pyarrow`). They are reported as `tool_unavailable` and are
  excluded from every eligibility denominator. A missing tool says nothing about
  TraceJIT.
- Provenance: generated fixtures are versioned by the SHA-256 of `corpus.py`
  recorded in the manifest. The four zlib workloads use the pinned upstream
  archive `https://zlib.net/fossils/zlib-1.3.1.tar.gz`, SHA-256
  `9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23`, verified
  by `fetch_inputs.py`. Each run records the digest of the inputs it actually
  used in `results.json`.
- Inputs are realistic where it matters: real upstream C translation units for
  the compiler family, real system text for the compressors, 5000-row CSV and
  3000-record JSON for the data family, and a 20000-line text file for the text
  family. Nothing is shaped to make TraceJIT eligible.

### 3.1 Split discipline

| Split | Workloads | Role |
| --- | ---: | --- |
| `dev` | 21 | used while building the harness |
| `validation` | 22 | used to check that the harness generalises beyond dev |
| `heldout` | 16 | frozen; executed once, for evidence |

The split was declared in `corpus.py` before any Phase AA number was produced.
Phase AA changes no product behaviour, so there is no optimization that could
have been selected on the held-out split. The held-out rows are still reported
separately, because the next phase will optimize and will need them untouched.

## 4. Measurement

### 4.1 Design

- **Randomized paired samples.** For each repetition both arms run once, in
  random order, from an identical pre-state. The reported interval is a
  percentile bootstrap over the *per-pair* ratio, which controls for drift
  between the arms. Independent-sample medians are also reported, because
  readers expect them, but the interval that matters is the paired one.
- Repetitions: 20 for light workloads, 10 for medium, 5 for heavy
  (`corpus.COST_REPS`). `--reps-scale` changes only the count.
- Cold tracing is sampled separately: `max(3, min(reps, 10/5/3))` fresh-cache
  runs, because a cold sample needs an empty cache and therefore cannot be
  paired with a warm sample.
- Two warm-up runs per arm before measurement. Warm-ups are not recorded.
- Pre-state before **every** timed sample: the workload's declared output paths
  are removed. This is the harsher case for TraceJIT (it must materialise
  outputs) and it makes the two arms start from the same bytes.
- Timed region: the whole wall-clock duration of the process
  (`subprocess.run`), including TraceJIT's own start-up. That is the cost a user
  actually pays.

### 4.2 What counts as a hit

A sample counts as a cache HIT only when TraceJIT reports `kind = "Reused"` for
that exact invocation. The reported `cache_decision` is recorded next to it.
A sample with `kind = "Executed"` and `cache_decision = "Deoptimized"` is a miss
and is never silently folded into a "hit" latency. If a warm sample is not a
HIT the timing row is aborted and recorded as `hit_lost_during_timing`; it is not
averaged with the rest.

### 4.3 Statistics

- Median, mean, p05, p95, min, max, and the raw nanosecond samples.
- Bootstrap 95 % CI of each arm's median (4000 resamples).
- Paired ratio `direct / arm` with a bootstrap CI on its geometric mean. A ratio
  **above 1** means the arm was faster than direct execution; **below 1** means
  slower. This convention is stated in the schema and in every report that uses
  it.
- Break-even repeat count
  `ceil((cold_median − direct_median) / (direct_median − warm_median))`, only
  when both differences are positive. Otherwise `null`, never a guess.
- Session model at 2, 5, 10, 25 and 50 repeats:
  `cold + (R − 1) × warm` versus `R × direct`.

### 4.4 Per-stage cost model

One instrumented two-run session per eligible workload with
`TRACEJIT_PHASE_TIMING=1` produces `process_startup_ns`, `identity_prepare_ns`,
`sqlite_query_ns`, `record_decode_ns`, `guard_validation_ns`, `cas_restore_ns`,
`stdio_replay_ns`, `decision_persist_ns` and `present_ns`.

Two properties of this probe are recorded because they matter:

1. TraceJIT hashes the inherited environment into the cache key. Enabling
   instrumentation on an already-populated cache turns the probe into a miss, so
   the probe runs its own session with instrumentation on for both runs.
2. Instrumentation costs time, so these numbers are a *breakdown*, never the
   headline hit latency.

## 5. Environment fingerprint and what is not controlled

Recorded per run: TraceJIT commit, binary SHA-256, `doctor` output, kernel
release and `uname`, distribution, glibc path and build ID, CPU model, logical
and physical core counts, frequency governor (when exposed), RAM, filesystem
type, virtualisation and container markers, exact versions of every tool that
matters, the allow-listed environment variables, and the active contract.

Not controlled, and therefore not claimed:

- **Page cache.** The host cannot establish a cold page cache reliably (no root,
  shared VM). Every timing row is warm-page-cache. `results.json` says so; no row
  may be described as cold-cache.
- **CPU frequency.** `scaling_governor` is recorded when readable. It is not
  changed, because that is a host-wide setting.
- **Noisy neighbours.** This is a 2-vCPU shared VM. That is why N is published,
  raw samples are published, and the paired design is used. Effects smaller than
  the reported interval are not claimed.
- **Hardware counters.** `perf` is not installed. The field
  `environment.hardware_counters` says so; no instruction or cycle count is
  reported or estimated.

## 6. Independent observational oracle

`benchmarks/realworld_v2/oracle.py` imports nothing from TraceJIT. For each
workload it compares a traced execution against a native execution in a
byte-identical twin directory.

**Covered observations** (a mismatch on a `Reused` decision is an incorrect hit):
exit status, stdout bytes, stderr bytes, the set of paths, each path's type,
regular-file contents, permission bits, symlink targets, hard-link grouping,
directory membership.

**Out-of-contract observations** (reported, never pass/fail): inode numbers,
mtime/atime/ctime, uid/gid, device numbers. The contract does not claim to
reproduce them, and a benchmark that scored them would be measuring the wrong
thing.

Byte equality of one output file is never accepted as proof of equivalence: the
whole workspace is fingerprinted, including deleted and created paths.

## 7. Cache-state transitions

Qualification runs this sequence for every workload and records the decision and
the observation at each step:

| # | Step | Required outcome |
| --- | --- | --- |
| 1 | clean native execution | reference observation |
| 2 | cold trace, fresh cache | `Executed`, not `Reused` |
| 3 | first warm attempt | `Reused`, observation equal to native |
| 4 | repeated HITs | timed warm arm, every sample `Reused` |
| 5 | input mutation | not `Reused`, or a correct observation if the mutated path is not an input |
| 6 | expected deoptimisation | recorded as `deoptimised_after_mutation` |
| 7 | immediate retry, no further change | recorded verbatim |
| 8 | input restored to the earlier state | candidate reuse attempted; a deoptimisation here is a performance finding, not a correctness failure |
| 9 | output corruption | a HIT must restore the correct output |
| 10 | stored CAS object removed | never a wrong HIT; retracing is correct |
| 11 | cache restart (new directory) | never `Reused` |
| 12 | reuse after the above | still correct |

Step 8 is where the corpus produced its most interesting negative result: for
several workloads the "return to an earlier input state" path deoptimises even
though a matching record exists, because metadata guards (access time, inode
change time) also moved. That is sound but costly, and it is reported as such.

## 8. Adversarial suite

`benchmarks/realworld_v2/adversarial.py` runs:

1. the preserved Phase W1 13-case matrix (rename source, rename destination,
   terminal delete, delete→create→delete, partial execution, symlink and
   hard-link aliases, replaced inode, program reads, multiple writes), and
2. an attempted Phase X same-size/same-mtime rewrite, which **measures** whether
   the timestamp collision was actually achieved on this kernel and filesystem
   instead of assuming it, and
3. workload-specific mutations, and
4. a race probe of the validate-to-restore window.

The race probe is reported with its exact wording: a stale observation
demonstrates the documented window; zero stale observations do **not** demonstrate
that the window is closed. Passing a test suite is not a proof about a TOCTOU
window.

## 9. Reporting rules

1. Numbers from different commits and different binary digests are never mixed.
2. Refusals, `tool_unavailable`, `eligible_but_no_hit`, `harness_error` and
   `skipped_budget` stay in the tables. Nothing is filtered out of the count.
3. An unavailable competitor is `unavailable`, never "slower".
4. A faster result caused by skipping work is labelled as skipping, not as a
   verified replay.
5. Aggregates are per `(tier, policy)` cell. There is no single headline
   eligibility number in `results.json`, and none should be invented by hand.
6. The best result from a previous version is not the default claim for current
   `main`.

## 10. Threats to validity

- **Two vCPUs.** All absolute latency is one shared VM. Ratios are the portable
  quantity; absolute milliseconds are not.
- **Small-N heavy workloads.** Five repetitions on the expensive commands. The
  bootstrap interval shows the resulting uncertainty rather than hiding it.
- **Fixture realism.** Generated fixtures are not production data. The four zlib
  workloads and the system text files are the only genuinely upstream inputs.
- **Contract coverage.** Two contracts are audited, for two specific runtimes.
  Any other libc or GCC build refuses, correctly, and the corpus then reports a
  refusal rather than a contract win.
- **Hit-path caching of the page cache.** Output restoration reads from the OS
  page cache. This makes warm hits look better on large outputs than they would
  on a cold cache; the report says so where it matters.

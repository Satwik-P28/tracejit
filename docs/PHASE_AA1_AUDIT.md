# Phase AA1 audit: benchmark integrity, attribution, reproducibility

Audit of Phase AA (`research/phase-aa`, PR #43) by an adversarial reviewer whose
job was to break its evidence, not to extend it. No product optimisation and no
compatibility change was made. One product-behaviour question (missing CAS
objects) was re-verified with new regressions; everything else is benchmark
infrastructure, documentation and measurement.

Evidence: `benchmarks/results/phaseaa1/`. Timing evidence was produced at commit
`1c87e027d3a5c86e7d00435bf573737f20949c3f` with a clean tracked tree
(`working_tree_dirty=false`) and binary sha256
`daca8b0dc9fda100abd8801d9f6f619c0e1c3082981f20be2de8f1dd4361dbe4`.
The reproduction evidence was produced from a separate clone at
`ae884c59320b1ee37ac2d0ae8af24eae98f26241` with the same binary hash.

## 0. Verdict

Phase AA's *conclusions about direction* survive: TraceJIT wins on compute-heavy
repeated commands, loses on everything cheap, is unusable under strict native
execution, and its compiler niche is contract-dependent. Three of its *numbers*
do not survive:

1. Eligibility and reuse were conflated. The table headed "Eligibility" reported
   `reused / attempted`, not `eligible / attempted`. The real eligibility rates
   are 4.1 %, 24.5 % and 38.8 % for the three policies, not 2.0 %, 20.4 % and
   34.7 %.
2. The hit latency of stdout-heavy workloads was inflated by the harness's own
   reporting channel. `sed` was published at 0.17–0.18× native; it is
   0.64–0.70×. `cut` 0.15× → 0.20–0.25×. `gzip -6` 0.44–0.50× → 0.64–0.77×.
   The direction (a loss) is unchanged; the magnitude was wrong by up to 4×.
3. The stage-timing section reported non-additive totals and negative residuals.
   The cause is now identified and the model reconciles to within 7 ms on every
   row. The `--json` channel accounts for the 15–50 ms that was unattributed.

A fourth claim — that no competitor baseline existed — was true for Phase AA's
environment but is no longer true here: ccache 4.10.2 was installed in user space
and measured. It is **14× cheaper per hit than TraceJIT** on the exact workload
that Phase AA presents as TraceJIT's best case.

## 1. Counting audit

### 1.1 The reconciliation

`177 = 59 workloads × 3 policies` is the number of *declared* cells. Of those,
15 are `tool_unavailable` — five workloads (`cppcheck-project`, `parquet-convert`,
`ruff-check`, `shellcheck-script`, `zstd-19-file`) that name a tool this image
does not have, each counted under all three policies. That leaves 162 *attempted*
cells = 54 available workloads × 3.

| Quantity | Native | `allocator-entropy-v1` | `compiler-runtime-v1` | Total |
| --- | ---: | ---: | ---: | ---: |
| Declared cells | 59 | 59 | 59 | 177 |
| Tool-unavailable | 5 | 5 | 5 | 15 |
| Attempted | 54 | 54 | 54 | 162 |
| Refused | 52 | 42 | 35 | 129 |
| Eligible but no HIT | 1 | 2 | 2 | 5 |
| Verified HIT (reused) | 1 | 10 | 17 | 28 |
| Timed rows | 1 | 8 | 11 | 20 |
| Incorrect HITs | 0 | 0 | 0 | 0 |

The published prose said "177 rows = 59 workloads × 3 policies, minus
unavailable-tool rows", which reads as 162 and never states how the subtraction
splits. The rate columns then divided *reused* cells by 49. Both halves are now
explicit, and `runner.py` recomputes the whole ledger from the rows on every run
(`aggregate.accounting`) and `validate.py` rejects any results file whose
`workloads` array does not reproduce it.

Every cell also carries `eligible_for_reuse`, so the two rates can never be
confused again:

| Policy (tier A, 49 available) | Eligible | Rate | Reused | Reuse rate |
| --- | ---: | ---: | ---: | ---: |
| native | 2 | 4.1 % | 1 | 2.0 % |
| `allocator-entropy-v1` | 12 | 24.5 % | 10 | 20.4 % |
| `compiler-runtime-v1` | 19 | 38.8 % | 17 | 34.7 % |
| tier C, any policy (5 available) | 0 | 0 % | 0 | 0 % |

The two cells that are eligible but never hit are real: `gzip-9-file` and
`objcopy-strip`/`strip-binary` style metadata-sensitive rows classify `Guarded`
and then deoptimise on the second run, because the command's own read updates the
`atime` their guard recorded. That is sound behaviour and a permanent miss, not a
harness error.

### 1.2 Permanent invariants

`benchmarks/realworld_v2/test_harness.py` now asserts, from synthetic rows, that
the ledger rejects: a tampered status, a tampered reused count, a row counted
twice, a missing decision, and a declared-cell count that no longer equals
`workloads × policies`. `validate.py` recomputes `accounting_errors()` on real
files. The suite that Phase AA ran is therefore able to fail on the exact class of
mistake it made.

## 2. Oracle audit

`oracle.py` was read in full. It compares a traced execution against a native
execution in a byte-identical twin directory and separates:

* **covered** — exit status, stdout, stderr, every workspace path's type, file
  bytes, permission bits, symlink target, hard-link group identity, directory
  entries, and files created or deleted;
* **out of contract** — atime/ctime/mtime nanoseconds, inode numbers, ownership,
  and any effect outside the workspace (network, other paths, stream
  interleaving between stdout and stderr).

That split is correct: TraceJIT's documented contract does not claim timestamp or
inode preservation, and a comparison that failed on them would make every row
wrong. The distinction is recorded per row, not just in prose, and only covered
differences can fail a run.

Two gaps were found and are now tested rather than assumed:

1. A stale output that the traced run did **not** rewrite is detected only because
   the workspace tree comparison includes unchanged files. The previous check
   compared only paths the record claimed to write, which would accept a stale
   `deflate.o` from an earlier build. `compare_workspace_trees` now diffs the whole
   tree against the native twin, and a row whose pre-state differs between the
   twins is rejected before timing.
2. Hard-link identity was not distinguishable from two identical files. The tree
   digest now groups by inode, so replacing a hard link with a copy fails.

Intentionally wrong replays constructed for the tests (all rejected): stale output
bytes, missing output, extra file, wrong mode, symlink retargeted, hard link
replaced by a copy, directory where a file is expected, stdout inequality, stderr
inequality, exit-status inequality, and an advisory-only difference that must
*not* fail. 29 harness tests pass; they are permanent, not a one-off script.

The oracle cannot see: effects outside the sandbox, interleaving between the two
streams, xattrs, ACLs, sparse layout, or timing. Those are listed as out of scope
in the module docstring and in `REAL_WORLD_BENCHMARK_PROTOCOL.md`. It also does
not prove that a *correct-looking* replay is the operation the user wanted; it
proves observational equivalence on the covered set.

## 3. Missing-CAS fix review

The Phase AA fix is in `crates/tracejit-cache/src/lib.rs`: `stage_output` maps
`NotFound` to `CorruptObject`, and staging of every object completes before the
first rename, so a missing object aborts the restore before any output is
replaced. The core then deoptimises and retraces, which is safe because nothing
was applied. `get_bytes` does the same for stream objects.

Reviewed cases and their disposition:

| Case | Behaviour | Verdict |
| --- | --- | --- |
| Missing stdout CAS object | `CorruptObject` → deopt → retrace | safe |
| Missing stderr CAS object | same, regression test | safe |
| Missing output artifact | same, regression test | safe |
| Corrupted artifact (bad hash) | `CorruptObject` → retrace | safe |
| Permission-denied CAS file | fail closed, command not run | correct: unresolved state |
| Failure during staging | no rename has happened | safe |
| Multiple outputs, one missing | nothing applied, retrace | safe |
| Interrupted restoration (`restore_intent`) | next HIT refused | fail closed |
| Cache restart | no intent → normal lookup | safe |
| Concurrent prune during restore | **not tested**; the existing `CorruptObject` path covers a vanished object, but a prune between hash check and read is a race with no test | open |

Three regressions were added to `linux_integration.rs` (missing stderr object,
permission-denied CAS with the command asserted not to have run, multi-output
missing object). Integration suite: 84/84 at `--test-threads=4`.

**Not proven:** concurrent pruning is safe in the sense that a failed read
deoptimises, but no test exercises a prune racing a restore. Phase AB should add
one, or document the window.

## 4. GCC classification instability

Phase AA saw `gcc-cc-small-tu` classified `Nondeterministic` in one full-suite run
and `Guarded` in others. Reproduced with a dedicated probe
(`classification_stability.py`, 100 trials per workload, cold trace each time):

| Workload | `Guarded` | `Nondeterministic` | Determinant |
| --- | ---: | ---: | --- |
| `gcc-cc-small-tu` | 94 | 6 | `getrandom` |
| `zlib-compile-deflate` | 98 | 2 | `getrandom` |
| `gcc-cc-heavy-tu` | 100 | 0 | — |

The effect is at the pid of the **gcc driver**, syscall sequence 57 of 323, before
`cc1` and `as` start. It is `getrandom`, which gcc's driver issues when it seeds
its own hash tables; whether it appears depends on the C library's
per-process AT_RANDOM availability and the driver's startup path. It is real
program behaviour, not a harness artefact and not a product defect: the tracer
observed a syscall that the classifier correctly refuses to model.

It is nevertheless a **benchmark** problem, and it is worse than a curiosity:

* a 2 % refusal rate makes a 20-row timing pass lose a row roughly one time in
  three; two consecutive timing passes here lost `zlib-compile-deflate` and then
  `gcc-cc-heavy-tu`, and the Phase AA count of 13 timed workloads was itself the
  result of one lost row;
* a user running 25 builds sees a refusal about 40 % of the time at 2 %, and 80 %
  of the time at 6 %, for reasons no user can see;
* `gcc-cc-heavy-tu` was 100/100 in the focused probe and still refused once during
  a loaded timing run, so 100 clean trials do not bound the rate on a shared VM.

The refusal rule was **not** weakened. What changed is that a refused timing
attempt is recorded rather than silently dropping the row: the row keeps
`timing_attempts` with the failed calibration and the successful retry. The
published table says which rows needed a retry.

## 5. Performance attribution

### 5.1 The 15–50 ms

Phase AA timed the hit arm with `--json`, which serialises the *entire* cached
stdout as a JSON byte array (`sed` report: 1,414,102 bytes) and made this harness
parse it inside the timed region. Measured on `sed`: `--json` 40.8 ms vs plain
20.2 ms for the same hit, with `present_ns` at 22.1 ms. The 40 ms of Python
decoding was then attributed to TraceJIT's "unattributed residual".

The timed arm now runs plain mode and reads the decision from TraceJIT's own
report block, with one `--json` calibration per row outside the timed region to
obtain authoritative identity fields. Effect: `sed` 73.4–79.9 ms → 15.5–17.3 ms;
`gzip -6` 13.1–17.1 → 8.1–10.2 ms; everything with a small stdout is unchanged.

### 5.2 Negative residuals

`runtime_ns` is captured in the core **before** the decision is persisted, so
`post_runtime_ns` (persistence) is additional to it, not part of it. Subtracting
`runtime_ns` from a wall that contained persistence produced negative residuals.
The model now publishes three measured spans and a remainder, and never subtracts
across a boundary it does not own:

```
wall = process work (pre_runtime + post_runtime) + core runtime_ns + presentation
hit path inside runtime_ns = validation + CAS reads + restore
residual = runtime_ns - measured hit path          (published, never hidden)
```

`process_startup_ns` is derived from tick-granular `/proc/self/stat` (10 ms
quantum on this kernel), so it is reported but never used in a sum.

Representative rows (ms, same run):

| Row | wall | pre | runtime | persist | present | hit-path measured | residual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `c-numeric` (allocator) | 19.66 | 7.56 | 7.58 | 4.42 | 0.10 | 7.25 | 0.34 |
| `gcc-cc-heavy-tu` (compiler) | 90.13 | 15.68 | 58.23 | 16.14 | 0.08 | 53.87 | 4.37 |
| `zlib-compile-adler32` | 107.32 | 16.44 | 70.59 | 20.22 | 0.07 | 63.75 | 6.84 |
| `sed-substitute-file` (allocator) | 43.01 | 6.57 | 7.76 | 3.50 | 25.18 | 7.21 | 0.55 |

Every row reconciles: `pre + runtime + persist + present = wall` exactly as
measured, and the hit-path residual is ≤ 7 ms, which is the part of `runtime_ns`
the existing phase instrumentation does not break down (candidate selection and
decode). No bottleneck percentage in this document is derived across those
boundaries; the three spans are additive because they were measured on disjoint
intervals of the same invocation.

`zlib-compile-deflate`'s cost model is empty in the evidence because its phase
probe hit was lost to a classification refusal; its timing row is valid (the
probe is separate from the timed samples) and is published without a model rather
than with a partial one.

## 6. Corrected results

Randomized paired design, 20 reps (`svc`/light), 10 (medium), 5 (heavy), 20 timed
rows over 13 workloads, 0 incorrect HITs, 0 stdout mismatches across all timed
samples.

| Workload | Policy | Direct ms | Cold ms | Warm ms | Warm ratio | CI95 | Break-even | Session 25× |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `c-numeric-integration` | allocator | 335.8 | 368.7 | 10.44 | **30.23** | 22.6–40.5 | 1 | 13.56 |
| `c-numeric-integration` | compiler | 334.8 | 364.2 | 10.83 | **33.74** | 26.1–45.7 | 1 | 13.41 |
| `gcc-cc-heavy-tu` | compiler | 470.3 | 735.4 | 63.77 | **7.35** | 7.16–7.57 | 1 | 5.19 |
| `zlib-compile-deflate` | compiler | 492.8 | 719.8 | 65.62 | **7.24** | 6.39–7.83 | 1 | 5.37 |
| `zlib-compile-adler32` | compiler | 87.5 | 333.6 | 68.91 | 1.28 | 1.22–1.36 | 14 | 1.10 |
| `gcc-noopt-compile` | compiler | 60.0 | 297.2 | 70.69 | 0.84 | 0.70–0.95 | — | 0.75 |
| `gcc-cpp-preprocess` | compiler | 13.3 | 167.1 | 60.04 | 0.22 | 0.20–0.24 | — | 0.21 |
| `gcc-fanalyzer` | compiler | 20.9 | 163.6 | 60.89 | 0.39 | 0.32–0.54 | — | 0.32 |
| `gcc-syntax-only` | compiler | 24.0 | 219.1 | 59.69 | 0.40 | 0.36–0.46 | — | 0.36 |
| `gzip-6-stdout` | native | 6.2 | 30.5 | 8.08 | 0.77 | 0.71–0.86 | — | 0.70 |
| `gzip-6-stdout` | allocator | 6.0 | 36.0 | 10.17 | 0.66 | 0.58–0.75 | — | 0.54 |
| `gzip-6-stdout` | compiler | 6.3 | 31.8 | 8.16 | 0.64 | 0.46–0.81 | — | 0.69 |
| `sed-substitute-file` | allocator | 11.1 | 65.3 | 17.33 | 0.64 | 0.58–0.77 | — | 0.58 |
| `sed-substitute-file` | compiler | 10.3 | 64.2 | 14.75 | 0.70 | 0.62–0.75 | — | 0.61 |
| `objdump-disassemble` | allocator | 3.7 | 44.3 | 15.36 | 0.25 | 0.24–0.28 | — | 0.22 |
| `objdump-disassemble` | compiler | 3.5 | 45.5 | 14.97 | 0.23 | 0.21–0.25 | — | 0.22 |
| `readelf-header` | allocator | 2.1 | 35.1 | 13.20 | 0.15 | 0.14–0.17 | — | 0.15 |
| `readelf-header` | compiler | 2.2 | 40.1 | 14.58 | 0.15 | 0.14–0.17 | — | 0.14 |
| `cut-columns` | allocator | 3.2 | 39.2 | 14.77 | 0.20 | 0.19–0.24 | — | 0.20 |
| `cut-columns` | compiler | 3.1 | 40.7 | 12.04 | 0.25 | 0.25–0.27 | — | 0.23 |

* **Faster than native by CI (4 workloads):** `c-numeric-integration` (30.2–33.7×),
  `gcc-cc-heavy-tu` (7.35×), `zlib-compile-deflate` (7.24×),
  `zlib-compile-adler32` (1.28×).
* **Slower than native by CI (9 workloads):** `cut-columns`, `gcc-cpp-preprocess`,
  `gcc-fanalyzer`, `gcc-noopt-compile`, `gcc-syntax-only`, `gzip-6-stdout`,
  `objdump-disassemble`, `readelf-header`, `sed-substitute-file`.
* **Worst regression:** `readelf-header`, 0.15× (medians 2.1–2.2 ms → 13.2–14.6 ms,
  6.7× slower).
* **Warm-hit floor:** 8.1 ms (smallest observed, `gzip -6` native) to 17.3 ms;
  gcc-shaped rows 59.7–70.7 ms. The AA figure of 11–17 ms was the floor for rows
  whose stdout was small; the floor is lower than published, not higher.
* **Cold tracing overhead:** +32 ms (`c-numeric`), +54 ms (`sed`), +227 to +265 ms
  (zlib translation units). The first two repeats recover it; `adler32` needs 14.
* 4 of 13 timed workloads have positive cumulative savings at 25 repeats.

Corrections against Phase AA's table: `sed` 0.17–0.18 → 0.64–0.70, `cut`
0.15–0.16 → 0.20–0.25, `gzip` 0.44–0.50 → 0.64–0.77, `c-numeric` 30.6 (CI
24.1–39.5) → 30.2–33.7 (CI 22.6–45.7), `deflate` 6.92 → 7.24, `adler` 1.32 →
1.28 (break-even 12 → 14), `gcc-noopt` 1.02 "indistinguishable" → 0.84 with CI
0.70–0.95 (slower). `gcc-cc-heavy-tu` is unchanged at 7.35× with a warm median
22 ms lower, because its stdout is small.

## 7. Competitive evidence

Phase AA reported ccache unavailable and made "measure ccache" a release blocker.
A ccache 4.10.2 user-space static build was installed here (no root) and measured
with `competitive_zlib.py`: same command, same directory, same CPU, interleaved
randomised order, output object deleted before every sample, every sample hashed
against a native reference.

`gcc -O2 -I zlib-1.3.1 -c zlib-1.3.1/deflate.c -o deflate.o`, 20 samples each:

| Arm | Median | Speedup vs native (CI95) | Hits | Population |
| --- | ---: | ---: | ---: | ---: |
| native | 490.6 ms | 1.00 | — | — |
| ccache 4.10.2 | **4.54 ms** | **108.1×** (97.2–116.6) | 20/20 | 556.5 ms |
| TraceJIT (compiler contract) | 65.18 ms | 7.53× (7.16–8.00) | 20/20 | 735.2 ms |

All 20 samples per arm produced a byte-identical object. ccache's fixed hit cost
is 14× lower than TraceJIT's, and its population cost is lower too.

This is the honest reading: on a single compiler invocation — TraceJIT's best
case in this corpus — a compiler cache is decisively better on both axes. The
"6.9–7.4× speedup" is real but irrelevant to anyone who can use ccache. TraceJIT's
remaining defensible ground is (a) commands a compiler cache cannot see, and
(b) output-integrity repair, which ccache also does not do (it verifies its own
object hash, but it does not notice that the file in your workspace was corrupted
and restore it). Neither has been demonstrated at scale here.

Not measured: sccache and ninja were downloadable but not run; firebuild was not
available; `perf` is absent; hyperfine 1.19.0 is installable (the pinned static
build was fetched and verified) but the Phase AA cross-check was not repeated.
The Phase AA claim that hyperfine was present is a statement about that sandbox,
not this one.

## 8. Independent reproduction

Conditions: `git clone --no-hardlinks` of the repository into a new directory,
checkout `ae884c5`, `cargo build --release --bin tracejit` with a normal `HOME`
(binary hash identical to the working tree's: `daca8b0d…`), then
`AA_MODE=smoke AA_SKIP_BUILD=1 AA_SKIP_COMPETITIVE=1` with `env -i`, `HOME` set to
an empty directory, a fresh scratch directory and a fresh vendor directory
containing only the pinned zlib archive.

Result: exit 0; 42 declared cells, 40 attempted, 9 reused, 7 timed, 10 verified
hit decisions, 0 incorrect hits; schema and accounting validation pass;
`environment.commit` = the clone's HEAD, `working_tree_dirty=false`,
`untracked_entries=0`; preserved counterexamples 13/13; 0 stale race observations
in 4 trials. Artifacts: `benchmarks/results/phaseaa1/repro/`.

This run found a real defect that local success had hidden:
`benchmarks/phase_w1/audit.py` defaulted to a fixed `/tmp/tracejit-phase-w1-audit`
and called `mkdir()` after a `rmtree(ignore_errors=True)`. On a shared `/tmp` that
directory can belong to another user; the removal silently failed and the audit
died with `FileExistsError`, so the adversarial gate failed with an empty stdout
tail and no diagnostic. Fixed by using a unique `mkdtemp` root, and the gate now
records the suite's stderr. Two consecutive audits pass 13/13.

`cargo` is correctly reported unavailable under an empty `HOME`; the package does
not need it when `AA_SKIP_BUILD=1` and an explicit binary are given.

## 9. Gates

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | pass (run at `0a7d08b`; no Rust change after) |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass (same) |
| `cargo test --workspace` | pass, exit 0 (same) |
| `cargo test -p tracejit-cli --test linux_integration -- --test-threads=4` | 84/84 |
| Harness unit tests (`test_harness.py`) | 29 pass |
| Oracle adversarial suite (W1) | 13/13, twice in a row |
| Model check (`scripts/modelcheck`) | PASS, `restore_crash` 2 mixed-kill states recorded as a limitation |
| Schema + accounting validation | pass on the full 177-row file and on the clean-clone smoke file |
| Packaging | pass: archive, `RELEASE_MANIFEST.json`, `SHA256SUMS`, SBOM (110 components); installer test pass |
| Differential fuzz, restore fault injection, `cargo audit` | **not run in this phase** |
| GitHub CI | **not verifiable here**: no credentials; REST API rate-limited |

## 10. Remaining risks and unproven claims

1. **Classification instability is unbounded on a loaded host.** 94–100 % stability
   per workload is measured; a 25-build session can still refuse. No deterministic
   classification test exists.
2. **A prune racing a restore has no test.** The code path fails closed, but that
   is reasoning, not evidence.
3. **Validate→restore TOCTOU is unchanged**, and 0 stale observations in 4 trials
   is not evidence that it is closed.
4. **`TRACEJIT_CACHE_DIR` relocation invalidates every record** because the
   environment is hashed into identity. Any benchmark or user who moves a cache
   silently gets zero hits.
5. **The oracle is silent about out-of-workspace effects**, stream interleaving,
   xattrs and ACLs.
6. **Single host, single kernel, 2 vCPU, no frequency control.** Ratios are
   reproducible in shape, not to the millisecond, and ccache was measured on the
   same host so the comparison is intra-host.
7. **Only 13 of 54 available workloads are timed.** The untimed 41 are refused or
   eligible-but-never-hit; their absence from the timing table is not evidence
   about their speed.
8. **The competitive picture is one command.** One translation unit is ccache's
   best case. A whole-build comparison (make + ccache vs make + TraceJIT over a
   mutation schedule) was not run here and is the correct Phase AB experiment.

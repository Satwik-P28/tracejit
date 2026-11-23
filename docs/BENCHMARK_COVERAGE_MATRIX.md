# Benchmark coverage matrix (Phase AA, Part I)

Audit of every benchmark asset in the repository at `e4f80ad`, what it covers,
what it was missing before Phase AA, which release state its numbers belong to,
and the reproducibility risks that remain.

## 1. Which commit does each number belong to?

This is the first thing a reader gets wrong, so it comes first. Three distinct
states exist in this repository and their numbers are **not** interchangeable.

| State | Commit | Artefacts | What it is |
| --- | --- | --- | --- |
| Published beta | tag `v0.2.0-beta.1`, `7a594b9` | `benchmarks/releases/v0.2.0-beta.1/` | the only binary a user can download |
| Historical `main` before the beta | `4ffde9a`, `ed3bd39`, `7b9e7ca` | `benchmarks/results/final_stab_pr3/`, `final_stab_pr4/` | measurements that produced the beta decision, not the beta itself |
| Current unreleased `main` | `e4f80ad` (this audit) | `benchmarks/results/phaseaa/` (Phase AA) and the phase reports | has never been released; includes `development/v0.3` model work and the Phase Z contract changes |

`VERSION` still says `0.2.0-beta.1` while `main` contains behaviour the beta does
not have (a second audited contract, `compiler-runtime-v1`; the 8.12 allocator
admission; the Phase X single-pass validation). Numbers from `main` must never be
presented as beta numbers, and the beta's numbers must never be used to describe
`main`.

## 2. Existing assets

| Asset | Kind | Covers | Strength | Gap found in the audit |
| --- | --- | --- | --- | --- |
| `benchmarks/harness/benchmark.py` | timing, one workload | C ETL, direct vs cold vs warm | asserts a cache HIT from stderr and a real `Reused`; records p95, stdev, raw samples | one synthetic workload; no paired randomization; no CI; no effect of mutation on latency |
| `scripts/benchmark.sh` | wrapper | refreshes `latest.json` | reproducible invocation | overwrites `latest.*` by hand-run only |
| `benchmarks/harness/break_even.py` | timing sweep | break-even by duration | explicit sweep | one workload family; no uncertainty |
| `benchmarks/releases/run_release.py` | release package | 9 scenarios incl. census, concurrency, invalidation | refuses a non-`Reused` warm sample; publishes raw samples and bootstrap CI; environment block | mostly synthetic/controlled workloads; no Tier C declarations; no machine-readable schema |
| `benchmarks/realworld/census.py` | eligibility | 32 real commands, native + outputs | missing tools separated from refusals; refusal reason categorisation; output equivalence on a hit | applies `GLIBC_TUNABLES`/`MALLOC_ARENA_MAX` to the **direct arm as well**, so its "native" label is really a controlled-environment label; his not randomized or paired; no confidence intervals; no mutation/restart/corruption transitions; no cache storage measurement |
| `benchmarks/realworld/census_v03.py` | eligibility | 20 held-out commands | imports the census harness instead of copying it | shares every gap above |
| `benchmarks/oracle/independent_obs.py` | correctness | 4 hand-built cases | CLI-only, imports no product crate; twin-directory comparison; preserves the rename-exchange and getrandom counterexamples | 4 cases; not wired to a workload corpus; no schema |
| `benchmarks/phase_w1/audit.py` | correctness | 13 snapshot-provenance cases | native twin per case; separates `expect_reuse` from `files_match` | not run in CI; no cache-state transitions for real workloads |
| `benchmarks/phase_z/adversarial.py`, `benchmarks/differential/fuzz.py` | correctness | allocator contract, fuzz seeds | end-to-end | scoped to one contract |
| `benchmarks/phase_x/*`, `benchmarks/phase_w/*` | research measurement | guard cost, sessions | raw samples, ablations | research scripts, not a protocol; no held-out split |
| `benchmarks/repos/*` | comparative | Make, Ninja, ccache, sccache (when present) | records missing tools instead of scoring them | ad-hoc scenarios; no scheduler-vs-cache role distinction |
| `.github/workflows/benchmark.yml` | CI | manual-only full harness run | builds and uploads `benchmarks/results/` | `workflow_dispatch` only; no PR gate; no schema validation; no artifact retention policy; uploads the whole results directory (including hand-committed files) |

## 3. Coverage before Phase AA, by task family

| Family requested | Before | Gap |
| --- | --- | --- |
| Compilers and build systems | gcc compile, link, ar, make, rustc (census) | no incremental header change, no clean, no heavy real translation unit at two optimisation levels, no repeated build session under the new protocol |
| Static analysis | clang-tidy, cppcheck, shellcheck, ruff named but almost never installed | treated as "missing tool" with no alternative; no `gcc -fanalyzer`, no bytecode compilation |
| Compression and packaging | gzip, bzip2, xz, tar, zip, unzip | no input-size/ratio recording; no ratio-vs-cost comparison at two presets |
| Data processing | jq, awk, sed, sort, cut, perl | no CSV→JSON, no Parquet (unavailable), no NumPy |
| Scientific compute | awk float reduction | no compiled numeric kernel, no image transform measured under the protocol |
| Interpreters/tooling | Python, node, perl, rustc | no separation of clock/entropy/identity barriers per workload; no toolchain inspection commands (`objdump`, `readelf`, `nm`, `strip`, `objcopy`) |
| Filesystem-sensitive | implicit in crash-recovery and W1 | no delete/recreate, symlink swap, hard-link alias, identical-content rewrite, or metadata change as *workloads* |
| Real upstream projects | none | no pinned third-party source tree |

## 4. What Phase AA adds

| Gap | New asset |
| --- | --- |
| No versioned corpus | `benchmarks/realworld_v2/corpus.py` + frozen `manifest.json` (59 workloads, 12 families, three splits) |
| Tier conflation | `environment_tier` (A/C) and `policy` (native / two contracts) recorded separately; eligibility reported per cell |
| No pinned upstream inputs | `fetch_inputs.py` with a SHA-256 pin for zlib 1.3.1 |
| No randomized paired timing | `runner.py`: random order per repetition, per-pair ratio, percentile bootstrap, raw samples |
| No per-stage cost model | instrumented two-run probe using `TRACEJIT_PHASE_TIMING` |
| Weak hit accounting | a HIT requires TraceJIT's own `kind = "Reused"`; deoptimisation is recorded as a miss |
| Oracle too narrow | `oracle.py`: whole-workspace fingerprint, covered vs out-of-contract split, twin directories |
| No transition matrix | twelve-step cache-state sequence with the decision at each step |
| No schema | `schema/results-v1.schema.json` + `validate.py` with semantic rules |
| No PR benchmark gate | `.github/workflows/benchmark-v2.yml`: smoke, full, correctness, competitive |
| No baseline comparison discipline | `compare_baseline.py`: refuses to compare across environment fingerprints; fails only on correctness |
| Adversarial suite not in CI | preserved W1 matrix + mutation cases + measured same-timestamp attempt + TOCTOU race probe |

## 5. Claims that were outdated or ambiguous at `e4f80ad`

| Claim (location) | Problem | Action in Phase AA |
| --- | --- | --- |
| README first results table, "Mandate §4 on final product tip" | measured at `4ffde9a`, which is neither the beta nor `main`; reads as current | relabelled by commit and state; current `main` numbers added from Phase AA |
| README "CPU-heavy `c-transform` 32.524 ms → 5.303 ms (~6.1×)" | synthetic workload with 250 M extra mix rounds, presented above real workloads | kept, but moved next to the real-workload table and labelled synthetic |
| README beta table "About 37× on this host" | beta-only, one synthetic workload | kept with the beta commit; not reused for `main` |
| `BENCHMARKS.md` short-command loss from `63e3363` | v0.1.0-era commit | marked historical and superseded by a measured floor on `main` |
| README "Census: 1/32" | mixes policy tiers: native defaults and contract runs are reported in one sentence | replaced by a per-cell table |
| `docs/COMPATIBILITY_V03.md` "1/32, 7/31, 0/20, 8/20" | development line, previously reported without the environment tier of each corpus | the Phase AA tables supersede it for `main`; the v0.3 numbers are retained as historical |
| "Warm HIT 8.8 ms" for the beta | measured on a different host than this audit and not comparable | kept as a beta figure only |
| `docs/LIMITATIONS.md` "fixed cost ~11 ms plus ~6 ms hashing" | from Phase U, not re-measured on `main` | re-measured in Phase AA and quoted with the new interval |
| `docs/BENCHMARKS.md` "312.913 ms → 3.972 ms" (v0.1.0) | still cited without the warning that the workload is synthetic | retained as explicitly historical |

## 6. Reproducibility risks that remain

| Risk | Status |
| --- | --- |
| Host-specific absolute latency | mitigated by publishing paired ratios, N, raw samples and an environment fingerprint; **not** solved — 2 vCPU shared VM |
| Page cache is warm in every sample | documented; a cold-page-cache claim is not made |
| `TRACEJIT_CACHE_DIR` is hashed into the identity | discovered in Phase AA: moving a cache directory invalidates every record. Documented; not fixed (product change out of scope) |
| Two audited contracts only | any other libc/GCC build refuses; the corpus then reports refusals, not contract wins |
| Tools absent on this image | `ccache`, `sccache`, `ninja`, `firebuild`, `perf`, `zstd`, `clang`, `clang-tidy`, `cppcheck`, `shellcheck`, `ruff`, `pyarrow` — reported as unavailable, never scored |
| `benchmarks/results/latest.*` can be overwritten by a single harness run | unchanged; Phase AA writes its own directory instead |
| No cold-cache or cold-start measurement | unchanged; no such claim is made |

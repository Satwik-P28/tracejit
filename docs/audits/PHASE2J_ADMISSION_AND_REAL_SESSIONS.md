# Phase 2J — admission ablation, real sessions, fuzzing and reliability

All timings are wall-clock milliseconds on the same 8-CPU Ubuntu 24.04 / kernel 6.1.102 host,
release build, one fresh cache per policy and a pristine `git archive` work tree per policy.
Speedup = direct ÷ policy; slowdown = policy ÷ direct. Raw data:
`benchmarks/results/phase2j/sessions/` and `.../differential/`.

## 1. Admission ablation and simplification

Phase 2I's estimator had five parts. The Phase 2J question was whether each earns its
complexity. Evidence available:

| Feature | Measured value | Decision |
| --- | --- | --- |
| Skip identities recorded as ineligible | Large: `always` re-traces every `make`/`pngtest` run; `auto`/`auto-v1` skip after the first record | **keep** (already in both policies) |
| Measure native runtime before tracing | Enables declining cheap commands; without it `always` is 0.27–0.79× on real sessions | **keep** |
| Track prior hits | Needed by any reuse estimate; also the denominator of the brake | **keep** |
| Track invalidations (`deopts`) | Phase 2I matrix: auto did not beat auto-v1; an edit-every-run loop is the case it targets | **keep as a simple brake** |
| 30-day sample expiry | One comparison; no session can measure it | **keep** (cheap, bounds staleness) |
| Laplace-smoothed probability × constant 3-invocation horizon vs 12 ms | Phase 2I: 3.54× vs 3.55× and 2.73× vs 2.84×; Phase 2J zlib: 1.099× vs 1.188× (A) and 1.228× vs 1.139× (B) | **removed** |

The removed model was:

```
reuse_probability = (hits + 1) / (hits + deopts + 2)
saving            = (direct - max(hit, 6 ms)) * reuse_probability * 3
trace if saving > 12 ms
```

The replacement is the Phase 2H threshold plus the deoptimisation brake:

```
trace if direct >= 2 * max(hit, 6 ms)  and  hits + 1 > deopts
```

It is integer arithmetic, uses only stored numbers, has no horizon constant, and is easier to
explain: one hit must be able to pay for a trace, and invalidations must not outnumber hits.
`--admission auto-v1` still selects the Phase 2H policy for comparison; the new rule is
strictly simpler than the Phase 2I estimator and is not claimed to be better. Unit test:
`simplified_admission_declines_cheap_and_frequently_invalidating_identities`,
including the balanced (`hits=1, deopts=1`, allowed) and losing (`hits=1, deopts=2`, refused)
cases.

## 2. Real developer sessions

Each policy gets a pristine checkout, then: configure where applicable, build, immediate
rebuild, unrelated edit, relevant source edit, project test target, and repeated invocation of
the project's own tool over a generated corpus. Sixteen-megabyte mixed content was used for
zlib so compression costs hundreds of milliseconds; libpng's own `pngtest` and lz4's CLI were
used unchanged.

| Repository | Session | direct | never | auto-v1 | always | auto |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| zlib v1.3.1 | A | 2728.99 | 2865.09 (0.952×) | 2297.30 (1.188×) | 10180.48 (0.268×) | **2482.38 (1.099×)** |
| zlib v1.3.1 | B | 2757.26 | 3017.06 (0.914×) | 2420.04 (1.139×) | 7743.73 (0.356×) | **2245.51 (1.228×)** |
| libpng v1.6.43 | A | 10746.95 | 11466.98 (0.937×) | 9639.21 (1.115×) | 17656.08 (0.609×, build failed) | 9719.95 (1.106×) |
| libpng v1.6.43 | B | 9817.18 | 12087.42 (0.812×) | 10419.93 (0.942×) | 18646.95 (0.526×, build failed) | 10364.77 (0.947×) |
| lz4 v1.9.4 | B | 15388.65 | 15424.57 (0.998×) | 16117.09 (0.955×) | 19470.66 (0.790×) | 15888.97 (0.969×) |

Reading these honestly:

- **zlib is the only positive result.** Both adaptive policies reuse `./minigzip` and now also
  `./minigzip -d` (`Reused`, `Guarded`, byte-identical output); `auto` saves 1.099× and 1.228×
  net across the whole session, while `always` costs 3.7× and 2.8× because it traces the build
  driver. The gain comes from repeated deterministic tool runs, not from faster compilation.
- **libpng's apparent 1.1× is not reuse.** `pngtest` takes ~7 ms; a hit costs ~12–15 ms, so the
  policy correctly declines to trace it and every probe reports `Skipped`. The deltas are
  configure/build variance, not savings.
- **`always` breaks libpng's build.** Under `always`, `./configure` exits 1 and every later
  phase (build, rebuild, edits, pngtest) also exits 1, so the 0.53–0.61× figure understates the
  damage: that session did not build at all. The cause was not diagnosed; it is recorded as an
  observed failure of tracing this configure script, not as a performance result.
- **lz4 cannot reuse, by contract.** Its CLI reads the monotonic clock
  (`process read system clock: monotonic`), so it is `NONDETERMINISTIC`; all adaptive policies
  skip it. Session B shows 0.969×, i.e. slight overhead with no reuse. Session A produced no
  valid sample: the harness failed to build `programs/lz4` for that run (`FileNotFoundError`),
  and the stale file is not used for any claim.
- No peak-RSS figure is reported: `/usr/bin/time` is absent on this host and no cgroup is
  delegated. Cache footprint is recorded per policy in the raw JSON (zlib ~7 MB, libpng ~2.5 MB
  for the adaptive policies, 44 MB for `always`; lz4 ~7 MB), and p50/p95 over the repeated tool
  phases are in the same file.

## 3. Expanded differential fuzzing

Cases per seed rose from 45 to **120**: 13 commands (added `cat`, `head`, `cut`, `sed -n`,
`sort`, a file-argument `tr`, and the previous set) crossed with 11 mutations (added truncation,
append and rename) plus the cold/warm and corrupt-object cases. Seeds 7, 11 and 17:
**360 comparisons, 360 `ok`, 0 incorrect hits.** Each result carries a reproduction command and
the raw JSON is committed. This is sampled evidence, not a proof of noninterference.

## 4. Reliability: the intermittent `ETXTBSY`

The failing test was `a_traced_script_sees_the_callers_script_path`, at its **direct** run,
before TraceJIT executes (`Os { code: 26, kind: ExecutableFileBusy }`). Reproduced
deterministically outside the project:

```
$ bash -c 'exec 9>prog; prog'
bash: prog: Text file busy    # exit 126
```

`execve` refuses a file that any process holds open for writing. The test harness runs tests in
parallel, so a sibling's `fork` can inherit this test's freshly written script descriptor
before its own `exec`. It failed 3 of 8 full-suite runs before the change and 8 of 8 passed
after adding a bounded retry (40 × 5 ms) for `ExecutableFileBusy` around this test's own spawns.
The retry is test-only, does not suppress an assertion, and cannot hide a TraceJIT defect: the
failure happens before the product is involved. It is a harness isolation limit, not a product
race.

## 5. Enforcement and readiness

`tracejit doctor`: `seccomp yes`, `landlock no`, `proven no` (LSM list `capability,selinux`;
`unshare -m` not permitted). `PROVEN` remains blocked and unexercised; no enforcement claim is
added. `GUARDED` reuse is unchanged in meaning and still does not imply sandboxing.

`cargo fmt --check`, `clippy --all-targets --all-features -D warnings` and the full workspace
suite pass: **110 tests** (16 cache, 5 CLI, 34 Linux integration, 8 core, 5 effects, 25 guards,
4 sandbox, 13 trace).

## 6. What a wider developer preview would still need

1. A contract for build-driver clock reads; this is the dominant blocker for `make`, and under
   `always` it also broke libpng's configure.
2. A hit path cheaper than ~6–12 ms, or a policy that can skip sub-10 ms tools without paying a
   process launch; otherwise most filters and test binaries are correctly declined.
3. Alias-aware descriptor tracking (a seek on a `dup` of stdin) and a decision on concurrent
   observers of a shared description.
4. A working, repeatable lz4 session harness (the CLI was not present after the build in one
   run) and a second lz4 session; only one valid lz4 sample exists.
5. Landlock-capable CI for `PROVEN`, still the only route to an enforced claim.

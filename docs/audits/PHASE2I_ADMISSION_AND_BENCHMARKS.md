# Phase 2I — admission policy, policy comparison, and real developer sessions

All times are wall-clock milliseconds from two independent sessions (`a`, `b`) on the same host,
release build, with `TRACEJIT_CACHE_DIR` pointing at a fresh directory per policy. Ratios are
labelled: **speedup = direct ÷ TraceJIT**, **slowdown = TraceJIT ÷ direct**. Every number is from
`benchmarks/results/phase2i/`. Both benchmark drivers run each policy against a freshly restored
workload; an earlier version of the policy matrix let the scripted edit leak into later policies and
its numbers were discarded rather than reported.

## 1. Admission lifecycle audit

Policies: `--admission always` (trace everything, the historical default), `--admission auto`
(Phase 2I cumulative-benefit policy), `--admission auto-v1` (Phase 2H threshold policy, kept for
comparison), and `--admission never` (run directly).

| Event | `always` | `auto` | Notes |
| --- | --- | --- | --- |
| First invocation | trace, store, may reuse later | run directly, record `direct_ns` | no cache entry yet |
| Initial measurement | after the traced run | after the direct run | stored per lookup key |
| First traced invocation | immediately | second invocation, if the estimate passes | auto pays one direct run first |
| First eligible hit | next invocation | third invocation | explains 0/N on "second run" metrics |
| Input mutation | miss, retrace | miss, retrace, `deopts += 1` | smoothed reuse estimate falls |
| Subsequent hits | every match | while the estimate justifies tracing | hits are recorded |
| Previously ineligible command | retried every invocation | retried, with its own cost sample | no negative cache |
| Executable change | new identity | new identity, re-measured from scratch | identity includes executable hash |
| Environment change | new identity | new identity, re-measured | identity includes the imported environment |
| Cache eviction | retrace | retrace; sample remains until TTL | no eviction path in this version |
| Cache corruption | repaired, retrace | repaired, retrace | fail closed on guard mismatch |
| Cost-model expiration | n/a | samples older than 30 days discarded | `ADMISSION_SAMPLE_TTL_MS` |

Defects found:

1. **Phase 2H could not decline cheap commands adaptively.** It traced any command whose direct run
   was at least 12 ms and always hit. `AutoLegacy` preserves that for comparison; `auto` estimates
   cumulative benefit.
2. **Invalidations were invisible.** There was no deoptimisation count, so a command that
   invalidated on every edit still looked profitable. The cache now stores `deopts`, incremented on
   a guard failure, and uses `(hits + 1) / (hits + deopts + 2)`.
3. **Samples never expired.** A 30-day TTL discards stale cost samples.
4. **A real concurrency defect was exposed and fixed.** Concurrent cold starts could fail with
   `database is locked` because `PRAGMA journal_mode=WAL` ran before the busy timeout applied.
   Cache initialization now arms `busy_timeout` on the connection and retries bounded
   `SQLITE_BUSY`/`LOCKED` with backoff. Three consecutive full-suite runs pass afterwards.
5. **Previously ineligible identities are re-examined** because admission is keyed by the full
   lookup key (contract, executable hash, environment, dependency identities), not command text.

### The decision

```
reuse_probability = (hits + 1) / (hits + deopts + 2)
expected_hits     = reuse_probability * 3            # EXPECTED_FUTURE_INVOCATIONS
saving            = (direct - max(hit, 6 ms)) * expected_hits
trace if saving > 12 ms                              # TRACE_OVERHEAD_NS
```

Deterministic, interpretable, no model file; it declines work whose expected saving cannot repay one
trace premium. Constants come from Phase 2G/2H cold-minus-direct samples (11–18 ms) and are
assumptions. No ML is used: nothing shows it would beat these arithmetic operations.

Known limitation: future invocations are a constant 3, so a workload invoked exactly twice pays a
trace it cannot repay and a workload invoked 30 times is credited with only 3. This is conservative
and is why the policy matrix below is not better than `auto-v1`.

## 2. Policy matrix: direct vs never vs always vs auto-v1 vs auto

One invocation is `sed → wc -c → md5sum → gzip -9 -c` over 5.4 MB. Twenty invocations; an unrelated
file is touched before invocation 6; the input is edited before invocation 11. The corpus is restored
before each policy.

| Policy | Session A (ms) | Speedup | Slowdown | Session B (ms) | Speedup | Slowdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct | 8776.59 | 1.00× | 1.00× | 7221.42 | 1.00× | 1.00× |
| never | 8907.87 | 0.99× | 1.01× | 7588.85 | 0.95× | 1.05× |
| always | **2176.43** | **4.03×** | **0.25×** | **2267.08** | **3.19×** | **0.31×** |
| auto-v1 | 2470.66 | 3.55× | 0.28× | 2539.30 | 2.84× | 0.35× |
| auto | 2482.49 | 3.54× | 0.28× | 2649.92 | 2.73× | 0.37× |

Cumulative totals for `auto` (A): 701.05 after 1, 1618.23 after 2, 1677.50 after 3, 1796.53 after 5,
2123.39 after 10, 2482.49 after 20. `auto-v1`: 708.37, 1622.38, 1679.27, 1793.55, 2054.00, 2470.66.
`always`: 943.02, 1005.15, 1085.57, 1266.92, 1683.74, 2176.43.

Honest reading:

- **`auto` does not beat `auto-v1` here.** It is within 0.5% in session A and 4% slower in session B.
  The improvement in the decision model did not translate into a win on this workload.
- **`always` beats both adaptive policies on this matrix** because every command is eligible and the
  run is long: tracing on invocation 1 is cheaper than measuring on invocation 1 and tracing on 2.
  The adaptive policies' advantage is refusing ineligible work, which this matrix does not contain.
- `never` is near parity (0.95–0.99×), as expected for a direct wrapper.

This is the central negative result for Part B: on a long, stable, fully eligible workload, a
measure-first policy loses to tracing immediately, and the cumulative-benefit estimate is not
distinguishable from the Phase 2H threshold. The policy change is justified by the zlib session
below, not by this matrix.

## 3. Real repository session: zlib v1.3.1

Checkout `51b7f2abdade71cd9bb0e7a373ef2610ec6f9daf` (tag `v1.3.1`). Per policy, on a clean copy:
`./configure --static`; `make clean`; `make -j1`; identical `make -j1`; touch `README` and `make`;
append a comment to `adler32.c` and `make`; `make test`; generate a 16 MB corpus; six `./minigzip`
compressions and four `./minigzip -d` decompressions.

| Policy | Session A (ms) | Speedup | Slowdown | Session B (ms) | Speedup | Slowdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct | 6781.17 | 1.00× | 1.00× | 6606.07 | 1.00× | 1.00× |
| never | 6925.23 | 0.98× | 1.02× | 6932.90 | 0.95× | 1.05× |
| always | 11582.43 | 0.59× | 1.71× | 12027.03 | 0.55× | 1.82× |
| auto | **5641.55** | **1.20×** | **0.83×** | **6150.66** | **1.07×** | **0.93×** |

Per-phase evidence (session A):

- `auto` compression: 388.96 (direct measurement), 513.42 (traced), then 27.61, 25.44, 28.16, 24.80 ms
  (hits). Native compression is ~380 ms, so each hit saves ~355 ms.
- `always` compression: 533.98 then 30.19, 23.38, 25.87, 27.18, 25.23 ms.
- `never` compression: 392, 381, 380, 378, 373, 381 ms.
- `auto` decompression: 82.73, 235.93, 69.30, 73.23 ms — never reused.

Why the session wins under `auto`: it refuses to trace `make` (classified `Nondeterministic` because
the build driver reads the realtime clock), so the multi-second build is not wrapped, and it caches
the repeated `minigzip` compressions. `always` traces the builds too — `configure` 1.9 s, build
6.6 s, relevant-edit rebuild 0.9 s in session A — and then refuses reuse anyway, producing 1.71× and
1.82× slowdowns. Session B has the same direction and a smaller margin because its build phase was
faster (6.6 s vs 8.8 s direct totals).

Why `never` is 0.95–0.98×: it still spawns the wrapper; build-time variance dominates the rest.

### What is still not accelerated

- `make` — `Nondeterministic`: `process read system clock: realtime`.
- `make test` — `Unknown`: unmodeled `setresuid(117)` / `setresgid(119)` with `-1` arguments and a
  failed fd operation on `-1`.
- `./minigzip -d` — `Unknown`: `lseek` on inherited descriptor 0 is not modelled.

The first two block whole build/test workflows. The third is a single missing rule and the cheapest
next unlock, because compression already reuses in the same program.

## 4. Reach and limits

- The only positive real-repository result is repeated invocation of a deterministic repository
  tool: 1.20× and 1.07× net session savings. Compilation itself is not faster.
- `always` remains a bad default: it turns eligible sessions into 1.7–1.8× slowdowns.
- `auto` beats `always` decisively on the edit-heavy real session, but ties `auto-v1`; no claim that
  it is a better admission policy in general is supported.
- No ccache/sccache/cmake comparison is possible here (not installed); no claim is made about them.
- Two sessions agree on direction; magnitude differs because build time dominates and varies.

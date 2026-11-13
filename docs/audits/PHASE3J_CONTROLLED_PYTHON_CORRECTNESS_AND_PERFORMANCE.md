# Phase 3J — controlled Python correctness and performance

Date: 13 November 2026

Status: research branch, unmerged. The experimental `python-runtime-v1` contract is retained under
the same explicit boundary as Phase 3I. A separate `python-runtime-v2` contract adds a logical clock
sequence rather than pretending the fixed v1 clock is a general clock. Neither contract is native
equivalence, and neither is proposed for merge. The native byte-exact directory policy remains the
default.

Branches and commits:

- Base: `main` at `29718cf55b7a9c937bd0c9147dfc650fbd2498f2`.
- `research/phase3j`: `e19aca8` (experimental Python contract), `b9a54fb` (controlled directory
  padding), `dcee712` (Phase 3H/3I artifacts).
- This audit and the performance work are additions on top of `dcee712`.
- The merged descriptor preflight, directory-generation cleanup and `dup2(fd, fd)` early return are
  retained. `crates/tracejit-trace/src/linux.rs` still returns before descriptor mutation when the
  source and destination are the same.

## 1. Reconciliation

The review branch starts from the merged correctness commit, not from the diverged PR #9 branch.
Only the experimental contract, its tests, the controlled padding policy and the Phase 3H/3I
benchmark/audit artifacts were brought over. The Phase 3I acceptance test was rerun on the
reconciled branch before the performance changes:

| Gate | Result |
| --- | --- |
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace` | 155 tests pass |
| `cargo test -p tracejit-cli --test linux_integration` | 53 tests pass |
| `cargo build --workspace --release` | pass |
| `./scripts/demo.sh` | pass |

Release binary SHA-256 after the final build: `dcbaf5d715da6a8c46cb134165298643ee532109245281152b53ec37c75cdb6d`.
Hosted CI on the pushed branch: run `43489814814` at `a369fb4` completed **success**. All 13 steps
passed: Formatting, Clippy, Tests, Release build, Doctor/kernel capabilities, Linux integration,
real-world compatibility census and Demo. The run was read from the public Actions API; the host has
no authenticated GitHub session.

The Phase 3I acceptance assertions remained true: cold `Executed`, warm `Reused`, invalidation
retraced, entropy never reused, output effects equal. Raw copy:
`benchmarks/results/phase3j/reproduced-acceptance.json`. The committed Phase 3I evidence was restored
after copying the run, so the historical Phase 3I result was not overwritten.

## 2. Semantic boundary

The probes are in `benchmarks/phase3j/probes/`; the harness is
`benchmarks/phase3j/run_semantics.py`; raw output is
`benchmarks/results/phase3j/semantic-probes.json`. Every probe runs natively once and twice under
each contract.

| Observation | Native | v1 | v2 | Reuse |
| --- | --- | --- | --- | --- |
| `time.monotonic_ns()` bounded 1 ms loop | real value, loop exits | fixed `0`, loop runs 1000 iterations | base `1e12` + 1 ms per observation; loop exits immediately | v1 and v2 `Reused` |
| `time.time_ns()` | real epoch | fixed `0` | base `1.7e18` + 1 ms per observation | v1 and v2 `Reused` |
| `gettimeofday` (`timeval`) | native timeval | zero timeval | native timeval; not virtualized | v1 `Reused`; v2 `Executed` |
| `os.getpid()/getppid()/gettid()` | real ids | `4242/1/4243` | same fixed ids | `Reused` |
| direct `syscall(SYS_getpid)` via `ctypes` | real ids | fixed ids | fixed ids | `Reused` |
| `threading.get_native_id()` | real tid | fixed tid | fixed tid | `Executed`, not reused |
| `os.urandom(8)` | random | random | random | `Executed`, not reused |
| `fork()` | real child | refused | refused | `Executed`, not reused |
| directory-entry padding | fill bytes survive | zeroes | zeroes | `Reused` under both |
| `os.kill(os.getpid(), SIGUSR1)` | `signal [10]` | `ProcessLookupError` | `ProcessLookupError` | `Executed`, not reused |

The v1 time result is a concrete counterexample, not a harmless display difference: the loop sees
`0 0 1000 0` and executes all 1000 iterations. The v1 and v2 identity values are deliberate
virtualization, but they are **not** a process-identity contract: a program that passes
`os.getpid()` to a signal, `waitpid`, `/proc`, or another process observes the virtual number. The
signal probe exits 1 under both contracts with:

```text
ProcessLookupError: [Errno 3] No such process
```

This is why fixed identity must not be presented as general deterministic process semantics. The
current trace still records the signal attempt and refuses reuse, but the first controlled execution
already has different behavior. A future contract must either map self-signals to the real tracee or
refuse to virtualize identity for workloads that can use it; neither is implemented here.

Direct syscalls are covered because ptrace stops at the syscall boundary: the `ctypes` probe prints
the same virtual IDs under both contracts. This is not evidence that a native extension's internal
library calls are audited. No third-party native extension is installed for the pinned
`/usr/bin/python3.12`; the `ctypes` direct-syscall probe is the available native-call boundary probe.

`time.time()` uses the realtime clock and advances under v2. `gettimeofday` is deliberately **not**
virtualized under v2: its ABI writes a `timeval` (seconds, microseconds), while v2's logical value is
a `timespec` (seconds, nanoseconds). Giving a caller an out-of-range `tv_usec` would be worse than
falling back; that path is left native and therefore not reusable. `time.monotonic()` and
`time.time()` are virtual clocks, not a scheduler or wall-clock equivalence claim. `sleep`, blocking
I/O and thread scheduling still use native time.

### 2.1 Alternative contracts

`python-runtime-v1` is the Phase 3H/3I fixed-clock/fixed-identity watchpoint. `python-runtime-v2`
keeps the exact ELF/build-ID/profile and fixed identity, but gives realtime and monotonic clocks
independent one-millisecond logical sequences. Its testable semantics are:

- monotonic starts at `1_000_000_000_000` ns;
- realtime starts at `1_700_000_000_000_000_000` ns;
- every admitted clock observation increments its sequence by `1_000_000` ns;
- `time()` returns `1_700_000_000 + floor(realtime_observations / 1000)` seconds;
- the logical values are recorded in the cache record and checked to be in the sequence;
- clock values from different contracts/records are never mixed.

This is still an explicit virtual contract. It does not prove anything about native clock
progression, instruction-level time, signals delivered during a timeout, or code that compares a
clock value with an externally supplied timestamp.

A call-site/instruction-aware contract was not implemented. The trace currently records the
observation class, not the caller address, so it cannot distinguish CPython startup reads from an
application's timeout loop. `python-runtime-v2` therefore admits application clocks as logical
observations rather than pretending to be startup-only.

## 3. Phase profile of the canonical ETL

The canonical workload is the original `python-csv-json` ETL (400 sales rows, 12 customers). The
profile script is `benchmarks/phase3j/profile.py`; raw output is
`benchmarks/results/phase3j/profile.json`. Each contract had 10 independent cold caches and 15
steady warm hits; the direct baseline had 12 runs.

Median values from the final run (shared VM, so p95 and stdev are noisy):

| Phase | v1 | v2 |
| --- | ---: | ---: |
| direct wall | 46.1 ms | 46.1 ms |
| cold wall | 301.0 ms | 268.6 ms |
| warm `runtime_ns` | 21.3 ms | 27.4 ms |
| process startup | 5.3 ms | 5.9 ms |
| identity preparation | 3.7 ms | 3.8 ms |
| SQLite query | 4.4 ms | 7.2 ms |
| record decode | 4.8 ms | 9.5 ms |
| guard validation | 12.0 ms | 15.9 ms |
| - hash | 10.2 ms | 13.5 ms |
| - directory | 0.78 ms | 0.91 ms |
| - metadata | 1.03 ms | 1.13 ms |
| CAS restore | 1.8 ms | 1.4 ms |
| stdio replay | 0.05 ms | 0.05 ms |
| decision persist, steady hits | 0 ms | 0 ms |

The first hit can persist a decision row: 14-49 ms in the stable-profile runs, and a 221 ms outlier
in the final shared-VM run. Steady hits do not persist. Phase timings are not additive with process
startup or with each other; `runtime_ns` starts after the candidate query and the phase record
contains earlier preparation fields. The benchmark harness is outside every measurement.

Top three steady-state costs, from the v1 profile:

1. **Dependency hashing** — 10.2 ms, dominated by repeated hashes of the Python executable and the
   shared library/input files.
2. **Candidate retrieval/decoding** — 4.4 ms SQLite query plus 4.8 ms record decode.
3. **Identity and startup** — 3.7 ms identity preparation plus 5.3 ms process startup.

Directory enumeration is below 1 ms for this workload. Output restoration is 1.4-1.8 ms. Those
ceilings did not justify weakening byte-exact directory guards or the output-inode/metadata
obligations.

### 3.1 Canonical acceptance after the optimization

Re-running the Phase 3I harness gave:

| Metric | Result |
| --- | ---: |
| direct median | 58.40 ms |
| warm median | 39.18 ms |
| cold median | 225.97 ms |
| 10-warm complete session | 625.91 ms |
| 10-direct complete session | 579.48 ms |

All five Phase 3I assertions passed and the output SHA-256 remained
`28bc8fa9e7c25a10aa121654b5df07381a78fd5d45873ef077c4132cf51054e8`. The original ETL is still a
cold-start loss for a short session: the complete 10-run session is slower than direct. The warm
median is lower than direct in this run, but that does not make the cold trace free. This is why the
CPU-heavy workloads below are the performance evidence, not the ETL alone.

## 4. Performance mechanism D — metadata-keyed hash reuse

The logical-clock v2 probe exposed a concrete guard-scheduling cost. A bounded probe produced 414
`ControlledRuntime` guards, each carrying the same executable path and expected hash. Before the
change, each guard re-opened and re-hashed the Python executable. A measured warm hit was
0.78-0.87 s, while direct execution was ~0.06-0.09 s.

`Guard::ControlledRuntime` still checks the profile, observation class, length, contract and value.
The change is narrower: `validate_all` now passes one hash cache through a validation pass.
`hash_file_cached` records the fingerprint observed immediately before hashing and returns the
cached hash only while the current fingerprint is equal. A changed size, inode, ownership, mode,
ctime or other recorded field forces a fresh hash. A test writes a new generation and proves the
cache rehashes.

Result on the same v2 clock probe: 13.1-13.5 ms warm hits instead of ~0.8 s. ETL warm `runtime_ns`
also fell from roughly 29 ms in the pre-change manual checks to 21.3 ms. The cache does not replace
the guards, does not weaken the executable profile check, and does not cache across validation
passes. Its documented limitation is content mutation that preserves every fingerprint field inside
one pass; the previous per-guard hash would catch a later write that the first hash missed, while a
single stat/hash snapshot does not. That is a deliberate trade-off for a guard set that otherwise
re-hashes the same immutable runtime dozens or hundreds of times.

## 5. CPU-heavy workloads

Two deterministic, standard-library workloads were added because the original ETL cannot amortize
its trace:

- `benchmarks/phase3j/workloads/heavy_transform.py`: 120,000 CSV rows, parsing, grouping, maxima and
  an FNV-style digest, JSON output.
- `benchmarks/phase3j/workloads/image_convolution.py`: 320x240 P6 PPM, 5x5 Gaussian blur and edge
  pass in pure Python, byte-exact PPM output.

`benchmarks/phase3j/run_workloads.py` runs direct, cold, warm and invalidation phases for v1 and v2.
Every warm run must report `Reused`; outputs are compared byte-for-byte with a native run on the
same input; invalidation changes a real input byte and compares the retraced output with the new
native output.

| Workload | Direct median | Contract | Cold | Warm wall | Warm report | Output equal | Invalidation |
| --- | ---: | --- | ---: | ---: | ---: | --- | --- |
| heavy transform | 1022.7 ms | v1 | 2692.5 ms | 39.2 ms | 19.6 ms | yes | `Executed`, recovered `Reused` |
| heavy transform | 1022.7 ms | v2 | 1498.2 ms | 87.0 ms | 49.8 ms | yes | `Executed`, recovered `Reused` |
| image convolution | 5116.3 ms | v1 | 5097.2 ms | 44.7 ms | 21.8 ms | yes | `Executed`, recovered `Reused` |
| image convolution | 5116.3 ms | v2 | 4887.3 ms | 50.3 ms | 28.5 ms | yes | `Executed`, recovered `Reused` |

Break-even from wall medians:

- heavy v1: 4 complete runs including the cold run; heavy v2: 3.
- image v1: 3 complete runs; image v2: 2.
- A prior run on a less loaded VM measured heavy direct 664 ms and warm 29.7 ms, and image direct
  2880 ms and warm 26.7 ms, both with break-even 3. The shared VM's load changes the absolute
  numbers; the raw run samples are retained in `cpu-workloads.json`.

The controlled warm path is roughly 20-50 ms of fixed work plus process startup. A 0.1 s workload
cannot repay that; a 0.6-5 s deterministic CPU workload can. This is the defensible improvement:
byte-identical output, explicit contract, measured invalidation, and break-even at 2-4 runs. It is
not native equivalence and not a claim about arbitrary Python.

## 6. Competing mechanisms

| Mechanism | Evidence | Decision |
| --- | --- | --- |
| A. Persistent cache connection / batch | Startup 5.3 ms, SQLite open/schema ~0.6 ms, query 4.4 ms. A daemon could remove some of that, but adds IPC, lifecycle, crash recovery and a second cache authority. | Not implemented. The small ETL gain is not shown, and the CPU workloads already amortize. |
| B. Compact dependency metadata | A heavy workload candidate is 927 KB; guards alone are 160 KB; record decode is 4.8-9.5 ms. | Not implemented. A compact encoding needs a complete guard representation and a new decode/validation equality proof; no such encoding was demonstrated. |
| C. Cached directory-field projections | Directory guards are 0.78-0.91 ms on the ETL. | Rejected for now. Savings are below 1 ms and a typed projection can hide padding from a reader that can observe it. Native byte-exact remains default. |
| D. Guard hash scheduling/memoization | Implemented; v2 probe 0.8 s to 13.5 ms; `hash_file_cached` test. | Implemented on the research branch. It preserves complete guards and executable profile checks. |
| E. Output restoration | CAS restore is 1.4-1.8 ms. | Not implemented. The inode, metadata, hard-link and crash-recovery obligations dominate any plausible 1-2 ms gain. |

No repeated-SQLite-query optimization from Phase 3D was reintroduced.

## 7. Graph-of-thoughts

The evidence connects five concerns:

```text
runtime virtualization
  -> what a target can observe (clock, pid, tid, entropy, padding)
  -> effect provenance (which observations belong to the target vs harness/startup)
  -> dependency validation (guards must reproduce admitted observations and refuse the rest)
  -> incremental computation (reuse only when the saved work exceeds the validation floor)
  -> filesystem replay semantics (outputs and directories must be restored without weakening native obligations)
```

Paths that survive:

- A **fixed** clock is not a clock contract. It is a bounded observation that can change loop
  behavior. v1 is retained only as an experimental watchpoint.
- A **logical advancing** clock makes timeout loops progress, but it is still virtual. It needs its
  own sequence checks and cannot support `gettimeofday`'s different ABI or native scheduling.
- **Fixed identity** enables reuse but does not compose with self-signals or other identity
  consumers. The signal probe is the counterexample; refusing reuse after the fact does not repair
  the first run.
- **Effect provenance** matters more than adding more fixed values: repeated logical-clock guards
  are the same runtime dependency, so one metadata generation hash can serve all of them without
  dropping any guard.
- **Dependency validation is the pricing function** for incremental computation. The ETL's 20-30 ms
  hit floor is larger than its direct execution; CPU-heavy work changes the ratio, not the
  correctness model.
- **Filesystem replay** has two separate obligations: native byte-exactness for arbitrary readers,
  and an explicit virtual policy only for an audited contract. Projection and padding-zero policies
  must never silently become the native default.

Negative results retained:

- v1's bounded timeout loop runs all 1000 iterations.
- both contracts make `os.kill(os.getpid(), SIGUSR1)` raise `ProcessLookupError`.
- entropy, thread creation and fork remain ineligible.
- the original ETL still loses over a short complete session despite a faster warm hit.
- typed directory projection remains unwired; it can make an observable padding change invisible.
- v2 `gettimeofday` is refused rather than encoded incorrectly.

## 8. Limitations and obligations

1. `python-runtime-v1` and `v2` are exact-ELF experiments. There is no general Python compatibility
   claim and no merge proposal.
2. v2's identity remains fixed. A strict identity/signal contract is future work; until then a
   workload that uses `getpid` for anything other than a display value is unsupported.
3. v2 time is virtual. `time.sleep`, blocking syscalls and scheduler order are native and are not
   remapped.
4. No third-party native extension was available for the pinned interpreter. The `ctypes` direct
   syscall probe covers the syscall boundary, not extension-internal call-site semantics.
5. The hash cache's guarantee is per validation pass and metadata generation. A same-metadata
   content mutation is outside that snapshot guarantee; a future design should either accept this
   documented boundary or add a stronger generation mechanism.
6. Hosted CI passed at `a369fb4`; the branch remains unmerged and no PR was opened in this session.
7. No Landlock, so `PROVEN` remains unavailable.

## 9. Reproduction

```bash
cargo build --release
/usr/bin/python3.12 benchmarks/phase3j/run_semantics.py
/usr/bin/python3.12 benchmarks/phase3j/profile.py
/usr/bin/python3.12 benchmarks/phase3j/run_workloads.py
/usr/bin/python3.12 benchmarks/phase3i/run.py
```

Raw evidence:

- `benchmarks/results/phase3j/semantic-probes.json`
- `benchmarks/results/phase3j/profile.json`
- `benchmarks/results/phase3j/cpu-workloads.json`
- `benchmarks/results/phase3j/reproduced-acceptance.json`

## 10. Conclusion

The controlled runtime now has both a correctness boundary and a measured economic case. On
deterministic CPU-heavy Python workloads, reuse is byte-identical, invalidates correctly, and
amortizes in 2-4 complete runs. The original short ETL is preserved as a correctness benchmark and
still does not amortize a cold trace over a ten-run session. The most important unresolved
correctness issue is not performance: fixed process identity changes signal behavior, and that must
be fixed or explicitly excluded before any broader Python claim.

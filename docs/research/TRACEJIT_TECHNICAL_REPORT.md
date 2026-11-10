# TraceJIT: Conservative Effect-Aware Memoization of Linux Processes

> **Phase 3A addendum (10 November 2026):** The analysis below was written against public
> `f90b4db` and is preserved as the original evidence-scoped report. Section 9 records the later
> candidate-retention, replay-ordering and hosted-CI enforcement changes. It does not retroactively
> change the historical measurements or the original limitations.

**Technical design and reproducibility report | 9 November 2026 | Non-peer-reviewed**

**Implementation inspected:** public `main` at `f90b4db15ec066373101692996c822e2c51c67cf` (TraceJIT 0.1.1 series). **Performance evidence:** historical benchmark commits `e9684c1c01a7bbbab4cae50e2389105596d613f1` and `63e33638709aacfaed896ab587435e64c0ecea62`. Measurements below were **not** rerun on the inspected commit. This report evaluates the publicly available implementation, not later experimental branches or unmerged Phase 2 work.

## Abstract

Repeated execution of an unchanged command can waste computation, but reusing an earlier result is unsafe when hidden inputs or external effects have changed. TraceJIT is a Rust prototype for **whole-process memoization** on Linux x86_64. It observes modeled process and filesystem behavior via `ptrace`, reconstructs dependencies, classifies effects conservatively, and attempts reuse only when pre-execution identity and synchronous guards validate. Output files are retrieved from a BLAKE3-addressed store; SQLite indexes prior execution records. An optional sandbox uses seccomp-BPF and Landlock for an additional enforcement condition. Unknown or nondeterministic effects are refused rather than treated as cacheable.

Historical measurements show a **312.913 ms to 3.972 ms** reduction (78.780x) for one intentionally compute-heavy synthetic C transform, but a **7.396 ms to 7.957 ms** regression (0.929x) for an earlier short C ETL. A duration sweep suggests a cache-hit floor near 4 ms. These results demonstrate a conditional advantage, not general-purpose acceleration or correctness for arbitrary programs. In the public implementation, sequential output restoration, hidden userspace dependencies, and guard-to-restore races remain material limitations.

## 1. Problem statement and contributions

For a previously executed command `C`, the central question is not merely whether the executable path and arguments match. It is whether all relevant inputs still have the same semantics **and** whether reproducing the observable outputs without rerunning the process is safe.

TraceJIT explores three engineering ideas:

1. **Effect-aware admission.** Syscalls and process events are normalized into read, write, control, or unknown effects, with explicit `GUARDED`, `PROVEN`, `EMPIRICALLY_STABLE`, `UNKNOWN`, and `NONDETERMINISTIC` classifications. Only the first two are eligible in V1.
2. **Guarded whole-command reuse.** A pre-execution identity locates candidates; observed file and runtime dependencies become guards checked before output restoration and replay of stdout, stderr, and exit status.
3. **Conservative enforcement and explanation.** An optional seccomp/Landlock mode provides a stronger *operational* label when both mechanisms are installed. It is not a formal proof of program determinism. The CLI can explain observed inputs and refusal reasons.

The tracer and effect classifier do not constitute a new theory of caching. Existing systems already perform observed-dependency caching. The contribution assessed here is this prototype's particular combination of effect classes, guard compilation, output replay, refusals, and testable Linux-specific behavior.

## 2. Design and execution model

~~~text
command + pre-execution identity
  -> candidate lookup (SQLite)
  -> validate all stored guards
       -> valid: verify cached objects, restore outputs, replay process result
       -> invalid/missing: trace process tree using ptrace
             -> normalize and classify effects
             -> reconstruct input dependencies and output artifacts
             -> compile guards; persist eligible record and CAS objects
~~~

The lookup key uses the executable hash, arguments, working directory, inherited environment, and runtime identity. File inputs discovered during observation are checked later by guards. In default strict mode, BLAKE3 hashes validate recorded file contents. Output files and process-result bytes are stored for replay.

The system follows process-tree events and models selected file-descriptor behavior. It refuses uncertain effects, including the observed clock, randomness, network activity, unsupported syscalls, and writable shared file-backed mappings. Redirecting three common vDSO time functions to syscalls is intended to expose clock reads; inability to do so refuses reuse.

**Safety interpretation:** `GUARDED` means modeled dependencies were observed and can be checked under the stated assumptions. `PROVEN` means a guarded profile additionally executed with the required seccomp and Landlock restrictions installed. Neither class proves that all possible userspace dependencies are observable.

Relevant implementation: [architecture](../../ARCHITECTURE.md), [effect classifier](../../crates/tracejit-effects/src/lib.rs), [guards](../../crates/tracejit-guards/src/lib.rs), [cache](../../crates/tracejit-cache/src/lib.rs), [safety model](../../SAFETY.md).

## 3. Experimental methodology and provenance

Measurements were collected on GitHub-hosted Ubuntu 24.04 Linux x86_64 runners using the committed Python benchmark harness. The published methodology uses **5 warmups followed by 30 recorded wall-clock runs per stable condition**:

- **Direct baseline:** execute the compiled workload without TraceJIT.
- **Traced cold:** execute via TraceJIT with a fresh cache for each cold sample.
- **Guarded cache hit:** prime a stable cache, then rerun via TraceJIT; the harness requires a reported hit.
- **Correctness checks:** compare observable output and process results where applicable and test input mutation leading to deoptimization.

The harness configures `GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and `MALLOC_ARENA_MAX=1` to suppress allocator entropy/arena queries for these controlled workloads. This is an experimental environment choice, **not** a general compatibility improvement. Python is separately classified, not counted as a cache-hit success. CPU frequency, neighboring runner load, and warm filesystem caches were not tightly controlled. Medians and p95s are descriptive, not confidence intervals.

Full raw measurements, environment information, and scripts: [duration-sweep JSON](../../benchmarks/results/break-even.json), [duration-sweep report](../../benchmarks/results/break-even.md), [short-command JSON](../../benchmarks/results/latest.json), [short-command report](../../benchmarks/results/latest.md), [sweep harness](../../benchmarks/harness/break_even.py), and [primary harness](../../benchmarks/harness/benchmark.py).

**Version warning:** the duration sweep and synthetic transform belong to commit `e9684c1`; the earlier short-command regression belongs to `63e3363`. They are deliberately **not** merged into a single same-commit comparison.

## 4. Results

### 4.1 Performance by command duration

The following values are historical medians from the duration sweep at `e9684c1`. Each target denotes intended workload duration; the **measured direct time** is used for speedup.

| Target | Direct median (ms) | Cold median (ms) | Hit median (ms) | Hit p95 (ms) | Speedup |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 ms | 1.796 | 11.833 | 4.165 | 4.461 | 0.431x |
| 5 ms | 5.274 | 15.104 | 4.100 | 4.529 | 1.286x |
| 10 ms | 9.694 | 19.544 | 4.188 | 4.607 | 2.315x |
| 25 ms | 22.598 | 32.671 | 4.000 | 4.182 | 5.649x |
| 50 ms | 43.983 | 54.158 | 4.165 | 4.562 | 10.561x |
| 100 ms | 86.556 | 96.321 | 3.909 | 4.457 | 22.144x |
| 250 ms | 214.120 | 224.031 | 3.994 | 4.653 | 53.615x |
| 500 ms | 426.746 | 436.898 | 4.277 | 4.486 | 99.771x |
| 1000 ms | 852.097 | 862.205 | 4.163 | 4.481 | 204.665x |
| 2000 ms | 1702.052 | 1712.741 | 4.072 | 4.667 | 417.991x |
| 5000 ms | 4253.836 | 4264.170 | 3.958 | 5.265 | 1074.873x |

The fastest measured *losing* direct baseline is 1.796 ms, and the fastest measured *winning* direct baseline is 5.274 ms. **No exact break-even point between them was measured or fitted.** Hit times are roughly constant in this controlled duration sweep, so speedups rise largely because the baseline computation becomes longer.

### 4.2 Representative workloads, including a regression

| Workload and benchmark commit | Direct median | Cache-hit median | Ratio | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Synthetic C transform, `e9684c1` | 312.913 ms | 3.972 ms | **78.780x** | Controlled demonstration, includes 250 million extra mixing rounds |
| Short C ETL, `63e3363` | 7.396 ms | 7.957 ms | **0.929x** | TraceJIT is slower; baseline/hit p95s were 10.620/18.618 ms |

For the short C ETL at `63e3363`, the cold traced median was **21.024 ms**, versus **7.396 ms** direct. The historical cold traced p95 was **168.417 ms** on the shared runner. Both first-run overhead and tail variability matter when evaluating whether reuse is worthwhile.

The synthetic transform is intentionally favorable to whole-command caching because it repeats substantial CPU work while preserving a small, restorable output. Its headline ratio must **not** be described as representative performance on real compilers, production ETL, or interactive commands.

### 4.3 Amortized break-even analysis

Let `D` be direct execution time, `C` the first traced execution time, `H` a guarded cache-hit time, and `n` the number of identical executions with no invalidation. TraceJIT is faster over the sequence when:

~~~text
C + (n - 1)H < nD

If D > H, then n > (C - H) / (D - H).
If D <= H, repeated cache hits do not amortize the initial trace cost.
~~~

Using **medians as a simplified cost model**, the measured 5 ms target (`D=5.274`, `C=15.104`, `H=4.100` ms) predicts that **10 total executions** are needed to beat direct execution. The 250 ms target (`D=214.120`, `C=224.031`, `H=3.994` ms) predicts **2 total executions**. These are **derived estimates, not separately verified multi-run experiments**. Real performance depends on cache invalidation, output size, guard cost, contention, and runtime variance.

This is the practically relevant tradeoff: maximizing a best-case speedup is less informative than measuring cache admission rate, invalidation frequency, cost to trace, and amortized savings over realistic repeated invocations.

## 5. Correctness and refusal evidence

The public [adversarial fixture manifest](../../tests/fixtures/cases.json) contains **47 expected-classification cases**: **30 `Guarded`**, **12 `Nondeterministic`**, and **5 `Unknown`**. Its cases exercise file and metadata changes, environment and working-directory dependence, symlinks, descendants, clock and random reads, process identity, network and Unix sockets, unknown ioctl, and writable shared mappings.

The Linux [integration tests](../../crates/tracejit-cli/tests/linux_integration.rs) include cache-hit/replay checks, mutation-triggered deoptimization, output restoration, refusal behavior, and conditional sandbox assertions. The public [CI workflow](../../.github/workflows/ci.yml) is configured to run formatting, Clippy, workspace tests, Linux integration tests, capability assertions, and the demo. This report **inspected the test definitions and published results** but did not independently rerun them on a native Linux host.

In the historical short-command result, output equivalence and mutation/deoptimization are recorded as **PASS**. That constitutes evidence for the tested paths, not a proof over all possible Linux executions.

## 6. Limitations and threats to validity

1. **Sequential output restore:** the inspected `restore_outputs` validates preconditions and cached contents before modifying outputs, but then persists/removes multiple outputs in a loop. A failure partway through may leave earlier modifications applied. It is **not** a cross-file transaction.
2. **Unobservable dependencies:** ptrace sees modeled kernel crossings, not arbitrary shared-memory or other userspace influences. The vDSO patch addresses specific clock entry points, not every potential unobserved input.
3. **TOCTOU:** other processes may modify an input between guard validation and restoration. Landlock confinement of the traced process does not freeze external writers.
4. **Conservative compatibility:** CPython, shell pipelines, and `cc -c` were refused in the published runs. A high apparent speedup on a tailored workload does not imply a high hit rate on typical development workloads.
5. **Security boundaries:** the local cache may contain stdout, stderr, outputs, and environment values, without encryption or multi-user isolation. `PROVEN` is an enforcement status, **not** a formal verification result.
6. **Experimental design:** one hosted-runner class, synthetic-heavy workload mix, 30 observations per condition, uncontrolled system noise, no independent external replication, and performance figures collected on earlier commits. The current public code has no new same-commit performance result here.
7. **Prior art:** automatic dependency observation and process-result caching already exist. No head-to-head matching-workload comparison with Firebuild or Rattle is reported, so superiority and research novelty are unestablished.

## 7. Related work

- [Firebuild](https://github.com/firebuild/firebuild) automatically observes command behavior and caches eligible process results. TraceJIT must be evaluated against this close precedent rather than claiming automatic process caching as a new idea.
- [Build Systems à la Carte](https://doi.org/10.1017/S0956796820000088), Mokhov, Mitchell, and Peyton Jones (2020), provides a formal framework for thinking about task scheduling and rebuild decisions.
- [Build Scripts with Perfect Dependencies](https://ndmitchell.com/downloads/paper-build_scripts_with_perfect_dependencies-18_nov_2020.pdf) discusses Rattle and tracing-derived build dependencies.
- [Linux Landlock documentation](https://docs.kernel.org/security/landlock.html) describes scoped access control; it should not be confused with complete observation or whole-system isolation.

TraceJIT is best understood as a systems engineering experiment at the intersection of dynamic dependency discovery, conservative cache eligibility, and guarded replay, not a novel JIT compiler in the conventional machine-code-generation sense.

## 8. Reproduction and next experiments

On supported Linux x86_64 with ptrace permissions and the required toolchain:

~~~bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
./scripts/demo.sh
./scripts/benchmark.sh --runs 30 --warmups 5
python3 benchmarks/harness/break_even.py --runs 30 --warmups 5
~~~

The scripts generate or refresh benchmark artifacts. Reproduction **should be recorded against the actual checked-out commit** and should not overwrite older results without retaining their provenance.

The most informative follow-up experiments are:

1. A same-commit multi-run study measuring total end-to-end time across 1, 2, 5, 10, and 50 invocations, including the cold run and forced invalidations.
2. A real-command compatibility census with predeclared commands, eligible/refused counts, refusal reasons, output equivalence, and no selective omission of failures.
3. Fault injection into multi-output restoration, concurrent writers, CAS corruption, and symlink races, followed by a verified transactional restore strategy.
4. Repetitions on different kernel/libc versions and hardware, with raw samples, uncertainty intervals, and a baseline against the closest existing tool under matched conditions.
5. A new benchmark at the latest public commit after the later Phase 2 changes have been integrated and independently validated.

## 9. Phase 3A addendum (10 November 2026)

This section records work on the development branch after the original report's inspected commit. It
does not replace the historical measurements above.

### Candidate retention and replay ordering

Schema version 2 keys execution rows by `execution_id` and indexes `(lookup_key, updated_unix_ms)`.
Up to eight guarded candidates are retained for one command identity, so an A/B/A input sequence can
return to A without losing A's record. A candidate is selected only after its guards pass. Cached
stdout and stderr are BLAKE3-verified before any output destination is modified; inherited-stream
seekability is probed and the recorded start offset restored before restoration. The v1 cache
migrates in one SQLite transaction. Restoration remains pathname-visible, not atomic across a hard kill
and not inode-preserving.

### Measured A/B/A change

A five-session A/B/A fixture (`plain_file_read`) changed the third invocation from `Executed` on the
pre-change binary to `Reused` on the new binary. The new median wall time was **13.841662 ms**, versus
**20.572657 ms** for the pre-change binary; all output bytes were correct in both arms. Raw result:
[`benchmarks/results/phase3a/candidate-reuse.json`](../../benchmarks/results/phase3a/candidate-reuse.json).
This is a small fixture measurement of candidate retention, not a general workflow speedup.

### Hosted-CI failure and enforcement fix

The first hosted run of the Phase 3A commit (`2aa662d`) failed the Linux integration target. The public
check annotation named `enforced_execution_is_proven_reused_and_invalidated`: the second `--enforce`
run returned `classification: "Guarded"` with the reason `enforcement unavailable for the recorded
output policy; execution remains guarded`. The discovered dependency profile contained an absent
`Metadata` observation for `/etc/ld.so.preload`; `policy_from_record` required that path to exist and
therefore refused to build the sandbox policy.

`7358720` separates stat-only dependencies (`Metadata`, `FilesystemStats`, `SymlinkMetadata`) from
inputs that must be opened or executed. An absent stat-only path is a valid negative observation and is
omitted from the readable policy; a missing executable, file read, directory, symlink or inherited
stream still fails closed.

A second hosted run (`e77e03f`, run `42891829903`) built the policy but still returned `Guarded` with
`Permission denied` from `execve`. A dynamically linked target's ELF interpreter is executed by the
kernel before tracing begins, so it was absent from the recorded dependencies and Landlock denied the
interpreter. `3e7f820` reads `PT_INTERP`, verifies the interpreter exists and adds it to the readable
policy; a missing interpreter still refuses enforcement.

Local verification after the final fix: formatting, Clippy, **128 workspace tests**, **42 Linux
integration tests**, the release build and the demo pass. The local `PROVEN` test remains SKIP because
this host has no Landlock. Release binary:
`ce80ac96ef38159b7044c90642d8f1f83233db2ddf268827eec09a2a73573354`. Hosted run `42896870132` at
`3e7f820` passed every CI step, including Doctor, Linux integration and Demo. That is hosted evidence,
not a local reproduction.

## Conclusion

TraceJIT demonstrates a coherent approach to conservatively reusing certain unmodified Linux processes by combining observed effects with explicit synchronous guards. Its measured advantage is strong for a controlled, CPU-heavy repeated command; its fixed overhead and refusal rate limit the broader usefulness. The engineering and failure analysis are substantively more informative than the maximum speedup. The current evidence supports **a promising systems prototype with bounded claims**, not a general-purpose production accelerator or a formally proved method.

---

**Evidence index:** [README](../../README.md) | [benchmark methodology](../../BENCHMARKS.md) | [historical sweep](../../benchmarks/results/break-even.md) | [historical short-command result](../../benchmarks/results/latest.md) | [safety](../../SAFETY.md) | [source architecture](../../ARCHITECTURE.md) | [tests](../../crates/tracejit-cli/tests/linux_integration.rs)

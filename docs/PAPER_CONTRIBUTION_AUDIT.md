# Paper contribution audit (Phase AD)

Question: does TraceJIT now support a defensible research contribution relative to existing
systems? This audit separates what is new from what is engineering, what is empirical, what is
negative, and what is methodology, and it refuses a novelty claim the prior-art comparison does
not support.

## 1. Contributions, separated

**Novel mechanism (defensible).** A whole-command cache whose *reuse* decision is a set of
constructed guards over an explicitly modelled observable execution contract, rather than a
fingerprint of assumed inputs. The contract enumerates which kernel observations are
deterministic, which are controlled by a named contract, and which are refused; the guard set
is generated from the recorded effects and every guard must pass before any cached byte is
exposed. Companion mechanisms: transactional restoration with a durable restore intent, and
deoptimisation as a first-class outcome (DEOPT) rather than a miss.

**Engineering (real, not novel).** ptrace-based tracing on x86-64 Linux, BLAKE3 content guards,
SQLite record store, restore-intent crash recovery, cache prune/restore concurrency, a
controlled-execution contract for glibc's allocator entropy and for the audited GCC toolchain.

**Empirical (new measurements).** (a) A same-host head-to-head against Firebuild 0.8.2 showing
that the closest competing system cannot cache timestamp-preserving file-output commands and
replays clock-dependent commands by quirk, while TraceJIT refuses both
(`docs/FIREBUILD_COMPARISON.md`). (b) A scale study on a pinned 140 MB release archive showing
the advantage grows with artifact size for compression (7.7× → 31× → 64× per hit) and reverses
for cheap hash-only commands below ~10 MiB (`docs/ARTIFACT_BENCHMARKS.md`). (c) Integer
break-even counts rather than fractional ratios.

**Negative findings (valuable).** Descriptor modelling of inherited `F_GETFD` is sound but
changes no eligibility (0/48 census cells), so the refusal is retained
(`docs/INHERITED_DESCRIPTOR_SEMANTICS.md`). Metadata guard relaxation is unjustifiable
(Phase AC). `auto` admission costs 4 % against `always` in a mixed session but protects
one-shots (`docs/ECONOMIC_ADMISSION.md`).

**Correctness methodology (a contribution in itself).** A frozen corpus with an independent
oracle, adversarial suites that must preserve their counterexamples, state-machine model
checking, restore fault injection, cache corruption tests, and a rule that a single incorrect
HIT blocks the responsible optimisation. The Phase AC twin-metadata defect is a worked example:
the benchmark, not the product, was wrong, and the fix was to make the comparison correct
rather than to weaken the check.

**Performance economics.** The measured statement is narrow and defensible: for repeated
compression/archive generation of artifacts ≥1 MiB, with a stable input, TraceJIT saves 3–64×
per hit at the cost of an 8–15 % trace premium, breaking even at the second invocation. Outside
that box (cheap filters, hash-only commands, mutation-heavy workloads, one-shots) it does not
pay, and for sub-10 ms filters its hit cost is close enough to direct execution that the
economics disappear.

## 2. Prior art and what may not be claimed

| system | mechanism | what TraceJIT may **not** claim |
| --- | --- | --- |
| Firebuild | LD_PRELOAD interception, per-process fingerprints, blob replay ("shortcut") | "first automatic command cache", "faster warm path than the state of the art" (it is not, for stdout filters), "the only system that caches arbitrary commands" |
| ccache / sccache | compiler-specific output hashing | "compiler caching is unsolved" or any compiler-cache speed claim |
| Bazel/remote execution, Vesta, Nix | content-addressed build actions, hermetic inputs | "content-addressed caching is new" |
| Rattle (traced command caching research) | trace-based record/replay of command traces | "first to use traces for command caching" |
| Make/ninja rebuild | timestamp and dependency-graph rebuild | any claim that rebuild avoidance is new |

The defensible novelty is the *contract + guards + fail-closed deoptimisation* combination, and
the empirical claim that this is affordable at artifact scale. It is a systems paper about
correctness-preserving reuse, not a new caching idea.

## 3. Proposed structure

1. **Introduction** — automatic whole-command reuse fails on correctness, not speed; the
   artifact-generation niche where it can be both correct and fast.
2. **Problem formulation** — an execution is a function of an observable contract; define
   observable equivalence, refusals and deoptimisation.
3. **Related work** — Firebuild, ccache, Rattle, content-addressed build systems; the guarantee
   each makes and how each obtains it (measured for Firebuild, cited for the rest).
4. **Observable execution contract** — effects, dependencies, refusal classes, controlled
   contracts (`allocator-entropy-v1`, `compiler-runtime-v1`).
5. **System architecture** — trace, classify, guard, record, restore; crate boundaries.
6. **Effect classification** — `PROVEN`/`GUARDED`/`UNKNOWN`/`NONDETERMINISTIC`/`EMPIRICALLY_STABLE`
   and why only the first two may be reused.
7. **Guard construction** — one guard per recorded observation; metadata, content, directory
   enumeration, filesystem stats, inherited streams, runtime identity.
8. **Transactional restoration** — restore intent, atomic apply, crash recovery, prune/restore
   concurrency.
9. **Economic admission** — the cost inequality, the measured failure cases, why admission is
   separate from eligibility.
10. **Evaluation** — Phase AC non-compiler corpus, Phase AD artifact scale, Firebuild
    head-to-head, mixed-session admission; all on one host with pinned inputs.
11. **Adversarial correctness** — differential fuzzing, model checking, fault injection,
    cache corruption, same-timestamp rewrites, rename-source, stale-archive, metadata matrix.
12. **Limitations** — validation-to-restore window, one host/kernel/libc, Firebuild version
    dependence, `PROVEN` untested on a Landlock host, no multi-machine reproduction.

## 4. Verdict

**B — a narrow, defensible fail-closed reuse paper with genuinely new competitive evidence.**
It is publishable as a workshop/systems-conference paper about correctness-preserving caching
for artifact generation, provided the claims stay inside the measured box and the Firebuild
comparison is presented as version- and host-specific. It is **not** a general build-accelerator
paper: on cheap filters and one-shots TraceJIT loses to the state of the art, and the paper must
say so in the abstract.

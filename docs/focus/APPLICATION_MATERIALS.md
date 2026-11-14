# TraceJIT application materials

Verified evidence only. Tip: `b089d5e774d6481a83ec3f308f479d551ed50ce7` (Phase G #16 on `main`). No peer-reviewed, production-adoption, collaborator, user-count, or award claims.

## Concise project summary

TraceJIT is a Rust prototype that memoizes unmodified Linux x86_64 commands by tracing modeled syscalls, classifying effects, and replaying outputs only when `GUARDED`/`PROVEN` records still pass synchronous guards. It fails closed on clocks, randomness, networks, and unmodeled behavior. Measured wins include a CPU-heavy transform (~11.6× warm hit on this host) and correct recovery where Make returns stale bytes; short commands and large restore+hash paths remain net losses.

## Two resume bullets

- Built a fail-closed Linux process memoizer (ptrace, BLAKE3 CAS, SQLite) that reuses whole commands only after effect classification and synchronous guards; closed inherited-descriptor and `/dev/null` identity P0s with regression tests and Landlock/`PROVEN` integration coverage.
- Measured honest performance boundaries: ~11.6× warm reuse on a CPU-heavy C transform and correct mtime/corrupt recovery vs Make, while retaining documented short-ETL (0.407×) and large-file restore losses; added reuse certificates, CEGAR-shaped refinement, and offline admission analysis without weakening production safety.

## 100-word technical description

TraceJIT observes an unmodified Linux x86_64 process with ptrace, reconstructs filesystem and descriptor dependencies, and classifies each run as GUARDED, PROVEN, UNKNOWN, or NONDETERMINISTIC. Only GUARDED and PROVEN records may reuse, and only after every compiled guard passes and cached streams verify—before any output is restored. PROVEN additionally requires installed seccomp and Landlock. The system stores artifacts in a BLAKE3 content-addressed store indexed by SQLite, retains a bounded set of alternate candidates, and refuses clocks, entropy, and unmodeled syscalls. Evaluation shows large speedups on long deterministic CPU work, correct recovery where Make is wrong, and deliberate losses on short commands.

## Hardest engineering problem

Inherited open-file identity: pathname-only trust for `/dev/null` and missing preflight for fds above stderr produced demonstrable false hits (EOF reuse after descriptor substitution). Fixing this required fstat identity checks, fail-closed `/proc/self/fd` enumeration, `dup2(fd,fd)` state preservation, forgetting directory enumeration on descriptor reuse, and a post-`Cache::open` re-scan so cache-owned descriptors could not hide non-CLOEXEC fds—without widening observation into an unsound full descriptor model.

## Most important failed experiment

Controlled CPython / allocator-entropy contracts (research PRs #9/#10) and related “make Python reusable” directions. Binding exact ELF build IDs and call sites still left clocks, `gettid`, and semantic changes (`os.kill(getpid)`, fixed clocks, hash-seed policy) that are not native-equivalent. Counterexamples blocked merge; native census stayed 0/9 reusable. Lesson kept on main: do not ship controlled runtimes that quietly change cold-run semantics.

## What was learned

- Observation plus guards can make whole-command reuse sound for a narrow class—and the refusals are as informative as the hits.
- Output-presence invalidation is often necessary, not a missing optimization (bzip2 identical-rerun deopt).
- Hit-path cost is dominated by CAS restore and hashing on large files; dropping fsync wins microseconds and loses durability.
- Adaptive admission earns its keep by skipping short commands while still caching long ones.
- Competitive honesty matters: skip missing tools; report Make’s incorrect fast path rather than claiming TraceJIT wins identical-rerun latency.

## Reproducibility instructions

On Linux x86_64, at `b089d5e` or a descendant that keeps these artifacts:

```bash
git checkout b089d5e774d6481a83ec3f308f479d551ed50ce7   # or later main with docs PR
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo build --workspace --release
cargo test -p tracejit-cli --test linux_integration -- --nocapture
./scripts/demo.sh
./scripts/benchmark.sh
# optional Phase G suite (writes under benchmarks/results/phase_g/):
python3 benchmarks/repos/phase_g_evaluation.py
```

Raw evidence: `benchmarks/results/latest.*`, `benchmarks/results/phase_f/`, `benchmarks/results/phase_g/`, `benchmarks/results/phase_d/differential/`. Technical report: [../research/TRACEJIT_TECHNICAL_REPORT.md](../research/TRACEJIT_TECHNICAL_REPORT.md). Claims: [../research/CLAIMS_LEDGER.md](../research/CLAIMS_LEDGER.md).

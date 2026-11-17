# TraceJIT

Reuse an unmodified Linux x86_64 command only when the dependencies TraceJIT observed still pass synchronous guards. If an effect is unknown, or the command reads the clock, randomness, or the network, TraceJIT runs it again. Correctness beats performance; uncertainty fails closed.

**Status:** `v0.2.0-beta.1`, a research-oriented prototype for Linux x86_64. It is not a general guarantee of execution equivalence, has not been peer reviewed, and has no production adoption. Read [known limitations](docs/LIMITATIONS.md) before trusting a hit.

## Install

Linux x86_64 only. The archive contains the binary, licenses, safety and security documentation, provenance manifest, and SBOM.

```bash
version=$(curl -fsSL https://raw.githubusercontent.com/Satwik-P28/tracejit/main/VERSION)
base="https://github.com/Satwik-P28/tracejit/releases/download/v${version}"
name="tracejit-v${version}-x86_64-unknown-linux-gnu.tar.gz"
curl -fsSLO "${base}/${name}" && curl -fsSLO "${base}/SHA256SUMS"
sha256sum -c --ignore-missing SHA256SUMS
tar -xzf "$name" && install -m 755 "tracejit-v${version}-x86_64-unknown-linux-gnu/tracejit" ~/.local/bin/tracejit
tracejit doctor   # requires supported yes and ptrace yes
```

Full instructions, source builds, and artifact verification: [docs/INSTALL.md](docs/INSTALL.md).

## Why this is hard

Declared build graphs (Make, Ninja, Bazel) and compiler caches (ccache, sccache) reuse work when inputs are listed or toolchain-specific. An already-built command does not come with that list. Replaying stdout and output files without checking what the process actually depended on is a stale-hit hazard. ptrace sees modeled kernel crossings, not arbitrary userspace influence; clocks, entropy, process identity, and unmodeled syscalls force refusal rather than a guessed hit.

## What it supports now

- Linux x86_64 whole-command memoization via ptrace, BLAKE3 CAS, and SQLite.
- Reuse only for `GUARDED` and `PROVEN` records after every guard passes.
- Optional `--enforce` (seccomp + Landlock ABI 3+) for `PROVEN`.
- Bounded alternate candidates per identity (default 8), A/B/A reuse, stream verify before output mutation.
- CLI: `run`, `analyze`, `explain`, `doctor`, `certify` / `verify-certificate`, `admission-eval`, cache stats/clear.
- Strict hashing by default; `--guard-mode fast` is an explicit opt-in.

Not supported: macOS/Windows/non-x86_64 reuse, partial in-process reuse, remote caches, peer-reviewed or production-adoption claims.

## Central contribution

Fail-closed **effect-aware whole-process memoization**: observe → classify → compile guards → reuse only when eligibility and guards hold, with testable refusals and an explicit Obs contract ([docs/research/EXECUTION_EQUIVALENCE.md](docs/research/EXECUTION_EQUIVALENCE.md)). Related systems already cache processes or builds; TraceJIT’s assessed contribution is this combination of classification, guards, certificates, refinement workflow, and measured negatives—not a claim of novelty for caching itself.

## Guarantees that actually hold

| Holds | Does not hold |
| --- | --- |
| No reuse for `UNKNOWN` / `NONDETERMINISTIC` / `EMPIRICALLY_STABLE` | Full execution equivalence or formal proof |
| Guards + stream verify before exposing cached bytes | Freeze of other processes (validate→restore TOCTOU remains) |
| `PROVEN` means seccomp and Landlock were installed | `PROVEN` as machine-checked Obs proof |
| Certificates never grant `FullEquivalenceProof` | Crash-atomic multi-output restore under hard kill |

Feature status table: [docs/research/CLAIMS_LEDGER.md](docs/research/CLAIMS_LEDGER.md). Safety narrative: [SAFETY.md](SAFETY.md).

## Measured wins and losses

All figures cite committed harness outputs with exact tips. Do not merge numbers across commits into one “speedup.”

**Mandate §4 on final product tip** (measured `4ffde9a`, product `crates/` ≡ `ed3bd39`/`7b9e7ca`; `benchmarks/results/final_stab_pr3/mandate_s4/`, n=30, bootstrap 95% CI):

| Scenario | DIRECT | Warm HIT | Note |
| --- | ---: | ---: | --- |
| CPU-heavy `c-transform` | 32.524 ms | **5.303 ms (~6.1×)** | Real workload; no safe warm-HIT opt landed |
| `/bin/true` / short floor | **0.351 ms** | 4.475 ms | Warm **loss** — DIRECT wins |
| Short-ETL session cumulative | **35 ms** | 177 ms | HITs can still lose the session |

**Census:** 1/32 eligibility under unmodified defaults (`mandate_s4/census/`).

**Withdrawn opt:** destination-match restore skip — synthetic back-to-back looked faster; with output consumption skip rate is **0/40**. Not a product claim ([final_stab_pr3/compare.md](benchmarks/results/final_stab_pr3/compare.md)).

**Competitive (tip `364331b`, `benchmarks/results/phase_k8/`):** Make/Ninja win identical-rerun wall time; TraceJIT stays content-correct on mtime-preserved edit / corrupt output where Make/Ninja returned WRONG. Missing tools are skipped, not scored as losses.

Release report: [docs/final/RELEASE_REPORT.md](docs/final/RELEASE_REPORT.md). Older adversarial packaging: [docs/final/FINAL_ANSWER.md](docs/final/FINAL_ANSWER.md).

## Demo

Linux x86_64:

```bash
cargo build --workspace --release
./scripts/demo.sh
./target/release/tracejit doctor
```

`demo.sh` compiles the synthetic transform, traces, reuses, explains, mutates the input, and requires `DEOPT`. It runs with `TRACEJIT` set to an installed binary as well:

```bash
TRACEJIT=~/.local/bin/tracejit ./scripts/demo.sh
```

For the short-command harness and the release benchmark package:

```bash
./scripts/benchmark.sh
python3 benchmarks/releases/run_release.py --runs 20 --warmups 3
```

Release evidence lives in `benchmarks/releases/v<version>/`; the methodology is in [docs/BENCHMARK_REPRODUCTION.md](docs/BENCHMARK_REPRODUCTION.md).

## Technical report and application notes

- Final adversarial package index: [docs/final/FINAL_ANSWER.md](docs/final/FINAL_ANSWER.md) · [EXECUTIVE_SUMMARY.md](docs/final/EXECUTIVE_SUMMARY.md) · [ARTIFACT_EVALUATION.md](docs/final/ARTIFACT_EVALUATION.md)
- Design/evidence report: [docs/research/TRACEJIT_TECHNICAL_REPORT.md](docs/research/TRACEJIT_TECHNICAL_REPORT.md)
- Claims ledger: [docs/research/CLAIMS_LEDGER.md](docs/research/CLAIMS_LEDGER.md)
- Prior-art matrix: [docs/final/PRIOR_ART_IMPLEMENTATION_MATRIX.md](docs/final/PRIOR_ART_IMPLEMENTATION_MATRIX.md)
- FOCUS / application materials: [docs/focus/APPLICATION_MATERIALS.md](docs/focus/APPLICATION_MATERIALS.md)

## 30-second path

```text
tracejit doctor
tracejit run -- <command> [args...]
tracejit run -- <command> [args...]
tracejit explain
```

The first `run` traces. The second reuses only when the class is `GUARDED` or `PROVEN` and every guard passes.

## How it works

```mermaid
flowchart TD
  run[Command] --> lookup[Lookup by executable, argv, cwd, environment, runtime identity]
  lookup --> hit{Prior record and every guard passes?}
  hit -->|yes| reuse[Restore outputs and replay stdout, stderr, exit status]
  hit -->|no| trace[ptrace the process tree]
  trace --> effects[Classify Read, Write, Control, and Unknown effects]
  effects --> det{Determinism class}
  det -->|UNKNOWN or NONDETERMINISTIC| closed[Fail closed: do not reuse]
  det -->|observed effects are guardable| guarded[GUARDED]
  guarded --> sandbox{--enforce and seccomp plus Landlock ABI 3+ installed?}
  sandbox -->|yes| proven[Promote to PROVEN]
  sandbox -->|no| stay[Stay GUARDED]
  proven --> store[Compile guards and store the result]
  stay --> store
  store --> next[Next run validates guards before exposing any cached byte]
  next --> reuse
  next --> deopt[Guard failure: deoptimize and retrace]
  deopt --> trace
```

## Supported platforms

Linux x86_64 (GNU) with `ptrace` permitted. `doctor` refuses other operating systems, architectures, and missing kernel features instead of degrading silently. There is no macOS, Windows, AArch64, or musl build; none is advertised.

## Architecture and tests

Crates: `effects → guards → cache → trace → sandbox → core → cli`. Details: [ARCHITECTURE.md](ARCHITECTURE.md).

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
```

Adversarial fixture narrative: [docs/ADVERSARIAL.md](docs/ADVERSARIAL.md). Comparisons: [docs/COMPARISONS.md](docs/COMPARISONS.md).

## License

Apache-2.0 or MIT, at your option ([LICENSE-APACHE](LICENSE-APACHE), [LICENSE-MIT](LICENSE-MIT)).

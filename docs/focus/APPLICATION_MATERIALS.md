# TraceJIT application materials

Verified evidence only. Tip: `827b7763a73cddda4e3a99c9883fbae4b18d87d2` (main after final-adversarial PRs #26–#30). No peer-reviewed, production-adoption, collaborator, user-count, or award claims. Agent assistance was used in implementation and documentation; do not claim otherwise.

## Concise project summary

TraceJIT is a Rust prototype that memoizes unmodified Linux x86_64 commands by tracing modeled syscalls, classifying effects, and replaying outputs only when `GUARDED`/`PROVEN` records still pass synchronous guards. It fails closed on clocks, randomness, networks, and unmodeled behavior. Measured wins include ~7.4× warm HIT on real `c-transform` (final_p1 e2e @ `026e660`) and correct recovery where Make returns stale bytes; short-command floor and short-ETL sessions remain net losses.

## Two resume bullets

- Built a fail-closed Linux process memoizer (ptrace, BLAKE3 CAS, SQLite) that reuses whole commands only after effect classification and synchronous guards; closed RENAME_EXCHANGE false-HIT, restore-intent refuse after hard kill, and pre-restore TOCTOU recheck with regression tests.
- Measured honest performance boundaries: ~7.4× warm reuse on a CPU-heavy C transform with bootstrap CIs, 1/32 native census eligibility, and documented short-command losses; shipped CEGAR refine without auto-deploy and an offline admission model that cannot override safety.

## ≤100-word Jane Street FOCUS description

TraceJIT observes an unmodified Linux x86_64 process with ptrace, reconstructs filesystem and descriptor dependencies, and classifies each run as GUARDED, PROVEN, UNKNOWN, or NONDETERMINISTIC. Only GUARDED and PROVEN may reuse, and only after every compiled guard passes and cached streams verify—before any output is restored. PROVEN additionally requires installed seccomp and Landlock. Artifacts live in a BLAKE3 CAS indexed by SQLite. Evaluation shows large speedups on long deterministic CPU work, correct recovery where Make is wrong, and deliberate losses on short commands. Correctness contract stops at modeled Obs—not full equivalence or multi-file atomic restore.

## 60-second interview explanation

Most caches trust a declared graph or a compiler wrapper. TraceJIT instead traces one unmodified command, keeps only what it can guard, and refuses clocks, entropy, and unknown syscalls. A hit must re-check every dependency and verify CAS bytes before touching your files. We found a false hit on rename exchange and fixed it by refusing that path. Warm hits win on heavy CPU transforms and lose on sub-millisecond commands—admission skips tracing when it will not pay off, but never skips safety.

## Hardest engineering problem

`renameat2(RENAME_EXCHANGE)` looked like a delete+rename under an incomplete model and produced a false HIT (native Obs diverged). Fixing it required treating exchange flags as unmodeled/UNKNOWN, preserving that refuse under adversarial fixtures, and keeping the independent oracle from sharing production validator code—without “fixing” performance by widening admits.

## Meaningful performance win and loss

- **Win:** `c-transform` warm HIT ≈ 4.40 ms vs DIRECT ≈ 32.66 ms (~7.4×), `benchmarks/results/final_p1/e2e.json`.
- **Loss:** `plain_file_read` warm HIT ≈ 5.73 ms vs DIRECT ≈ 0.38 ms; short-ETL session cumulative also loses — same artifact.

## Design decisions (human)

Prefer refuse over stale reuse; keep soft restore rollback and hard-kill intent refuse rather than a false all-or-nothing journal; keep production admission as analytical CurrentAuto; reject bandit defaults and controlled runtimes that change cold semantics; document competitor skips instead of inventing losses.

## Ten adversarial follow-ups (accurate answers)

1. **Is PROVEN a proof?** No — installed seccomp+Landlock for that run, not machine-checked Obs equivalence.
2. **Can two renames be atomic?** No — sequential visibility; soft rollback only.
3. **What about TOCTOU?** Recheck shrinks the window; residual race remains.
4. **Why not eBPF?** Lost events unbounded; measurement adjunct only.
5. **Why refuse getrandom?** Nondeterministic; workload env like PYTHONHASHSEED is not a classifier exception.
6. **Did you beat Ninja?** Identical rerun: no. Content-correct on mtime/corrupt: yes (phase_k8).
7. **Auto-deploy CEGAR?** Never — `VerifiedOfflineNotDeployed` ceiling.
8. **Census 1/32 — failure?** Boundary under native randomness/clock; not tuned to pass.
9. **SQLite CVE?** Documented deferred bump; audit not claimed clean.
10. **Did a model write all code?** No — agent assistance was used; claims avoid fabrication.

## Reproducibility

```bash
git checkout 827b7763a73cddda4e3a99c9883fbae4b18d87d2
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo build --workspace --release
cargo test -p tracejit-cli --test linux_integration -- --nocapture
./scripts/demo.sh
python3 scripts/modelcheck/check_state_machines.py
./scripts/phase_k4_restore_fault.sh ./target/release/tracejit
```

Evidence index: `docs/final/FINAL_ANSWER.md`, `docs/final/ARTIFACT_EVALUATION.md`, `docs/research/CLAIMS_LEDGER.md`.

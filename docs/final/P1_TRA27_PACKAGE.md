# TRA-27 / mandate §§6–10 — verified package

Tip base: `origin/main` `026e660f6722ee7dddbf8ec00caaf52a817c36cf`  
Branch: `cursor/final-adversarial-p1-perf-6ed7`

## Deliverables

| § | Doc | Raw artifacts |
| ---: | --- | --- |
| 6 | `P1_TRACING_ARCHITECTURE.md` | `benchmarks/results/final_p1/tracing_completeness.json` |
| 7 | `P1_DEPENDENCY_DAG.md` | design only (no semantic code change) |
| 8 | `P1_COMPATIBILITY_CENSUS.md` | `benchmarks/results/final_p1/census/` |
| 9 | `P1_E2E_PERFORMANCE.md` | `benchmarks/results/final_p1/e2e.{json,md}` |
| 10 | `P1_ADMISSION_REGRET.md` | `benchmarks/results/final_p1/admission-eval.txt` |

Harness: `scripts/final_p1_measure.py` + expanded `benchmarks/realworld/census.py` (32 workloads).

## Headline counts (e2e package)

- HIT (`kind=Reused`): **140**
- EXECUTED (`kind=Executed`): **113**
- DEOPT (`kind` deoptimized): **0** in this run set
- Admission `Skipped`: **37**

Census: **1 / 32** verified reuse (`gzip-compress-stdout`); eligibility 0.031.

## Deferred / rejected (explicit)

- Selective seccomp-BPF / eBPF-trusted tracing (§6) — deferred pending complete-event proof
- Typed dependency DAG implementation (§7) — design frozen; not shipped
- Bandit/ML admission default (§10) — rejected
- Expanding eligibility by weakening randomness/clock refusals — rejected
- Re-scoring absent competitors as losses — rejected
- Power-loss ≠ SIGKILL; multi-file atomic visibility — unchanged non-claims from P0

## Reproduce

```bash
cargo build --workspace --release
python3 benchmarks/realworld/census.py --runs 2 --warmups 1 \
  --output-dir benchmarks/results/final_p1/census
python3 scripts/final_p1_measure.py --output-dir benchmarks/results/final_p1 \
  --warmups 5 --runs 30
```

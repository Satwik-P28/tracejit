# Phase Q — quantum-inspired dependency optimisation (isolated research)

Status: **research, not merged, not on the production path.** The product crates
(`crates/`) and `Cargo.toml` are unchanged.

Result: see [REPORT.md](REPORT.md). Short version: guard/candidate ordering is a
polynomial sequential-testing problem; the greedy `cost/failure-probability` sort is
provably optimal for independent guards, `8!` enumeration is exact for candidates, and
every annealer/QUBO arm evaluated is dominated on decision cost or fails a hard
constraint. No production adoption is recommended.

## Layout

| File | Purpose |
| --- | --- |
| `tjq_anchors.py` | extracts measured anchors from `benchmarks/results/phase3c` and `phase_k9` (no invented numbers) |
| `tjq_model.py` | guard/candidate instances, exact expected-cost objective, correlated invalidation model |
| `tjq_solvers.py` | current order, ratio greedy, exact DP, branch and bound, SA, tabu, parallel tempering, QUBO knapsack/partition, LPT, Ocean samplers |
| `tjq_verify.py` | independent plan verifier; shares no cost arithmetic with the solvers |
| `tjq_experiments.py` | E1–E9, writes `results/measurements.json` and `results/summary.md` |
| `tjq_selftest.py` | 19 tests (verifier rejections, brute-force agreement, QUBO energy, anchors) |
| `FORMULATION.md` | objective, interchange proof, correlation model, hard constraints, QUBO limits |
| `RELATED_WORK.md` | prior art (Boothroyd/Mitten/Creemers), libraries, licenses, method-fit table |
| `PAPER_DRAFT.md` | technical-paper draft separating prior art from this work's measurements |
| `results/` | raw measurements and generated summary |

## Reproduce

```bash
cd research/phase_q
python3 -m venv --system-site-packages .venv
.venv/bin/pip install dwave-samplers dimod   # Apache-2.0
.venv/bin/python tjq_selftest.py
.venv/bin/python tjq_experiments.py
```

`./run.sh` does the same from the repository root. The venv is git-ignored; no Rust
dependency is added.

## Invariants

- Reordering never removes a guard. `validate_all` still runs over the full list before
  any cached byte is exposed.
- Plans are verified structurally (permutation, metadata/content adjacency, inherited
  stream order) and numerically (cost recomputed independently) before use.
- Nothing here is wired into `tracejit-core`; there are no remote calls.

# Phase 2H: cost-aware admission and end-to-end measurements

Verdict: caching still pays only for work above roughly 10 ms. `--admission auto` removes the
losses on short commands and on workloads already proven ineligible, and the fixed workflow suite
now shows a positive end-to-end result in both modes. The developer-loop suite is still a net
slowdown for always-cache (1.52–1.59x) because most of its work is refused; auto brings it to 1.08x.

## Policy

`--admission always | auto | never` (core `Admission`):

- **always** — historical behaviour: trace, store, reuse when guards pass.
- **auto** — the first invocation of an identity runs **directly** and records its measured cost;
  a later invocation is traced only if `direct >= 2 x max(measured hit, 6 ms)`. Once an identity is
  recorded as ineligible (compilers, `sort`, `tar`), auto never traces it again: the question has
  already been answered, so the cost is paid once, not on every run.
- **never** — always run directly.

The thresholds are constants in `tracejit-core` (`HIT_COST_FLOOR_NS`, factor 2) and the stored cost
is a 3:1 blend in the cache's `admission` table. Nothing is learned across identities and no model
is involved.

## Fixed suites, two sessions

| Suite | Native | Controlled always | Controlled auto | Equivalence |
| --- | --- | --- | --- | --- |
| Direct 16, session A | 1/16 | **7/16** | 0/16 on the second run | 16/16 |
| Direct 16, session B | 1/16 | **7/16** | 0/16 on the second run | 16/16 |
| Census 9, A | 0/9 | 0/9 | — | 9/9 |
| Census 9, B | 0/9 | 0/9 | — | 9/9 |

The controlled set is `gzip`, `bzip2`, `sed`, `tr`, `base64`, `md5sum`, `wc` — `tr` is now stable in
both sessions after removing `atime` from the inherited-stdin identity. Auto's `0/16` is by design:
the suite measures the *second* invocation, and auto spends the first measuring and the second
tracing; the third is the first hit. The suite's purpose is compatibility, not auto's steady state.

## Workflow (5.4 MB, `sed` → `wc -c` → `md5sum` → `gzip -9 -c`)

| Session | Mode | Direct ms | Cached ms | Speedup | Hits |
| --- | --- | ---: | ---: | ---: | --- |
| A | always | 659.50 | 73.68 | 8.95x | 4/4 |
| B | always | 660.23 | 68.47 | 9.64x | 4/4 |
| A | auto | 657.91 | 63.50 | 10.36x | 3/4 (wc skipped) |
| B | auto | 657.91 | 64.06 | 10.27x | 3/4 (wc skipped) |

Auto is slightly faster because it stops caching the 1 ms `wc` step; skipping is worth more than a
hit there.

## Developer-loop suite (`benchmarks/realworld/dev_loops.py`)

Five fixed scenarios: transform, repeated compilation, code generation then compile, short beside
expensive, and an edit between runs. Medians of 5, two sessions.

| Scenario | Direct A | Always A | Auto A | Direct B | Always B | Auto B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| transform | 30.89 | 27.65 (0.90x) | 19.87 (0.64x) | 30.93 | 25.18 (0.81x) | 20.79 (0.67x) |
| compile | 327.76 | 476.67 (1.45x) | 334.07 (1.02x) | 320.74 | 494.75 (1.54x) | 346.53 (1.08x) |
| codegen | 160.45 | 243.89 (1.52x) | 196.06 (1.22x) | 161.86 | 251.05 (1.55x) | 175.52 (1.08x) |
| mixed | 28.42 | 31.56 (1.11x) | 25.12 (0.88x) | 26.72 | 31.08 (1.16x) | 25.74 (0.96x) |
| edit | 5.66 | 63.68 (11.25x) | 20.70 (3.66x) | 5.72 | 65.21 (11.40x) | 22.18 (3.88x) |
| **total** | — | **1.52x** | **1.08x** | — | **1.59x** | **1.08x** |

Slowdowns: always 4/5 scenarios in both sessions; auto 3/5. `edit` is a deliberate invalidation
loop — `sed -i` changes the input every iteration — so caching can only lose there; that is
reported, not hidden. Auto's remaining losses are `edit` and the first trace of a refused compile.

## What this shows

- Positive savings exist and are reproducible: 8.95–9.64x (always) and 10.27–10.36x (auto) on a
  realistic four-command workflow in both sessions.
- Always-caching is the wrong default for mixed workloads: 1.5x slower on a loop suite dominated by
  refusals and tiny commands.
- Auto is not a predictor and makes no claim to be: it removes two measured classes of loss
  (sub-6 ms commands, identities already proven ineligible) and leaves the rest unchanged.
- Nothing here reaches the census workloads, whose shell layer still reads clocks, PIDs and sockets.

## Reproduce

```bash
cargo build --release -p tracejit-cli
python3 benchmarks/realworld/direct_suite.py --runs 5 --contract allocator-entropy-v1 --output-dir benchmarks/results/phase2h/direct-controlled-a
python3 benchmarks/realworld/direct_suite.py --runs 5 --contract allocator-entropy-v1 --admission auto --output-dir benchmarks/results/phase2h/direct-auto-a
python3 benchmarks/realworld/workflow.py --reps 5 --admission auto --output-dir benchmarks/results/phase2h/workflow-auto-a
python3 benchmarks/realworld/dev_loops.py --reps 5 --session a --output-dir benchmarks/results/phase2h/dev-loops
python3 benchmarks/realworld/census.py --runs 2 --warmups 1 --contract allocator-entropy-v1 --output-dir benchmarks/results/phase2h/census-controlled-a
python3 benchmarks/differential/fuzz.py --seed 7
```

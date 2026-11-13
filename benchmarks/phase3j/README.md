# Phase 3J — controlled Python probes and workloads

These scripts reproduce the Phase 3J evidence. They do not merge or promote the experimental
contracts.

## Prerequisites

- Linux x86_64.
- Release binary at `target/release/tracejit`.
- The audited CPython at `/usr/bin/python3.12`.
- No third-party Python packages: the workloads use the standard library only.

```bash
cargo build --release
```

## Scripts

```bash
/usr/bin/python3.12 benchmarks/phase3j/run_semantics.py
/usr/bin/python3.12 benchmarks/phase3j/profile.py
/usr/bin/python3.12 benchmarks/phase3j/run_workloads.py
```

`run_semantics.py` runs the native control and two controlled runs for each probe and both
contracts. It records fixed v1 clock/identity behavior, v2 logical clock progression, entropy/thread/
fork refusal, virtual directory padding, direct syscalls and the self-signal counterexample.

`profile.py` measures the original `python-csv-json` ETL with independent cold caches, steady warm
hits, phase timings and an input invalidation.

`run_workloads.py` measures the 120k-row CSV transform and 320x240 pure-Python image convolution.
It requires byte-identical output, a `Reused` decision on every warm run, and a retraced changed-input
output matching direct execution.

## Results

Raw JSON is written to `benchmarks/results/phase3j/`:

- `semantic-probes.json`
- `profile.json`
- `cpu-workloads.json`
- `reproduced-acceptance.json` (copy of the rerun Phase 3I acceptance; the committed Phase 3I
  evidence is left untouched)

## Scope

`python-runtime-v1` and `python-runtime-v2` are explicit experimental contracts for the exact
audited CPython ELF. `v2` advances a logical clock; it is not wall-clock or scheduler semantics.
Fixed identity does not make `os.kill(os.getpid(), ...)` work. Native byte-exact directory guarding
remains the default. See `docs/audits/PHASE3J_CONTROLLED_PYTHON_CORRECTNESS_AND_PERFORMANCE.md`.

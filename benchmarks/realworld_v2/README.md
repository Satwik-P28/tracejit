# Real-world benchmark package, version 2 (Phase AA)

This package answers one question with evidence: **for which ordinary Linux
commands is TraceJIT's whole-command reuse actually correct and actually
faster?** It is deliberately separate from `benchmarks/harness/` (one synthetic
workload) and from `benchmarks/realworld/census.py` (eligibility only, no
randomized timing).

Run everything:

```bash
./benchmarks/realworld_v2/run.sh
```

Evidence lands in `benchmarks/results/phaseaa/` (Phase AA) and
`benchmarks/results/phaseaa1/` (the Phase AA1 re-measurement): `results.json`
(raw samples), `results.md`, `environment.json`, `adversarial.json`,
`competitive_zlib.json`, `repro/` (a clean-checkout run), and one
`raw/<workload>__<policy>.json` per measurement.

Every results file carries `aggregate.accounting`, recomputed from its own rows by
`runner.py` and independently checked by `validate.py`: declared cells, attempted
cells, refusals, eligible-but-no-hit rows, verified HITs and timed rows. Eligibility
and reuse are different fields; do not divide one by the other's denominator.

## What is measured

Fifty-nine workload configurations across twelve families: compilers and build
systems, static analysis, compression and packaging, data processing, scientific
compute, interpreters and developer tooling, filesystem-sensitive workflows, and
four workloads built from the pinned upstream zlib 1.3.1 tree. Five of the
declared workloads need tools that are not installed on this image; they are
reported as `tool_unavailable` and never counted as refusals or as wins.

| Tier | Meaning |
| --- | --- |
| A | Strict native: no workload adaptation, no execution contract |
| B | Controlled execution: `--contract allocator-entropy-v1` or `--contract compiler-runtime-v1` |
| C | Adapted workload: a declared environment, input or invocation change |
| D | Unsupported: refused by TraceJIT, kept as a negative result |

Tier A and tier C rows are never summed. Native-contract rows are never averaged
with contract rows. `results.json` carries an eligibility cell per
`(tier, policy)` pair for exactly this reason.

## The measurement protocol in one paragraph

Every timed row uses a **randomized paired** design: for each repetition both
arms run once in random order, from the same pre-state (declared outputs are
removed first), and the confidence interval is computed on the per-pair ratio,
not on two independent samples. Cold tracing is sampled separately because it
needs an empty cache directory. Raw nanosecond samples are always written. A
cache HIT is counted only when TraceJIT itself reports `kind = "Reused"` for that
invocation. A `Reused` decision whose independent oracle observation differs
from a native twin is an **incorrect hit** and fails the run.

## The correctness oracle

`oracle.py` imports nothing from TraceJIT. It fingerprints the whole workspace —
paths, types, file contents, permission bits, symlink targets, hard-link
grouping — plus exit status, stdout and stderr, and compares a traced execution
against a native execution in a byte-identical twin directory. Timestamps,
inode numbers and ownership are recorded separately as *out-of-contract*
observations: they are reported, never counted as a pass or a failure.

## Cache-state transitions

Qualification exercises, for every workload: clean native run, cold trace, first
warm reuse, input mutation, immediate retry, input restored to its earlier
state, cache restart, removal of a stored CAS object, output corruption, and
reuse after that corruption. Every decision is recorded verbatim in the row's
`decisions` array. Repeated HITs are the timed warm arm.

## Reproducing it yourself

Requirements: Linux x86_64, `ptrace` permitted, Rust 1.85+, `gcc`, `make`,
`python3` 3.11+, and the usual coreutils plus `gzip`, `bzip2`, `xz`, `tar`,
`zip`, `unzip`, `jq`, `perl`, `node`. Optional: `hyperfine` for the independent
wall-clock cross-check and a ccache binary for `competitive_zlib.py`.
`ccache`, `sccache`, `ninja`, `firebuild`, `perf`, `zstd`, `clang-tidy`,
`cppcheck`, `shellcheck`, `ruff` are recorded as unavailable when absent;
absence is not a result about TraceJIT.

The harness is re-runnable: scratch roots, cache directories and the preserved
counterexample audit use unique temporary paths, and `test_harness.py` (29 tests)
asserts the oracle rejects wrong replays and the accounting rejects tampered rows.
`competitive_zlib.py` measures one compile under native, ccache and TraceJIT with
the same command, mixed order and byte-verified objects.

```bash
cargo build --workspace --release
python3 benchmarks/realworld_v2/fetch_inputs.py --vendor /tmp/tracejit-realworld-v2/vendor
python3 benchmarks/realworld_v2/runner.py --tracejit target/release/tracejit \
    --mode both --policies native,compiler-runtime-v1 --splits dev \
    --output-dir /tmp/aa-dev
python3 benchmarks/realworld_v2/validate.py /tmp/aa-dev/results.json
```

The zlib input is pinned by SHA-256 in `corpus.py`
(`9a93b2b7…`); `fetch_inputs.py` refuses a mismatched archive. Everything else is
generated deterministically by `corpus.py`.

## Expected outcomes and unsupported environments

* A workload whose tool is missing is `tool_unavailable`; the run continues.
* A workload TraceJIT refuses is `refused`, with the refusal reasons and a
  categorised blocker count. This is a result.
* If TraceJIT reports a workload eligible but no hit is obtained, the row says
  `eligible_but_no_hit` and the harness exits non-zero only if the observation
  was *wrong*, not because the hit was absent.
* On macOS, AArch64, musl, or with `ptrace` denied, `tracejit doctor` refuses and
  this package has nothing to measure. It does not degrade silently.
* `results.json` without a 40-hex commit or a 64-hex binary digest fails
  `validate.py`; results from different commits must not be compared.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `missing pinned upstream source` | run `fetch_inputs.py`, or pass `--vendor` |
| every row `tool_unavailable` | `PATH` is missing the toolchain |
| `validate.py` complains about a missing eligibility cell | partial run with `--policies`/`--workloads`; that partial result must not be committed as a full one |
| warm hits are slower than native on 5 ms commands | expected; TraceJIT has a fixed hit cost and this package reports it |
| `perf` counters absent | `perf` is not installed on this image; the field says so |

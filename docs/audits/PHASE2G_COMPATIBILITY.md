# Phase 2G: compatibility, performance and adoption

Both fixed suites keep their denominators: 16 direct-command workloads and the nine-workload
census. Native and controlled modes are reported separately. Every number below came from this host
in the runs named; raw samples are in `benchmarks/results/phase2g/`.

## Compatibility

| Suite | Mode | Session A | Session B | Output equivalence |
| --- | --- | --- | --- | --- |
| Direct, 16 workloads | native | **1/16** (`gzip`) | **1/16** (`gzip`) | 16/16 |
| Direct, 16 workloads | `allocator-entropy-v1` | **7/16** | **6/16** | 16/16 |
| Census, 9 workloads | native | **0/9** | **0/9** | 9/9 |
| Census, 9 workloads | `allocator-entropy-v1` | **0/9** | **0/9** | 9/9 |

Controlled-mode reusable set, session A: `gzip`, `bzip2`, `sed`, `tr`, `base64`, `md5sum`, `wc`.
Session B: the same minus `tr`. `tr`'s stdin read updates `atime`, which is part of the remembered
stdin identity, so the second run is a miss rather than a guard failure. That is a reach limitation
(and the reason the result is reported as 6–7, not 7).

Census blockers did not move: 4 workloads still read the clock, 4 read randomness (CPython, `jq`,
`sort`, `strip`), 3 read process identity, 1 reads `/proc/self/maps`, and one pipe transfer is
packetisation-dependent. The census invokes workloads through `sh -c`, so the shell's own effects
are part of those measurements; the contract does not and cannot absorb them.

Refusals that matter for adoption:

- `sort`: `sched_getaffinity`, `prlimit64`, `sysinfo` — system information, not randomness.
- `tar`: realtime clock and a failed socket-control probe.
- `jq`, `strip`, `python-json`: application/randomness and identity.
- `gcc`/`as`: unmodelled `getrusage` (syscall 98), unchanged from Phase 2C/2D.
- `grep`: `/proc/self/maps`.

## Performance

Direct suite, 5 timing runs per reusable workload. `cached` is the whole TraceJIT process; `cold` is
the tracing run (no JSON in timing runs).

| Workload | Session | Direct ms | Cached ms | Cold ms | Speedup | Hits to repay | p95 direct/cached |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `gzip` | A native | 28.98 | 4.42 | 44.69 | 6.56x | 0.64 | 30.70 / 7.47 |
| `gzip` | A controlled | 28.61 | 3.87 | 47.36 | 7.39x | 0.76 | 30.47 / 6.78 |
| `gzip` | B controlled | 28.66 | 3.88 | 40.56 | 7.39x | 0.48 | 28.94 / 7.03 |
| `bzip2` | A controlled | 17.55 | 4.28 | 34.40 | 4.10x | 1.27 | 17.73 / 6.93 |
| `bzip2` | B controlled | 17.62 | 4.34 | 34.63 | 4.06x | 1.28 | 17.69 / 7.06 |
| `sed` | A controlled | 3.59 | 5.19 | 22.53 | 0.69x | — | 3.66 / 7.95 |
| `tr` | A controlled | 1.13 | 4.51 | 17.13 | 0.25x | — | 1.19 / 6.86 |
| `base64` | A controlled | 1.52 | 5.10 | 18.00 | 0.30x | — | 1.74 / 7.68 |
| `md5sum` | A controlled | 1.74 | 5.74 | 17.86 | 0.30x | — | 1.78 / 8.60 |
| `wc` | A controlled | 2.85 | 4.08 | 13.50 | 0.21x | — | 0.86 / 6.26 |

The hit path costs about 4–6 ms (startup, identity, SQLite lookup, guards, CAS restore). Any command
whose native runtime is below that is **slower** cached. Positive savings require real work: `gzip`
and `bzip2` pay back in under one and a little over one hit respectively; the small filters do not.

### The controlled runtime's own overhead

Tracing under the contract adds a ptrace stop per syscall plus the entropy interception. Measured
cold vs direct: `sed` 22.53 vs 3.59 ms, `tr` 17.13 vs 1.13, `base64` 18.00 vs 1.52, `wc` 13.50 vs
2.85, `gzip` 47.36 vs 28.61. The intercept itself is a few microseconds; the dominant cost is the
tracer and the 13–23 ms startup path, not the contract.

### Ordinary developer workflow

`benchmarks/realworld/workflow.py`, 5.416 MB input, four sequential commands (`sed`, `wc -c`,
`md5sum`, `gzip -9 -c`), 5 measured repetitions after priming:

- direct total median **645.62 ms** (samples 645.62, 646.05, 651.17, 641.68, 643.50)
- cached total median **43.80 ms** (samples 43.66, 49.01, 42.89, 47.06, 43.80)
- **14.74x**, about 602 ms saved per iteration
- per step (direct / cached): sed 51.41 / 18.91, wc 1.01 / 7.11, md5sum 10.27 / 8.45,
  gzip 582.51 / 8.95

This is the adoption case: a workflow with one expensive stage hides the fixed hit cost of the cheap
ones. It is also why isolated-subcommand hit rates are a misleading target.

## Contract differential validation

`benchmarks/realworld/contract_check.py`, `sed`/`tr`/`base64`/`wc`, three independent native runs
per tool:

- 4/4 reusable under the contract, 4/4 fully verified;
- every first and reused run matched the native bytes;
- input change never reused and returned the new bytes;
- environment change missed;
- native invocation never reused a controlled entry.

## Costs and limitations

- Small commands (below ~6 ms native) lose on a hit; the cache is not a win for them.
- `tr`'s stdin-atime identity can turn a hit into a miss across sessions.
- The contract covers only allocator-internal entropy; `sort`, `tar`, `gzip -d`, Python, `jq`,
  compilers and anything network-facing remain refused.
- No comparison with ccache/sccache/Firebuild is possible on this host; those tools are absent.

## Reproduce

```bash
cargo build --release -p tracejit-cli
python3 benchmarks/realworld/direct_suite.py --runs 5 --output-dir benchmarks/results/phase2g/direct-native-a
python3 benchmarks/realworld/direct_suite.py --runs 5 --contract allocator-entropy-v1 --output-dir benchmarks/results/phase2g/direct-controlled-a
python3 benchmarks/realworld/census.py --runs 3 --warmups 1 --output-dir benchmarks/results/phase2g/census-native-a
python3 benchmarks/realworld/census.py --runs 3 --warmups 1 --contract allocator-entropy-v1 --output-dir benchmarks/results/phase2g/census-controlled-a
python3 benchmarks/realworld/contract_check.py --output-dir benchmarks/results/phase2g/contract
python3 benchmarks/realworld/workflow.py --reps 5 --output-dir benchmarks/results/phase2g/workflow
```

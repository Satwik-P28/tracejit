# Reproducing the release benchmarks

Every number in `benchmarks/releases/v<version>/` was produced by this
repository's scripts on the host recorded in `results.json`. No number is
hand-edited, and no table mixes results from different commits.

## Requirements

- Linux x86_64, `ptrace` allowed (`tracejit doctor` prints `ptrace yes`).
- Rust stable (1.85+), `cc`, `python3` 3.11+, `gzip`.
- `make` for the competitive comparison; `ninja` is optional and recorded as
  missing rather than scored as a loss.
- Write access to the repository (workloads write inside it, then restore).

## Full package

```bash
cargo build --workspace --release
python3 benchmarks/releases/run_release.py --runs 20 --warmups 3
```

Writes into `benchmarks/releases/v<version>/`:

| File | Contents |
| --- | --- |
| `results.json` | Every raw sample, medians, p95, bootstrap 95% CI, environment |
| `RESULTS.md` | Human-readable tables, scenario notes and refusals |
| `census/` | Unmodified real-world command census |
| `competitive/` | Make/Ninja/CAS comparison |
| `*.log` | Exact command line, exit status, stdout/stderr of delegated harnesses |

`--runs`, `--warmups`, `--tracejit`, `--release-dir` and `--skip-delegated`
change only scale and location, never methodology.

## Scenarios

| Scenario | Kind | What it measures |
| --- | --- | --- |
| `cpu_transform` | synthetic | 250M-round C transform: direct, cold trace, warm hit |
| `short_command` | synthetic | `/bin/true`: the fixed cost of a warm hit |
| `compression` | controlled | `gzip -9 -n -c` over a deterministic 4 MiB file |
| `etl_session` | controlled | 10 sequential ETL runs, direct vs one trace + nine hits |
| `large_restore` | synthetic | 64 MiB output; restore cost and output hash check |
| `cache_invalidation` | controlled | mutated input must `Deoptimized`, never `Reused` |
| `concurrency` | controlled | 8 simultaneous runs sharing one cache, cold and warm |
| `compatibility_census` | real-world | Third-party commands under default policy |
| `make_ninja_competitive` | real-world | Identical-rerun and edit-recovery versus Make/Ninja |

Each timed sample is wall-clock process time. Cold samples always use a fresh
cache directory. Warm samples must report `kind=Reused`; a sample that does not
aborts the run instead of being recorded as a fast hit.

## Environment controls

The runner sets `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`,
`MALLOC_ARENA_MAX=1`, `PYTHONHASHSEED=0` and `PYTHONDONTWRITEBYTECODE=1`. These
stop glibc and CPython from drawing entropy or querying CPU count during
startup. They are workload settings, not classifier exceptions.

Not controlled: CPU frequency scaling, neighbouring VM activity, page-cache
state. That is why every table publishes raw samples and a bootstrap interval
rather than a single median.

## Rebuilding the binary

```bash
cargo build --workspace --release
sha256sum target/release/tracejit
```

Compare against `build.binary_sha256` in the release manifest. Byte-for-byte
rebuild equality is **not** claimed: this project has not independently
demonstrated it.

## Re-running one scenario

All scenarios are plain Python functions in
`benchmarks/releases/run_release.py`, and the underlying harnesses stay usable
on their own:

```bash
python3 benchmarks/harness/benchmark.py --runs 30 --warmups 5
python3 benchmarks/realworld/census.py --runs 3 --warmups 1
python3 benchmarks/repos/phase_k8_competitive.py --runs 8 --warmups 3
./scripts/demo.sh
```

## Honest reporting

Numbers from different commits are never merged into one comparison. Warm
losses, refusals and weak eligibility are kept in the package. A refusal is not
a zero; it means TraceJIT declined to reuse.

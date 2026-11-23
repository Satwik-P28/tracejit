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

---

# Phase AA: real-world corpus (`benchmarks/realworld_v2/`)

This is the maintained benchmark. It does not use the `GLIBC_TUNABLES`/"controlled"
settings above for its native arm: the native tier runs the command exactly as a
user would, and the allocator contract is a separate, labelled policy.

## Requirements

- Linux x86_64 with `ptrace` allowed (`tracejit doctor` prints `ptrace yes`).
- Rust stable, `cc`, `make`, `python3` 3.11+, `gzip`, `bzip2`, `xz`, `tar`,
  `zip`/`unzip`, `jq`, `groff`, `readelf`/`objdump`/`nm` (binutils).
- Network access **once**, to fetch the pinned inputs (`zlib-1.3.1` and the
  corpus data). Their SHA-256 values are checked; a mismatch aborts.
- ~2 GiB free in the scratch directory, and no root.
- Optional: `hyperfine` for the independent wall-clock cross-check. Absent is
  reported, not failed.

Missing optional tools (`clang`, `clang-tidy`, `cppcheck`, `shellcheck`, `ruff`,
`zstd`, `pyarrow`) never fail the run: their workloads are recorded
`tool_unavailable` and stay in the report.

## One command

```bash
./benchmarks/realworld_v2/run.sh                 # full: 3 splits, 3 policies, ~30 min
AA_MODE=smoke ./benchmarks/realworld_v2/run.sh   # PR smoke: dev split, 2 policies, ~5 min
```

Environment knobs (all optional): `AA_TRACEJIT`, `AA_OUTPUT`, `AA_SCRATCH`,
`AA_VENDOR`, `AA_SKIP_BUILD=1`, `AA_COMPETITIVE_REPEATS`.

Writes into `benchmarks/results/phaseaa/`:

| File | Contents |
| --- | --- |
| `results.json` | Schema `tracejit.realworld.results/v1`: every raw sample, medians, bootstrap CIs, decisions, oracle results, fingerprint |
| `results.md` | Human-readable tables, including every refusal and unavailable tool |
| `raw/<workload>__<policy>.json` | One row per workload × policy, so a single workload can be checked alone |
| `adversarial.json` | Preserved counterexamples, mutation scenarios, race probe |
| `competitive.json`, `competitive.md` | Scheduler/cache comparison, hyperfine cross-check, tool availability |
| `environment.json`, `TRACEJIT_SHA256.txt` | Fingerprint and binary digest |

## What a correct run looks like

- `validate.py` prints `OK: … satisfies tracejit.realworld.results/v1`. A
  validation failure, a rate that does not equal reused/attempted, or a `Reused`
  decision whose oracle observation differs from native **fails the run**.
- `incorrect_hits` is empty.
- On a 2-vCPU VM of this class: 1/49 strict-native eligible, 10/49 under
  `allocator-entropy-v1`, 17/49 under `compiler-runtime-v1`, 0/5 adapted
  workloads. Different hardware changes the timings, not these counts, unless a
  tool version differs.
- Tier-C (interpreter) workloads refuse under every policy. That is expected, not
  a harness bug.

## Phase AA fresh-checkout check

The point of the exercise: someone who did not write this project, starting from
a clean clone and an empty cache.

```bash
git clone https://github.com/Satwik-P28/tracejit && cd tracejit
git checkout research/phase-aa            # or main after merge
cargo build --workspace --release
mkdir -p /tmp/fresh-home
HOME=/tmp/fresh-home AA_MODE=smoke \
  AA_SCRATCH=/tmp/fresh-scratch AA_OUTPUT=/tmp/fresh-out \
  ./benchmarks/realworld_v2/run.sh
```

`HOME` is pointed at an empty directory so no user-level cache, cargo config or
`$HOME/.tracejit` state can be inherited. `AA_SCRATCH` and `AA_OUTPUT` are new
directories. Result: see below.

## Unsupported environments

| Environment | Outcome |
| --- | --- |
| macOS / Windows | Refused. The harness requires Linux `ptrace`; the product does not support these platforms. |
| Kernel without `ptrace` permission (e.g. some hardened containers) | `tracejit doctor` fails, the runner aborts before measuring anything rather than reporting zeros. |
| No network, cold vendor directory | `fetch_inputs.py` fails loudly with the missing SHA-256; nothing is substituted. |
| `python3` < 3.11 | Harness will not run (uses `tomllib`-era syntax and `Path.is_relative_to`). |
| Run as root | Works, but results are not comparable to the recorded fingerprint. |

## Troubleshooting

- `missing TraceJIT binary` — build first, or set `AA_TRACEJIT=/path/to/tracejit`.
- A workload reports `other_failure` — read `raw/<id>__<policy>.json` →
  `error`; the run keeps going and the row stays in the report.
- Timings look 2× slower than the committed ones — check for a noisy neighbour or
  CPU throttling: the same warm hit measured 42 ms quiet and 74–80 ms under load
  on the reference host. The ratios are more stable than the absolutes.
- Zero HITs anywhere — `TRACEJIT_CACHE_DIR` must be stable across invocations;
  moving it invalidates every record.

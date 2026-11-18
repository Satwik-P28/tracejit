# Phase U evidence (`development/v0.3`)

Every file here was produced by the two censuses in `benchmarks/realworld/` on
the host described in `docs/PHASE_U_REPORT.md` §8. Nothing was edited by hand;
`census.json` is the raw record and `census.md` is its rendering.

## Provenance

| Directory | Binary | SHA-256 | Recorded commit |
| --- | --- | --- | --- |
| `baseline/`, `baseline/contract/`, `baseline/heldout-*` | `v0.2.0-beta.1` build | `5a1100c5fd92dd7f2593451932d1ba93a2bd1f83d8681bb18861a4bc246db990` | `e107bb8` (tag `v0.2.0-beta.1` tree) |
| `census-native/`, `census-contract/`, `heldout-*` | `development/v0.3` build | `8ca8d76dfa80b4d9d7ddb9fbb8958b97613e27062bc8e9c622d396b32a290734` | `b975232` |
| `contract-timed/` | `development/v0.3` build | same as above | `b975232` |

The baseline binary hash equals the one recorded for the packaged
`v0.2.0-beta.1` artifact in `benchmarks/releases/v0.2.0-beta.1/artifacts`, so the
baseline is the shipped binary, not a re-build with different flags.

Each `census.json` records the commit of the working tree it ran in. The candidate
runs happened with the branch worktree still dirty (the doc and evidence commits
came afterwards); the shipped binary hash above is the exact one measured, and
later commits touch only documentation, tests and this evidence directory.

## Layout

| Path | Corpus | Configuration |
| --- | --- | --- |
| `census-native/` | original 32 workloads | native defaults |
| `census-contract/` | original 32 workloads | `--contract allocator-entropy-v1` |
| `heldout-native/` | held-out 20 workloads | native defaults |
| `heldout-contract/` | held-out 20 workloads | `--contract allocator-entropy-v1` |
| `contract-timed/` | original 32 workloads | contract, 5 measured runs + 1 warmup |
| `baseline/` | original 32 | the four configurations above on the beta binary |

Eligibility runs use one measured run and no warmup, which is sufficient for a
classification decision and keeps the two corpora cheap to reproduce. The
`contract-timed/` directory exists only for the latency table in the report and is
the only run with repeated samples.

## Headline counts

| Directory | Attempted | Reused | Blocked (missing tool) |
| --- | ---: | ---: | ---: |
| `census-native/` | 31 | 1 | 1 (`clang`) |
| `census-contract/` | 31 | 7 | 1 (`clang`) |
| `heldout-native/` | 20 | 0 | 0 |
| `heldout-contract/` | 20 | 8 | 0 |
| `baseline/census.json` | 31 | 1 | 1 |
| `baseline/contract/` | 31 | 7 | 1 |
| `baseline/heldout-native/` | 20 | 0 | 0 |
| `baseline/heldout-contract/` | 20 | 6 | 0 |

No run recorded an output-equivalence failure (`FAIL`) or an unexpected prime
result. The three `reuse_was_not_obtained` entries (`objcopy` in
`census-contract/`, `strip` and `unzip` in `heldout-contract/`) deoptimize on the
second run; `docs/COMPATIBILITY_V03.md` §6 gives the failing guard and the reason
it is sound.

## Reproduction

```bash
cargo build --workspace --release
python3 benchmarks/realworld/census.py    --tracejit target/release/tracejit --output-dir /tmp/census
python3 benchmarks/realworld/census.py    --tracejit target/release/tracejit --contract allocator-entropy-v1 --output-dir /tmp/census-contract
python3 benchmarks/realworld/census_v03.py --tracejit target/release/tracejit --output-dir /tmp/heldout
python3 benchmarks/realworld/census_v03.py --tracejit target/release/tracejit --contract allocator-entropy-v1 --output-dir /tmp/heldout-contract
```

For the baseline, check out `v0.2.0-beta.1` in a separate worktree and point
`--tracejit` at that build. `clang` is absent on the measurement host, so
`clang-compile-large` is reported as blocked there and excluded from the rate.

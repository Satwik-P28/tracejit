# TraceJIT Experiment Register

All results are tied to the local workspace and binary hashes below. They are not hosted-CI results.

## Environment

- Linux x86_64, kernel 6.1.102, 8 vCPU.
- Rust stable toolchain from `rust-toolchain.toml`.
- No Landlock; seccomp available. `PROVEN` is therefore unavailable locally.

## E-3A-01 — A/B/A alternate-candidate reuse

**Question:** Does retaining more than one guarded record let a return to an earlier input reuse without
retracing?

**Fixture:** `tests/fixtures/fixture_driver.c`, mode `plain_file_read`. It copies `input.txt` to
`output.txt`; the path and content are guards, not part of the lookup key.

**Sequence:** input one -> input two -> input one, in a fresh workspace and cache per session.

**Arms:**

- Current release: `79ee6501d7b09e8e0f4c02cb4cc32e0f4243b7525377f596e40c550cfafc084c`
- Pre-change release from `a11ae4b`: `3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`

**Command:**

```bash
python3 benchmarks/repos/candidate_reuse.py \
  --binary target/release/tracejit \
  --baseline .baseline/target/release/tracejit \
  --sessions 5 \
  --output benchmarks/results/phase3a/candidate-reuse.json
```

**Result (5 sessions):**

| Arm | Third-run decision | Median wall | Median report runtime | Correct bytes |
| --- | --- | ---: | ---: | --- |
| Current | `Reused` 5/5 | 13.841662 ms | 3,854,780 ns | yes |
| Pre-change | `Executed` 5/5 | 20.572657 ms | 5,258,884 ns | yes |

**Interpretation:** The candidate index changes the decision on this specific sequence and avoids a
retrace. The wall-time difference is a single small-command measurement, not a general speedup claim.

**Raw:** `benchmarks/results/phase3a/candidate-reuse.json`.

## E-3A-02 — Schema migration

**Question:** Can a v1 cache with `lookup_key` as a primary key be migrated without dropping its record?

**Test:** `crates/tracejit-cache/src/lib.rs::tests::v1_cache_is_migrated_without_losing_its_record`.

**Result:** `user_version` becomes 2; the legacy row survives; two rows with the same lookup key can be
inserted afterwards. Pass.

## E-3A-03 — Workspace and Linux integration gates

**Commands:**

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture --test-threads=1
```

**Result:** fmt pass; Clippy pass; 128 workspace tests pass; 42 Linux integration tests pass. The
`proven-reuse` integration test reports `SKIP` because Landlock is unavailable.

## E-3A-04 — Candidate bound

**Question:** Is eight the right retention bound?

**Status:** not measured. Eight is a conservative implementation bound, not an optimum. The next
experiment should measure lookup, decode, and guard-validation cost for 1, 2, 4, 8, and 16 candidates.

## E-3A-05 — Corrupt stream before output mutation

**Question:** Can a corrupt stdout/stderr object be detected before any workspace mutation?

**Status:** implemented ordering, but not isolated by a dedicated transient-state test. Existing
corruption tests prove that corrupt objects are not served and the command retraces; a new regression
should use a workspace state that would expose the old restore-then-fail order.

## Retained negative result — Phase 2T incremental comparison

The prior comparison remains authoritative for the claim boundary. Three sessions, 2.8 MB × 3 assets:

| Scenario | TraceJIT | Make | Ninja | Content cache |
| --- | ---: | ---: | ---: | ---: |
| Identical rerun | 678.59 ms | 2.63 ms | 2.82 ms | 60.22 ms |
| Five sessions | 2445.11 ms | 800.41 ms | 835.88 ms | 1071.34 ms |

Raw: `benchmarks/results/phase2t/incremental.json`. The result is a valid negative for whole-workflow
speed. Do not overwrite it with a more favorable definition.

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

## E-3B-01 — bzip2 transition and stable rerun

**Question:** Why did all three Phase 2T commands deoptimize on the identical rerun?

**Fixture:** three 2.8 MB assets compressed with `bzip2 -9 -k -f`; absent-output build, present-output
transition, stable third run, deleted outputs, edited input.

**Arms:** current `5c829977a78bff07b4905a7c575e16b9c805c3d0e97041991717f5f0422c2db4`; pre-Phase-3A
`3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`.

**Result:** transition is a `FileMetadata` failure on the command's own `.bz2` output. Current
833.464 / 793.821 / 231.120 / 261.146 / 474.566 ms; old 809.446 / 811.263 / 242.411 / 807.075 /
831.204 ms. The invalidation is necessary; stable reruns reuse.

**Raw:** `benchmarks/results/phase3b/identical-rerun-current.json`, `...-old.json`.

## E-3B-02 — candidate scaling

**Question:** What does retaining 1–32 candidates cost, and does newest-first remain viable?

**Result:** 1 candidate 9.133 ms, 8 17.726 ms, 32 41.087 ms for the oldest target; worst-case miss
13.943–41.655 ms; SQLite query 0.24–2.07 ms; decode 0.22–4.87 ms; guard validation ~0.94–1.07 ms.
Eviction with 16 states and bound 8 retained 8. Eight concurrent read-only readers all reused.
The default stays 8; no unsound ranking shortcut was added.

**Raw:** `benchmarks/results/phase3b/candidate-scaling.json`.

## E-3B-03 — corrupt stream before output mutation

**Question:** Can a corrupt stream object be rejected before any output restoration?

**Result:** `corrupt_stream_is_rejected_before_output_restoration` passes for both stdout and stderr
using fixtures that branch on output presence. The output remains `ABSENT\n` after the corrupt hit
and the retrace emits the correct stream.

## E-3B-04 — strict dependency hashing

**Result:** guard validation 1.130 ms at 1 KiB, 9.886 ms at 16 MiB, 99.400 ms at 256 MiB; about
2575 MiB/s at the largest size. No fs-verity or fanotify implementation was added.

**Raw:** `benchmarks/results/phase3b/hash-profile.json`.

## E-3B-05 — native compatibility census

**Result:** 9 attempted, 0 reused, 9 refused; `clock` and `randomness` each block 2; `lseek` blocks
3 and is the narrowest next candidate. Raw: `benchmarks/results/phase3b/census-native/`.

## E-3B-06 — old/current Phase 2T one-session check

**Result:** current 643.52 / 603.29 / 54.87 / 2171.11 ms for cold, transition, deleted outputs and
five sessions; old 611.64 / 615.12 / 610.16 / 2470.50 ms. One session, not a replacement for the
three-session historical table. Raw: `benchmarks/results/phase3b/phase2t-current-1session.json` and
`...-old-1session.json`.


## E-3C-01 — stable-workflow latency attribution

**Question:** What is actually spent in the three-asset bzip2 stable rerun?

**Result:** the Phase 3B 231 ms figure included 165-215 ms of post-command bzip2 output
decompression. The replay command loop is in the tens of milliseconds: 46.5-106.8 ms across two
sessions, with 15.4-31.6 ms per command. Dominant phases are process startup (6.3-6.9 ms), guard
validation (5.9-6.2 ms), and CAS restore (3.4-21.9 ms, writeback dependent). Shell-batch workflow
was 45.0-57.7 ms; there is no in-process batch mode.

**Raw:** `benchmarks/results/phase3c/latency.json`.

## E-3C-02 — repeated 1-64 candidate scaling and lazy decode

**Result:** three fresh-cache sessions per bound. Newest-hit medians were 11.5, 12.6, 11.3, 12.2,
12.3, 13.5 and 14.5 ms for 1, 2, 4, 8, 16, 32 and 64 candidates. Oldest-target medians were 6.3,
12.2, 14.6, 21.0, 25.1, 42.3 and 82.2 ms; misses were 16.8-77.2 ms. At 64, an oldest hit is more
expensive than a miss. Lazy `CandidateBytes` decoding is used in the `always` path; full guards
remain mandatory and non-always admission still decodes the full set.

**Raw:** `benchmarks/results/phase3c/candidate-scaling.json`.

## E-3C-03 — `/dev/null` inherited seek

**Result:** exact-path `/dev/null` `lseek` is constant-zero and now admitted; arbitrary inherited
character devices and directory seeks remain refused. `dev_null_seek_is_reusable` passes. Census
remains 9 attempted, 0 reused, 9 refused; `lseek` is no longer in the unmodeled ranking.

**Raw:** `benchmarks/results/phase3c/census-native/`.

## E-3C-04 — output restoration unchanged-file branch

**Result:** not implemented. Restore is 3.4 ms in the clean session and 21.9 ms under a writeback
tail. Skipping a matching output would change inode/ctime/ownership and hard-link semantics; a
managed contract and crash journal are prerequisites.


## E-3D-01 — Descriptor identity for inherited `/dev/null`

**Question:** Does the seek guard identify the actual open device rather than a pathname that can be
substituted?

**Test:** `linux::phase3d_tests::null_device_identity_is_not_path_only` stats a real `/dev/null` fd
and a regular-file fd through `/proc/<pid>/fd`. It requires a character device with major/minor 1:3.
`dev_null_seek_is_reusable` and `regular_file_stdin_seek_is_reused_as_an_offset_stream` cover the
end-to-end paths.

**Result:** real null accepted; regular descriptor rejected; regular stdin uses the tracked offset
stream and remains safe. A true bind-mount substitution was not run without mount privileges, and
that limitation is explicit.

## E-3D-02 — ID-first incremental candidate retrieval

**Question:** Does fetching only ordered IDs and one record per validation step reduce oldest-target
cost?

**Method:** same three fresh-cache sessions and 1-64 bounds as Phase 3C; three sessions for the new
code.

**Result:** newest hits improved 0.6-3.4 ms, but oldest-target hits were worse at four of seven
bounds (64: 80.397 ms versus 82.210 ms). The hypothesis of a general performance win is **rejected**.
The retrieval is genuinely incremental and full guards remain; the default bound stays 8.

**Raw:** `benchmarks/results/phase3d/candidate-retrieval.json`.

## E-3D-03 — Native census after descriptor correction

**Result:** **9 attempted, 0 reused, 9 refused, 0 execution failures**. `lseek` is gone from the
unmodeled ranking. Blockers: `getrusage` (both C builds), pipe `fstat`/scheduling and `TCGETS`
(shell/groff), clock/randomness/PID (Python/awk), `epoll_create1` (Pillow), and unrestorable output
(cc lint). Raw: `benchmarks/results/phase3d/census-native/`.

## E-3D-04 — Complete-session hit/miss/refusal

**Method:** three fresh-cache sessions; prime a guarded copy, rerun unchanged, change the input,
then run a randomness workload.

**Result:** prime 19.04 ms `Executed`; hit 8.57 ms `Reused`; invalidation 16.69 ms `Executed`;
randomness 11.05 ms `Executed`, classification `Nondeterministic`, never reused. Outputs were correct
in all three sessions. Raw: `benchmarks/results/phase3d/complete-session.json`.

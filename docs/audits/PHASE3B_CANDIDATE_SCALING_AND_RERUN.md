# Phase 3B: Candidate Scaling, Rerun Invalidation, and Validation Cost

Base: `58c39a7927e6d25b9f9cdde711f29d7f3b9fbf5d`. Work is on a review branch; the final hosted
run and PR are not claimed by this document until they exist.

## 1. Identical-rerun root cause

The Phase 2T finding reproduces on the current implementation. The workload is three 2.8 MB
JavaScript assets compressed with `bzip2 -9 -k -f`. On the first build the `.bz2` outputs are absent.
The next invocation is the transition to present outputs.

Recorded result for the current binary
(`5c829977a78bff07b4905a7c575e16b9c805c3d0e97041991717f5f0422c2db4`):

| Round | Wall | Decisions | Correct |
| --- | ---: | --- | --- |
| First build, outputs absent | 833.464 ms | Executed ×3 | yes |
| Identical rerun, output transition | 793.821 ms | Deoptimized ×3 | yes |
| Identical rerun, stable | 231.120 ms | Reused ×3 | yes |
| Outputs deleted | 261.146 ms | Reused ×3 | yes |
| One input modified | 474.566 ms | Deoptimized, Reused, Reused | yes |

The same sequence on the pre-Phase-3A binary
(`3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`):

| Round | Wall | Decisions |
| --- | ---: | --- |
| First build, outputs absent | 809.446 ms | Executed ×3 |
| Identical rerun, output transition | 811.263 ms | Deoptimized ×3 |
| Identical rerun, stable | 242.411 ms | Reused ×3 |
| Outputs deleted | 807.075 ms | Deoptimized ×3 |
| One input modified | 831.204 ms | Deoptimized ×3 |

Raw data: `benchmarks/results/phase3b/identical-rerun-current.json` and
`benchmarks/results/phase3b/identical-rerun-old.json`.

### Exact guard

Every transition failure is a `FileMetadata` guard whose path is the command's own `.bz2` output,
for example:

```text
path: /tmp/tracejit-phase3b-rerun/work/assets/worker.js.bz2
expected: FileFingerprint { device: u64::MAX, inode: u64::MAX, ... } // absent sentinel
actual:   FileFingerprint { device: 65024, inode: ..., size: 377233, ... }
reason:   metadata changed; no content hash was recorded
```

`bzip2` calls `stat` on the destination before opening it with `O_CREAT|O_WRONLY`. The first trace
therefore records a negative metadata dependency. On the next run the destination exists, so the
guard fails. The cache retraces and records a present-output candidate; the third run reuses it.

### Why this is necessary, not a conservative bug

A program can branch on whether its output exists and write different bytes. The existing regression
`un_audited_program_does_not_reuse_across_its_output_presence_change` verifies exactly that case.
Converting the observation to `OutputPrestate::AbsentOrWritableFile` for arbitrary programs would
make that test unsound. No guard was weakened to manufacture a transition hit.

The transition is one-time per output state, not permanent: the stable rerun is 231.120 ms with all
three commands reused. The multi-candidate index also recovers the deleted-output state: current is
261.146 ms versus 807.075 ms on the old binary. This is a real improvement in a later state, not a
claim that the first post-build rerun beats Make or Ninja.

### Minimal regression fixture

`tests/fixtures/fixture_driver.c` now has `output_presence_stdout` and `output_presence_stderr`.
They branch on output presence, write `PRESENT\n` or `ABSENT\n`, and emit a stream. The corruption
test below uses them.

## 2. Track A: candidate scaling

`benchmarks/repos/candidate_scaling.py` creates one distinct input state per retained candidate,
then targets the oldest state so every candidate is evaluated newest-first. One sample per bound on
this host; the raw timings are in `benchmarks/results/phase3b/candidate-scaling.json`.

| Bound | Retained | Target hit | Worst-case miss | SQLite query | Record decode | Guard validation | Cache bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 9.133 ms | 13.943 ms | 0.240 ms | 0.220 ms | 1.070 ms | 165,247 |
| 2 | 2 | 9.914 ms | 14.248 ms | 0.240 ms | 0.351 ms | 0.956 ms | 161,542 |
| 4 | 4 | 12.228 ms | 15.855 ms | 0.420 ms | 0.669 ms | 0.958 ms | 303,334 |
| 8 | 8 | 17.726 ms | 20.538 ms | 0.592 ms | 1.256 ms | 0.935 ms | 475,619 |
| 16 | 16 | 24.309 ms | 29.178 ms | 0.982 ms | 2.412 ms | 0.978 ms | 824,626 |
| 32 | 32 | 41.087 ms | 41.655 ms | 2.071 ms | 4.873 ms | 0.980 ms | 1,518,102 |

Guard validation stays near 1 ms because each fixture candidate hashes a small input state; SQLite
query and JSON decoding are the costs that grow. At 32 candidates the hit is effectively as
expensive as a miss. The default remains eight. `TRACEJIT_CANDIDATE_BOUND` is an experimental
benchmark knob, clamped to 1–32; it is not part of the command identity and invalid values keep 8.

Eviction: writing 16 distinct states with bound 8 retained exactly 8. The evicted state returned
`Deoptimized`; the surviving newest state returned `Reused`. Eight concurrent read-only readers
all reused after the harness stopped racing on a shared output file.

Candidate ordering remains newest-first and stops at the first passing candidate. No unverified
index or content shortcut was added. A dependency-signature index or cost-aware ordering is still a
hypothesis; the measurement shows record decode, not guard hashing, is the first scaling cost for
small inputs.

## 3. Track B: corrupt stream before output restoration

New regression: `corrupt_stream_is_rejected_before_output_restoration`. It runs both
`output_presence_stdout` and `output_presence_stderr`, records an absent-output execution, corrupts
the recorded stream object, removes the output, and reruns. A restore-first implementation would
restore `ABSENT`, discover the corrupt stream, retrace against `PRESENT`, and write the wrong bytes.
The test asserts:

- the run executes rather than reusing;
- the output remains `ABSENT\n`;
- the stream bytes match the direct execution;
- the recovery reason names corruption.

Result: `RESULT corrupt-stream-order PASS`.

## 4. Track C: strict dependency validation

`benchmarks/repos/hash_profile.py` measures the `plain_file_read` fixture from 1 KiB to 256 MiB.
Warm runs include metadata and BLAKE3 content validation plus output restoration.

| Input | Cold | Warm median | Guard validation | Hash throughput |
| ---: | ---: | ---: | ---: | ---: |
| 1 KiB | 18.025 ms | 7.777 ms | 1.130 ms | 0.86 MiB/s |
| 64 KiB | 22.633 ms | 9.125 ms | 1.244 ms | 50.26 MiB/s |
| 1 MiB | 52.436 ms | 11.640 ms | 1.524 ms | 656.32 MiB/s |
| 16 MiB | 628.097 ms | 109.299 ms | 9.886 ms | 1618.52 MiB/s |
| 64 MiB | 2433.226 ms | 361.462 ms | 27.973 ms | 2287.89 MiB/s |
| 256 MiB | 10184.423 ms | 1422.897 ms | 99.400 ms | 2575.45 MiB/s |

Raw: `benchmarks/results/phase3b/hash-profile.json`. At 256 MiB the guard phase is about 99 ms,
while the complete warm path is 1.42 s because the fixture copies the output as well. This is a
fixture measurement, not a general throughput claim.

Mechanisms considered:

1. **Metadata-assisted validation with full-content fallback.** Existing strict mode already does
   this for a safe metadata change, but an unchanged timestamp still requires the content hash.
   A metadata-only hit would be unsound for writable files.
2. **fs-verity or authenticated immutable storage.** This is the only mechanism with a precise
   digest trust boundary, but it requires filesystem and setup support and protects immutable files
   only. It was not prototyped because the measured workloads use ordinary writable inputs.
3. **fanotify/event-assisted invalidation.** Events can avoid rescanning, but lost events, queue
   overflow, mounts, renames, and watcher startup windows need explicit recovery. No watcher was
   added; an event-only design without a full-content fallback is not sound.

No cache format or trust claim changed. Content hashing remains the default.

## 5. Track D: research graph

`docs/research/RESEARCH_GRAPH.md` now records ccache/sccache manifests, Salsa/Adapton incremental
validation, Firebuild, fs-verity, fanotify/OverlayFS, and counterexample-guided refinement against
the measured outcomes. The negative and unverified branches are retained rather than dropped.

## 6. Track E: practical compatibility

Native census, 9 workloads, 3 runs, 1 warmup, no contract:
`benchmarks/results/phase3b/census-native/census.md`. All nine remain refused; the direct outputs
were all correct, so this is a compatibility boundary, not an execution failure.

| Rank | Blocker | Workloads | Value / difficulty / risk | Decision |
| ---: | --- | ---: | --- | --- |
| 1 | unmodeled `lseek` | 3 (Python/Pillow) | high / medium / medium | narrowest next candidate; regular-file seek state needs explicit replay tests |
| 2 | `fstat` on pipe descriptors | 2 | medium / high / high | do not model buffered pipe counts; scheduling-dependent |
| 3 | `getrusage` | 2 (compilers) | medium / medium / high | resource usage can steer compilation; no narrow proof yet |
| 4 | `unrestorable_output` | 1 (lint) | low / medium / low | syntax-only lint has no reusable artifact; not worth a restoration exception |
| 5 | `clock` / `randomness` | 2 each (awk/lint) | low / high / high | keep refused under native mode; no contract was requested |
| 6 | `process_identity` / `system_information` | 1 each | low / high / high | environment identity is already the narrower boundary |
| 7 | failed descriptor operation / short pipe read | 2 | low / high / high | keep refused; the short-read case is scheduling dependent |

The census contract run was also recorded but is not used for eligibility: it reports the contract
marker as a refusal and is not native equivalence.

## 7. Verification

- `cargo fmt --all -- --check`: pass.
- Clippy `--workspace --all-targets --all-features -- -D warnings`: pass.
- `cargo test --workspace`: pass.
- Linux integration: **43 passed**, 0 failed; `corrupt-stream-order PASS`; `PROVEN` tests SKIP
  locally because Landlock is unavailable.
- Release binary before the documentation commit:
  `5c829977a78bff07b4905a7c575e16b9c805c3d0e97041991717f5f0422c2db4`.
- Demo: pass.
- Hosted CI and PR: not claimed until observed.

## 8. Remaining work

1. Final fmt/Clippy pass and the review-branch commit.
2. Hosted CI on the review branch.
3. If the hosted result passes, open/merge through the normal PR path; do not force-push.
4. The first transition remains a deoptimization by design. Do not weaken output-presence guards
   without a new executable contract and an adversarial branch fixture.

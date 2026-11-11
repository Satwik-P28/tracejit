# Phase 3C: Latency Attribution, Lazy Candidates, and /dev/null Seek

Base: `df6cc86243972f7200be9dfb2cc4a3c52db9cf2b` (Phase 3B on `main`).
Branch: `phase3c/latency-candidates-lseek`.

## 1. The 231 ms stable-workflow number was not TraceJIT replay time

Phase 3B's `phase3b_identical_rerun.py` called `verify_output` after every command. That
verification opens and decompresses each 2.8 MB `.bz2` output. The round wall time therefore
included roughly 165-215 ms of bzip2 decompression even though every TraceJIT command reused.

`benchmarks/repos/phase3c_latency.py` separates the command loop from verification and records
each command's phase timings. Two clean repeated runs gave:

| Measurement | Run A | Run B |
| --- | ---: | ---: |
| Stable command median | 15.427 ms | 31.574 ms |
| Stable three-command workflow | 46.527 ms | 106.808 ms |
| Shell-batch three-command workflow | 57.659 ms | 44.950 ms |
| Command verification (excluded from workflow) | 165-215 ms/round | 165-215 ms/round |

The two runs differ mainly in `cas_restore_ns`, which is dominated by output writeback/fsync
variance on this host: 3.37 ms median in run A, 21.90 ms in run B. The reproducible conclusion is
that the 231 ms Phase 3B number was inflated by verification; the direct replay workflow is in the
tens of milliseconds, not hundreds. The absolute number remains noisy and is reported as a range.

Per-command phase medians in the clean run:

| Phase | Median |
| --- | ---: |
| Process startup | 6.86 ms |
| Guard validation | 6.24 ms |
| Output staging/restore | 3.37 ms |
| SQLite open/schema | 0.56 ms |
| Candidate query/decode | 1.42 ms |
| Cache prepare | 0.03 ms |
| Stdio replay | 0.03 ms |
| Decision persistence | 0.00 ms (already `Reused`) |

The shell batch can be slower than separate parent invocations because it adds shell work; it is
not a TraceJIT batch mode. More importantly, changing stdout from a pipe to a file changes the
execution identity and correctly produces a miss. The harness keeps pipes and uses the same
`TRACEJIT_PHASE_TIMING_PATH` for both arms.

## 2. Repeated candidate scaling, 1 through 64

`benchmarks/repos/phase3c_candidates.py` runs three independent fresh-cache sessions at each bound.
The target is the oldest retained input state, forcing newest-first evaluation of every candidate.
The "newest" row is the common stable hit. Medians in milliseconds:

| Bound | Newest hit | Oldest-target hit | Miss | Retained |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 11.489 | 6.304 | 16.755 | 1 |
| 2 | 12.558 | 12.181 | 16.600 | 2 |
| 4 | 11.327 | 14.605 | 20.035 | 4 |
| 8 | 12.195 | 20.979 | 20.014 | 8 |
| 16 | 12.289 | 25.057 | 34.874 | 16 |
| 32 | 13.465 | 42.281 | 46.372 | 32 |
| 64 | 14.520 | 82.210 | 77.210 | 64 |

At 64 candidates the worst retained hit (p95 88.0 ms) is more expensive than a miss. The default
bound remains 8. The experimental `TRACEJIT_CANDIDATE_BOUND` ceiling is now 64; it is not part of
the execution identity.

### Lazy candidate prototype

`Cache::find_candidates` now returns encoded `CandidateBytes` in newest-first SQL order instead of
decoding every record up front. `tracejit-core` decodes one candidate at a time and runs that
candidate's full guards before considering the next. The newest-hit rows above show the intended
shape: 64 retained candidates still take 14.5 ms to reach a first-candidate hit, while the
oldest-target arm pays 82.2 ms.

This is not a skip-validation optimization. Admission modes other than `always` decode the full
candidate set because their eligibility decision needs it; `always` is the lazy path. Malformed
records remain skippable, and no fingerprint is allowed to replace a guard.

## 3. `/dev/null` seek compatibility

The native census refusal was not a regular-file seek. It was
`lseek(0, ..., SEEK_CUR/SET/END)` on an inherited `/dev/null`. Every admitted whence returns zero
for `/dev/null`, and a read still returns EOF, so the offset cannot affect later reads. The tracer
now admits exactly the path `/dev/null`; arbitrary inherited character devices and directory seeks
remain refused. No global nondeterministic-syscall exemption was added.

Regression: `dev_null_seek_is_reusable` runs `dev_null_lseek` twice and requires a second-run
`Reused` with the correct output. `RESULT dev-null-lseek PASS`.

Post-change native census (`benchmarks/results/phase3c/census-native/`): **9 attempted, 0 reused,
9 refused**. `lseek` has disappeared from the unmodeled-syscall ranking. Python and Pillow now
report clock, randomness, process identity, and residual image-transform effects; the result is
still not reusable. A narrower blocker disappearing is not a compatibility win unless a workload
reuses, and none does.

## 4. Output restoration semantics

Restoration already stages and verifies every CAS object before mutating a destination. The restore
phase is 3.4 ms in the clean run and 21.9 ms under the writeback tail. Leaving an existing output
unchanged when its bytes/metadata already match would avoid the write, but would also preserve the
old inode, hard links, ctime, and any replacement semantics that a native run may change. No such
shortcut was implemented. A managed-workspace contract would need explicit rules for inode
replacement, ownership, timestamps, aliases, and crash recovery; that remains open.

## 5. Research graph additions

- `P10`: Phase 3B workflow timing included verifier decompression, not replay. Status: rejected
  measurement, corrected by `E-3C-01`.
- `H9`: Lazy candidate decoding preserves full guard validation and helps newest-first hits.
  Status: prototype verified by `E-3C-02`; oldest-target cost remains linear.
- `P11`: `/dev/null` seeks are constant-zero but were blanket-refused as inherited fds. Status:
  fixed narrowly; `E-3C-03` and the new regression.
- `H10`: Frequency-aware candidate ordering/indexing could reduce oldest-target cost. Status:
  open; no frequency index was added.
- `H11`: Unchanged-output fast path. Status: rejected for native equivalence pending a managed
  contract and crash-recovery design.
- Sources: ccache manifest/direct mode, sccache dependency manifests, Salsa red-green validation,
  Adapton, Firebuild, fs-verity, fanotify, and CEGAR; see `docs/research/RESEARCH_GRAPH.md`.

## 6. Verification

- `cargo fmt --all -- --check`: pass.
- Clippy `--workspace --all-targets --all-features -- -D warnings`: pass.
- `cargo test --workspace`: **130 passed**.
- Linux integration: **44 passed**, 0 failed; `PROVEN` skips locally (no Landlock).
- Release build: pass.
- Native census after the change: 9 refused, 0 reused, 0 execution failures.

Raw evidence: `benchmarks/results/phase3c/latency.json`,
`benchmarks/results/phase3c/candidate-scaling.json`, and
`benchmarks/results/phase3c/census-native/`.

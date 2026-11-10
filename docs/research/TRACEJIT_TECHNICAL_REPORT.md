# TraceJIT Technical Report

Version: Phase 3A working draft, 2026-11-10. This is an engineering report, not a peer-reviewed result.

## 1. Abstract

TraceJIT observes an unmodified Linux process with ptrace, reconstructs its observable effects, and
reuses a command only when compiled guards and an execution contract permit it. The current system
targets whole-command reuse on Linux x86_64, with BLAKE3 content-addressed storage, SQLite metadata,
strict synchronous validation, and fail-closed classification.

Phase 3A fixes two concrete defects: cached stdout/stderr were verified after output restoration, and a
command identity retained only one execution record, so an A/B/A input sequence lost the A result.
The change retains at most eight guarded candidates and verifies streams before mutating outputs. A
five-session A/B/A fixture changes the third decision from `Executed` to `Reused`; median wall time was
13.84 ms versus 20.57 ms in this small case. This does not establish a general speed advantage.

## 2. Motivation

Build systems and compiler caches are effective when they know the dependency graph. An arbitrary
command run by a developer often does not have a trustworthy graph. TraceJIT asks whether observation
can recover enough of that graph to reuse the command safely, without modifying it.

The motivating value is not "replace Make". It is reducing repeated work for an expensive command whose
inputs are visible in the trace, while refusing when the observation is incomplete.

## 3. Problem formulation

Given executable path, argv, cwd, environment, runtime identity, and (optionally) a controlled contract,
TraceJIT computes a lookup key. An execution record contains guards, outputs, captured streams, status,
classification, and model/contract metadata. Reuse is permitted only if:

1. the record's contract equals the active contract;
2. the classification is eligible (`GUARDED` or `PROVEN`, subject to enforcement);
3. every guard validates against the current world;
4. every stream and output object verifies; and
5. output preconditions and inherited-stream state can be reproduced.

The hard problem is not storing bytes. It is establishing that the observations are complete enough for
the requested equivalence.

## 4. Related work

Compiler caches such as ccache use compiler-specific direct-mode manifests that include source,
options, and include-file hashes. Firebuild uses process interposition to cache broader commands. Build
systems such as Bazel and Buck2 own the action graph and can skip work before starting a process.
Incremental-computation systems such as Salsa separate dirtying from re-execution and can stop
propagation when a recomputed value is unchanged.

TraceJIT occupies a different point: it does not know the compiler or the build graph, and it must infer
dependencies from syscalls. It therefore pays validation and tracing costs that graph-owning systems
avoid. The Phase 2T negative result confirms that this is a real disadvantage on an unchanged
well-configured build.

## 5. Threat model and execution contract

- The cache is local to the user and not shared with an untrusted writer.
- The executable can be replaced between identity hashing and `execve`; that final race remains open.
- `PROVEN` means seccomp and Landlock were genuinely installed for the execution, not merely available.
- `GUARDED` means all observed effects were guardable, but the execution did not receive the enforced
  policy.
- Controlled contracts deliberately change selected observations; they are never native-equivalent.
- Restoration is pathname-visible. It is not inode-preserving and is not a durable multi-file
  transaction.

## 6. Architecture

`effects -> guards -> cache -> trace -> sandbox -> core -> cli`

- `tracejit-effects`: syscall/effect reconstruction and classification.
- `tracejit-guards`: compiled predicates and replay logic.
- `tracejit-cache`: SQLite metadata, candidate selection, BLAKE3 CAS, output staging/restoration.
- `tracejit-trace`: ptrace process tracking and syscall capture.
- `tracejit-sandbox`: seccomp/Landlock policy installation and capability reporting.
- `tracejit-core`: run orchestration, admission, identity, report construction.
- `tracejit-cli`: command-line and JSON presentation.

## 7. Dependency and effect model

Reads, metadata observations, directory enumeration, access checks, inherited streams, environment,
working directory, executable hashes, filesystem statistics, and supported controlled observations are
compiled into guards. Writes, deletions, renames, metadata mutations, and output pre-states are modeled
as effects with restoration artifacts.

Unsupported or unguardable effects make the record ineligible. The system does not use a global
"syscall is allowed" list as a substitute for a context-sensitive predicate.

## 8. Cache and validation algorithms

### Candidate retention

Schema v2 keys rows by `execution_id` and indexes `(lookup_key, updated_unix_ms)`. Up to eight candidates
are retained. A candidate is selected only after its guards pass. Failed candidates are not silently
promoted; if none passes, the command executes.

### Replay ordering

For each matching candidate:

1. validate guards;
2. read and BLAKE3-verify stdout and stderr;
3. probe inherited-stream seekability without leaving the descriptor moved;
4. validate and stage output artifacts;
5. rename staged outputs and apply recorded deletions;
6. apply inherited-stream offsets;
7. report the hit.

A corrupt stream or output object is a miss. A failed output precondition is a miss for a replacement;
an unsafe deletion remains fatal.

### Migration

v1 caches are copied into the new table in one SQLite transaction. `user_version` is bumped to 2 only
after the copy and rename. Existing rows survive.

## 9. Correctness reasoning

The candidate loop preserves the old invariant: no record is reused without full guard success. A
malformed record cannot cause another record's bytes to be exposed; it is skipped. The stream-before-
restore order removes the concrete late-failure path. Inherited-stream probing makes the post-restore
seek a practical no-op failure mode, though it is not a formal atomicity proof.

The system still has a hard-kill window between output renames. It does not claim crash-consistent
multi-file restoration. It does not claim inode identity or open-descriptor equivalence. Hard-linked
destinations are refused rather than approximated.

## 10. Experimental setup

Host: Linux x86_64, kernel 6.1.102, 8 vCPU, no Landlock. Rust stable toolchain. Release binary
`79ee6501d7b09e8e0f4c02cb4cc32e0f4243b7525377f596e40c550cfafc084c`.

A/B/A fixture: `tests/fixtures/fixture_driver.c`, mode `plain_file_read`. Fresh workspace and cache per
session. Five sessions per arm; arm order alternates by session. The baseline is the pre-change release
from `a11ae4b`, hash `3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`.

## 11. Baselines

The A/B/A baseline tests the specific single-candidate defect. It is not a build-system baseline.

The retained Phase 2T baseline is more important for the product claim: correct Make 4.3 and Ninja 1.13.2
skip an unchanged pipeline far more cheaply than TraceJIT; a content cache is also faster. TraceJIT
remains correct on a preserved-mtime edit and a corrupted output where mtime-based tools are stale.

## 12. Ablation studies

The multi-candidate change is the only mechanism ablated in Phase 3A: running the same sequence on the
pre-change binary produces `Executed` for the third invocation. The stream-ordering change is verified by
inspection and the integration corruption test, but not by a dedicated transient-state ablation.

No candidate-bound sweep, fs-verity prototype, chunking prototype, or workflow scheduler was evaluated.

## 13. Compatibility analysis

The change preserves the crate boundaries and the existing classification rules. It does not broaden
syscall coverage. It does not alter the `PROVEN` definition, the controlled contracts, or the native
lookup key. Existing v1 caches migrate. Records with malformed JSON are skipped individually.

The local `PROVEN` gate remains skipped. Any compatibility claim beyond the tested fixtures requires a
new discovery and real-workflow run.

## 14. Performance results

| Measurement | Result |
| --- | --- |
| A/B/A third invocation, current | `Reused` 5/5, 13.841662 ms median wall |
| A/B/A third invocation, pre-change | `Executed` 5/5, 20.572657 ms median wall |
| Workspace tests | 128 passed |
| Linux integration | 42 passed |

The A/B/A result is a small fixture, and the report runtime is only 3.85 ms. The wall-time difference is
not a general workflow acceleration.

## 15. Limitations and negative findings

- TraceJIT loses badly to Make/Ninja and a content cache on an unchanged incremental build.
- Candidate retention can multiply guard work; eight is an unmeasured bound.
- Restoration is not atomic across a hard kill.
- No fs-verity, chunking, compression, remote cache, or workflow scheduler was added.
- Local `PROVEN` is blocked by missing Landlock.
- No hosted CI run for this commit was observed at the time of writing.
- The A/B/A fixture is synthetic and uses the repository's test driver.

## 16. Future work

The highest-value next steps are, in order:

1. observe CI for the pushed commit and require `RESULT proven-reuse PASS`;
2. instrument candidate lookup/validation cost and choose a bound from data;
3. build the corrupt-stream transient-state regression;
4. profile hashing of large dependencies before considering fs-verity;
5. only then evaluate workflow-level ownership against a realistic graph.

## 17. References

- ccache manual, direct mode and manifest: <https://ccache.dev/manual/latest.html>
- Firebuild project: <https://github.com/firebuild/firebuild>
- Salsa red-green algorithm: <https://salsa-rs.github.io/salsa/reference/algorithm.html>
- FastCDC paper: <https://www.usenix.org/system/files/conference/atc16/atc16-paper-xia.pdf>
- fs-verity: <https://docs.kernel.org/filesystems/fsverity.html>
- Landlock: <https://docs.kernel.org/userspace-api/landlock.html>
- seccomp filter: <https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html>

## 18. Reproduction

```bash
export PATH="$HOME/.cargo/bin:$PATH"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture --test-threads=1
cargo build --release --workspace
python3 benchmarks/repos/candidate_reuse.py \
  --binary target/release/tracejit \
  --baseline .baseline/target/release/tracejit \
  --sessions 5 \
  --output benchmarks/results/phase3a/candidate-reuse.json
```

The `.baseline` worktree is a local comparison aid and is not committed.

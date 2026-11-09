# Phase 2S: real-workflow acceleration and execution-contract validation

Base commit: `d6c9e05`. This report covers the independent audit, realistic recurrence, complete
workflow measurements, eligibility ranking, cache-path measurement, gates, and the readiness
decision. All measurements used the release binary built from this tree
(`3ea020aadd082d2aa01becb319c30c11334c755ee870e24983b0bee3bbe17981`).

## Part A: independent audit of Phase 2R

### Confirmed defect: partial version-2 metadata was accepted

A version-2 `OutputArtifact` could omit any one of `unix_mode`, `unix_uid`, `unix_gid`,
`unix_accessed_ns` or `unix_modified_ns`. `serde(default)` supplied `None`, and `stage_output`
silently skipped that effect, so the hit restored only part of the declared metadata. A
deletion artifact could likewise carry content or metadata. This is now rejected before any
destination is touched:

- `a_version_two_file_artifact_without_complete_metadata_fails_closed`
- `a_deletion_artifact_with_metadata_fails_closed`

The file case requires content and all five Unix metadata fields; the deletion case requires all
of them to be absent. `OUTPUT_ARTIFACT_VERSION` remains 2; version 0 and every other version fail
closed.

### Previously fixed defects rechecked

- Legacy records without `artifact_version` decode as 0 and are refused; they cannot be mistaken
  for a complete v2 record.
- Metadata is captured before hashing, so the cache's read cannot change the recorded atime.
- Malformed record JSON is treated as a metadata miss and retraced; a corrupted CAS object is
  rejected by rehashing before any destination is touched.
- Every output is validated and staged before the first rename. Failure on a later output rolls
  back earlier replacements from hard-link backups; a failed rollback is reported separately.
- Hard-linked destinations, symlinks, directories, non-writable existing files and missing files
  without create permission are refused. Tests cover each case, including two-link untouched
  assertions.
- Controlled and native identities are different: the existing `sed` contract test records a
  controlled hit, then confirms a native invocation is `Nondeterministic` and not `Reused`.
- Corruption and concurrency regressions from prior phases still pass.

### Declared external-effect contract

TraceJIT promises the **pathname-visible** result: content bytes, mode, owner, atime/mtime, exit
status, stdout/stderr and declared filesystem presence. It does not promise inode identity,
inode generation, ctime, xattrs, or the state seen through a descriptor opened before restoration.
`restore_outputs` replaces the directory entry; a process holding an old descriptor keeps that
old inode. A native in-place truncate would mutate that descriptor instead. The trace currently
records both rename-style and truncate-style writes as `CreateOrModify`, so TraceJIT cannot
conservatively distinguish them at restore time; this is a contract limit, not claimed equivalence.
Hard links and symlinks at the destination are refused, so the common aliasing cases fail closed.

An extended-attribute probe using `os.setxattr` was refused as `unmodeled successful syscall 188`
before reuse; xattrs are therefore not silently dropped. The probe also included a regular-file
stdin to avoid a harness-only `lseek` refusal.

## Part B: independent bzip2 validation

Command: `bzip2 -9 -k -f big.txt`; input 6.0 MB; output 201,556 bytes; contract
`allocator-entropy-v1`; isolated cache per scenario; five repetitions. Definitions are those in
the report: per-run = native median / controlled median; session = total native / total controlled
including the cold trace; net = native session minus controlled session.

| Scenario | Native total | Cold | Warm total / median | Per-run | Session | Net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A output removed each run | 3,095.25 ms | 728.49 ms | 71.29 / 14.02 ms | 43.87x | 3.87x | +2,295.46 ms |
| B output retained | 3,047.19 ms | 757.56 ms | 81.31 / 15.69 ms | 38.51x | 3.63x | +2,208.32 ms |
| C input regenerated each run | 2,976.04 ms | included | 733.38 ms (controlled total) | 0.81x | 0.81x | -708.61 ms |

A: cold `Executed`, all five warm runs `Reused`; warm SHA-256, size, mode, uid and gid match the
native output. B: cold `Executed`, all five warm runs `Reused`; bytes/mode match native and the
warm metadata equals the cold artifact, including mtime. C: first run `Executed`, then four
`Deoptimized` runs; output bytes match the native output for the same edit sequence. The negative
C result is correct: changing the input before every invocation rejects reuse.

### Phase 2R discrepancy

Phase 2R reported a median-based 37.63x and a second-session aggregate 20.43x. The difference was
not a cache failure: the ten-run aggregate in session 2 had 269.35 ms warm total (26.9 ms/run),
while the median was 17.21 ms; the aggregate was sampled after changed-argument, corruption and
concurrency tests, and `all_reused` only inspected the first five reports. Phase 2S records the
decision from the same process as each timing sample and includes cold tracing in session totals.
On stable pre-states the per-run ratios are 38.5–43.9x and sessions are 3.6–3.9x; on changing
inputs the correct result is a loss.

## Part C: four realistic workflows

`benchmarks/repos/phase2s_workflows.py` runs each complete sequence with the same inputs and
output preconditions. The controlled arm has a fresh cache and includes its cold trace.

| Workflow | Natural recurrence | Native total | Controlled total | Session | Net | Decisions |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Log archive: append record, `bzip2 -9 -k -f app.log` | every rotation | 3,026.17 ms | 3,711.59 ms | 0.82x | -685.42 ms | Executed, 4 Deoptimized |
| Static assets: precompress 3 stable JS files | every build/deploy | 1,363.68 ms | 397.44 cold + 209.14 warm | 2.25x | +757.10 ms | cold all Executed, 15 Reused |
| Release stream: `gzip -9 -c release.tar` | repeated release packaging | 338.71 ms | 155.05 cold + 161.61 warm | 1.07x | +22.05 ms | all warm Reused |
| CSV ETL: aggregate 160k sales rows | repeated reports | 2,417.21 ms | 3,470.39 ms | 0.58x | -1,768.35 ms | all Ineligible |

All output bytes match native. Static assets are byte-identical for all three files; release gzip
is byte-identical; log archive and ETL outputs also match. The ETL refusal is attributed to
`getpid`, `getppid`, monotonic/realtime clocks, `gettid` and `getrandom`. The log-append workflow
correctly deoptimizes on each edit; it is a negative result for caching, not a false hit.

Cumulative across these four complete workflows is negative because ETL and log edits dominate.
The positive result is real but bounded: **two workflows save time** (stable assets and release
stream), one is correctly rejected, and one correctly pays trace overhead after every edit.

## Part D: eligibility and next bottleneck

`benchmarks/results/phase2s/discovery.json` (present pre-state, contract active) has one reusable
workload, bzip2. All others remain ineligible; the full recorded reasons are in the JSON.

| Rank | Workload | Native | All recorded blockers | Natural reuse | Correctness risk | Cost/breadth |
| ---: | --- | ---: | --- | --- | --- | --- |
| 1 | xz -6 | 1,990 ms | `sysinfo`, monotonic clock | medium release/asset | high: clock semantics | high / compression |
| 2 | gcc -O2 | 812 ms | unmodeled `getrusage` (98) | high build loop | high: compiler contract | high / narrow compiler |
| 3 | Python JSON | 240 ms | pid/ppid/gettid, both clocks, getrandom | high scripts/CI | high: runtime-wide | high / broad runtime |
| 4 | jq | 206 ms | pid/ppid, application getrandom | high reports | medium | medium / JSON |
| 5 | sort | 67 ms | `sched_getaffinity` | high ETL | medium | medium / text |
| 6 | gzip `-f` | 64 ms | failed `O_EXCL` EEXIST | high assets | medium: presence/unlink | low-medium / compression |
| 7 | sed/awk | 61/40 ms | pid/ppid, realtime clock | medium logs | medium | low: below hit floor |
| 8 | tar/zip | 7/10 ms | realtime/monotonic clock, failed socket | high packaging | medium | low: below hit floor |
| 9 | objdump/nm/readelf/strip/objcopy | 3–20 ms | pid/ppid, `prlimit64` | medium inspection | low | low: below hit floor |

No new compatibility profile was implemented. The highest-value candidate, xz, needs a clock and
`sysinfo` model, not a narrow entropy profile; substituting those broadly is explicitly out of
scope and no xz-version call-shape audit exists. A compiler profile would likewise need a
`getrusage` model and a version-specific contract. Adding one would be speculative, so the only
code change this phase is the fail-closed metadata completeness fix.

## Part E: common cache path

Warm bzip2 phases: identity/executable preparation **0.172 ms**, guard validation **6.76 ms**,
CAS restore **2.36 ms**, decision persistence **3.58 ms**, SQLite query 0.23 ms, decode 0.42 ms.
Executable identity is under 2% of the warm path. Session-scoped executable/library validation
would save at most a fraction of 0.17 ms and require new invalidation state, so it was not added.
No persistent inode/mtime shortcut was introduced; content hashes remain authoritative.

## Part F: benchmark method and raw results

- Binary: release build of this tree; hash recorded in `workflows.json`.
- Fixtures under `/tmp/tjq/phase2s`, outside the repository.
- Each controlled scenario has its own cache; output preconditions are established before cold
  tracing; cold is included in session totals.
- Native and controlled order is fixed (native then controlled) because the controlled cold trace
  must precede warm hits; this is a limitation of this benchmark, not a randomized trial.
- Raw samples, medians, decisions, binary hash, host details and output fingerprints are in
  `benchmarks/results/phase2s/workflows.json` and `discovery.json`.

Commands:

```bash
cargo build --release --workspace
python3 benchmarks/repos/phase2s_workflows.py --reps 5
TRACEJIT_DISCOVERY_CONTRACT=allocator-entropy-v1 \
TRACEJIT_DISCOVERY_ADMISSION=always \
TRACEJIT_DISCOVERY_PRESTATE=present \
TRACEJIT_DISCOVERY_RESULTS=benchmarks/results/phase2s \
python3 benchmarks/repos/workload_discovery.py
python3 benchmarks/differential/fuzz.py --seed 20261109 \
  --output benchmarks/results/phase2s/differential
```

## Part G: gates, security and enforcement

- `cargo fmt --all -- --check`: pass.
- Clippy `--workspace --all-targets --all-features -- -D warnings`: pass.
- `cargo test --workspace`: **125 passed**, 0 failed.
- Differential fuzz: **120 cases, 120 ok, 0 incorrect hits**.
- `PROVEN` remains **BLOCKED**: Landlock unavailable (`landlock no`), seccomp available
  (`seccomp yes`). Landlock alone would not eliminate every external filesystem race; the
  destination validation/rename window remains.
- The allocator contract stays opt-in; a fixed tcache key is not native randomness.
- Output comparison is evidence for these cases, not a proof of noninterference.

## Part H: repository and readiness

The branch is local until the authorized push at the end of this phase. GitHub Actions has not
been re-run from this branch; the last remotely verified run remains failed at `c7f2c681`.
No release or package publication was performed.

**Developer-preview readiness:** limited, not general. A preview may expose stable, explicit
`allocator-entropy-v1` workloads such as `bzip2 -9 -k -f` with a retained or removed output
pre-state and `gzip -9 -c`; the static-asset precompression workflow measured 2.25x session
speedup. It must not advertise log-append/ETL acceleration, inode identity, open-descriptor
consistency, or native-equivalent randomness. Existing caches written before schema v2 will
retrace once, which is intentional.

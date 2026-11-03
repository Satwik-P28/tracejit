# Phase 2E: the directory dependency, traced and fixed

The largest practical defect in Phase 2D was that creating an unrelated file — including the command's
own output — invalidated an otherwise reusable execution. This phase found the mechanism, split the
observation into a correctly typed dependency, and measured the correction.

## 1. Call graph, from syscall to comparison

Reproduced with `gzip -9 -c /tmp/diag/work/in.txt` and structured diagnostics enabled
(`TRACEJIT_DIAG_DEPS=1`, raw capture in `benchmarks/results/phase2e/diag-deps.txt`). Each event names
the recording site, thread, path and resulting effect:

```
{"event":"dependency","tid":14731,"site":"tracejit-trace::open_pending",
 "path":"/tmp/diag/work","detail":"syscall=257 flags=0x10000 dirfd=-100"}
{"event":"dependency","tid":14731,"site":"tracejit-trace::complete_syscall",
 "path":"/tmp/diag/work","detail":"fd=3 effect=DirectoryOpened flags=0x10000"}
{"event":"dependency","tid":14731,"site":"tracejit-trace::open_pending",
 "path":"/tmp/diag/work/in.txt","detail":"syscall=257 flags=0x900 dirfd=3"}
```

| Step | Location | What happens |
| --- | --- | --- |
| 1. Syscall | `openat(AT_FDCWD, "/tmp/diag/work", O_RDONLY\|O_DIRECTORY)` = 257, `flags=0x10000` | gzip opens the input's **parent directory** and keeps it as fd 3 |
| 2. Entry | `tracejit-trace::open_pending` | resolves the path; `before_hash = None` because it is not a file; `before_fingerprint = Some(dir)` |
| 3. Exit | `tracejit-trace::complete_syscall`, `PendingSyscall::Open` arm | not a random device, not procfs, no write flags, no hash, `path.is_dir()` → **recorded as a metadata read of the directory** |
| 4. Dependency | `tracejit-effects::reconstruct_dependencies` | became `InputDependency::Metadata { path, fingerprint }` |
| 5. Guard | `tracejit-guards::compile_guards` | became `Guard::FileMetadata { path, expected }` |
| 6. Comparison | `Guard::validate` | compared all twelve `FileFingerprint` fields, including `modified_ns` and `changed_ns` |

Step 1 is the part both Phase 2D explanations missed. Independent `strace` of the same command shows
**no** `stat`, `statx`, `newfstatat`, `lstat` or `getdents64` against that directory — only
`openat(... O_DIRECTORY) = 3`, followed by `openat(3, "in.txt", ...)`. The directory's metadata is
never observed: the descriptor exists to serve as a name-resolution base. (The three `fstat` calls in
the trace are `ld.so` and the input file, on fds 3 and 4 of different processes' numbering; none is on
the directory.)

So the Phase 2D report was wrong twice over: the dependency is **not** created during path resolution,
and it is **not** created by a metadata syscall. It is created by a real `open` of a directory, which
the tracer conservatively modelled as "the program read this directory's metadata" because a directory
has no content hash to fall back on. The contradiction the phase brief identified was real, and the
answer is that neither of the two documented hypotheses was the call chain.

## 2. Why the full fingerprint was wrong here, and why it was not simply removed

An `open(dirfd, O_RDONLY|O_DIRECTORY)` can report: existence, that the path is a directory, and whether
this process may open it. It cannot report `mtime`, `ctime`, `atime`, `size`, `blocks` or `nlink`.
Those change on every create and delete in the directory, so comparing them turned an unrelated
sibling, or the command's own output, into an invalidation.

Removing the guard was not an option: a fresh run would fail the open if the directory vanished or its
permissions changed, while the cached entry would happily replay success. The distinction the previous
phase said was missing is exactly the one needed:

| Observation | Recorded when | Compared at validation |
| --- | --- | --- |
| `DirectoryOpened` (new) | `open` on a path that is a directory | `device`, `inode`, `mode`, `uid`, `gid`; still a directory; a probe `open` of it succeeds |
| `Metadata` (unchanged) | `stat`, `lstat`-family, `fstat`, `newfstatat`, failed lookups | all twelve fields, including every timestamp |
| `SymlinkMetadata` (unchanged) | `lstat`/`newfstatat` with `AT_SYMLINK_NOFOLLOW` | all twelve fields of the link itself |
| enumeration | now **refused** | entry sets are not modelled |

Timestamps are not ignored anywhere. A program that reads directory metadata issues a `stat`, which
still produces `Metadata` and still compares timestamps; the test
`explicit_directory_metadata_guard_still_compares_timestamps` pins that.

## 3. A soundness hole found on the way

`getdents64` was listed in `is_known_internal_syscall`, so directory enumeration was **silently
ignored**: a program could list a directory and produce output that no guard covered. That is the
opposite error from the one this phase set out to fix, and it was not reachable by the reuse suite only
because those workloads hit other refusals first. Enumeration is now explicitly refused with the
directory named, rather than assumed irrelevant. It remains unimplemented; a real entry-set dependency
is the honest fix and is listed as remaining work.

## 4. Tests added

Guards (`crates/tracejit-guards`):

- `directory_open_guard_ignores_entries_created_beside_an_input` — create a sibling, delete it, and
  create a child directory (which changes `nlink`); all still valid.
- `directory_open_guard_ignores_timestamps_size_and_link_count` — synthesizes changes to the fields an
  open cannot observe and requires success.
- `directory_open_guard_detects_permission_change`, `..._detects_removal`, `..._detects_replacement`,
  `..._detects_a_type_change`.
- `explicit_directory_metadata_guard_still_compares_timestamps` — the reduced comparison does not leak
  into a genuine metadata read.

End to end (`crates/tracejit-cli/tests/linux_integration.rs`):
`gzip_reuse_survives_creating_entries_beside_the_input` records, reuses, writes the output beside the
input, requires `Reused` with byte-identical stdout, adds an unrelated sibling, requires `Reused` again,
then changes the input and requires `Deoptimized` with the *new* bytes.

Timestamps are synthesized in the unit tests rather than produced by a real write, because this host
was measured not to publish an entry-creation timestamp to a `stat` in the same process promptly (a
sibling existed, yet the directory's `modified_ns` was unchanged after a 50 ms re-stat). Testing the
comparison directly avoids asserting on filesystem timing. Total tests: **95 passing** (was 87).

## 5. Measurements

All at the same commit as the artifacts, `benchmarks/results/phase2e/`; binary `target/debug/tracejit`.

### Ordinary use, before and after

`gzip -9 -c input.txt`, output then unrelated siblings written into the input's directory between runs:

| Session | Cell | Direct | Warm hit | p95 | Hits | Invalidation |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| session-a | small, isolated | 112.25 ms | 6.02 ms | 8.67 | 15/15 | 0% |
| session-a | small, output beside input | 112.18 ms | **5.86 ms** | 6.69 | 15/15 | **0%** |
| session-a | large, isolated | 1494.55 ms | 10.41 ms | 15.96 | 15/15 | 0% |
| session-a | large, output beside input | 1470.92 ms | **9.99 ms** | 11.13 | 15/15 | **0%** |
| session-b | small, isolated | 111.65 ms | 5.88 ms | 12.26 | 15/15 | 0% |
| session-b | small, output beside input | 111.85 ms | 5.92 ms | 12.11 | 15/15 | 0% |
| session-b | large, isolated | 1482.99 ms | 11.04 ms | 13.67 | 15/15 | 0% |
| session-b | large, output beside input | 1493.90 ms | 12.04 ms | 21.81 | 15/15 | 0% |

Small = 480 kB, large = 6 MB, 15 runs per cell, deterministic varied text. Speedups 18.6–19.1x small
and 124–147x large; one hit repays the trace in every cell (≤0.42). **The two layouts are now
indistinguishable**, which is the point: output placement stopped mattering.

Baseline built from `0ccf181` in a detached worktree, same machine, same payload, 6 runs per cell:

| Cell (baseline) | Direct | Warm hit | Hits | Invalidation |
| --- | ---: | ---: | ---: | ---: |
| small, isolated | 112.31 ms | 9.46 ms | 6/6 | 0% |
| small, output beside input | 113.68 ms | **138.21 ms** | **1/6** | **83%** |
| large, isolated | 1491.03 ms | 14.30 ms | 6/6 | 0% |
| large, output beside input | 1492.00 ms | **1548.51 ms** | **1/6** | **83%** |

Before the fix, writing the output beside the input made the cache *slower than not using it*
(0.82x small, 0.96x large) because every run retraced. After the fix, the same sequence is 23x and 155x
faster than that baseline. The `dir_guard_probe.py` decisions show the same thing in decision form:
`sibling-created-after-1` and `output-written-beside-input-after-1` were `Deoptimized` at `0ccf181`
and are `Reused` now, while `input-content-changed-after-1` is still `Deoptimized`.

### Cost of the new guard

The hit path still assembles the same number of guards, but the directory guard now performs a `stat`
plus an `open`/`close` instead of a `stat` alone. Measured against the `0ccf181` binary on identical
payloads: fixed 6.02 / 10.41 ms versus baseline 9.46 / 14.30 ms on the isolated cells. The fixed build
measured *faster*, which is the opposite of the expected small increase, with p95 spreads of
8.67–13.43 and 15.96–19.52 ms. The difference is therefore within this VM's run-to-run variance, and I
do not attribute it to the change: the defensible claim is that the added work is **below the
measurement floor here**, not that it is negative.

### Compatibility suites, unchanged denominators

- Direct suite, two sessions, 3 runs per workload: **1 of 16 reused** (`gzip`), **16 of 16** traced
  output identical to a direct run. No additional category was obtained (see §7).
- Shell-wrapped census, original nine workloads: **0 of 9** eligible, 9 of 9 output equivalent,
  0 execution failures. Unchanged from Phase 2C/2D.

## 6. Safety assumptions that remain

- The probe `open` runs as the validating process, whose identity the `RuntimeIdentity` guard already
  covers. A program that opened the directory under different effective credentials than its parent
  (setuid) is not separately modelled; this is the pre-existing executor-identity limitation.
- The probe uses a read-only open, so an `O_PATH` open that would only need search permission is
  validated more strictly than recorded. That fails closed, at the price of a lost hit.
- Comparing `inode` is conservative: replacing a directory with an identical copy invalidates reuse.
- An ACL change is caught when it alters `mode`, or when it makes the probe open fail for the
  validating user. A change that does neither cannot make a fresh run behave differently from the
  cached one for the recorded observation.
- A directory that is opened and *then* enumerated is refused outright; entry sets are not guarded.
- `stat` on a directory still compares timestamps, including `atime`.
- `PROVEN` enforcement remains **unverified**: kernel 6.1.102 has no Landlock here (`ENOSYS`, LSM
  `capability,selinux`).

## 7. What did not improve

Priority 4 aimed at two additional reusable categories. The result is **none**:

- `sed`, `tar` — still refused at `statfs`; no change was attempted, so the refusal chain is unchanged.
- `grep` — still refused at `/proc/self/maps`; process-memory identity was not modelled.
- `tr` — still refused for an inherited descriptor read.
- `gcc`/`as` — `getrusage` policy unchanged, deliberately.
- `getrandom` workloads (bzip2, xz, sort, base64, md5sum, wc, jq, python-json, strip) — unchanged; an
  observed random read is not evidence of nondeterministic output, and no enforceable model exists.

The directory fix raised the *value* of the one reusable workload rather than adding new ones, which is
what the mission's primary criterion asked for; the secondary objective is reported as unmet.

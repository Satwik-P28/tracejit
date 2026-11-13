# Phase 3I — `dup2(fd, fd)` review and controlled directory replay

Date: 13 November 2026

Status: P0 review complete. The successful Linux `dup2(fd, fd)` no-op no longer destroys the
descriptor's TraceJIT state, and the regression is covered at both unit and integration level. A
controlled `python-runtime-v1` hit now exists on the **original** `python-csv-json` workload using
explicit zeroing of `linux_dirent64` alignment padding. That hit is a controlled observation result,
not native equivalence and not a general Python compatibility claim. The native byte-exact policy is
still the default and still refuses the target.

Branches: `hotfix/descriptor-dup-noop` (four commits on top of PR #8's P0 fix) and
`research/phase3i` (experimental contract plus Phase 3I evidence). Neither PR is merged. Hosted CI
must be recorded after the branches are pushed; this host has no authenticated GitHub session.

## 1. P0 — `dup2(fd, fd)` is a successful no-op

### 1.1 Defect

`PendingSyscall::Dup` treated every successful duplicate as a replacement:

```text
forget_descriptor(destination);   // removes fd state, CLOEXEC and enumeration state
source_state = lookup(source);    // source may be the same descriptor
install(destination, source_state);
```

Linux returns success without changing the descriptor when `oldfd == newfd`:

```text
dup2(fd, fd)  -> fd, FD_CLOEXEC unchanged, same open file description
dup3(fd, fd)  -> -1, EINVAL
dup(fd)       -> new descriptor, normal duplicate
fcntl(fd, F_DUPFD/F_DUPFD_CLOEXEC) -> new descriptor, normal duplicate
```

The bug therefore appeared only on the successful `dup2` path. For a file descriptor, the trace lost
the fd classification and CLOEXEC bit. For a directory, it lost the in-progress enumeration record,
so the next `getdents64` was classified `Unknown`. For an internal pipe, the duplicate state was
erased. The target still ran, but the trace became ineligible for reuse.

### 1.2 Correction

The duplicate handler now returns immediately when the destination equals the source, before the
destination is forgotten or the source is looked up. `dup3(fd, fd)` never reaches that successful
path: the kernel rejects it with `EINVAL`, so it falls into the existing normal failure path. Normal
`dup`, distinct `dup2`, `dup3` and `fcntl` replacement handling is unchanged.

### 1.3 Reproduction

`7f15832 test: reproduce dup2 same-descriptor state loss` added a failing unit test before the fix.
`e74f9ee fix: preserve dup2 same-descriptor state` made it pass. The unit suite covers:

- a file descriptor with `FD_CLOEXEC` set;
- a directory descriptor with an in-progress enumeration;
- an internal pipe;
- ordinary `dup`, distinct `dup2`, distinct `dup3` and `fcntl` duplication/replacement.

`c2f1e9c test: exercise dup2 self-duplication end to end` adds fixture cases
`dup2_same_file`, `dup2_same_directory` and `dup2_same_pipe` to
`tests/fixtures/fixture_driver.c`, plus
`dup2_same_descriptor_preserves_directory_and_pipe_tracking` in
`crates/tracejit-cli/tests/linux_integration.rs`. The test was run with the early return removed; it
failed on the first non-reusable case, then passed with the fix restored:

```text
before fix: test result: FAILED. 0 passed; 1 failed
after fix:  test result: ok. 1 passed
```

The file case also checks that `FD_CLOEXEC` survives the self-duplicate; the directory case reads
`getdents64` before and after the duplicate; the pipe case reads after duplicating the read end onto
itself.

### 1.4 Preflight errors fail the invocation

`PreparedExecution::new` propagates `GuardError::DescriptorEnumeration` with `?`. The CLI exits with
status 1 before candidate lookup; it does **not** fall back to direct execution. This is fail-closed
behavior, and it means a readdir fault makes an otherwise runnable command fail until the fault is
removed.

`77c8715 test: pin descriptor preflight failure behavior` extends the existing `LD_PRELOAD` test to
assert the exact status (`1`) and that the target's output file was not created. The existing test
already asserted that no `HIT` or `MISS` was reported.

### 1.5 Preflight-to-`exec` race — corrected assessment

Phase 3H said that "the parent or another process" could change the descriptor table between the
scan and `execve`. That wording is wrong for the current architecture. The preflight and the
`Command` spawn both run in the TraceJIT process, which is single-threaded at that point. The parent
of TraceJIT cannot mutate TraceJIT's descriptor table after the fork/exec that started TraceJIT, and
an unrelated process cannot either. Cache initialization happens after the scan and before lookup;
its files are opened with close-on-exec semantics, so they cannot leak into the target.

The remaining window is therefore narrower: a future TraceJIT thread, a signal handler, or a
preloaded constructor that opens a non-CLOEXEC descriptor between the scan and spawn would invalidate
the scan. None exists on the current path. The code still does not have an atomic handoff, so the
invariant must be maintained, not assumed. Closing it completely requires either a scan-and-exec
helper with no intervening user-space window or a proven prohibition on descriptor-table mutation.
This is recorded as an unresolved architectural limitation, not an observed cache hit or exploit.

## 2. P1 — what the directory bytes are

### 2.1 Exact identities and failure

| Property | Value |
| --- | --- |
| Interpreter | CPython 3.12.3, `/usr/bin/python3.12` |
| ELF build ID | `337d65cf00021797985cc9f77c0cc334a9fbeb38` |
| SHA-256 | `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f` |
| glibc | 2.39, build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` |
| SHA-256 | `3a15d66867d83762c7f2f1e37359cb8f6c5743edb369c65285cb0b1c4f7498bf` |
| Host | Linux 6.1.102, x86_64 |

The failing directory is `/usr/local/lib/python3.12/dist-packages`. Its first enumeration returns 48
bytes: two 24-byte `linux_dirent64` records, `.` and `..`. The semantic fields are stable; the bytes
after the NUL terminator of `.` differ. The Phase 3H record contained the non-zero padding `sl.` and
`ux`; the replay record contained zeroes. Names, order, inode numbers, `d_off` values, `d_reclen` and
`d_type` matched.

### 2.2 Explanation A — padding is preexisting/uninitialised buffer content

Confirmed at the syscall boundary. The kernel's `getdents64` implementation (`fs/readdir.c`,
`filldir64` on this host) writes the fixed fields `d_ino`, `d_off`, `d_reclen`, `d_type`, the name
and its terminator. It does not clear the alignment bytes between the terminator and `d_reclen`.

`benchmarks/phase3i/getdents_probe.c` fills its user buffer with `0xaa` or `0x55`, calls
`getdents64`, and prints every field. The same 48-byte directory yields identical semantic fields
and different padding:

```text
fill aa: record . padding=aaaaaa   record .. padding=aaaa
fill 55: record . padding=555555   record .. padding=5555
```

The probe's results are in `benchmarks/results/phase3i/getdents-probe.txt`. In glibc 2.39,
`__readdir64` returns a pointer into the `DIR` buffer rather than a fresh copy, so the padding a
program can see is whatever occupied that buffer before the kernel wrote the record. The target's
`sl.`/`ux` bytes are consistent with that heap content, not with a directory name or a TraceJIT
field.

### 2.3 Explanation B — descriptor generations, offsets or boundaries

Not supported. After the P0 lifecycle correction, the failing observation is a single request at
offset zero with a stable 48-byte boundary. Two independent cold traces have the same request
boundary, the same `d_off` cookies and the same names. A generation or boundary confusion would
change which names or how many records appear, or would append a second stream to the first; neither
happens. The fill-byte probe also reproduces the padding difference without any TraceJIT descriptor
model, which isolates it from generation handling.

The P0 `forget_descriptor` fix is still required: it prevents a real second defect where a reused
descriptor number appends a new stream to an old record. It is not the cause of the padding bytes.

### 2.4 Explanation C — semantic fields are stable, unobserved padding differs

Confirmed for the audited reader. CPython's `FileFinder._fill_cache` calls `_os.listdir`; on this
build `_posix_listdir` reads directory entries with `readdir` and decodes only `d_name`. It does not
copy or inspect `d_name`'s trailing alignment padding. glibc's `__readdir64` also returns the raw
record pointer; the ABI exposes the padding to a caller that reads past the terminator, but this
reader does not.

That makes the observation stable at the semantic-field level for this exact reader, while the
underlying bytes remain different. It does **not** make the bytes semantically irrelevant to an
arbitrary program. A C program that copies `d_reclen` bytes, hashes the buffer or compares it with
`memcmp` can observe the padding.

## 3. P2 — three controlled approaches

| Approach | Native semantics | Virtualized semantics | What a program can observe | Status |
| --- | --- | --- | --- | --- |
| Byte-exact native guard (baseline) | All returned bytes, including padding | None | Exactly the kernel's bytes | Default; target refuses |
| `VirtualZero` contract | Fields, names, order, offsets, record lengths | Alignment padding after the NUL is zeroed in the target and replayed as zero | Every padding byte is zero; a padding-sensitive program sees a different value from native | Implemented only under `python-runtime-v1`; target hits |
| Typed reader projection | Fields, names, order, offsets, record lengths | Padding is excluded from comparison | A padding-sensitive reader can still observe native bytes; a typed guard would accept a byte change it cannot see | Benchmark-side prototype; **not** wired into the guard |

`VirtualZero` is implemented in
`crates/tracejit-effects/src/lib.rs` (`DirectoryPaddingPolicy`, `zero_directory_entry_padding`) and
`crates/tracejit-trace/src/linux.rs` (`virtualize_directory_padding`). The policy is attached to each
`DirectoryEnumerationRequest`; `tracejit-guards` zeroes the current padding only for a
`VirtualZero` request before the byte comparison. Native requests are unchanged. The replay side
therefore applies the same explicit policy rather than silently normalising both sides.

`benchmarks/phase3i/compare_directory_policies.py` is the typed prototype. It compares the two
probe runs with padding excluded and reports:

```json
{
  "native_byte_exact_equal": false,
  "typed_fields_equal": true,
  "changed_record_indices": [0, 1],
  "padding_bytes_changed": 5
}
```

This demonstrates why a typed guard would make the target pass and why it is not a native
equivalence claim. It is deliberately benchmark-side; making it a production guard would require an
independently audited reader identity, not just a field list. The byte-exact baseline remains the
correct default for arbitrary programs.

A fourth variant, clearing the entire caller buffer before the syscall, was not implemented. It
would alter bytes beyond the returned length that belong to the caller and could be observed after
the call; zeroing only the returned alignment bytes is the narrower operation.

## 4. P3 — controlled acceptance on `python-csv-json`

### 4.1 Result

The original workload is `benchmarks/realworld/workloads/etl.py`, run with 400 sales rows and 12
customers. The command used:

```text
python3.12 etl.py sales.csv customers.csv report.json
```

with `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1` and `MALLOC_ARENA_MAX=1`.

| Arm | Result |
| --- | --- |
| Direct | success, 249-byte output |
| 3 independent cold runs, fresh cache | `Executed` / `Guarded` each time |
| 10 warm runs, same cache | `Reused` each time |
| Changed input | `Deoptimized`; new output matches direct |
| Entropy probe (`os.urandom(8)`) | `Executed`, never `Reused` |
| Identity probe | `4242 1 4243`; second run `Reused` (controlled values) |
| Time probe (`time.time_ns()`) | `0`; second run `Reused` (controlled value) |

Output SHA-256 for the original input:
`28bc8fa9e7c25a10aa121654b5df07381a78fd5d45873ef077c4132cf51054e8`.
Changed-input output SHA-256:
`c348fbdc8053676d057e02827ceac2509b7faa27e5c3231fc2cee5b08e2a9a0e`.

Filesystem effects matched for direct, cold, warm and changed-input arms: 249 bytes, mode `0644`,
`nlink=1`, and the expected SHA-256. The harness asserts cold execution, warm reuse, invalidation,
entropy refusal, identity/time control and effects equality; all seven assertions are true in
`benchmarks/results/phase3i/acceptance.json`.

### 4.2 Timings

The table is from one load-sensitive run; the first cold run had a 2.06 s outlier (cold-start page
cache on the just-built binary), so the cold median and complete-session number are reported with
the outlier visible rather than hidden.

| Measurement | Time |
| --- | --- |
| Direct median, 11 runs | 36.88 ms |
| Cold runs | 2063.19, 206.75, 214.07 ms |
| Cold median | 214.07 ms |
| Warm median, 10 runs | 51.09 ms |
| Invalidation execution | 192.02 ms |
| Complete session (one cold + 10 warm) | 730.76 ms |
| Direct complete session (11 direct runs) | 408.61 ms |

The controlled session is **slower** than the direct session on this workload. The warm hit is also
slower than direct execution. A hit exists, but there is no performance claim for this workload. The
2.06 s first-cold outlier is not evidence of steady-state cost; it is retained because it happened.

### 4.3 Caveats

- The target hit exists only with the explicit `python-runtime-v1` contract and `VirtualZero`
  padding. Native execution still refuses.
- `time.time_ns()` is fixed at zero; this is virtualized behavior and does not prove clock
  progression, timeout or liveness compatibility.
- PID/TID are fixed (`4242`/`1`/`4243`); lock names, cache names and process-identity checks can
  observe that.
- The contract is bound to one ELF build ID and one exact `python-csv-json` invocation shape. It is
  not proof of general CPython compatibility.
- The target's directory reader was audited for this build. A different reader or a trace of a
  different Python build needs its own audit.
- The preflight-to-`exec` atomicity limitation remains.
- Hosted CI has not been run from this host because there is no GitHub authentication. The local P0
  gates are in Section 5.

## 5. Gates and raw evidence

P0 branch `hotfix/descriptor-dup-noop`:

```text
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
cargo build --workspace --release
```

At `77c8715`: **150 workspace tests**, **53 Linux integration tests**, fmt and Clippy clean, release
build pass, release SHA-256
`0e47cfd34d4f14798cc82cf555067b23f58b6cfece454cd7eca62823e147293a`. The
`dup2` unit regression was confirmed failing at `7f15832` and the end-to-end regression was confirmed
failing with the early return removed.

Research branch `research/phase3i`:

```text
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
python3 benchmarks/phase3i/run.py
python3 benchmarks/phase3i/compare_directory_policies.py
```

The harness writes `benchmarks/results/phase3i/acceptance.json`,
`directory-records.json`, `getdents-probe.txt`, `policy-comparison.json` and
`strace/target-getdents.strace`. `directory-records.json` retains the full request bytes and the
semantic projection; the raw trace is not reduced to a name list.

## 6. Unresolved

1. Push both branches and record hosted CI. No authenticated GitHub session is available here.
2. Do not merge PR #8 until its hosted checks pass and the `dup2` review is accepted.
3. Do not merge PR #9's Python contract merely because the target now hits. It remains experimental,
   is bound to one build, and has a constant clock.
4. Decide whether a typed reader projection can be made a production guard with an executable reader
   identity; until then keep `Native` byte-exact by default.
5. Keep `VirtualZero` opt-in and contract-separated. It changes bytes the target can observe.
6. Maintain the descriptor-table invariant that the preflight scan assumes; do not add a
   non-CLOEXEC descriptor between scan and spawn.

# Phase 2J — inherited descriptors: semantics, model and correctness contract

## 1. What the old refusal actually was

`./minigzip -d` was refused with:

```
unmodeled successful syscall 8: lseek on inherited descriptor 0 is not modelled
```

`strace` shows zlib calls exactly one seek on stdin, before any read:

```
lseek(0, 0, SEEK_CUR) = 0
read(0, ...8192) = 8192
```

It is a seekability probe (`SEEK_CUR` with offset 0), not a rewind. The Phase 2F model
recorded only the start offset, the bytes consumed, and the end offset; it refused *every*
seek on the inherited description, so one query made decompression permanently ineligible.

## 2. Semantics audit

A descriptor is a process-local handle; the position, status flags and file identity live in
the **open file description**. `dup`, `dup2`, `dup3` and `fork` share one description;
`exec` keeps descriptors without `FD_CLOEXEC`; `open` creates a new description. The caller
of `tracejit run` observes the description it passed as stdin, so a child's seek is an
effect on the caller's state, not a private cursor.

| Operation | Effect on the description | In the model |
| --- | --- | --- |
| `read` | advances by the bytes returned | advances the model position by the syscall result |
| `readv` | same; request length unknown | advances by the result; length only affects pipe packetisation rules |
| `pread64` | **does not** advance; reads at an explicit offset | contributes to the content guard but leaves the position unchanged |
| `lseek(fd, 0, SEEK_CUR)` | returns the position, no change | recorded as a seek; position set from the result (unchanged) |
| `lseek` `SEEK_SET`/`SEEK_CUR`/`SEEK_END` | repositions | result becomes the model position |
| `lseek` `SEEK_DATA`/`SEEK_HOLE` | answers about allocation layout | **refused** — a content hash does not imply extents |
| failed `lseek` | no change | no position change; the errno is already baked into cached output |
| `lseek` on a duplicate | moves the same description | **refused** — one position per stream, no alias accounting |
| `lseek` on a directory fd | changes a `getdents64` stream | **refused** (pre-existing rule) |
| stdin as pipe/terminal/socket | not seekable or no offset contract | not modelled; failed seeks are harmless and other reads already refuse |

`O_APPEND`, `O_NONBLOCK` and file-status flags do not change read offsets; writes through an
inherited descriptor were already refused as unclassified I/O, so a seek cannot hide a write.

### Why the final position is the right contract

Reuse does not replay the program's control flow; it replays the recorded output. What must
still match the direct run is the caller-visible state after the process exits. For a read-only
inherited regular file that is:

- the same file (device, inode, content hash, regular-file mode);
- the same initial position (otherwise different bytes would have been read);
- the same **final** position of the shared description.

The seek *history* is not observable afterwards, and every seek result the program could have
branched on is a deterministic function of the guarded size, content and initial position for
`SET`/`CUR`/`END`. `SEEK_DATA`/`SEEK_HOLE` break that argument, which is why they stay refused.

## 3. Implementation

`crates/tracejit-trace/src/linux.rs`:

- `InheritedStreamState` now treats `end_offset` as the model's current position. A read adds
  the returned byte count only when it is not `pread64`; a successful modelled seek sets it
  to the syscall result.
- One `InheritedStreamRead` effect per stream carries the start and final offsets and the
  content hash. A helper updates it in place, because the effect layer deduplicates by path
  and keeps the first record; a per-read record would replay the first read's end position.
- The dispatch admits `lseek` only on **fd 0 itself** when fd 0 is the recorded inherited
  stream and the whence is `SET`, `CUR` or `END`. Aliases, other whences and directory
  descriptors are recorded as `Unknown`, which makes the execution ineligible.
- `pread64` is now distinguished from `read`; before this change a `pread` on stdin counted
  its bytes as consumed and would have replayed the wrong final offset.
- A failed seek is a no-op for the model (the position did not move).

The guard (`crates/tracejit-guards/src/lib.rs`) is unchanged in shape: it requires the same
device/inode, a regular file, the recorded content hash and the recorded start offset. On a
hit, `apply_inherited_stream_offsets` seeks fd 0 to the recorded final offset after every
guard has passed and cached output has been verified.

## 4. Adversarial tests

`inherited_stdin_seek_model_reproduces_offsets_and_refuses_unsound_cases` compiles
`tests/fixtures/stdin_seek.c` and checks bytes **and** the caller's file position:

| Case | Expectation | Result |
| --- | --- | --- |
| read 4, `SEEK_SET 0`, read 10 | output 14 bytes, final position 10, second run `Reused` | PASS |
| `SEEK_CUR 0` probe (zlib) | position unchanged, reused | PASS |
| `SEEK_END -4` | last 4 bytes, final position = size, reused | PASS |
| `pread(0, 4, 8)` then `read(0, 4)` | pread bytes plus head, final position 4, reused | PASS |
| failed `SEEK_SET -1` | command stays eligible, position 4, reused | PASS |
| `dup(0)` then seek the alias | `Unknown`, never `Reused`, reason names the alias | PASS |
| `SEEK_DATA` | `Unknown`, never `Reused`, reason names whence 3 | PASS |
| different initial offset | no reuse of the zero-start record, correct bytes | PASS |
| content mutation | no reuse, correct new bytes, correct final position | PASS |

Every reused result is compared with a fresh native run and with the caller's expected offset;
the test fails on either a byte difference or an offset difference.

## 5. zlib decompression

`./minigzip -d` with a regular-file stdin now classifies `Guarded`, executes on the first run
and reports `Reused` on the second, with stdout byte-identical to a native decompression
(SHA-256 prefix `7f05e853c4cbd741`, 2,026,316 bytes in the reproduction). In both Phase 2J
sessions, `./minigzip` and `./minigzip -d` both report `Reused` under `auto` and `auto-v1`.

## 6. Limits that remain

- **Concurrent observers.** Reuse skips the reads and jumps the description to the final
  position. Another process sharing the description could observe fewer intermediate reads
  than a direct run. The same limitation already applied to sequential reads; it is not made
  worse, but it is not solved. The model refuses if the position moved before validation.
- **Seek history is not replayed**, only the final position. Nothing else is caller-visible.
- **Aliases** of fd 0 are refused rather than tracked, so a tool that seeks a `dup` of stdin
  stays ineligible. Tracking per-open-file-description identity would be the next step.
- **`SEEK_DATA`/`SEEK_HOLE`** stay refused; a content hash does not prove extent layout.
- **atime** is not reproduced (pre-existing): a hit performs no reads, so it may update atime
  fewer times. atime is not part of the stdin guard.
- **File mutation during execution** is not detected mid-run; the guard compares content
  before reuse, as it did before this change.
- The contract is Linux x86_64 ptrace, single traced process tree; no claim about seccomp or
  Landlock enforcement is added here.

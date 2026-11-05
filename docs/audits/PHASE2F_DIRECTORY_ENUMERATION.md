# Phase 2F: the directory enumeration model

Phase 2E found that `getdents64` had been listed as a known-internal syscall and therefore
**silently ignored**, which is unsound: a program could list a directory and emit output no guard
covered. Phase 2E made it fail closed. This phase implements a real dependency.

## 1. What is observed

`getdents64(fd, buf, count)` returns a byte stream of `linux_dirent64` records. Each record carries
`d_ino`, `d_off`, `d_reclen`, `d_type` and a NUL-terminated name. The program observes:

- the exact set of names;
- the **order** in which the kernel returned them;
- `d_off` cookies for each entry, which the program may use to resume enumeration;
- `d_type` for each entry;
- the buffer fill pattern: how many bytes each call returned, including the final short/zero read.

Hashing a sorted filename set preserves none of the ordering, cookie or `d_type` information, and
cannot distinguish a program that read four entries in one call from one that read two and two.
The model therefore records the stream itself.

## 2. Model

`DirectoryEnumerationRead` contains the resolved directory path, its fingerprint, the credential
digest, the mount-namespace identity, and a `Vec<DirectoryEnumerationRequest>`:

```rust
pub struct DirectoryEnumerationRequest {
    pub requested: u64,   // count passed to getdents64
    pub returned: Vec<u8>, // exactly the bytes the kernel wrote
}
```

One request per `getdents64` call, in order. `DirectoryEnumerationRead` is produced by
`PendingSyscall::Enumerate`; the tracer captures the returned buffer (`EnumerationState`) rather than
parsing it, so names, cookies, `d_type`, padding and ordering are all preserved bit-for-bit.

## 3. Validation

`replay_directory_enumeration` opens the recorded path and issues `getdents64` with each recorded
requested size in sequence, comparing each returned buffer to the recorded bytes. Any difference —
including a shorter or longer stream, a reordered entry, a changed `d_type`, or a changed cookie —
invalidates. The path is also fingerprinted, and the credential and mount namespace must match.

This is sound because the bytes are the observation. If the replay reproduces them exactly, the
program would have parsed exactly the same entries in exactly the same order; if it does not, the
entry is discarded and the command runs normally.

## 4. Refusals

Enumeration refuses, rather than approximates, when:

- the first `getdents64` starts at a non-zero directory offset (a preceding `lseek`), because the
  recorded stream would not begin where the program began;
- the recorded stream exceeds 1 MiB (`MAX_ENUMERATION_BYTES`), to bound memory and replay cost;
- the descriptor does not resolve to a directory path the tracer can re-open;
- the directory is not readable under the recorded credentials at validation time.

A large tree (`tar` of a big directory) is therefore refused by the size bound even before its other
blockers. This is a deliberate reach limitation; the bound is a constant, not a heuristic.

## 5. Mutation and concurrency

Any entry creation, deletion or rename changes the byte stream (names, `d_off` cookies, and often
order), so the guard invalidates. The test
`directory_enumeration_guard_replays_the_exact_entry_stream` requires a hit on replay and a
deoptimization after adding an entry. Concurrent enumeration by another process does not change the
stream; concurrent mutation is caught by the comparison at validation. Mutation between validation
and restore is the general TOCTOU limitation.

## 6. Why this is not a sorted-set digest

A sorted digest would accept a directory whose entries are identical but whose kernel order changed.
Programs print directory listings (`ls`, `find`, documentation generators, `nm`'s plugin search) in
kernel order, so that acceptance would be a false reuse with directly visible output. The byte
stream also preserves `d_type`, which a name set cannot, and the per-call split, which matters for
programs that stop after a short read.

## 7. What it unlocked

`nm`'s plugin lookup was the concrete case: four `getdents64` calls on
`/usr/lib/x86_64-linux-gnu/bfd-plugins`, previously a refusal, now a modelled dependency
(`DIRLIST ... (4 calls)` in `benchmarks/results/phase2f/explain-nm.txt`). `nm` then refuses on
`getrandom` and `prlimit64`, so no hit results. `tar` advances past enumeration and `statfs` and
also stops at `getrandom`.

The minimum mechanism needed for a broader immutable-tree model is a **directory version** or
generation counter that the kernel guarantees across the whole subtree — Linux does not expose one.
Without it, the choice is per-stream byte replay (implemented) or refusing large trees (the 1 MiB
bound). A subtree-merkle approach would still need a way to detect mid-walk mutation, so it does not
remove the need for the stream comparison.

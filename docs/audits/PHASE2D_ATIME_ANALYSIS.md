# Phase 2D: the timestamp invalidation defect

Host: Linux 6.1.102, x86-64, 2 vCPU, ext4 mounted `rw,relatime`. Working tree at the Phase 2C tip
plus this phase's changes; the trace/guard code is unchanged from `bd59a0e`.

## Summary

The Phase 2C note that a **future-dated input mtime** caused repeated deoptimization was **wrong**,
and so was the accompanying atime hypothesis. Reproduction at this commit shows the invalidation
does not come from the input file's `atime` at all. It comes from a `FileMetadata` dependency on a
**directory**: the parent directory of every path the command opens.

That dependency is stored as a full `FileFingerprint`, which includes `atime`, `mtime`, `ctime` and
`size`. A directory's `mtime` and `ctime` change whenever *any* entry in it is created, removed or
renamed — including the command's own output. The guard therefore refuses a reuse that no
observation of the traced program justifies, and it does so on the ordinary developer pattern of
writing an output next to the input.

## What was measured

Reproduction: `gzip -9 -c in.txt` from a directory whose contents change between runs.

| Sequence | Result |
| --- | --- |
| record, then repeat with the directory untouched | `Reused` (3/3, and 4/4 in a second cache) |
| create an unrelated file in that directory, then repeat | `Deoptimized` |

`explain` names the failing guard and both fingerprints. In the failing case the fields differ in
`modified_ns` and `changed_ns`; `accessed_ns` is **identical**:

```
deopt     file metadata changed
expected  FileFingerprint { device: 65024, inode: 262299, size: 4096, mode: 16877,
                            accessed_ns: 1793650824921065357,
                            modified_ns: 1793650824741065357, changed_ns: 1793650824741065357 }
actual    FileFingerprint { device: 65024, inode: 262299, size: 4096, mode: 16877,
                            accessed_ns: 1793650824921065357,
                            modified_ns: 1793650825113065357, changed_ns: 1793650825113065357 }
```

`mode: 16877` is `0o40755`: a directory, not the input file.

Who the dependency belongs to was isolated by moving the input away from the working directory:

```
cwd = /tmp/w (empty)      argv = gzip -9 -c /tmp/q/in.txt
recorded: FileMetadata /tmp/q      <- the input's parent directory
          File       /tmp/q/in.txt
          FileMetadata /tmp/q/in.txt
```

The working directory `/tmp/w` does not appear. So the dependency is produced when a path is
**opened**, for that path's parent, not for the cwd and not for the input itself.

Additional controls:

- `/bin/true` records no directory dependency at all.
- `cat in.txt` records none either; it is refused earlier for `getrandom`.
- The Phase 2C `20/20 Reused` gzip result holds at this commit **when nothing touches the input
  directory during the run**. It is a property of that benchmark's setup, not of the system.

## Why this is not the access-time problem it looked like

For a regular file read, the recorded fingerprint is compared first and the content hash is the
fallback. `metadata_change_allows_hash_fallback` permits that fallback when `mode`, `uid` and `gid`
are unchanged, so an input whose `atime` advanced under `strictatime` or under `relatime` with
`atime < mtime` still reuses — it pays a full BLAKE3 pass instead of a `stat` comparison, which is a
performance cost, not a correctness failure. [INFERENCE: derived from `validate_all` and
`metadata_change_allows_hash_fallback`; not measured under a `strictatime` mount, which this host
cannot create because remounting requires privileges the session does not hold — BLOCKED.]

Directories have **no** content hash, so a directory fingerprint mismatch cannot fall back. That is
why the symptom was a hard, permanent `Deoptimized` rather than a slower hit.

`atime` is still part of the fingerprint for genuine `stat` observations, and it must stay: a
program can `stat` a path and print `st_atime`, so dropping the field globally would be unsound.

## Filesystem policies

| Policy | atime update on read | Effect here |
| --- | --- | --- |
| `relatime` (this host) | only if `atime < mtime` or older than 24h | file reads usually leave `atime` alone; when it does advance, the hash fallback covers files |
| `strictatime` | every read | every hit on a read file pays a content hash (correct, slower). BLOCKED to test: no mount privilege |
| `noatime` | never | `atime` is stable; no effect |
| `nodiratime` | never for directories | relevant only to directory reads |

The defect above is independent of all four: it is a `mtime`/`ctime` change on a directory, which
`noatime` does not prevent.

## Remedy that was scoped and deliberately not applied

The dependency is over-strong in a way that could be corrected without weakening any real
dependency: a directory used only to **resolve** a child path needs its *identity* — `device`,
`inode`, and the `mode`/`uid`/`gid` that decide search permission — and not its `mtime`, `ctime`,
`atime` or `size`. A process cannot learn a directory's timestamps by resolving a path through it.

Doing that soundly requires distinguishing a resolution-time directory snapshot from a directory the
program genuinely `stat`ed, because both currently serialize as `InputDependency::Metadata`. That
means a new dependency/guard variant carrying the reduced comparison. The recording site for the
parent-directory snapshot was **not located** in this session: it is not in `open_pending`, not in
`resolve_path`, and `record_metadata` is only reachable from an actual `newfstatat`. Shipping a
guard-level change (for example, "compare directories on identity only") without that distinction
would silently stop noticing a genuine directory `stat` whose `mtime` reached the output, which is
the exact class of unsoundness this project exists to avoid. It is therefore recorded as an open
defect with a scoped fix, not patched speculatively.

[UNVERIFIED: the provenance of the parent-directory snapshot. What is verified is its existence, its
path, its full-fingerprint serialization, and that a directory `mtime` change invalidates reuse.]

## Reproduction

```bash
mkdir -p /tmp/probe && cd /tmp/probe
python3 -c "import random; random.seed(7); open('in.txt','w').write('x'*480000)"
export TRACEJIT_CACHE_DIR=/tmp/probe/cache
tracejit run -- gzip -9 -c in.txt >/dev/null      # records
tracejit run -- gzip -9 -c in.txt >/dev/null      # Reused
touch unrelated.txt
tracejit run -- gzip -9 -c in.txt >/dev/null      # Deoptimized
tracejit explain                                   # shows the directory fingerprint above
```

# Metadata guard correctness

Question: can TraceJIT safely stop guarding whole `stat` structures and guard
only the fields a program actually used, which would let more workloads reuse?

Short answer: **no general rule is sound, and none was adopted.** The audit found
that the current guards are already field-precise in the one direction that is
provable (content equality can absorb timestamp drift only when mode and
ownership still match), and that the remaining fields are all observable. Making
the guard narrower would have been a heuristic dressed as analysis. Eligibility is
therefore unchanged, and this document records why, with an adversarial matrix
that would fail if the conservative behaviour were ever removed.

## 1. What is observed today

| Observation path | What TraceJIT records | What a program can do with it |
|---|---|---|
| `open` / `openat` / `creat` | path, flags, mode, and the file's fingerprint + content hash | everything the descriptor allows, including the file's metadata via `fstat` |
| `stat` / `lstat` / `fstat` / `statx` | full fingerprint of the named path (device, inode, size, blocks, block size, atime, mtime, ctime, mode, link count, uid, gid, and device identity for special files) | read any subset of those fields; the trace cannot tell which |
| `access` / `faccessat` | refused: "access check cannot be guarded" | a command whose decision depends on an access check is not reused at all |
| `read` / `readdir` / `getdents` | content hash (strict) and the path set | content, names, ordering |
| missing paths | explicit absence guard | creation decisions |
| output preconditions | open flags, `allows_create`, mode, ownership, absence, hard-link and symlink status | whether the restore may legally proceed |

Two deliberate details:

* **Content is authoritative in strict mode.** A `FileMetadata` guard is paired
  with a `ContentHash` guard for the same path; when the metadata differs, the
  pair still validates if `metadata_change_allows_hash_fallback` holds - which
  requires **mode, uid and gid to be unchanged** - and the content hash matches.
  So permission or ownership changes always fail, while timestamp/size drift on a
  file that is byte-identical can pass *when the trace recorded a hash pair*.
* **TraceJIT's own bookkeeping cannot poison the identity.** Reading a file to
  hash it updates its atime. The stdin fingerprint zeroes `accessed_ns` for that
  reason, and the paired-hash path re-reads from the same descriptor. This is
  the atime issue Phase X reported (`tr`), not a classifier exception.

## 2. The fields, one by one

| Field | Can it influence program behaviour? | Sound to drop from the guard? |
|---|---|---|
| file type | yes: `open` fails, `readdir` reports it, `S_ISDIR` branches | no |
| mode | yes: permission checks, `stat` output, `test -x` | no |
| size | yes: read counts, `seek`, `stat` output, allocation | no - but content hash subsumes it when paired |
| link count | yes: hard-link identity, `stat` output, "same file" decisions | no |
| uid / gid | yes: `stat` output, permission decisions | no (never relaxed) |
| mtime | yes: `stat` output, `tar`/`zip` headers, `make`, `find -newer` | no |
| ctime | yes: `stat` output, `find -cnewer`, change detection | no |
| atime | yes: `stat` output, `find -anewer`; also **mutated by TraceJIT's own hashing** | only via the paired-hash rule |
| inode / device | yes: `stat` output, hard-link grouping, `st_ino` comparisons | no |

"There is no evidence the program read field X" is not available from ptrace:
the kernel returns a whole structure and userspace picks fields afterwards. The
only sound statement is the one already implemented - identical content *and*
unchanged mode/ownership makes timestamp drift unobservable *for a program that
only reads content*, and that is exactly the case the fallback permits.

## 3. Adversarial matrix (measured)

`benchmarks/phase_ac/metadata_guards.py` runs `gzip -9 -c corpus.txt` under
`allocator-entropy-v1`: one cold run, one mutation applied identically to a
native twin and to the traced workspace, then a native run and a traced run
compared by the independent oracle.

| Mutation | Traced decision | Reused | Observation matches native |
|---|---|---|---|
| unchanged (control) | `Reused` | yes | yes |
| mtime +5 s, identical content | `Deoptimized` | no | yes |
| atime +5 s, identical content/mtime | `Deoptimized` | no | yes |
| chmod 640 then 644 (new ctime) | `Deoptimized` | no | yes |
| identical bytes rewritten, mtime restored | `Deoptimized` | no | yes |
| unlink + recreate, identical bytes and mtime | `Deoptimized` | no | yes |
| mode 0644 -> 0600 | `Deoptimized` | no | yes |
| replaced by hard link to an identical copy | `Deoptimized` | no | yes |
| replaced by symlink to an identical copy | `Deoptimized` | no | yes |

Summary: 9 mutations, 8 deoptimisations, 1 legitimate control hit, **0 incorrect
hits**, and every after-mutation observation matched native execution.
Evidence: `benchmarks/results/phaseac/metadata_guards.json`.

The mtime row is the important one. `gzip` without `-n` writes the input's mtime
into its output header, so an mtime-only change *does* change the command's
observable output. The guard refused the hit. A field-precise guard that treated
"content equal" as sufficient would have produced a wrong result here - which is
precisely the class of mistake this mission forbids.

## 4. Why no change was merged

* No field-precise rule could be proved sound. Dropping mtime would break
  metadata-serialising tools (measured above); dropping ctime would break change
  detection; dropping inode/link count would break hard-link semantics that the
  oracle already scores.
* The one relaxation that *is* sound is already present (paired content hash with
  mode/uid/gid equality), and it was not extended.
* Eligibility would not improve measurably: the workloads that refuse do so for
  structural reasons (`fcntl` on inherited descriptors, `sched_getaffinity`,
  `prlimit`, clocks, unmodelled syscalls), not because a timestamp differs. The
  refusal reasons in `benchmarks/results/phaseac/noncompiler_probe.json` and the
  smoke run show no workload whose only obstacle is an input timestamp.

## 5. Eligibility before and after

No guard code changed, so the numbers are identical by construction; they are
recorded here so a later change can be compared against them.

| Corpus | Rows | Reused | Refused | Tool unavailable | Eligible but no hit |
|---|---|---|---|---|---|
| Phase AA committed baseline (`benchmarks/results/phaseaa1/results.json`) | 177 | 28 | 129 | 15 | 5 |
| Dev split at this head, both policies (`benchmarks/results/phaseac/smoke/results.json`) | 42 | 10 | 30 | 2 | 0 |
| Phase AC non-compiler corpus, 16 configurations (`noncompiler_probe.json`) | 16 configs x 3 policies | 10 configs reusable | 6 configs refused | 0 | 1 (nm, eligible but the warm run did not hit) |

Incorrect hits: **0** in every measurement above.

## 6. Residual limitation worth naming

`nm-symbols-real-binary` was classified `Guarded` and eligible, but its warm run
did not reuse (`eligible_but_no_hit`). The cause was not isolated in this phase;
it is recorded rather than explained, and the workload contributes no claimed
saving. It is a candidate for a later investigation into admission and identity
stability, not a correctness finding.

## 7. Recommendation

Keep the conservative guards. If field-precise guards are ever revisited, the
minimum bar is: (a) a mechanism that proves which fields the process observed -
not a heuristic from repeated runs; (b) the adversarial matrix above extended to
every relaxed field; (c) no workload added to the eligible set whose only change
is the relaxed field. None of that exists today, and the measured matrix shows
why the bar should be high.

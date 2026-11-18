# Phase W1: snapshot-provenance correctness audit

Audits the Phase W optimisation (`prestate_snapshot` dependency elision, PR #40) independently:
re-derives the invariants, builds a counterexample per axis, and repairs what did not hold.

Base: `main` = `cb4783f10bc4de0c8b7cf269121cfd83710730df`. Audit head: see `git log` on
`research/phase-w`. Baseline binary for every comparison is built from `cb4783f`
(`/tmp/tj-base-target/release/tracejit` when this was measured). Host: Linux 6.1.102, x86_64.

Harness: `benchmarks/phase_w1/audit.py` (13 cases; native vs cold vs warm, byte-exact files,
symlink targets, modes, exit status, stdout/stderr). Raw result:
`benchmarks/results/phasew1/audit.json`.

## 1. What Phase W claimed, and what it got wrong

The rule was: a tracer snapshot taken immediately before a `delete`/`rename` is not an input, so
drop it whenever the same execution later re-creates the path (the path's last write is not
`Delete`). Terminal deletions keep the exact content guard.

That is correct for `unlink` and wrong for `rename`, because the two syscalls destroy the pre-state
in different ways:

- `unlink(P)`: the bytes named by `P` become unreachable. If the run re-creates `P`, its content is
  authored by the run, so the old bytes cannot reach any output.
- `rename(P, Q)`: the bytes named by `P` **are still reachable — at `Q`**, and `Q` is an output the
  cache restores. The source snapshot is not a superseded pre-state; it is content flowing into
  `Obs(E)`.

The tracer emits `Delete(P)` + `RenameDestination(Q)` for one `rename`, so `P` looked exactly like
an unlinked path. When the program then re-created `P` (`mv out.o out.o.bak && cc -o out.o`), both
snapshots were elided and the record had no guard on the bytes it relocated.

### Counterexample (incorrect HIT)

`fixture_driver.c: rename_aside_recreate` — `rename(output.txt, second.txt)`, then recreate
`output.txt` with fixed bytes.

| | `second.txt` after execution |
| --- | --- |
| native, `output.txt` = `old result` | `old result` |
| native, `output.txt` = `changed result that is longer` | `changed result that is longer` |
| TraceJIT warm, pre-state `changed result that is longer` | **`old result`** (restored from cache) |

The warm run reported `kind: Reused`, `classification: Guarded`, and restored bytes native execution
never produces. This blocks merge; it is a wrong filesystem result, not a missed optimisation.

## 2. Repair

The source side of a rename is provenance `false` (an ordinary content read); the destination side
stays `true` (superseded pre-state). Nothing else about the rule changes.

- `crates/tracejit-trace/src/linux.rs`: `record_snapshot` takes the provenance it is recording;
  `rename` records the source as a content read and the destination as pre-state; `delete` records
  pre-state. The source read is still filtered by `precedes_first_write`, so a path this same
  execution created before renaming it (compiler temp objects) adds no guard.
- `crates/tracejit-effects/src/lib.rs`: documentation of the invariant at the field and at the
  elision site.

Effect on the measured workload: none. `cc` unlinks its object, and none of the 27/48-invocation
sessions contain a rename whose source is re-created.

## 3. Invariant matrix

`benchmarks/phase_w1/audit.py`: 13/13 cases pass (`files`, `streams`, `decision`), 0 incorrect hits.

| axis | case | decision | evidence |
| --- | --- | --- | --- |
| successful `unlink` → recreate | `replace_output` | Reused | output bytes match native; pre-state elided |
| successful `rename`, source re-created | `rename_aside_recreate` | Deoptimized | guard fails on the moved bytes; destination matches native |
| `rename` destination replaced | `rename_over_existing` | Reused | destination pre-state elided; source bytes still guarded |
| failed `unlink` (`EISDIR`) | `failed_unlink_directory` | never Reused | `Unknown`: failed filesystem effect is not guardable |
| failed `rename` (`ENOENT`) | `failed_rename_missing` | never Reused | `Unknown`: failed rename is not guardable |
| partial execution, path ends absent | `partial_then_exit` | never Reused | `FileHash` guard on the removed bytes |
| terminal delete | `delete_only` | never Reused | `FileHash` guard on the removed bytes |
| delete → create → delete | `delete_create_delete` | never Reused | last write is `Delete`, so the pre-state stays |
| multiple writes to one path | `multiple_writes` | Reused | last write authors the content |
| program read before replacement | `read_then_replace` | never Reused | program read (`prestate_snapshot: false`) is never elided |
| symlink pre-state | `symlink_delete_recreate` | never Reused | snapshot is `Unavailable` → `Unknown` |
| hard-link alias | `delete_recreate` + `twin.txt` | Reused | twin keeps its bytes; it is not an output |
| same bytes, new inode | `replaced_inode` | Reused | elided pre-state does not depend on inode identity |

Permanent regressions for the defect: `rename_source_bytes_are_an_input_even_when_the_source_is_recreated`
(integration), `a_rename_destination_prestate_is_elided_while_its_source_stays`,
`records_written_before_the_marker_existed_stay_strict` (unit).

## 4. Proof assumptions

1. **Successful effects only.** `complete_failed_syscall` records a failed `delete`/`rename` as
   `Unknown` (unreusable), except `ENOENT`, which records absence as an ordinary metadata read
   (`prestate_snapshot: false`) that survives independently of the snapshot. No write effect is
   emitted for a failed mutation.
2. **Order.** `Collector::push` assigns one global monotonic `sequence` across tracees; `last_write`
   takes the maximum, `precedes_first_write` compares read sequence against the first write of that
   path. A snapshot is pushed at syscall entry, so it always precedes the write it describes.
3. **Reachability.** An elided pre-state can only be observable if the same inode's bytes survive
   under some pathname. `unlink` and rename-destination replacement remove the name and the run's
   own write defines the final bytes; `link`/`linkat` are refused (`Unknown`), so no alias can be
   created by the execution that would revive them. The one surviving-name case is a rename, and its
   source is now always a dependency (section 2).
4. **Pre-existing aliases.** A twin hard link that existed before tracing is not written by the run
   and is not an output, so native and replay both leave it untouched.
5. **Output pre-state.** `OutputPrestate` guards are separate `ReadEffect::OutputPrestate` entries
   produced from the toolchain's own metadata reads; the elision touches `File`/`FileMetadata`
   reads only, so output-prestate sufficiency is unchanged. Corrupted and deleted outputs are still
   overwritten from the cache (Phase W `corrupt`/`delete` scenarios).
6. **Structural pre-states.** `unlinkat(AT_REMOVEDIR)` records the directory's metadata as its
   snapshot; re-creating the path (`mkdir`) elides it. The directory's entries are gone by
   definition (`rmdir` requires empty), and the new directory's mode comes from the run's `mkdir`,
   so the old mode/ownership cannot reach an output.
7. **Schema.** `prestate_snapshot` is `#[serde(default)]`, so records written before the field
   existed load as ordinary reads (strict). The stored `input_dependencies` list — not the effect
   flag — is what replay consumes, so a record written by this binary also replays correctly under
   an older one. `CACHE_SCHEMA_VERSION` stays 2: no reader can misinterpret a record either way.

## 5. Performance, re-measured after the repair

Three units, real `cc -O2 -c`, `compiler-runtime-v1`, edits at rounds 3 and 6 (27 invocations) and
7 and 12 (48). Two independent runs each; medians shown.

| arm | 27 invocations | 48 invocations |
| --- | --- | --- |
| native | 15.072 s | 27.250 s |
| `main` (`cb4783f`) | 14.714 s (1.02×) | 17.298 s (1.58×) |
| fixed | **10.164 s (1.48×)** | **13.748 s (1.98×)** |
| ccache 4.9.1 | 5.636 s | 5.807 s |
| sccache 0.10.0 | 5.860 s | 6.036 s |
| GNU make | 5.160 s | 5.084 s |
| ninja | 5.842 s | 5.003 s |

Deoptimisations per session: 12 → 6 in both, i.e. one per edit instead of two; hits 12 → 17 (27
invocations) and 33 → 39 (48). All final objects byte-identical to native in every arm. The
compiler-specific caches and the build schedulers remain 1.8×–2.7× faster than TraceJIT on compile
workloads; nothing here changes the Phase W conclusion that a whole-command cache cannot win a
compile-caching race.

## 6. Gates

`cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets --all-features -D warnings`,
`cargo test --workspace` (72/72 Linux integration including the new regression, 29 effects,
36 guards), `python3 scripts/modelcheck/check_state_machines.py` (0 violations),
`scripts/phase_k4_restore_fault.sh` (soft-fail retrace + hard-kill recovery PASS),
`python3 benchmarks/differential/fuzz.py --seed 29` (120 ok, **0 incorrect hits**).

## 7. Remaining limitations

- Phase W's metadata barrier is unchanged: gcc's PCH `stat` of the header still deoptimises a
  byte-identical rewrite with a new mtime, and revisiting an earlier input state still misses.
- `rename` sources are now guarded even when the execution replaces the destination again later;
  that is conservative and cost nothing in the measured sessions.
- A `delete → create → delete` sequence keeps the *first* pre-state guard (the last write is a
  delete), so changing the bytes the run destroyed deoptimises. Sound, slightly over-strict.
- PR #40 is still a draft authored by the repository owner; this workspace cannot mark it ready,
  merge it, or edit its description (no API credentials), and therefore cannot verify post-merge
  `main` CI. Everything up to that point is prepared and pushed.
- No v0.3 release: the published beta is untouched and no tag was moved.

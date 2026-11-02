# Reassessment of internal-pipe correctness

Commit: `b57bc7f` (mechanism), `bd59a0e` (measurements). Scope: the pipe model added in Phase 2B,
re-examined against what it actually guarantees.

## What the implementation enforces

For a pipe created inside the traced tree, reuse is permitted only when all three hold:

1. exactly one process wrote to the pipe;
2. no read returned fewer bytes than requested and was later followed by more data;
3. no write was partially accepted, and no `readv`/`writev` length was untracked.

Violations are attached to the execution as unknown effects naming the pipe and the observation.

## The precise claim

If a single writer produced the stream, and every read either received its full request or was the
final data before end-of-file, then the sequence of read results is determined by the concatenated
byte stream and the sequence of requested sizes. A fresh execution of the same program on the same
inputs therefore observes the same read sequence, hence the same behaviour.

That is a claim about the **reader's observations**, and it is the part a syscall tracer can actually
establish. It is not a claim that every program's output is a function of the byte stream: a program
whose behaviour depends on chunk boundaries would be mis-served, and condition 2 is exactly what
excludes the observable case where boundaries are demonstrably schedule dependent.

## What it does not guarantee

- **It constrains the observed sequence, not the program's semantics.** A reader that consumes the
  whole stream to EOF and never sees a short-then-more pattern is safe in this model even if it is
  internally "chunk-sensitive", because its chunk sizes are fixed by its own request sizes.
- **EOF is the load-bearing condition.** Without observing `read → 0`, a reader may have stopped
  early; a writer that then succeeded only because its data fit in the 64 KiB buffer would look fine
  in the recorded run and behave differently under a different schedule.
- **Multiple writers are never admitted**, even when each writes atomically, because inter-process
  ordering is not observable.
- **It says nothing about `fstat` on a pipe**, which reports buffered byte counts and is refused.

## Evidence

| Test | What it pins |
| --- | --- |
| `a_scheduler_stable_pipe_transfer_is_not_an_effect` | the admitted pattern produces no effect |
| `a_short_read_followed_by_more_data_refuses_reuse` | condition 2 |
| `a_short_read_before_end_of_file_stays_stable` | EOF legitimises a short final read |
| `two_writers_make_byte_order_scheduling_dependent` | condition 1 |
| `a_partial_write_refuses_reuse` | condition 3 |
| `an_untracked_vectored_transfer_refuses_reuse` | condition 3 for `*v` calls |
| `pipe_roundtrip` (fixture) | one real create/write/close/read returns `Guarded` |
| `pipe_short_read` (fixture, ordered by a second pipe) | a genuine short-then-more returns `Unknown` |

The second fixture is ordered by a synchronisation pipe instead of a sleep, so it cannot flake.

## Measured consequences

Real pipelines are refused by condition 2: `shell-pipeline` records two occurrences, `groff` one.
That is not a bug in the check — a streaming producer legitimately hands its consumer partial chunks
— but it does mean whole-command reuse cannot certify a streaming pipeline. `shell-pipeline` is also
blocked by `fstat` on a pipe and a failed `tcgetattr` on fd 0.

## Comparison with prior systems

Riker (Curtsinger, USENIX ATC 2022) is a forward build system that guarantees correct incremental
builds from simple specifications. Published descriptions place its correctness argument at the level
of the observed commands/processes it replays rather than at the level of an arbitrarily interleaved
pipeline evaluated as one unit — **[INFERENCE]**: the paper was not read for this phase, and this
comparison should not be cited as a claim about Riker's internals until it is. The structural point
that *does* follow from the architectural difference is:

- A system that caches **per process** never has to certify an interleaving: each stage's inputs are
  its own reads, and its output writes are replayed into the next stage's inputs.
- A system that caches **per whole command**, as TraceJIT does, must either certify the interleaving
  (this model, which refuses streaming cases) or change its unit of reuse.

That is the honest framing of the remaining pipeline gap: it is an architectural limit of
whole-command reuse, not a missing syscall.

## Unresolved risks

- Writer termination by signal is not distinguished from clean exit; a reader that observes EOF still
  satisfies condition 2, which is correct, but the *exit status* of a killed producer is part of the
  recorded result and is replayed as recorded.
- `SCM_RIGHTS` descriptor passing is unmodelled, so a pipe end can leave the traced tree undetected if
  it is handed over a socket; socket operations are already `NONDETERMINISTIC`, which covers the
  currently reachable paths.
- Pipe capacity is not observed. Condition 2 is designed to be independent of it, but this was not
  tested under a reduced `F_SETPIPE_SZ`.

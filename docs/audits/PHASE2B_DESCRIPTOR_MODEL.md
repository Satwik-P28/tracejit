# Priority 1 — internal pipe and descriptor model

Commit: `b57bc7f`. Everything below was measured on this host (Linux 6.1.102, x86-64).

## What was missing

Every descriptor that was neither a known file nor a socket fell into `FdState::Other`. Reads from it
produced `read from unclassified fd N`, writes produced an `IpcWrite` (nondeterministic), and
`pipe2` itself was an unmodeled syscall. The Phase 1 census ranked this second: 5 workloads blocked
by `pipe2`, 4 by unclassified descriptors. Since a shell pipeline, a compiler driver and `groff` all
communicate over pipes, nothing in that class could ever be reused.

## The model

`FdState::InternalPipe { pipe, readable, writable }` identifies a pipe by an id allocated when the
tracer observes `pipe`/`pipe2` returning, not by descriptor number. Descriptor numbers are reused
constantly, so an id is the only stable handle.

- **Creation.** The returned descriptor pair is read from the traced process's memory at syscall
  exit (two adjacent `int`s). If the pair cannot be read, the trace gets an unknown effect and cannot
  be reused.
- **Dup.** `dup`, `dup2`, `dup3` and `fcntl(F_DUPFD*)` copy the variant, so a duplicated pipe end
  keeps its identity.
- **Fork.** A child state is a clone of the parent's, so both processes refer to the same pipe id —
  which is exactly what makes the multi-writer rule detectable.
- **Exec.** Execution `exec` keeps `fds` and drops only close-on-exec entries, so pipe ends survive
  into the next process of a pipeline.
- **Close.** Removes the descriptor; the pipe record outlives it.

## When pipe traffic permits reuse

A pipe's bytes are a function of inputs that are already guarded, so the bytes themselves are not a
new dependency. What is *not* implied is that the reader's observations are reproducible: the kernel
packetises the stream according to scheduling. Three conditions are checked, each from the trace, and
reuse is permitted only when all hold:

1. **One writing process.** The write order is then that process's program order. Two processes
   writing the same pipe interleave by scheduler decision.
2. **No short read followed by more data.** A read either receives its full request or it is the
   final data before end-of-file. Under that pattern the sequence of read results is determined by
   the concatenated stream and the requested sizes alone, so a re-run with the same inputs must
   observe the same sequence. A short read that is later followed by more data means the reader was
   served a partial chunk that a different schedule could have delivered whole.
3. **No partial or untracked transfer.** A write that was only partly accepted, or a `readv`/`writev`
   whose length was not extracted, means the split is unknown.

Any violation appends one unknown effect naming the pipe and the observation that triggered it, so
the run deoptimizes with a precise reason instead of a generic one. This is why the reason text now
appears in the census.

`fstat` on a pipe is refused explicitly: `st_size` for a pipe is the number of buffered bytes, which
is a scheduling artefact, and the tracer cannot know whether the program reads it.

## Evidence

Unit tests (`crates/tracejit-trace/src/linux.rs`):

| Test | Expectation | Result |
| --- | --- | --- |
| `a_scheduler_stable_pipe_transfer_is_not_an_effect` | one full write, one short read before EOF → no effect | PASS |
| `a_short_read_followed_by_more_data_refuses_reuse` | unknown effect | PASS |
| `a_short_read_before_end_of_file_stays_stable` | no effect | PASS |
| `two_writers_make_byte_order_scheduling_dependent` | unknown effect | PASS |
| `a_partial_write_refuses_reuse` | unknown effect | PASS |
| `an_untracked_vectored_transfer_refuses_reuse` | unknown effect | PASS |

End-to-end fixtures (`tests/fixtures/`):

| Fixture | Behaviour | Classification | Result |
| --- | --- | --- | --- |
| `pipe_roundtrip` | one process writes 9 bytes, closes the write end, reads 9 into a 64-byte buffer, writes them to stdout | `Guarded`, eligible | PASS |
| `pipe_short_read` | writer sends one byte, waits until the reader has consumed it, then sends another; the reader's 64-byte request is satisfied with 1 byte | `Unknown` (schedule dependent) | PASS |

The second fixture is ordered through a second pipe rather than a sleep, so the test is deterministic
instead of racy.

## Measured effect on the real-world census

`benchmarks/results/phase2b/census-b57bc7f/` versus `benchmarks/results/phase2/census-2edbf0d/`:

- `pipe2` (293) disappears from the unmodeled-syscall ranking entirely (was 5 workloads).
- `unclassified_descriptor` disappears from the blocker ranking entirely (was 4 workloads, 11
  occurrences).
- Both are replaced, for three workloads, by the model's own precise refusals:
  `pipe N: a read returned less than it requested and more data followed` (3 occurrences) and
  `fstat on pipe descriptor N reports buffered byte counts` (6 occurrences, all in one workload).

Eligibility did not move (0 of 9). That is the honest outcome: the model removed a blind spot and
made the remaining obstruction legible, but real streaming pipelines violate condition 2. `cat`
hands `sort` several partial chunks because its writes and the reader's reads are interleaved, and no
observation available to a whole-command tracer proves the program's output is insensitive to those
boundaries.

## Why the obvious relaxation is unsound

The tempting fix is to ignore short reads because "the concatenated stream is the same". It is not
the same for the program: `head -1` stops after the first line and its producer then sees `EPIPE`,
and a reader that processes each chunk as it arrives can emit different output for different
boundaries. Detecting that is not possible from the trace alone without knowing the reader's
algorithm. Whole-command reuse therefore cannot certify a streaming pipeline; per-process reuse,
where each stage's writes are replayed as inputs to the next, can — that is a different architecture
and belongs to a later phase, not to this one.

## Not modeled

`epoll_create1`/`epoll_ctl`/`epoll_wait`, `eventfd`, `signalfd`, `timerfd`, shared memory objects,
`SCM_RIGHTS` descriptor passing, and `/dev/null` as a non-restorable output sink remain unmodeled and
fail closed.

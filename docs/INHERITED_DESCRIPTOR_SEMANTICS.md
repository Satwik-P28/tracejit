# Inherited descriptor semantics (Phase AD)

Phase AC's largest actionable refusal class was "inherited descriptor observations" blocking
`tar` and `xz`. This document separates the kernel semantics, the calls the stock programs
actually issue, the subset TraceJIT could model soundly, and the measured result — which is
that modelling the narrowest sound subset changed **no** eligibility cell in the frozen
census, so the change was reverted and the refusal retained. Negative results are results.

## 1. Kernel semantics used in the analysis

| concept | what it is | shared with other processes? | survives `exec`? |
| --- | --- | --- | --- |
| file descriptor number | an index into one process's descriptor table | no (unless `CLONE_FILES`) | yes, unless `FD_CLOEXEC` |
| descriptor-local flags (`F_GETFD` → `FD_CLOEXEC`) | one bit on that table entry | **no** — owned by the descriptor table | cleared on every descriptor that survives `exec` |
| open file description (OFD) | the kernel object holding offset and status flags | **yes** — `dup`, `fork`, `SCM_RIGHTS` share it | yes |
| status flags (`F_GETFL` → `O_NONBLOCK`, `O_APPEND`, …) | fields of the OFD | **yes** — any process holding the OFD can change them | yes |
| offset | field of the OFD | **yes** | yes |
| pipe occupancy/readiness | kernel pipe buffer state | **yes** | n/a |

Two consequences drive the design:

* `F_GETFD` on a descriptor inherited across `exec` is **always 0**: `exec` closes every
  descriptor with `FD_CLOEXEC` set and clears the flag on the survivors. Later changes can only
  come from the program itself (`F_SETFD`, `F_DUPFD_CLOEXEC`, `FIOCLEX`) or a thread sharing
  the table through `CLONE_FILES`.
* `F_GETFL` is an observation of shared, externally mutable state. It can change between two
  executions of the same command without the workspace changing at all (another process can
  set `O_NONBLOCK` on a shared pipe or terminal).

## 2. What the stock programs actually issue

`benchmarks/phase_ad/descriptor_probe.py` runs each command under `strace -f -y` and
correlates `open*` return values to separate descriptors the program created from ones it
inherited. Raw output: `benchmarks/results/phasead/descriptor_probe.json`.

| command | fcntl calls (fd, command, origin) |
| --- | --- |
| `tar -cf out.tar src` | (0,F_GETFD,inherited) (1,F_GETFD,inherited) (2,F_GETFD,inherited) (4,F_GETFL,process) (4,F_SETFD,process) |
| `tar -cf - src` | (0,F_GETFD,inherited) (1,F_GETFD,inherited) (2,F_GETFD,inherited) (3,F_GETFL,process) (3,F_SETFD,process) |
| `xz -9 -c blob` | (0..2,F_GETFD,inherited) (3,F_GETFL/F_SETFL,process) (4,F_GETFL/F_SETFL,process — **shared pipe end**) (1,F_GETFL/F_SETFL,inherited) ×2 |
| `xz -9 -k -f blob` | (0..2,F_GETFD,inherited) (3,F_GETFL/F_SETFL,process) (4,F_GETFL/F_SETFL,process) |
| `gzip -9 -n -c text` | none |

TraceJIT's refusal reasons for the same commands (two runs each, `allocator-entropy-v1`):

* `tar`: three `fcntl query 1 on inherited or unclassified fd {0,1,2}` — only `F_GETFD`.
  After those, `tar` is still `Nondeterministic`: `process read system clock: realtime` and,
  with the allocator contract, `process wrote network: failed socket control (errno 2)`.
* `xz`: the three `F_GETFD` queries **plus** `status-flag change on fd 3` and `fd 4` (its own
  pipes) and, for the stdout form, `fd 1` (inherited stdout). TraceJIT refuses `F_SETFL` on any
  description that is shared or unclassified, because the toggle is visible to another process
  and pipe readiness is scheduling state, not content.

So the descriptor blocker is real but it is not the *binding* blocker for either program:

* `tar` needs a clock model (it reads `CLOCK_REALTIME` even with `--mtime=@…`) and a socket
  control that TraceJIT does not model.
* `xz` needs `F_SETFL(O_NONBLOCK)` on its own pipe pair and on inherited stdout. That is
  exactly the class the phase was told not to expand for eligibility's sake.

## 3. The narrow promotion that was implemented and then reverted

A sound subset exists: `F_GETFD` on an inherited descriptor is self-determined, because
`FD_CLOEXEC` is descriptor-local and cleared by `exec`. The experiment:

1. Classify that query as `None` when the descriptor table is not shared (`CLONE_FILES`
   excludes the case where a sibling thread can race the query).
2. Keep `F_GETFL`, `F_GETOWN`, `F_GETLEASE`, `F_GETPIPE_SZ` and every mutating command refused.
3. Re-run the frozen non-compiler census (16 configurations × 3 policies = 48 cells) with the
   patched binary.

Result: **0 of 48 eligibility cells changed.** `tar` became `Guarded` on its dependencies but
stayed `Nondeterministic` for the clock and socket reasons; `xz` stayed refused for the pipe
status flags; no previously ineligible configuration started hitting. A unit test now pins the
retained refusal so a future phase cannot promote it by accident
(`fcntl_flag_queries_refuse_inherited_descriptors`).

The change was reverted: an unused classification relaxation is surface without purpose, and
the project's rule is to keep the simplest thing that produces a reproducible improvement.

## 4. Adversarial results

| case | expected | observed |
| --- | --- | --- |
| `F_GETFD` on inherited fd | refused today (was `None` with the promotion) | refused / `None` respectively, both fail closed on reuse |
| `F_GETFL` on inherited stdin after an external `O_NONBLOCK` change | refused | refused |
| `F_SETFL(O_NONBLOCK)` on the process's own pipe, then restoring it (`xz`) | refused | refused, reason names the shared description |
| `F_SETFD(FD_CLOEXEC)` then `F_GETFD` on the same descriptor | allowed (self-determined) | allowed, and the second run replays byte-identically |
| `CLONE_FILES` sibling querying `F_GETFD` | refused (race with the sibling) | asserted refused in the unit test |
| inherited descriptor > 2 | refused before lookup | refused (`inherited descriptor N beyond stdin is not modelled`) |
| `tar` with `--mtime=@0 --owner=0 --group=0 --numeric-owner` | still ineligible | ineligible: realtime clock read remains |

No false-HIT counterexample was found for the implemented subset because the subset was never
enabled in a release; the argument for its soundness is that the value is a kernel invariant
after `exec` plus the program's own calls, and the probe confirms TraceJIT's child always sees
`F_GETFD = 0` on stdio even when the caller closed stdin (TraceJIT supplies the descriptor).
That last fact is itself a wrapper-level semantic difference worth stating in the paper: under
TraceJIT a program that branches on `F_GETFD(0)` cannot observe a closed stdin, whereas native
execution can.

## 5. Conclusion

Retain the refusal. The largest actionable class is not actionable *enough*: modelling it
does not make any real workload reusable, and the remaining blockers are clock reads, socket
control and shared-description status flags — all correctness-relevant and none worth modelling
for a benchmark. `xz` and `tar` stay out of the reusable set; compression through `gzip`/`bzip2`
(which issue no `fcntl`) and archiving through `tar` with an explicit fixed clock contract
remain the documented boundary.

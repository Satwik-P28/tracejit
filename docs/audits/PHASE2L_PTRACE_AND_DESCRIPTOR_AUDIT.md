# Phase 2L — ptrace process-state repair and inherited-descriptor audit

Base `53aef79`. Host Linux 6.1.102 x86_64, glibc 2.39, 8 CPUs. Raw benchmarks:
`benchmarks/results/phase2l/`.

## 1. Process-tree audit

The Phase 2K repair is sound in its main path but had two remaining defects; both are fixed.

| Event / condition | Behaviour | Reuse effect |
| --- | --- | --- |
| `PTRACE_EVENT_FORK/VFORK/CLONE` | Idempotent `adopt_child`; a late event cannot overwrite post-exec state | clone records unknown; fork/vfork inherit |
| Child stop before the parent's event | Reconciled from `/proc/<pid>/status` (`TracerPid`, `Tgid`, `PPid`) before decoding | state copied from the real parent |
| `PTRACE_EVENT_VFORK_DONE`, `PTRACE_EVENT_EXIT` | **Not requested** in `OPTIONS`, so never delivered; no handler is claimed | n/a |
| Child reaped before its event | **Fixed:** no state is installed for a dead pid (it would never receive another status and the loop would not terminate); an unknown effect is recorded | reuse refused |
| Reparenting / `CLONE_PARENT` / TID change at exec | **Fixed:** if no tracked `/proc` parent exists, state is reconstructed conservatively from a live process and marked unknown; previously this aborted the command | reuse refused, execution preserved |
| Exec on a still-unknown pid | Explicit error: decoding without close-on-exec state would risk reuse | refuse |
| Initial child stop | Options set, group-stop resumed; adoption runs first | inherited |
| Signals / group stops | `SIGSTOP` suppressed for auto-attached children; other signals recorded and delivered; `SIGCHLD` not recorded | signals make reuse ineligible through recorded effects |
| `waitpid(-1, __WALL)` | Threads and children both observed; `ECHILD` ends the loop | n/a |
| Threads (CLONE_THREAD) | Reconciled from the group leader's state; clone still records an unknown effect | reuse refused |

Residual risk, stated rather than hidden: the reconstructed state is the parent's fd table and cwd,
which is correct for fork/vfork but is an approximation for a thread group or a reparented process.
Those paths always emit an unknown effect, so the approximation cannot produce a cache hit. The
`/proc` read and the state copy are separated by a short window; a stopped child's parent and
group identity cannot change in that window, but the fallback path does not rely on that.

Verification:

- `vfork_exec_children_are_registered_before_their_first_stop` — 160 parallel vfork+exec children;
  **failed on the pre-fix tree, passes now**, and compares exit status and stdout with native.
- `vfork_children_that_exit_without_exec_do_not_stall` — 160 parallel children that `_exit(0)`
  before exec, run under `timeout 60`; passes without stalling and matches native stdout.
- Sustained storms are part of the ordinary suite, not a one-off script.

## 2. Inherited descriptors

Supported: fd 0 is a regular file whose description has no other descriptor in the process, with
`SEEK_SET`/`SEEK_CUR`/`SEEK_END`, reads, `pread64` (which does not advance), EOF, failed seeks, and a
content hash plus start/final offsets in the guard.

Refused and fail-closed: descriptors other than fd 0, aliases (including an fd 3 duplicate created
before exec), a child's read or seek on the shared description, directory descriptors,
`SEEK_DATA`/`SEEK_HOLE`, a changed start offset, and content/inode replacement.

`kcmp` is `ENOSYS` on this kernel, so alias detection uses equal device, inode and position. This is
a conservative test, **not general alias detection**: it can refuse an independent open at the same
position, and it cannot see a second process that shares the description without holding a
descriptor in the traced process. The model checks `/proc/<pid>/fdinfo/0` after each operation and
before `exit_group`, so an out-of-band move is caught if it happens before the next operation or
exit. A move after the last operation and after exit remains invisible. That is documented as an
unsupported sharing configuration, not silently accepted: a caller that shares the description with
a concurrent writer must not rely on reuse.

zlib compression and decompression remain `Guarded` then `Reused` with byte-identical output.

## 3. Execution-fidelity matrix

`crates/tracejit-cli/tests/execution_fidelity.rs` now compares 14 workloads on exit status, stdout,
stderr, the full resulting file tree (content, mode, symlink targets) and the caller's stdin offset,
then reruns each to judge reuse. Result: **14/14 accounted, 0 fidelity failures**.

| Outcome | Count | Workloads |
| --- | ---: | --- |
| Native equivalent / safely reused | 3 | gzip compression, gzip decompression, inherited-stdin fixture |
| Executed without reuse (unsupported) | 10 | configure-shaped shell, make serial/parallel/test, sort, cc, test runner, shell mutations, pipeline, nonzero exit |
| Unavailable | 1 | autoconf (not installed) |

No workload is omitted from the denominator. A traced failure in any of these would be a release
blocker; none occurred.

## 4. Clean-commit sessions

Measured from committed source (`dirty: false`) with release binary SHA-256
`b6a9611752e5ba4b70400caa057ae089f172028df2498a3b50762b90c42fe00c`. Sessions A and B identify
`7157cc0` and `2590d1d`; the latter two commits contain only the harness dirtiness fix and raw
results, not implementation changes. Every phase succeeded and every tool artifact digest matched
the native run.

| Repo | Session | direct | never | auto-v1 | always | auto |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| zlib | A | 2800.89 | 2926.12 (0.957x) | 3512.49 (0.797x) | 6389.82 (0.438x) | **2554.46 (1.096x)** |
| zlib | B | 2900.32 | 3115.95 (0.931x) | 2542.51 (1.141x) | 6528.13 (0.444x) | **2578.17 (1.125x)** |
| bzip2 | A | 3936.69 | 3867.37 (1.018x) | 4077.23 (0.966x) | 5760.71 (0.683x) | 4004.28 (0.983x) |
| bzip2 | B | 3866.20 | 3963.90 (0.975x) | 3845.34 (1.005x) | 5727.57 (0.675x) | 3722.67 (1.039x) |

zlib's `auto` is the only repeatable net win, from reusing both `./minigzip` and `./minigzip -d`
(`Reused`, `Guarded`). **bzip2 is a negative result despite reuse**: its compression and
decompression probes report `Reused`, but the ~3 s build dominates a ~4 s session, so the net is
0.983x/1.039x. `always` is slower everywhere (0.44-0.69x). libpng and lz4 were not rerun from a
clean commit in this phase; their Phase 2K numbers (dirty-tree at `f3bd191`) remain the latest
measurements and are labelled as such.

`--admission never` is itself slightly slower than direct in most cells (0.93-0.98x, bzip2 A 1.018x),
i.e. its overhead is within run-to-run variance but not a win.

## 5. Enforcement

`tracejit doctor`: `ptrace yes`, `seccomp yes`, `landlock no`, `proven no`. `PROVEN` is **BLOCKED**
and unexercised. GUARDED reuse is not a sandbox and no formal-correctness claim is made.

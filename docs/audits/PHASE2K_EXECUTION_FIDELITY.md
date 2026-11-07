# Phase 2K — execution fidelity, the libpng failure and the shared-descriptor contract

Host: 8-CPU Ubuntu 24.04, kernel 6.1.102, release build. Repositories are pristine `git archive`
copies of libpng v1.6.43 (`ed217e3`), zlib v1.3.1 (`51b7f2a`) and lz4 v1.9.4 (`5ff8396`).
Raw data: `benchmarks/results/phase2k/`. Base commit `f3bd191`.

## 1. The Phase 2J libpng diagnosis was wrong

Phase 2J recorded "`always` makes configure exit 1". The stored session data contradicts that:
`configure` exited **0** under `always` in both sessions (16.8 s and 17.9 s). The first failing
phase was `build` (`make -j4`), which exited 1 in 0.45-0.52 s with:

```
tracejit: ptrace failed: missing process state for 167146
```

The direct configure run and `--admission never`/`auto-v1`/`auto` all succeeded. A fresh pristine
traced configure also succeeds at `f3bd191`, so the failure is in the traced build, not configure.
The expensive traced configure is why the whole-policy total looked like a configure problem.

## 2. First divergence and root cause

With temporary event logging, the missing pid was a **bash** whose `/proc` parent was a tracked
make child and whose `TracerPid` was the tracer, but for which no fork event had been registered:

```
Stopped(Pid(14070), SIGSTOP)        <- first stop of the child
PtraceSyscall(Pid(14070))           <- no state, error
tracked=[... 14066 ...] PPid: 14066
```

The kernel guarantees the child is stopped before it runs, not that the **parent's**
`PTRACE_EVENT_FORK/VFORK/CLONE` is dequeued before the child's own stop. `vfork` makes this
concrete: the parent cannot stop until the child execs or exits, so the child's `SIGSTOP` and even
its `PTRACE_EVENT_EXEC` can be reported first. `make -j1` did not reproduce it; `make -j4`
failed 2/2 before the fix and passes 5/5 after.

Fix in `crates/tracejit-trace/src/linux.rs`:

- `adopt_child` registers a child idempotently, records one spawn edge and one process node.
- Before dispatching any stop for an unknown pid, `traced_parent` reads `/proc/<pid>/status`
  (`TracerPid`, `Tgid`, `PPid`), requires the process to be traced by this tracer, and reconciles
  a thread from its group leader or a child from its parent.
- The fork event now uses the same idempotent registration, so a late event cannot overwrite the
  post-exec state already applied by the child's `PTRACE_EVENT_EXEC`.
- An exec event for a still-unknown pid is an explicit error instead of a silent resume without
  clearing close-on-exec state.

Regression: `tests/fixtures/spawn_storm.c` runs parallel `vfork`+`exec` workers
(`40 x 4`). `vfork_exec_children_are_registered_before_their_first_stop` **fails on the pre-fix
tree and passes after**, and compares exit status and stdout with a direct run.

## 3. Inherited-descriptor audit (fd vs open file description)

A descriptor is a handle; `dup`/`fork`/`exec` share one open file description whose offset is the
only caller-visible cursor. The Phase 2J model tracked fd 0 only. This phase adds:

- **All inherited descriptors are classified at exec** from `/proc/<pid>/fd`. A regular file
  inherited on fd 3 is now `InheritedFile`, so a read is refused; previously it fell through to
  the generic path and was recorded as an ordinary content read, which ignored its starting offset
  and its caller-visible position.
- **Startup alias refusal.** If any other descriptor in the root has the same device, inode and
  position as fd 0, the stream is not modelled and a `Unknown` effect is recorded. `kcmp` is
  `ENOSYS` on this kernel, so this conservative signature (which also refuses an independent open
  at the same offset) is the enforceable test. `alias-fd3` covers an alias inherited across exec.
- **Child reads and seeks refuse.** A forked child shares the description but has no consumption
  model; its stdin read already refused, and a child's `lseek` on fd 0 previously fell into the
  process-internal no-op path. It now records an unknown effect.
- **Position verification.** After every modelled stdin read/seek, and at `exit_group` entry,
  `/proc/<pid>/fdinfo/0` is compared with the model. A mismatch withdraws the stream and records
  an unknown effect. A closed descriptor is not a mismatch (closing does not move the offset).

Tests in `inherited_stdin_seek_model_reproduces_offsets_and_refuses_unsound_cases` cover child
read, child seek, an exec-inherited fd 3 alias, `dup` alias, failed seek, `pread` (no advance),
`SEEK_END`, a non-zero start offset and content change, besides the Phase 2J cases. zlib
decompression still records `Guarded` then `Reused` with byte-identical output.

**Unsupported boundary, stated plainly:** a separate process that shares the description and moves
it while the traced process is idle is only detected if it moves before the next stdin operation or
before `exit_group`; a move after the last operation and after exit remains invisible. That caller
contract is not silently assumed to be safe for a *fresh* record, but it is strictly weaker than a
kernel-enforced isolation and is not claimed as `PROVEN`. `kcmp`-based proof and mount-namespace
isolation are unavailable here.

## 4. Execution-fidelity suite

`crates/tracejit-cli/tests/execution_fidelity.rs` compares native and traced execution of nine
workloads: autoconf configure (unavailable: autoconf is absent), configure-shaped shell, `make -j4`
build, `cc -c`, test runner, shell file/symlink/directory mutations, multi-process pipeline,
inherited stdin with the caller's descriptor position, and non-zero exit with stdout/stderr. It
compares exit status, stdout, stderr, the whole resulting file tree (content, mode, symlink target)
and the caller-visible stdin offset, then runs the workload again to judge reuse.

Result: **9/9 accounted; 0 fidelity failures**; 1 `Unavailable`, 1 `SafelyReused`
(inherited-stdin fixture), 7 `UnsupportedSafelyExecuted` (shell, make, cc and pipeline commands are
refused for clocks/entropy/pipes but execute identically). No workload is dropped from the
denominator.

## 5. Session-harness corrections

`benchmarks/repos/real_sessions.py` had a reporting defect: the `always` policy passed only
`--contract`, relying on the CLI default. Every policy now passes `--admission` explicitly. A
session is `valid` only if every phase exits 0, every tool phase's stdout SHA-256 equals the direct
run's, and then (and only then) a speedup is computed; otherwise `speedup` is `null` and
`invalid_reason` names the failed phases or mismatched artifacts. The record includes the workload
version `phase2k-v1`, commit, dirty state, kernel and CPU count. Raw per-phase samples stay in the
JSON.

Two independent sessions, same pristine inputs:

| Repository | Session | direct | never | auto-v1 | always | auto |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| zlib | A | 2785.00 | 3088.70 (0.902x) | 2478.42 (1.124x) | 7055.48 (0.395x) | **2695.45 (1.033x)** |
| zlib | B | 2839.58 | 2981.14 (0.953x) | 2592.30 (1.095x) | 7478.22 (0.380x) | **2439.67 (1.164x)** |
| libpng | A | 11094.73 | 10434.15 (1.063x) | 10596.95 (1.047x) | 35632.32 (0.311x) | 10514.66 (1.055x) |
| libpng | B | 10375.60 | 10723.37 (0.968x) | 10923.52 (0.950x) | 36682.67 (0.283x) | 11163.63 (0.929x) |
| lz4 | A | 15917.92 | 16034.89 (0.993x) | 16979.98 (0.937x) | 22070.37 (0.721x) | 17210.82 (0.925x) |
| lz4 | B | 17608.63 | 16976.62 (1.037x) | 17281.93 (1.019x) | 21607.81 (0.815x) | 16670.80 (1.056x) |

All six workflows are valid and artifact-equal. zlib's `auto` reuses both `./minigzip` and
`./minigzip -d` (`Reused`, `Guarded`) in both sessions and is the only positive workflow. libpng's
adaptive deltas are measurement noise: `pngtest` costs ~7 ms and is correctly declined; `always`
traces every build and costs 3-3.5x but no longer breaks it. lz4 never reuses (`process read system
clock: monotonic`), so its 0.925x/1.056x are overhead and variance, not reuse. zlib's gains are
smaller than Phase 2J's 1.099x/1.228x; the per-read position check and run-to-run variance both
contribute, and no improvement is claimed.

The two sessions were measured from the working tree at `f3bd191` with the fix applied, so their
JSON records `"dirty": true`; the measured release binary hashed `60d85526255d96b61f261ac848e4aa3e0e25a74c2364c3b76bfc863dfbf69229`.
No source changed after that build, and the tree was committed as `31bade5`-`9fc010d`. The raw
records identify that state explicitly rather than pretending the tree was clean.

## 6. Reliability, fuzzing and concurrency

- `ETXTBSY`: reproduced as a cross-test fork inheritance of a freshly written executable. Writing
  through a sibling name and renaming removes this test's writer window, but a sibling fork can
  still inherit the temporary inode before the rename. A bounded, test-only retry remains, scoped
  to this test's own spawns; it is a harness limit, not a product descriptor leak.
- Differential fuzzing: seeds 7 and 11, **240 comparisons, 240 ok, 0 incorrect hits** after the
  tracer change (`benchmarks/results/phase2k/differential/`). This is sampled evidence, not proof.
- Concurrency: 8 simultaneous `--admission always` gzip runs on one cold cache all exited 0,
  produced bytes equal to native (SHA-256 `a8e821d2...`), and reported `Executed` with no
  `database is locked` error. Raw record: `benchmarks/results/phase2k/concurrency.json`.
- The full workspace suite passes: **112 tests**; fmt and clippy with `-D warnings` are clean.

## 7. Enforcement

`tracejit doctor` still reports `seccomp yes`, `landlock no`, `proven no` (LSM list
`capability,selinux`). `PROVEN` remains **BLOCKED** and unexercised; `GUARDED` reuse is unchanged
and is not a sandbox. No push, merge or release was performed.

## 8. Limits

- autoconf is not installed, so the real autoconf-configure workload is `Unavailable`; a
  configure-shaped script is covered instead.
- `kcmp` is unavailable, so shared-description detection uses the conservative device/inode/
  position signature.
- External mutation of a shared description after the last observed operation and after exit is
  not detectable; documented, not claimed.
- Peak RSS remains unavailable (`/usr/bin/time` absent, no delegated cgroup).
- lz4 cannot reuse by contract, and only zlib provides a positive developer workflow.

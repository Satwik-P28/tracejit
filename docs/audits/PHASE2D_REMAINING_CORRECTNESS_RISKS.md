# Phase 2D: remaining correctness and safety risks

Nothing here is claimed as verified. Items marked **open** are known and unmitigated; **blocked**
means the environment cannot test them.

## Open correctness risks

1. **Directory metadata over-approximation** (`PHASE2D_ATIME_ANALYSIS.md`). A `FileMetadata`
   dependency on the parent directory of an opened path stores `atime`/`mtime`/`ctime`/`size`, so any
   create, delete or rename in that directory invalidates reuse. This is *conservative* — it refuses
   reuse it could allow — so it is not a soundness hole, but it destroys the benefit of reuse for the
   common pattern of writing an output beside the input. The scoped fix (identity-only comparison for
   resolution-time directory snapshots) is not implemented because the recording site was not
   located and a guard-level change would also weaken genuine directory `stat` observations.

2. **Executable identity window.** The executable is re-hashed immediately before `execve`, which
   narrows but does not close the window between the check and the kernel loading the file. A
   same-uid attacker who can replace the binary inside that window is not stopped.

3. **Every guard has a validation-to-restore TOCTOU window.** Validation completes before cached
   output is exposed, but the state it validated can change afterwards. There is no kernel-enforced
   isolation during restore; that is what the `PROVEN` path is meant to provide.

4. **Restoration is not crash-atomic.** A crash mid-restore can leave a partially written output;
   recovery re-executes the command. Multi-output restoration was fixed in Phase 1, but atomicity
   across several outputs was not.

5. **Pipe packetisation.** Reuse of pipe traffic assumes one writer, no short read followed by more
   data, and no partial or untracked transfer. The tracer refuses violations it observes; an
   interleaving it does not observe is not covered. Streaming pipelines are refused outright.

6. **`getrusage` remains unmodelled.** With the shell removed, `getrusage` is the *sole* refusal
   reason for `gcc -O2 -c` and for `as`. Four interventional runs showed the value reaches no
   observable output for those inputs; that is empirical, not a proof, and it is not generalised.

7. **`statfs` (137) and `/proc/self/maps`.** These block `tar`, `sed` and `grep`. `statfs` returns
   filesystem state (free space, block counts) that a program can legitimately print; modelling it
   would need a guard, not a constant.

8. **Inherited descriptors.** Reading a redirected stdin file is refused as "not replayable" even
   when the file is unchanged. This blocks `tr` and would block most filter compositions.

9. **Runtime identity is coarse.** It covers uname, uid/gid quadruple, stack rlimit, and the stdin
   target fingerprint. It does not cover the full rlimit set, locale-archive selection beyond
   `LC_ALL`, or cgroup limits, which can change behaviour without invalidating a record.

10. **The nine-workload census is shell-contaminated.** Its numbers include the `sh` wrapper's own
    syscalls. It is deliberately left unchanged for comparability, which means it cannot be read as a
    statement about the workloads themselves; the direct suite is the workload-level measurement.

## Environment-blocked items

- **`PROVEN` / Landlock**: kernel 6.1.102 has no Landlock (`ENOSYS`; LSM list `capability,selinux`).
  `PROVEN` has never been executed on any host. No enforcement claim is made anywhere in this phase.
- **`strictatime` / `noatime` / `nodiratime`**: changing mount options requires privileges the session
  does not hold. The atime analysis is therefore an analysis of the code path plus `relatime`
  observation, not a measured matrix across policies.
- **Competitive comparison**: `ccache`, `sccache` and Firebuild are not installed and `clang` is
  absent. No claim of superiority, parity or regression against them is made.
- **Missing tools** for the compatibility suite: `zstd`, `pandoc`, `convert`, `ffmpeg`, `cmake`, `yq`.
  Deterministic image conversion and documentation conversion are BLOCKED, not refused.

## Things this phase did *not* change

- The classifier: `getrusage` is still `NONDETERMINISTIC`, no whitelist exists, and no
  `EMPIRICALLY_STABLE` reuse was introduced.
- The nine-workload census denominator.
- The guard set, the record format, or the restore path.
- The `PROVEN` gate.

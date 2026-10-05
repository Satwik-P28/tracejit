# Where a naive cache would be wrong

A naive cache keys on the command string and returns the previous stdout. The cases in `tests/fixtures/cases.json` are the classes `analyze` is expected to return. The Eligible column is that classification. It does not mean a mutated input is still reused.

Separate Linux tests check the reuse decision. `guarded_hit_deopt_restore_and_replay` requires a hit, an output restore, a `DEOPT` after `input.txt` changes, an environment miss, and replay of stdout, stderr, and a non-zero exit. `metadata_symlink_and_environment_changes_miss` requires `DEOPT` after a same-byte rewrite and after a symlink retarget. `nondeterministic_and_unknown_cases_never_reuse` runs `getrandom`, `unknown_ioctl`, and `network_send` twice and forbids `HIT`. This file does not add measurements from a machine that did not run those tests.

| Case | Naive cache | Expected class | Eligible |
| --- | --- | --- | --- |
| `file_content_changed` | Returns the old output after the input bytes change | `GUARDED` on the original run; a later guard must fail | yes, until the bytes change |
| `file_mtime_changed` | Ignores metadata, or trusts mtime alone | `GUARDED` | yes |
| `symlink_target_changed` | Follows the path string and misses a retarget | `GUARDED` | yes |
| `environment_dependency`, `unset_environment_dependency` | Misses an env change that was not in argv | `GUARDED` | yes |
| `cwd_dependency` | Ignores the working directory | `GUARDED` | yes |
| `clock_realtime`, `clock_monotonic` | Reuses a result that read time | `NONDETERMINISTIC` | no |
| `getrandom`, `urandom` | Reuses a result that read randomness | `NONDETERMINISTIC` | no |
| `process_identity`, `system_info` | Reuses a pid, tid, or sysinfo read | `NONDETERMINISTIC` | no |
| `network_connect`, `network_send`, `dns_lookup`, `unix_socket` | Replays a program that talked to something else | `NONDETERMINISTIC` | no |
| `unknown_ioctl` | Ignores an unmodeled device call | `UNKNOWN` | no |
| `proc_self` | Treats `/proc/self` as a stable file | `UNKNOWN` | no |
| `clone_thread` | Assumes threads have separate file tables | `UNKNOWN` | no |
| `fork_child`, `exec_child`, `child_file_dependency` | Misses a descendant's file use | `GUARDED` | yes |
| `tempfile_creation` | Treats a temp file as irrelevant | `NONDETERMINISTIC` | no |

`proc_cpuinfo` and `hostname` are expected `GUARDED` because the tracer records a guardable read, not because those values are universally stable. If the guarded content changes, reuse has to stop. That is a guard, not a promise that hostname never matters.

## What is not in the fixture list

These are real gaps. They are not covered by a passing fixture in this repository:

- Another process changes an input after guards pass and before outputs are restored. `SAFETY.md` calls this interval out. `GUARDED` does not close it.
- A libc `clock_gettime` that would have stayed in the vDSO. `vdso_clock` calls `clock_gettime`, `gettimeofday`, and `time` through libc. The tracer redirects those vDSO entry points to syscalls first, and the case is `NONDETERMINISTIC`. The raw `syscall(SYS_clock_gettime)` fixtures remain separate.
- A `MAP_SHARED` write is expected `UNKNOWN` (`mmap_shared_write`, `mmap_shared_mprotect`). That is a refusal, not a replay of the store.
- Concurrent writers to a guarded file during the traced run.
- The shell and `cc -c` refusals in `benchmarks/results/break-even.md`. Those commands were `UNKNOWN`. Making them reusable requires a modeled syscall and a new fixture, not a looser class.

## How to add a case

Use the Break TraceJIT issue template. A report that should never reuse needs a fixture whose expected class is `UNKNOWN` or `NONDETERMINISTIC`. A report that should reuse needs the guard that makes the invalidation happen, and a test that a stale hit does not. Do not change `cases.json` to green a run by weakening the expected class.

# Red team

Answers use the code and the published result files. Where the code is weak, the limitation is the answer. This is not a claim that a reviewer will be satisfied.

**What exactly is novel?**
Not ptrace, not BLAKE3, not seccomp, and not the idea of caching a command. The V1 combination is automatic classification of modeled effects, reuse only for `GUARDED` and `PROVEN`, and `PROVEN` only after both enforcement mechanisms install. Prior art is named in the README and in `docs/COMPARISONS.md`. Do not claim the mechanisms are unprecedented.

**Why isn't this strace plus a cache?**
strace does not decide which events are inputs, which outputs can be restored, or which syscalls forbid reuse. That decision is `classify` in `crates/tracejit-effects/src/lib.rs` and the guard checks in `crates/tracejit-guards`. A log plus a hash of argv would still return stale results.

**What prevents stale reuse?**
Guards run before any cached stdout, stderr, exit status, or file is exposed. A content change in a recorded input fails the hash. The Linux test `guarded_hit_deopt_restore_and_replay` rewrites `input.txt` and asserts the next run is not a hit. `./scripts/demo.sh` does the same for the synthetic transform. This is not a proof for every program.

**What does PROVEN actually mean?**
The effects classified as `GUARDED`, and `trace_command` was started with a sandbox policy whose `pre_exec` hook called `tracejit_sandbox::apply` successfully. `apply` returns only after Landlock restrict and seccomp install. `sandbox_enforced` is then true, and core promotes `GUARDED` to `PROVEN`. It does not mean a machine-checked proof of the command's function. It does not constrain other processes.

**What happens with network access?**
A modeled network read or write becomes `NONDETERMINISTIC`. The command is not reused. seccomp in the enforced policy is written to deny network. DNS is in the fixture list as nondeterministic. An unmodeled network path becomes `UNKNOWN`, which also does not reuse.

**What about time and randomness?**
A `clock_gettime`, `gettimeofday`, or `time` syscall is `NONDETERMINISTIC`. `getrandom` and `/dev/urandom` are too. A libc `clock_gettime` that the vDSO answers without entering the kernel is not seen, and that program can still be `GUARDED`. The fixtures use the raw syscall, so they do not cover the libc path. That remains a hole.

**What about mmap?**
Anonymous mappings stay internal. A file-backed `MAP_SHARED` mapping that is writable, or that `mprotect` makes writable, is `UNKNOWN` (`mmap_shared_write`, `mmap_shared_mprotect`). `mremap` of a recorded file mapping is `UNKNOWN`. Private and read-only file mappings are not themselves effects; the earlier open is the content guard. This is not a replay of the store.

**What about subprocesses?**
fork, vfork, and exec are followed. A child's file use can be `GUARDED`; `fork_child` and `child_file_dependency` expect that. `clone` forces `UNKNOWN` because shared file-descriptor and cwd tables are not modeled.

**What about threads?**
`clone_thread` is expected `UNKNOWN`. TraceJIT does not claim a threaded program is reusable.

**What about filesystem races and TOCTOU?**
The check and the restore are not atomic with respect to other processes. `GUARDED` does not close that interval. `PROVEN` does not either. Use it where concurrent mutation is controlled, or do not use it.

**What about unsupported syscalls?**
They become `UNKNOWN` on success, and failed unmodeled calls can too, because the errno can affect control flow. No reuse.

**What is the trusted computing base?**
The kernel interfaces this process calls (ptrace, seccomp, Landlock), the tracer and guard code, BLAKE3, SQLite, and the permissions on the cache directory. It is not a verified base. Say that plainly.

**Where does this lose performance?**
Cold traces are slower than the direct binary in every published row. Hits near 4 ms lose to commands around 2 ms and won against a 5.274 ms command in the later sweep. The 7.396 ms ETL became 7.957 ms at `63e3363`. Startup, SQLite, guard hashing, and restore are the floor. A daemon was not added.

**Why not Bazel or Nix?**
They reuse work whose inputs were declared. TraceJIT is for a command without that declaration, and it refuses shell and `cc` today. If a correct rule exists, TraceJIT is the worse tool.

**Is the 78x number cherry-picked?**
It is one workload, chosen to be CPU-heavy: 250,000,000 extra mix rounds plus a small file. The harness used 30 runs and published the median. The loss on the short ETL is in the same README. Treating 78x as a typical speedup would be cherry-picking. The document does not do that. The workload is still synthetic, and a reviewer should say so. That criticism is fair.

**Does tracing cost more than recomputation?**
On the first run, yes, in the published tables. Reuse is the later run. If the command is shorter than the hit floor, even the later run loses.

**What happens when enforcement fails?**
`doctor` reports that `PROVEN` is unavailable and that `GUARDED` can still run. If `--enforce` is requested and `pre_exec` cannot apply the policy, core retries without the sandbox and does not promote the result. A missing kernel feature does not become `PROVEN`.

**What assumptions are hidden?**
The whole environment is a key, which hides the fact that individual `getenv` calls are not observed. `NoUnexpectedEffects` always returns success, which is easy to misread in a debug dump. glibc malloc can call `getrandom` unless the benchmark disables tcache, so "this C program looks pure" is not enough. Fast guard mode can skip a hash. The cache is not encrypted.

**Is this safe for production CI?**
Not as a general accelerator. Shell and compilers were unknown. The TOCTOU window and mmap hole are documented. A long deterministic command with controlled inputs is the only shape the measurements support, and even that is one synthetic program plus one small ETL.

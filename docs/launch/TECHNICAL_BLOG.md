# Can you automatically determine when a Linux process is safe to skip?

Draft. Do not publish until the checklist is done. This should stand alone if the reader never installs anything.

## The problem

A command finishes. You run it again. Sometimes nothing it depends on has changed, and the second run is waste. Sometimes one file, one environment variable, or the clock changed, and skipping the run would return a lie.

Build systems avoid the lie by making a person write the inputs down. That works when the program is a build step and someone maintains the rule. It does not help a binary you did not write, a script whose inputs are implicit, or a command whose author never thought about caching.

The question TraceJIT is trying to answer is smaller than "cache all the things." It is: from the outside, can you infer enough of what a Linux process observably depended on to reuse its result, and can you refuse when you cannot?

## Why caching is harder than it looks

The command line is not the input set. The process can open files, stat paths that do not exist, read a symlink, exec a child, consult the environment, or talk to the network. Two runs with the same argv can be different computations. Two runs with different argv can be the same one. A cache that keys only on argv will sometimes be fast and wrong.

Wrong is the failure that matters. Recomputing a command that could have been skipped wastes time. Replaying a stale result can poison everything downstream. A system that cannot tell those cases apart should recompute.

## Observable effects

ptrace reports kernel crossings. TraceJIT sorts the ones it understands into reads, writes, and control events. A read of a file before that file is written is an input. A write of a regular file can be an output to restore later. An exec is a dependency on that binary. A syscall with no safe model becomes unknown, including some failed calls, because the failure itself can change control flow.

This is not a view of the program's memory. A userspace read of an environment variable never has to enter the kernel if the bytes are already in the process. TraceJIT therefore puts the entire inherited environment into the identity it looks up, instead of pretending it saw every `getenv`. That over-approximates. Over-approximation causes extra misses. Under-approximation causes stale hits. The project picks the extra miss.

## Reconstructing dependencies

The lookup key, before the process starts, is the executable content, the arguments, the working directory, the inherited environment, and a runtime identity. Input paths are not guessed into that key. They show up during the trace and become guards that must pass before any cached byte is exposed.

A read that happens only after the same path was written is treated as a read of the command's own output, not as an input. That distinction is the difference between "this file is a dependency" and "this file is scratch the command just created."

## Determinism is not binary

TraceJIT uses five labels.

- `GUARDED` means every observed effect was either something it can check next time or an output it captured.
- `PROVEN` means the run was `GUARDED` and, separately, seccomp and Landlock were installed so the process was confined to the policy built from that profile. Looking at a trace does not produce this label.
- `EMPIRICALLY_STABLE` would mean "it came out the same a few times." V1 does not reuse that. Repetition is not a dependency.
- `UNKNOWN` means at least one effect had no safe model.
- `NONDETERMINISTIC` means the process read a clock, randomness, the network, sent a signal, or did something else the cache must not replay.

Unknown wins over nondeterministic if both appear. The command is not reused in either case.

## Guarding assumptions

A guard is a check performed on the next run, before restore. File guards hash content with BLAKE3 in the default strict mode. They also compare a fingerprint: device, inode, size, timestamps, mode, link count, ownership. Fast mode may trust the fingerprint and skip the hash. Fast mode is experimental because metadata is not content. A permission change fails even if the bytes match.

The executable, the working directory, the runtime identity, and each environment entry are guards too.

## Enforcement

seccomp can deny classes of syscalls. It cannot express "only these paths." Landlock can express paths, including truncate once the ABI is new enough. TraceJIT requires ABI 3 or newer before it will combine the two and say `PROVEN`. If either mechanism is missing, a guarded run stays `GUARDED`. If the sandbox cannot be installed, the code falls back to an unenforced trace and does not apply the stronger label.

`PROVEN` still does not stop a different process from changing a file. It constrains the process being traced.

## Deoptimization

When a guard fails, the cached result is not exposed. TraceJIT records the failure and traces again. The demo in the repository appends one line to the transform's input and checks that the following run is not a hit. That is the entire product in one gesture: reuse, then stop reusing when the dependency moves.

## Adversarial cases

The fixture list is aimed at caches that would get these wrong: file bytes, mtime, symlink targets, environment, cwd, child processes, clocks, `getrandom`, `/proc/self`, threads, ioctl, sockets. The expected classes live in `tests/fixtures/cases.json`. A Linux test checks them. A second test checks that a changed input does not hit, and that `getrandom`, an unknown ioctl, and a network send never hit.

Some cases are still open. A writable shared file mapping is classified unknown and is not replayed. A clock answered by the vDSO may never appear as a syscall, and that program can still be labeled guarded. Another process can still win the race between the guard and the restore.

## Benchmarks

The numbers below are medians from a harness on GitHub-hosted Ubuntu 24.04 x86_64, 5 warmups and 30 runs. They are tied to commits. They are not a claim about your laptop or your build.

The workload behind the large ratio is synthetic. It folds a small file of integers and then runs 250,000,000 extra mix rounds so the command takes long enough to measure. At commit `e9684c1` the median was 312.913 ms direct and 3.972 ms on a guarded hit.

The short C ETL at commit `63e3363` was 7.396 ms direct and 7.957 ms on the hit. Caching made it slower.

A later sweep, after a change that stopped rewriting the cache record on a steady-state hit, lost at a 1.796 ms command and won at a 5.274 ms command. Hits sat near 4 ms. No curve was fit between those two points.

## Where it loses

The first traced run is slower than the direct command, often by a lot, because ptrace stops the process on syscalls. The win, when it exists, is on a later run.

Below the hit floor, reuse cannot win. Hashing inputs, opening SQLite, and starting the TraceJIT process cost more than a tiny command. Publishing only the 78x row would be a way to hide that. Both rows belong in the same paragraph.

Python loses for a different reason. CPython reads randomness and its thread id while starting. TraceJIT refuses. Seeding the hash with `PYTHONHASHSEED=0` does not remove those calls, and the classifier does not special-case them. A shell pipeline and `cc -c` were unknown syscalls and access checks, so they were not reused either.

## Limitations

The trusted computing base is the kernel's ptrace, seccomp, and Landlock behavior, the tracer, and the local cache. None of that is formally verified. The cache holds outputs and environment values in a normal directory. Whole-command reuse cannot skip half of a process. There is no macOS or Windows implementation. There is no remote cache.

## What this could become

More modeled syscalls would make more ordinary commands eligible, if each one comes with a test that still fails closed. The vDSO clock path is the remaining way a time-dependent program can be reused. Partial reuse inside a process is a different system and should wait until the whole-command argument is boring.

It should not become a quieter ccache or a worse Bazel. Declared graphs are better where they exist. The interesting remainder is the command nobody declared, and the decision to run it anyway.

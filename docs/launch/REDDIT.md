# Reddit drafts

Check each community's self-promotion rules the day you post. Several of these treat project announcements as spam unless there is a technical question. Do not post the same text in all of them. Do not ask for stars. If the rules disallow project posts, do not post.

## r/rust

Rules change. Confirm the current self-promotion policy before posting.

Title: TraceJIT 0.1.1 – ptrace, guards, and reuse for whole Linux commands

TraceJIT is a Rust workspace (effects, guards, cache, ptrace, seccomp/Landlock, core, CLI) that reuses an unmodified Linux x86_64 command only after synchronous guards pass. UNKNOWN and NONDETERMINISTIC do not reuse. PROVEN additionally requires seccomp and Landlock ABI 3+ to be installed. The inherited environment is in the cache key because getenv is not a syscall.

The harness result I trust: a synthetic C transform in the repo, 250,000,000 extra mix rounds, 312.913 ms median to 3.972 ms on a GitHub-hosted runner (commit e9684c1, 30 runs). A 7.396 ms C ETL got slower (7.957 ms, commit 63e3363). Python, shell, and cc are refused rather than special-cased.

I would rather have an adversarial case than a feature request. If you can make it reuse a command it should rerun, the Break TraceJIT issue template is how that becomes a fixture.

https://github.com/Satwik-P28/tracejit

## r/linux

Rules change. Confirm before posting. This is a user-space tool, not a kernel patch.

Title: Tracing a process to decide whether its result can be reused

I have been working on a user-space tool that ptrace's a Linux x86_64 command, classifies the syscalls it understands, and skips a later run only when file, executable, cwd, and environment guards still match. Clock, getrandom, network, and unmodeled syscalls disable reuse. Optional seccomp and Landlock are required before it will say PROVEN. Landlock does not freeze other processes, so there is still a TOCTOU window.

It is not a build system. cc and a shell pipeline were classified UNKNOWN in the published run. The performance story is mixed on purpose: one synthetic CPU-bound command dropped from about 313 ms to about 4 ms, and a 7 ms command got slower.

https://github.com/Satwik-P28/tracejit

## r/programming

Rules change. Many weeks this belongs in a daily thread rather than as its own post. Check first.

Title: Can you tell from the outside when a Linux process is safe to skip?

Write-up of the problem, not a feature tour: observable effects are not the same thing as the process's actual dependencies, determinism is not a boolean, and a cache that misses an input is worse than a slow command. The project is TraceJIT. The interesting measured case is synthetic and published with the machine and the commit. A shorter command got slower. A writable shared file mapping is refused. A vDSO clock read is not seen.

https://github.com/Satwik-P28/tracejit

## r/commandline

Rules change. Confirm before posting.

Title: tracejit run -- <command>, then the same command again

On Linux x86_64, `tracejit doctor` tells you if ptrace works. `tracejit run -- <command>` traces. The next invocation reuses only if the guards pass. `tracejit explain` shows the recorded inputs. I would not put it in front of short commands: the published hit floor was about 4 ms, and a 7 ms ETL got slower. Python is refused.

https://github.com/Satwik-P28/tracejit

## r/devops

Rules change. This is a poor fit if the community wants production tooling. TraceJIT is not a CI cache and does not support shell pipelines yet. Post only if you frame it as an experiment, and skip it if the rules disallow that.

Title: An experiment in skipping a rerun command, with the cases it refuses

Not a replacement for Bazel, Nix, or ccache. Those already have declared inputs. This is a tracer for a command that does not. It refuses network, clocks, and unknown syscalls. The published compiler invocation was UNKNOWN. I am posting it for the failure mode, not as something to drop into a pipeline.

https://github.com/Satwik-P28/tracejit

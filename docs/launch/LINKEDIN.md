# LinkedIn draft

Do not post a "excited to announce" version. The audience that can evaluate this will stop reading.

I have been working on a narrow question: after a Linux process exits, do the syscalls we managed to see tell us enough to skip the process next time, and can we refuse when they do not?

TraceJIT is a Linux x86_64 command that traces an unmodified program with ptrace, classifies effects as reads, writes, control events, or unknown, and reuses the whole command only when synchronous guards still hold. Unknown syscalls, clocks, randomness, and network activity are not reused. A stronger label, PROVEN, is used only when seccomp and Landlock were actually installed. That label does not freeze other processes. A writable shared file mapping is refused. A libc clock read is forced through a syscall, or the command is not reused.

The measurement I will publish beside the claim: on a GitHub-hosted runner, a synthetic CPU-bound transform in the repository went from 312.913 ms to 3.972 ms (30 runs, commit e9684c1). A shorter C program went from 7.396 ms to 7.957 ms. Tracing the first run is slower than running the command. Python and a C compiler invocation are refused.

I would like criticism of the safety model from people who work on build systems, sandboxes, or runtime instrumentation. In particular: where a guard checked at reuse time is the wrong tool, and where this should stay a refusal.

https://github.com/Satwik-P28/tracejit

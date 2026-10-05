# Show HN drafts

Do not post until `LAUNCH_CHECKLIST.md` is done. HN readers punish a missing limitation more than they punish a small number.

## Titles, best first

1. Show HN: TraceJIT – reuse a Linux command only when traced dependencies still hold
2. Show HN: TraceJIT – ptrace, guards, and no reuse when a syscall is unmodeled
3. Show HN: TraceJIT – a synthetic Linux command went from 313 ms to 4 ms, and a 7 ms one got slower
4. Show HN: TraceJIT – fail-closed memoization for whole Linux processes
5. Show HN: TraceJIT – guarded computation reuse for unmodified Linux commands

Use 1. It states the rule. Title 3 is the most concrete and also the easiest to read as a benchmark ad. Use it only if the post body leads with the loss.

## Post

TraceJIT runs in front of an unmodified Linux x86_64 command, traces the syscalls it knows how to model, and reruns the command from a local cache only when those guards still hold. If it sees the clock, getrandom, the network, a thread that shares file-descriptor state, or a syscall it does not model, it does not reuse.

I wanted the opposite of a cache that trusts the command string. The question was whether observable effects are enough to skip a process, and whether the system can refuse instead of guessing.

The implementation is ptrace, a small effect taxonomy (read, write, control, unknown), a determinism class, and synchronous guards. PROVEN is not "we looked at the trace." PROVEN means the effects were guardable and both seccomp and Landlock ABI 3+ were installed for that run. GUARDED means the guards passed and enforcement was not claimed. There is a TOCTOU gap between the check and the restore. A writable shared file mapping is refused. A clock read that stays in the vDSO is not seen. The inherited environment is part of the cache key because ptrace does not see getenv.

The number I will stand behind is from the harness, 5 warmups and 30 runs, on a GitHub-hosted Ubuntu 24.04 x86_64 runner. A synthetic C transform in the repo (fold a file, then 250,000,000 mix rounds) went from 312.913 ms to 3.972 ms at commit e9684c1. The same kind of measurement lost on a shorter C ETL: 7.396 ms became 7.957 ms at commit 63e3363. Cold traces are slower than the direct command. Hits on the later runner sat near 4 ms. Python is refused because CPython calls getrandom and gettid. A shell pipeline and cc -c were UNKNOWN.

Linux demo from a checkout: ./scripts/demo.sh. It traces, reuses, then appends to the input and checks the next run is not a hit.

The useful feedback is a command this reuses when it should have rerun. Those reports become fixtures. I am not looking for a star drive.

https://github.com/Satwik-P28/tracejit

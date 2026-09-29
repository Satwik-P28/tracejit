# r/programming draft

Title: Reusing a Linux command only when the traced dependencies still match

Repeated commands are often rerun from scratch because the safe thing is to assume they might have changed. TraceJIT records what an unmodified Linux process actually read and wrote, then refuses to replay the result unless those checks pass. On one deterministic C transform that cost 312.913 ms, the guarded replay was 3.972 ms. A shorter 7.396 ms command was slower with TraceJIT in front of it. Python, shell, and the C compiler are not accepted workloads in 0.1.0.

Linux x86_64 only. The safety rule is fail closed: if the effect is unknown or nondeterministic, it runs again. The benchmarks are in the repository.

Try `./scripts/demo.sh` on Linux x86_64: first trace, guarded hit, explain, then an input change that forces a rerun. If that classification is wrong, file a Break TraceJIT issue.

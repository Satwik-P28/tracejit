# X thread draft

Post only after the checklist. Attach a terminal recording that matches `docs/assets/storyboard.md`, including the input change and the short-command loss. Do not post a 78x card by itself.

1. TraceJIT reuses an unmodified Linux command only when the dependencies it observed still hold. One synthetic workload: 312.913 ms → 3.972 ms. A 7.396 ms command got slower (7.957 ms). Linux x86_64.

2. First run is a ptrace. TraceJIT records file reads, execs, and outputs it can model. Clock, getrandom, network, and unknown syscalls disable reuse. The second run checks guards before it replays stdout or restores files.

3. Append one line to the input. The next run is a deoptimization, not a stale hit. That is the part that matters. An argv cache would have returned the old result.

4. PROVEN means seccomp and Landlock were installed for that run. It does not mean other processes cannot change a file in the gap. A writable shared file mapping is refused. A vDSO clock read is not seen. Python, shell, and cc are refused today.

5. Code, both benchmark tables, and the demo script: https://github.com/Satwik-P28/tracejit

The useful reply is a command it should not have reused.

# Show HN draft

Title: Show HN: TraceJIT – guarded reuse for unmodified Linux commands

TraceJIT puts `tracejit run --` in front of a Linux x86_64 command, traces what that process actually depends on, and reruns it from cache only when those guards still hold. The interesting measured case is a deterministic C transform in the repo: 312.913 ms down to 3.972 ms (78.780x) with no source changes. Cache hits on that runner sat near 4 ms, and a 7.396 ms command got slower (7.957 ms). Python is refused because CPython calls getrandom and gettid. Shell and cc are not supported yet.

The hard part is failing closed. UNKNOWN and NONDETERMINISTIC never reuse. PROVEN means seccomp and Landlock were actually applied, not inferred. I would like people to try to break that classification. Benchmarks and the machine details are in the repo under benchmarks/results.

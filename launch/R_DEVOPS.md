# r/devops draft

Title: A guarded command cache for Linux, with the cases it will not cache

TraceJIT is aimed at repeated deterministic commands in build and CI loops: prefix the command, trace its files and outputs, and skip the work on the next run when the guards match. The measured win in the repo is a C transform, 312.913 ms to 3.972 ms. It is not a general CI speedup. Hits cost about 4 ms on the published runner, so tiny commands get slower, and it will not cache Python, shell pipelines, or `cc -c` yet.

Those refusals are intentional. An unknown syscall or a nondeterministic read disables reuse instead of guessing. Linux x86_64 only. Benchmarks: https://github.com/Satwik-P28/tracejit/blob/main/benchmarks/results/break-even.md

If you have a deterministic job that is still refused, or a cached result that should have been recomputed, file a Break TraceJIT issue with the command and a minimal testcase.

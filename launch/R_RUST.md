# r/rust draft

Title: TraceJIT 0.1.0 – ptrace, guards, and reuse for whole Linux commands

TraceJIT is a Rust workspace that traces an unmodified Linux x86_64 process with ptrace, classifies the effects, and reuses the command only after synchronous guards pass. PROVEN additionally requires seccomp and Landlock. UNKNOWN and NONDETERMINISTIC do not reuse.

The number I trust is from the committed harness, not a single demo run: a C data transform went from 312.913 ms to 3.972 ms (78.780x). The same machinery loses on short commands. A 7.396 ms ETL was 7.957 ms on the cache hit, and the later hit floor was about 4 ms. Python startup (getrandom, gettid), shell, and cc are refused rather than special-cased.

I am looking for adversarial cases more than features. If you can make it reuse something it should recompute, file a Break TraceJIT issue. Accepted reports become permanent fixtures. Code and tables: https://github.com/Satwik-P28/tracejit

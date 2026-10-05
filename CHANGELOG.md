# Changelog

## 0.1.1

- `tracejit explain` prints observed inputs, outputs, and guards without environment values.
- `tracejit doctor` names an unsupported OS and architecture, explains a ptrace denial, and separates `GUARDED` reuse from `PROVEN`.
- A file-backed `MAP_SHARED` mapping that is writable, or that `mprotect` makes writable, is `UNKNOWN`. `mremap` of a recorded file mapping is `UNKNOWN`. v0.1.0 ignored these syscalls.
- vDSO `clock_gettime`, `gettimeofday`, and `time` are redirected to real syscalls before the first userspace instruction. If that cannot be completed, the trace is `UNKNOWN` and is not reused.
- The 312.913 ms and 7.396 ms results stay attached to commits `e9684c1` and `63e3363`. They were not remeasured for 0.1.1.

## 0.1.0

Linux x86_64 release. The published measurements are the synthetic C transform at `e9684c1` (312.913 ms to 3.972 ms) and the short C ETL at `63e3363` (7.396 ms to 7.957 ms).

# Roadmap

V1 is whole-command reuse on Linux x86_64. The items below are not implemented. None of them is implied by the current CLI.

Final adversarial verified subset is summarized in [docs/final/FINAL_ANSWER.md](docs/final/FINAL_ANSWER.md). Short-command losses and low native census eligibility are retained on purpose.

## Next, and small enough to review

These are the concrete gaps already visible in this repository. Labels a maintainer can apply later are noted in [docs/launch/PROPOSED_ISSUES.md](docs/launch/PROPOSED_ISSUES.md). They are not open GitHub issues until someone creates them.

- Focused dependency bump for `libsqlite3-sys` / rusqlite addressing RUSTSEC-2026-0459 (deferred from TRA-28 audit).
- Model high-frequency census refusals (randomness/clock) only with minimal semantics + oracle + chaos — never silent admits.
- Complete-event proof obligation before any selective seccomp-BPF tracing experiment ([docs/final/P1_TRACING_ARCHITECTURE.md](docs/final/P1_TRACING_ARCHITECTURE.md)).
- vDSO `clock_gettime`, `gettimeofday`, and `time` are redirected to syscalls before the program runs. Other vDSO helpers, including the signal trampoline, are left in place.

## Deliberately later

- Partial-subgraph reuse.
- eBPF as a second tracer. It needs its own story for lost events before it can be compared with ptrace.
- A warm process that skips startup. The published hit-path notes say the safety checks would remain. Do not add a daemon to hide them.
- macOS, Windows, remote caches, GPU tracing, network replay, speculative execution, and a web UI.

## Not goals

TraceJIT is not trying to become Bazel, Nix, or ccache. If a command already has a correct declared graph, use that system.

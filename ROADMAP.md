# Roadmap

V1 is whole-command reuse on Linux x86_64. The items below are not implemented. None of them is implied by the current CLI.

## Next, and small enough to review

These are the concrete gaps already visible in this repository. Labels a maintainer can apply later are noted in [docs/launch/PROPOSED_ISSUES.md](docs/launch/PROPOSED_ISSUES.md). They are not open GitHub issues until someone creates them.

- Model the syscalls that made `shell-pipeline` and `cc -c` `UNKNOWN` in `benchmarks/results/break-even.md`, each with a fixture that still fails closed if the model is incomplete. The recorded numbers include 115, 293, and 439. Confirm those numbers against the benchmark host's `unistd_64.h` before naming them in a patch.
- Add one workload that is allowed to be slower than baseline, and keep publishing the loss.
- vDSO `clock_gettime`, `gettimeofday`, and `time` are redirected to syscalls before the program runs. Other vDSO helpers, including the signal trampoline, are left in place.

## Deliberately later

- Partial-subgraph reuse.
- eBPF as a second tracer. It needs its own story for lost events before it can be compared with ptrace.
- A warm process that skips startup. The published hit-path notes say the safety checks would remain. Do not add a daemon to hide them.
- macOS, Windows, remote caches, GPU tracing, network replay, speculative execution, and a web UI.

## Not goals

TraceJIT is not trying to become Bazel, Nix, or ccache. If a command already has a correct declared graph, use that system.

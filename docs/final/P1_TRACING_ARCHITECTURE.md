# P1 §6 — Tracing architecture competition (measured)

Date: 2026-11-14  
Tip: see `benchmarks/results/final_p1/tracing_completeness.json` (`commit` field).

## Production baseline (accepted)

TraceJIT V1 observes with **ptrace syscall-stop coverage for the whole process tree** (`tracejit-trace` Linux backend). Fork/vfork/clone/exec events are registered before child work proceeds. Unmodeled successful syscalls classify `UNKNOWN` and refuse reuse.

This is the reference backend for effect observation. No selective filter is enabled in production.

## Complete-event coverage obligation (before selective tracing)

A filtered/seccomp-assisted tracer is admissible only if all of the following hold on the supported command set:

1. Observed effects match the ptrace-all reference on held-out fixtures (independent oracle / census equivalence).
2. Fail-closed semantics remain intact (dropped/lost events ⇒ refuse reuse).
3. Real trace overhead improves materially (measured, not assumed).
4. Unknown kernels / missing features fall back to the reference backend.

Anything filtered must be **proven irrelevant** for Obs (not merely rare), or become a hard deopt. Descriptor creation, mmap/mprotect, signal delivery, and restart/event ordering are treated as high-risk to filter.

## Alternatives studied (not ported)

| System | Idea | Applicability | Decision |
| --- | --- | --- | --- |
| strace `--seccomp-bpf` / syscall classification | Selective stop | Attractive for overhead | **Deferred** until obligation above is discharged with version-specific tests |
| rr syscall buffering / record-replay | Full replay semantics | Different product (replay ≠ whole-command reuse) | **Not adopted** as TraceJIT architecture |
| eBPF as trusted dependency logger | Low overhead | Lost events / attach races / child coverage unbounded | **Measurement adjunct only**; never sole dependency source |
| Custom JIT / daemon tracer | Long-lived attach | Startup/security/cleanup cost dominates short commands | **Rejected** (prior Phase G/K) |

## Measured samples (this tip)

Raw: `benchmarks/results/final_p1/tracing_completeness.json`

- Host `strace -c -f` summaries for `c-etl` and `plain_file_read` (adjunct).
- TraceJIT cold-run `process_count`, `dependency_count`, `output_count`, `effect_counts` for the same shapes.
- `selective_tracing.status = deferred`.

## Non-claims

- No claim that seccomp-BPF selective tracing is safe for TraceJIT Obs yet.
- No claim that eBPF completeness equals ptrace-all.
- No unjustified custom JIT.

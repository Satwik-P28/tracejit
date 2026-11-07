# Phase 2L — developer-preview release gate

No release, crate publication or announcement was made.

## What a developer can do today

```bash
cargo build --release
./target/release/tracejit doctor
./target/release/tracejit run -- gzip -9 -c input.txt > out.gz
./target/release/tracejit run --json -- gzip -9 -c input.txt > report.json
./target/release/tracejit explain --json
./target/release/tracejit cache stats
./target/release/tracejit cache clear
```

There is no installer or packaged binary; installation is a source build. Supported platform is
Linux x86_64 with ptrace. `doctor` reports os, arch, support, ptrace, seccomp, Landlock, whether
`PROVEN` is available, the cache path and its writability, and explicit problem lines. On this host:
`landlock no`, `proven no`, with the reason that both seccomp and Landlock are required.

The safe default is visible: unsupported commands still run and produce native output; they are
simply not reused. `--admission auto|always|never|auto-v1` is explicit, `auto` is the default, and
JSON output exposes classification, decision, reasons, guard status and outputs. Cache inspection
and clearing exist. The allocator-entropy contract is opt-in and profile-checked; it is not general
determinism.

## Release blockers

### Correctness
- `PROVEN` has never been exercised: no Landlock on this host. Reuse is `GUARDED` only.
- A shared stdin open file description mutated by another process after the last observed operation
  and after exit is not detectable. Documented, not solved.
- `kcmp` is unavailable; alias detection is the conservative device/inode/position test.
- `PTRACE_EVENT_EXIT`/`VFORK_DONE` are not requested; exit-time state is verified at `exit_group`
  instead. Reparented/CLONE_PARENT processes are reconstructed and marked unknown.

### Environment support
- Linux x86_64 with ptrace only; no aarch64, no non-Linux, no container-specific evidence.
- Landlock-dependent enforcement requires a kernel with Landlock ABI 3+; untested here.
- autoconf is absent from this host, so a real autoconf configure is not in the measured matrix.

### Performance
- Only zlib shows a repeatable net win (1.096x/1.125x); bzip2 reuses but nets 0.98-1.04x because the
  build dominates; libpng and lz4 show no reuse benefit (`always` is 0.28-0.82x).
- Whole-command admission refuses `make`, `cc`, shells and pipelines, so accelerator coverage is
  narrow and dominated by deterministic filter/compressor tools.
- The hit path costs milliseconds; sub-10 ms tools are correctly declined but this caps usefulness.
- No peak-RSS measurement (`/usr/bin/time` absent, no delegated cgroup).

### Usability
- No installer, no shell completion, no progress reporting; diagnostics are text or JSON.
- Users must know to pass `--contract allocator-entropy-v1` to admit common glibc tools; without it
  most tools stay refused.
- No documented compatibility matrix for common distros/kernels beyond `doctor`.
- Troubleshooting is `explain --json` plus `doctor`; there is no guided first-run experience.

## Gate decision

Not ready for an external developer preview as a general accelerator. The engine is trustworthy for
what it accepts: 14/14 fidelity workloads, zero known incorrect hits in the regression and fuzz
suites, correct parallel fork/vfork behaviour, and reproducible clean-commit sessions. It is not yet
broadly useful: one positive repository workflow, `PROVEN` blocked, and the dominant developer
commands are refused by design.

Recommended next steps before preview: Landlock-capable CI, a wrapped-child experiment for build
tools, and a first-run walkthrough that explains why a command was refused.

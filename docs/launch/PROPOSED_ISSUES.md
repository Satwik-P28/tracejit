# Proposed issues

These are not open yet. Create them after review if they are still accurate. Do not file them in bulk on launch day.

## Model one recorded unknown syscall

Labels: `syscall-coverage`, `help wanted`, `correctness`

`benchmarks/results/break-even.md` records unmodeled syscalls for the shell pipeline and for `cc -c`, including numbers 115, 293, and 439 on that x86_64 runner. Confirm the names in that host's syscall table before writing a decoder. The patch needs a fixture. If the syscall's result can change control flow and TraceJIT cannot guard it, the class stays `UNKNOWN`.

## Make a libc clock_gettime visible or refuse it

Labels: `safety`, `correctness`

`vdso_clock` calls libc `clock_gettime`, `gettimeofday`, and `time` and is expected `NONDETERMINISTIC`. Do not replace that with a raw `syscall` fixture, and do not treat a missing clock syscall as proof that time was unused.

## Good first issue: explain a fixture in the adversarial doc

Labels: `good first issue`, `documentation`

Pick one case in `tests/fixtures/cases.json` whose row in `docs/ADVERSARIAL.md` is only the expected class. Read the matching branch in `tests/fixtures/fixture_driver.c` and add two sentences: what the process does, and which effect forces the class. Do not change the expected class.

## Publish the hit-path floor next to every new win

Labels: `performance`, `benchmark`

Any new workload added to the harness must keep a command short enough to lose, or must point at the existing loss and say why this workload is above the floor. Hand-edited numbers are not acceptable. The harness output is the result.

## Doctor on a container without SYS_PTRACE

Labels: `good first issue`, `documentation`

Run `tracejit doctor` in a default Docker container on Linux x86_64 and paste the output. If the ptrace message does not tell the reader whether reuse can continue, adjust the message. Do not weaken the probe.

## Fast guard mode needs a written caveat in the CLI help

Labels: `documentation`, `safety`

`--guard-mode fast` is experimental. The clap help should say that metadata is not content, in one sentence. No behavior change.

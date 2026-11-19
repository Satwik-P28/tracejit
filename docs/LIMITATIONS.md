# Known limitations

TraceJIT is a research-oriented prototype. It is not a general guarantee of
execution equivalence, has not been peer reviewed, and has no production
adoption. The list below is deliberately explicit; a beta release that hides
these would be dishonest.

## Correctness boundaries

- **Validate-to-restore TOCTOU.** Guards are checked, then cached outputs are
  materialised. Another process can modify an input in the window between the
  two steps. Guards are validated once, immediately before the restore; that is
  the last observation point, not a filesystem freeze. A wrong hit is possible in
  principle; report it with the Break TraceJIT template.
- **No hard-kill atomicity for multi-output restores.** A single output is
  renamed into place atomically. Multiple outputs are staged, recorded with a
  restore intent, and rolled back on a detected soft failure. A hard kill
  (`SIGKILL`, power loss) between renames can leave a partially restored output
  set. Restore intent causes the next attempt to refuse a hit and retrace
  instead of exposing a mixed result.
- **Observation is ptrace-level.** TraceJIT sees modelled kernel crossings, not
  arbitrary userspace influence. Unmodelled syscalls, `io_uring` edge cases, or
  data passed through a helper the tracer does not observe can force a refusal
  or, in an unmodelled case, be missed. Fail-closed refusal is the intended
  behaviour; a missed effect is a bug.
- **`PROVEN` is not a proof.** It means seccomp and Landlock ABI 3+ were
  installed for that execution. Certificates never assert
  `FullEquivalenceProof`.
- **Determinism classes are conservative.** `UNKNOWN`,
  `NONDETERMINISTIC` and `EMPIRICALLY_STABLE` never reuse. That means many
  ordinary commands (Python, most shells, compilers) simply never hit.

## Performance boundaries

- Warm hits have a fixed cost of several milliseconds. Short commands lose.
  Multi-step ETL sessions can lose even when every individual hit is correct.
- Output materialisation and `fsync` dominate warm-hit time for large outputs.
  Hashing inputs is a minority of the cost.
- Eligibility under unmodified defaults is low: Most real-world commands read a
  clock, entropy, or process identity. The census in
  `benchmarks/releases/` records this rather than tuning the classifier to look
  good.
- Measured numbers are per-commit and per-host. They are not a promise about
  other machines or workloads.

## Platform boundaries

- Linux x86_64 GNU only. There is no macOS, Windows, AArch64, or musl build.
  `doctor` refuses other platforms instead of degrading silently.
- `ptrace` must be permitted. Under restrictive `yama.ptrace_scope` settings,
  TraceJIT refuses rather than working around the policy.
- The cache is local, unencrypted, and not isolated between users.

## Research results kept as negatives

- fs-verity as a content witness cannot be validated on the test kernel
  (`EOPNOTSUPP`); the prototype stays off the default path.
- Reflink-based restore (`FICLONE`) is unsupported on the test filesystem.
- Restore-intent elision saved approximately 0 ms and was rejected.
- Persisted success statistics for admission were not justified by measurement.
- Destination-match restore skipping saved nothing once outputs were consumed.

## Release-engineering boundaries

- Byte-for-byte reproducible builds are not claimed; the manifest exists so a
  second build can be compared by hand.
- Artifact attestations require GitHub OIDC and are not produced by the local
  packaging script.

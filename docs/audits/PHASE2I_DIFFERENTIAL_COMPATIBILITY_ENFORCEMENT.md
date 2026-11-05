# Phase 2I — differential testing, compatibility reach, enforcement

## 1. Differential testing

`benchmarks/differential/fuzz.py` now runs 45 comparisons per seed (up from 32) and saves the raw
result JSON. Runs: seed 7 and seed 11, both **45/45 ok, 0 incorrect hits**. This is sampled evidence,
not a proof.

Case construction:

- Eight commands: `sed`, `wc`, `md5sum`, `gzip`, `base64`, `tr`, and `sed` over `sub/input.txt`.
- Each command is run cold and warm, and the warm bytes are compared with a fresh native run.
- Mutations between the two runs: file content replacement, symlink repointing, permission change,
  executable replacement, inherited-stdin offset, a concurrent writer, metadata-only `utime`, and
  directory replacement (rename the directory a relative path resolves through, then put a new one
  with different content in its place).
- Each case records a reproduction line (`repro`).
- A corrupt CAS object is overwritten and the next run must either refuse or match native bytes.
- A mutation is never skipped silently for the cases it applies to; `sed-sub` exists specifically so
  directory replacement is exercised.

Failure shrinking: every case is already a minimal two-run reproduction; when a case fails, the
harness reports the case name, the command line, the decision, and whether the bytes differed, which
is the shrinking target. No automated delta-debugger is implemented, and the report says so rather
than claiming one.

Deterministic seeds are recorded in the JSON (`"seed": 7` / `11`). Re-running a seed reproduces the
case order and the injected random content.

Limits: 45 cases × 2 seeds cover the listed mutation classes only. Zero failures cannot establish
noninterference, and no such claim is made.

## 2. Compatibility reach

Fixed suites retained: 16-workload direct suite and the nine-workload historical census, native and
controlled, re-run at the final Phase 2I tree. Results are in
`benchmarks/results/phase2i/direct/` and `.../census/`.

- Direct 16, native: **1/16 reused** (`gzip`), 16/16 traced output identical.
- Direct 16, controlled: **7/16 reused** (`gzip`, `bzip2`, `sed`, `tr`, `base64`, `md5sum`, `wc`),
  16/16 output identical.
- Census 9, native: **0/9** reused, 9/9 output equivalence.
- Census 9, controlled: **0/9** reused, 9/9 output equivalence.

These match the Phase 2H baselines, so the admission change did not move contract coverage.

The zlib session adds a real repository data point: `./minigzip` (compression) is `Guarded` and
reuses at ~24 ms versus ~390 ms native. `./minigzip -d` is `Unknown` because of one rule:

```
unmodeled successful syscall 8: lseek on inherited descriptor 0 is not modelled
```

This is the highest-value compatibility change available: modelling `lseek` on an inherited,
seekable stdin descriptor (recording the resulting offset as a dependency) would unlock
decompression, `cat`-style filters and many tools that rewind stdin. It is a narrow, testable rule,
unlike modelling a whole build system.

The other realistic blockers measured in this phase:

- `make`: `Nondeterministic` (`process read system clock: realtime`). Build drivers read the clock
  for timestamps; whole-command reuse of a build system is not achievable under the current model.
- `make test` / compiler and test runners: `Unknown` on `setresuid`/`setresgid` (117/119) with `-1`
  arguments, and a failed fd operation on `-1`. These are process-identity calls, not effects, but
  they are currently unmodeled and therefore refused.

Prioritisation by workflow, not syscall count:

1. inherited-stdin `lseek` — unlocks decompression and filter pipelines (single rule).
2. `setresuid`/`setresgid` with `-1` — a no-op query form; unlocks test binaries that drop
   privileges defensively (two rules, must be recorded exactly, including the failure case on `-1`).
3. build-driver clock reads — requires a contract for timestamp effects, not a syscall table entry.

## 3. Portability of the allocator-entropy profile

The contract is pinned to glibc build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65`, resume offset
`0xa9e89`, destination `0x20b178`, signature `0f 05 48 8d 5d d0 48 83 f8 08`. A different glibc
version or distro build is refused, by design. No second build is available on this host, so
portability is **untested**; no general glibc compatibility is claimed.

This is a real scaling limit: each supported libc build needs an audited call-site profile. The
sustainable alternative is not "more profiles by hand" but an execution strategy that does not
depend on intercepting a libc-internal call site — for example a narrower contract that treats the
allocator initialisation as an explicit, declared input, or a runtime that can identify the call
site semantically rather than by byte offset. Neither is implemented here.

## 4. Enforcement status

Unchanged and still blocked:

- `/sys/kernel/security/lsm` reports `capability,selinux`; Landlock is not present.
- `tracejit doctor` reports `landlock no` and `proven no`.
- `unshare -m` is not permitted, so mount-namespace invalidation remains untested.
- `PROVEN` stays blocked. Controlled entropy is not a sandbox and no isolation is claimed.

The controlled contract's safety rests on classification and guards, not on kernel enforcement.
Any future `PROVEN` claim requires seccomp plus Landlock ABI 3+ actually exercised in CI, not just
detected.

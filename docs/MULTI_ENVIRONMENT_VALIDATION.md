# Multi-environment validation (Phase AE)

Question: does TraceJIT behave the same way outside the one host every earlier phase used?
This document records the environments that were actually exercised, the probe results, and
the environments that were **not** obtained, with the exact blockers.

## 1. What was tested, and what each environment is

| # | environment | userspace | glibc | kernel | workspace fs | LSM list | how |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | this VM | Ubuntu 24.04.3 | 2.39 | 6.1.102 | ext4 | `capability,selinux` (no Landlock) | native |
| E2 | unpacked Ubuntu 25.10 base root, user+pid+mount namespace | Ubuntu 25.10 | 2.42 | 6.1.102 (shared) | ext4 directory inside the root | same as E1 | `unshare -Urmpf --map-root-user` + `chroot` |
| E3 | GitHub Actions `ubuntu-24.04` runner | Ubuntu 24.04 | 2.39 | runner-dependent | runner | runner-dependent | workflow `.github/workflows/phase-ae-environment.yml` (prepared, see §5) |

E2 is a genuinely different userspace — different glibc build, loader, distribution and
coreutils — but **the same kernel and the same host**. It is not a second machine and it is not
third-party reproduction. The harness says so in the JSON it writes.

No additional kernel was available: the VM runs one kernel, there is no container runtime
(`docker info` fails: no daemon), and no privileged mount/namespace or module loading is
available. Landlock is absent from `/sys/kernel/security/lsm` in every environment, so the
`PROVEN` path could not be exercised anywhere.

## 2. Environment E1 — full probe

`benchmarks/results/phaseae/environment-local.json` (regenerated in this phase with the
corrected enforcement probe):

* kernel 6.1.102, x86_64, 8 CPUs, glibc 2.39, ext4 workspace, tmpfs at `/dev/shm`,
  `doctor`: `supported=true`, `ptrace=true`, `seccomp=true`, `landlock_abi=null`, `proven=false`.
* `guarded_runs`: `Executed/MISS/GUARDED` then **`Reused/Reused`** — the ordinary reuse path
  works on this host.
* `enforce_runs`: `Executed/MISS/GUARDED` twice — under `--enforce`, reuse requires a `PROVEN`
  candidate (`crates/tracejit-core/src/lib.rs:471`), which this host cannot produce, so no
  reuse happens and no run is labelled `PROVEN`. Commands still exit 0 and produce correct
  output, which matches `SAFETY.md` ("a failed sandbox spawn can fall back to an unenforced
  discovery trace; that result is not promoted").
* `label_never_exceeds_capability=true`,
  `enforce_refuses_reuse_without_proven_capability=true`,
  `enforce_commands_still_succeed=true`.

The previous version of this probe inferred enforcement from
`enforced == doctor.proven`, which is vacuously true when both are false. It reported
`label_consistent=true` while nothing was enforced. That field is gone; the probe now records
the two arms separately, and `ci_annotations.py` publishes the corrected pair of booleans.

## 3. Environment E2 — a second userspace

Harness: `benchmarks/phase_ae/multi_environment.py`; raw output
`benchmarks/results/phaseae/multi_environment.json`.

| probe | result |
| --- | --- |
| distribution / glibc | Ubuntu 25.10 / `GLIBC 2.42-0ubuntu3` |
| kernel | 6.1.102 (inherited) |
| `ldd --version`, `/etc/os-release`, `stat -f` | all read successfully inside the root |
| `gzip -9 -n -c` twice, `--contract allocator-entropy-v1` | `MISS/NONDETERMINISTIC` both runs; **stdout byte-identical** to the host run; no reuse |
| same workload, native policy (no contract) | `MISS/NONDETERMINISTIC` both runs; identical stdout |
| `--enforce` twice | `MISS/UNKNOWN` both runs; no reuse, no `PROVEN` |
| exit status | 0 everywhere; no crash, no incorrect output |

The cause is not a portability defect in the tracer but the definition of the entitlement:
`allocator-entropy-v1` is admitted only for an **audited libc build**
(`tracejit-core/src/lib.rs:826-837`, `allocator_entropy_profile(build_id)`). glibc 2.42 is not
audited, so the contract is unavailable, the `getrandom` call from the allocator is observed
as ordinary entropy, and the trace is `NONDETERMINISTIC` — refused. Under `--enforce` the
trace is `UNKNOWN` because the sandbox could not be installed in the namespace.

Practical consequence for the release notes: **on an unaudited glibc, TraceJIT is safe but
provides no reuse for ordinary malloc-using programs.** That is a portability limit of the
strongest eligibility path, and it must be stated wherever reuse numbers are quoted.

## 4. Capability matrix (what each environment could and could not do)

| capability | E1 Ubuntu 24.04 | E2 Ubuntu 25.10 (namespace) | needed for |
| --- | --- | --- | --- |
| ptrace of a child | yes | yes | tracing |
| seccomp-BPF | yes | yes | `PROVEN` (with Landlock) |
| Landlock ABI ≥ 3 | **no** | **no** | `PROVEN`, enforcement |
| `allocator-entropy-v1` | yes (audited 2.39) | **no** (unaudited 2.42) | reuse for malloc-using programs |
| guarded reuse | yes | no | ordinary caching |
| enforcement path | refuses reuse, no `PROVEN` | refuses reuse, no `PROVEN` | the `PROVEN` claim |
| Firebuild competitor runs | yes | not attempted | competitive matrix |

## 5. Environment E3 — CI runner, prepared but not qualified

`.github/workflows/phase-ae-environment.yml` builds the project, runs
`environment_probe.py`, publishes the fingerprint and the corrected enforcement booleans as
public annotations, and runs the accounting regressions. It was **not** used as evidence in
this phase: the runner's annotations could not be read back from this environment (the GitHub
API is rate-limited for unauthenticated callers and no token is configured), so no run of it is
claimed. Even when it does run, a GitHub-hosted runner is vendor infrastructure of the same
project, not independent third-party reproduction.

## 6. What is still missing

* A second **kernel** (the only meaningful way to exercise Landlock, different ptrace
  behaviour and different `statx`/`O_PATH` semantics). Blocked: no privileges, no VM runtime,
  no container daemon in this environment.
* An **audited** second glibc. Adding a build to the audit list is an engineering task with a
  security review, not a benchmark; it is out of scope here.
* A second **machine** and an independent operator for the competitive numbers.

These are release-scoping facts, not implementation defects: the binary was correct and its
output byte-identical in every environment it ran in.

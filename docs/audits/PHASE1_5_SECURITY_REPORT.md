# Phase 1.5 security report

## 1. Trusted computing base

Enforcement runs in `crates/tracejit-sandbox`, inside the child's `pre_exec` closure, between
`fork` and `exec`:

1. `ptrace(PTRACE_TRACEME)` so the parent can trace;
2. if a policy is supplied, `tracejit_sandbox::apply(policy)`:
   - refuse unless `capabilities().can_prove()`;
   - `landlock_create_ruleset` with every handled access right it supports for the ABI;
   - one `landlock_add_rule(PATH_BENEATH)` per declared readable path and writable path;
   - `prctl(PR_SET_NO_NEW_PRIVS, 1)`;
   - `landlock_restrict_self`;
   - install the seccomp filter (architecture check, then a deny list).

Trusted: the kernel's ptrace, seccomp and Landlock implementations, and the parent tracer process.
Not trusted, and not intended to be: the traced program, the workspace it runs in, and the cache
directory's contents (every CAS object is rehashed on read).

## 2. Enforcement results on this host

| Check | Result | Evidence |
| --- | --- | --- |
| Landlock available | **BLOCKED** | `/sys/kernel/security/lsm` = `capability,selinux`; `landlock_create_ruleset(VERSION)` returns `-1`, errno 38 `ENOSYS`; no `landlock` module in `/lib/modules/6.1.102` |
| Landlock ABI 3+ | **BLOCKED** | same |
| Full `PROVEN` path | **BLOCKED** | requires Landlock; not exercised here or in Phase 1 |
| Seccomp filter installation | **PASS** | new `seccomp_filter_alone_denies_its_forbidden_surface` installs the exact filter `apply` installs |
| Denied network access | **PASS** | `socket(AF_INET, SOCK_STREAM)` returns `EPERM` under the filter |
| Denied forbidden syscall | **PASS** | `ptrace(PTRACE_TRACEME)` returns `EPERM` under the filter |
| Ordinary filesystem work unaffected | **PASS** | `open`/`write` on `/dev/null` still succeed under the filter |
| Failed policy cannot become reuse | **PASS** | `apply` returns `Err` whenever `can_prove()` is false; `enforcement_refuses_when_landlock_is_absent` asserts it on this kernel |
| Denied undeclared filesystem read | **BLOCKED** | needs Landlock; the pre-existing probe skips here |
| Re-execution under an existing profile | **BLOCKED** | needs Landlock |

**A skipped enforcement test is not a successful enforcement validation.** The two Landlock probes
in `tracejit-sandbox` print `skipped …` and return; they are reported as SKIP, never as PASS.

### Why the environment cannot be fixed from inside

Landlock is a kernel build/LSM-selection property. The host kernel (6.1.102) does not include it in
the active LSM list, no module is loadable, and a container cannot enable it. `/dev/kvm` exists, so
a nested kernel *could* in principle be booted, but no kernel image, initramfs tooling or QEMU is
installed and building one is outside this task's scope. The sanctioned path is a compatible CI
runner: `.github/workflows/ci.yml` already sets `TRACEJIT_REQUIRE_PROVEN: 1`, asserts
`proven yes` from `doctor`, and **fails the job if `RESULT sandbox SKIP` appears**. That gate is the
mechanism by which this report's BLOCKED items become verified, and it cannot be executed here
because pushing is not authorised.

## 3. Defect found and fixed: the capability probe

`capabilities()` reported `seccomp: true` from `prctl(PR_GET_NO_NEW_PRIVS) >= 0`, which is true on
any kernel with `prctl` and says nothing about filter installation. `doctor` could therefore claim
`seccomp yes`, and `PROVEN` could be granted, from a capability that was never established. The
install fails closed (`pre_exec` returns an error and the spawn aborts), so the consequence was
misleading telemetry rather than unsafe reuse. Fixed by probing `SECCOMP_GET_ACTION_AVAIL`, which
answers exactly the question `apply_seccomp` needs. A kernel too old to answer now reports
`seccomp no` and `can_prove()` is false.

## 4. What `PROVEN` actually guarantees

Established by code and by the tests above:

- the child cannot create sockets or use the denied control syscalls (`mount`, `bpf`, `keyctl`,
  module and swap operations, `ptrace`) — it gets `EPERM`;
- filesystem access is confined to the declared readable/writable path set, with write rights only
  where the profile declared them (Landlock, **untested here**);
- no set-uid escalation, via `no_new_privs`.

Not guaranteed, and never claimed in the documentation:

- that the observation was *complete*. `PROVEN` describes enforcement of the recorded profile, not
  proof that the profile captured every real dependency;
- anything about data already reachable through inherited descriptors (fd 0/1/2 are inherited, and
  a write to an inherited socket is a write, not a connection);
- memory safety, or isolation from the parent tracer;
- atomic multi-file restoration (see below);
- behaviour against a hostile *kernel*. No userspace sandbox can.

## 5. Residual security risks, ranked

| Risk | Severity | Status |
| --- | --- | --- |
| Landlock enforcement unverified on any kernel | **High (evidence gap)** | BLOCKED here; CI gate exists and would fail on skip |
| Guard→restore window: a dependency mutated after validation is not rechecked | Medium | Documented; renames replace entries rather than follow them, so redirection is not possible, but data mutation in that window is undetectable |
| Executable replaced between identity hashing and `exec` | Medium | **UNVERIFIED**: the recorded hash would describe the old binary while the new one ran. Not reproduced; no test |
| Crash during restoration leaves a mixed workspace and stray files | Medium | Documented limitation, no journal, no directory `fsync` |
| Cache ownership marker is unauthenticated | Low | Any directory containing `.tracejit-cache-v1` is adopted; the cache directory is trusted input, so this is a trust assumption, not a vulnerability, and it is now stated |
| Marker of the wrong type (directory/fifo) is adopted as "initialized" | Low | Introduced by the D7 fix; harmless because the rest of the root is still enumerated against an allow list |
| Same-process multi-connection cache use can raise `database is locked` | Low | Unsupported by design; one `Cache::open` per process |
| CAS repair path overwrites a mismatched object | Low | Safe by construction: the replacement's name is its own BLAKE3 digest, verified again on read |

## 6. Secrets and data

The cache stores captured stdout/stderr and output bytes verbatim in content-addressed objects under
the cache root, plus a full execution record in SQLite. It is not encrypted and not access-controlled
beyond filesystem permissions, so anything a traced program prints is readable by anyone who can read
the cache directory. `tracejit doctor` and the reports print paths and syscall names, never
environment values.

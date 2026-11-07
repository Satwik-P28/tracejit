# Phase 2M: the failed CI seccomp test

## Symptom

GitHub Actions run [42319563118](https://github.com/Satwik-P28/tracejit/actions/runs/42319563118)
(`CI`, commit `c7f2c68`) failed in `cargo test --workspace` at

`tracejit-sandbox::tests::seccomp_filter_alone_denies_its_forbidden_surface`

with the child exiting 125. The test maps every `apply_seccomp` error to 125, so the report named no
failure reason, which is how the defect survived Phase 1.5 and every local run.

## Root cause

`apply_seccomp` installed the filter without `PR_SET_NO_NEW_PRIVS`. Production enforcement did not
notice, because `apply` calls `apply_landlock` first, and that function sets `PR_SET_NO_NEW_PRIVS`
before `landlock_restrict_self`. The standalone test calls `apply_seccomp` directly and therefore
depended on the *ambient* value of `no_new_privs`.

seccomp(2) requires `CAP_SYS_ADMIN` in the caller's user namespace or `no_new_privs` before
`SECCOMP_MODE_FILTER` can be installed; otherwise `PR_SET_SECCOMP` fails with `EACCES`.

- This workspace shell has `NoNewPrivs: 1` and `CapEff: 0000000000000000`, and every test child
  inherits `no_new_privs`. The filter install therefore succeeded locally and the missing
  precondition was invisible.
- A GitHub `ubuntu-24.04` runner starts the job without `no_new_privs` and without
  `CAP_SYS_ADMIN`, so the install failed with `EACCES` and the child exited 125.

`CHANGELOG`-style summary: the test was not wrong about what to assert; the installation path was
wrong about what it must establish. The test's 125 also discarded the errno.

## Fix

`crates/tracejit-sandbox/src/lib.rs`

1. `apply_seccomp` now sets `PR_SET_NO_NEW_PRIVS` itself before installing the filter, and fails with
   `set no_new_privs before seccomp: <errno>` if that fails. The flag is idempotent, so the
   production path (Landlock first) is unchanged and no guarantee is lowered.
2. The probe child writes `seccomp installation failed: <error>` to fd 2 before `_exit(125)`, so a
   future failure names the errno instead of only an exit code.
3. The child asserts `PR_GET_NO_NEW_PRIVS == 1` after installation and fails if it is not, so the
   precondition can no longer be satisfied only by luck of the caller.

The test still installs exactly the filter `apply` installs, still requires `socket(AF_INET,
SOCK_STREAM)` and `ptrace(PTRACE_TRACEME)` to return `EPERM`, still requires `/dev/null` writes to
succeed, and still fails (rather than skips) on an installation error. Nothing was disabled or
weakened, and the capability-based early return for a kernel with no seccomp interface is unchanged.

## Verification

| Check | Result |
| --- | --- |
| `cargo test -p tracejit-sandbox -- --nocapture` | 4 passed, including the seccomp probe |
| `cargo fmt --all -- --check` | clean at `f5a9486` |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | clean |
| `cargo test --workspace` | 113 passed, 0 failed |
| Ambivalent local masking reproduced | `NoNewPrivs: 1` in this shell; a raw probe installs with `no_new_privs` and without `CAP_SYS_ADMIN` |

The runner-like precondition (`no_new_privs` clear, no `CAP_SYS_ADMIN`) cannot be re-created here:
`no_new_privs` is inherited and cannot be cleared, `setpriv` lacks the required privilege, and Docker
is installed but its daemon is unreachable. No claim is made that the failing path was re-executed
locally; the fix removes the dependence on that ambient state and the kernel contract is explicit.

## CI rerun

Not performed. The Phase 2M brief forbids pushing without explicit authorization, so the fixed
commit has no GitHub Actions run. The CI workflow triggers on `push`, so the rerun is one authorized
push of the Phase 2M commits away. `PROVEN` was not weakened to obtain a green run.

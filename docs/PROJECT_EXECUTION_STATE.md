# TraceJIT execution state

Updated at the Phase 2H worktree (base `45bd1c3`, branch `verify/phase1-5`). This file is the resume
point: what is done, what is measured, and what is blocked.

## Phase status

| Phase | Objective | Status | Evidence |
| --- | --- | --- | --- |
| 2A.1 | Executable identity cannot file a profile under the wrong identity | **PARTIAL PASS** — re-hashed before exec, fails closed; final window open | `PHASE2_EXEC_IDENTITY.md` |
| 2A.2 | Landlock + seccomp `PROVEN` path executed | **BLOCKED** — LSM list `capability,selinux`; no Landlock | `PHASE1_5_SECURITY_REPORT.md` |
| 2A.3 | Restoration crash consistency | **ACCEPTED LIMITATION** — recovery by re-execution | `PHASE1_5_INDEPENDENT_REVIEW.md` |
| 2B.2 | Permission checks guardable | **PASS** | `PHASE2B_ACCESS_SOUNDNESS.md` |
| 2B | Descriptor and pipe model | **PASS for soundness, FAIL for reach** | `PHASE2C_PIPE_SOUNDNESS.md` |
| 2C | First real-world workload reused | **PASS** — `gzip -9 -c` | `PHASE2C_FIRST_REALWORLD_HIT.md` |
| 2D.1 | Timestamp invalidation defect explained | **WRONG, corrected in 2E** | `PHASE2D_ATIME_ANALYSIS.md` |
| 2D.2 | Fixed direct-execution suite | **PASS** — 16 workloads | `PHASE2D_DIRECT_COMPATIBILITY.md` |
| 2D.3 | Certified effect noninterference | **ASSESSED, NOT IMPLEMENTED** | `PHASE2D_NONINTERFERENCE_RESEARCH.md` |
| 2E | Directory dependency origin and typed guard | **PASS** | `PHASE2E_DIRECTORY_DEPENDENCY.md` |
| 2F | `statfs`, enumeration, inherited stdin; directory audit | **PASS with defects fixed**; two-category target **FAIL** | `PHASE2F_*.md` |
| 2G.A | Path-resolution adversarial audit | **PASS after fix** — confirmed false hit removed | `PHASE2G_PATH_RESOLUTION.md` |
| 2G.B | Allocator randomness identified | **PASS** — glibc `tcache_key_initialize`; musl untested | `PHASE2G_ALLOCATOR_ENTROPY.md` |
| 2G.C–E | Contracts, prototype, adversarial tests | **PASS (narrow)** — 4 verified tools | `PHASE2G_EXECUTION_CONTRACTS.md` |
| 2G.F | Fixed suites, two sessions, workflow | **PASS** — 1/16 native, 7/16 controlled, 14.74x workflow | `PHASE2G_COMPATIBILITY.md` |
| 2H.1 | Audit and harden the entropy contract | **PASS** — audited call-site profile; unknown builds/offsets refused | `PHASE2H_CONTRACT_HARDENING.md` |
| 2H.2 | Allocator security implications | **PASS with documented weakening** — double-free detection preserved; fixed-key secrecy loss is opt-in and scoped | `PHASE2H_ALLOCATOR_SECURITY.md` |
| 2H.3 | Adversarial differential testing | **PASS** — 32 cases, 0 incorrect hits; coverage, not proof | `PHASE2H_DIFFERENTIAL.md` |
| 2H.4 | Stable inherited-stdin reuse | **PASS** — `atime` removed from the runtime identity; `tr` reuses in both sessions | `linux_integration.rs` |
| 2H.5 | Cost-aware admission | **PASS** — `--admission auto` beats always on mixed workloads | `PHASE2H_ADMISSION_AND_BENCHMARKS.md` |
| 2H.6 | Developer-loop benchmarks, two sessions | **PASS with slowdowns reported** | `PHASE2H_ADMISSION_AND_BENCHMARKS.md` |
| 2H.7 | Expand compiler/test-runner compatibility | **NOT DONE** — refusal chain analysed, no handler added | this file §Next |
| 2D.6 | `PROVEN` enforcement | **BLOCKED** — never executed on any host | — |
| 3 | Performance engineering | **NOT STARTED** | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **NOT ESTABLISHED** | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild/clang | — |

## Latest verified test results

`cargo test --workspace` **108 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 33 Linux
integration + 7 core + 5 effects + 25 guards + 4 sandbox + 13 trace), with `fmt --check` and
`clippy -D warnings` clean, at the Phase 2H worktree.

## Latest measured results (two sessions)

- **Direct 16:** native **1/16**; controlled **7/16** in both sessions (`tr` is now stable);
  auto **0/16 on the second run** by design (measure, trace, then hit on the third).
- **Census 9:** **0/9** native and controlled, both sessions, 9/9 output equivalence. Shell clocks,
  PIDs and sockets remain the blockers; the allocator key is no longer one of them.
- **Workflow (5.4 MB, 4 commands):** always 8.95x (659.50 → 73.68 ms) and 9.64x (660.23 → 68.47 ms);
  auto 10.36x (657.91 → 63.50 ms) and 10.27x (657.91 → 64.06 ms), skipping `wc`.
- **Developer loops:** always 1.52x/1.59x slower than direct; auto **1.08x/1.08x**. Per-scenario
  losses are reported, including the deliberate invalidation loop (`edit` 3.66x/3.88x under auto).
- **Differential fuzzer:** 32 cases, 32 ok, **0 incorrect hits**, seed 7.

## Open correctness and security risks

1. **Fixed allocator key removes per-process secrecy.** Double-free detection still works (tested),
   but an attacker with a heap write could forge a tcache entry using the published key. Recommended
   correction: derive the key from the cache identity instead of a global constant.
2. **The contract is narrow, not determinism.** Only the audited glibc probe is controlled; clocks,
   PIDs, `sysinfo`, `sched_getaffinity`, application randomness, `/proc/self/maps` and network still
   refuse.
3. **Unknown runtime builds are refused**, which is deliberate; a profile must be audited and added.
4. **Validation-to-restore TOCTOU** remains for every guard.
5. **Symlinked output ancestors are refused**; restoration through a repointable path is unsafe.
6. **Mount-namespace changes** are only bound by `statfs`/enumeration; the path case is untested
   (`unshare -m` is not permitted here).
7. **`PROVEN` has never been executed**; the contract is not a sandbox and makes no isolation claim.
8. **Restoration is not crash-atomic.** Re-execution repairs it.

## Next executable actions

1. Derive the allocator key per identity and re-run the contract tests and two benchmark sessions.
2. Model `/proc/self/maps` for `grep`, or keep it refused.
3. Decide `getrusage`/`prlimit64` explicitly (recorded, falsifiable certificate or refusal); the
   developer-loop `compile`/`codegen` scenarios are the reference workload.
4. Finish the allocator matrix with a musl and a fully static program.
5. Landlock-capable CI job for the `PROVEN` gate.

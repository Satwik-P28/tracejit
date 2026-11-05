# TraceJIT execution state

Updated at the Phase 2I worktree (base `9b777ee`, branch `freebuff/phase2f`). This
file is the resume point: what is done, what is measured, and what is blocked.

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
| 2I.1 | Allocator-key security decision | **DECIDED** — fixed key retained, contained; derived and fresh-random options rejected with glibc evidence | `PHASE2I_ALLOCATOR_KEY_DECISION.md` |
| 2I.2 | Cost-aware admission and lifecycle audit | **IMPLEMENTED, MIXED** — deopts + TTL + cumulative estimate; ties `auto-v1`, loses to `always` on a long stable matrix | `PHASE2I_ADMISSION_AND_BENCHMARKS.md` |
| 2I.3 | Real repository developer session | **PASS** — zlib v1.3.1, `auto` 1.20×/1.07× net; `always` 1.71×/1.82× slower | `benchmarks/results/phase2i/repo/` |
| 2I.4 | Expanded differential testing | **PASS** — 45 cases × 2 seeds, 0 incorrect hits; repro lines saved | `benchmarks/results/phase2i/differential/` |
| 2I.5 | Compatibility measurement | **PASS** — 1/16 native, 7/16 controlled, 0/9 census, all equivalence counts unchanged | `PHASE2I_DIFFERENTIAL_COMPATIBILITY_ENFORCEMENT.md` |
| 2I.6 | Enforcement | **STILL BLOCKED** — no Landlock; `PROVEN` unexercised | same |
| 2D.6 | `PROVEN` enforcement | **BLOCKED** — never executed on any host | — |
| 3 | Performance engineering | **NOT STARTED** | — |
| 4 | Developer integrations | **NOT STARTED** | — |
| 5 | Research contribution | **NOT ESTABLISHED** | — |
| 6 | Competitive benchmarking | **BLOCKED** — no ccache/sccache/Firebuild/clang | — |

## Latest verified test results

`cargo test --workspace` **109 passed, 0 failed** across 8 suites (16 cache + 5 CLI + 33 Linux
integration + 8 core + 5 effects + 25 guards + 4 sandbox + 13 trace), three consecutive runs, with
`fmt --check` and `clippy --all-targets --all-features -D warnings` clean, at the Phase 2I tree.
The cache initialization now retries `SQLITE_BUSY`/`LOCKED` and arms the busy timeout first; before
that fix, concurrent cold starts failed intermittently with `database is locked`.

## Latest measured results (two sessions)

- **Direct 16:** native **1/16**; controlled **7/16**, 16/16 output equivalence in both modes.
- **Census 9:** **0/9** native and controlled, 9/9 output equivalence. Shell clocks, PIDs and sockets
  remain the blockers; the allocator key is no longer one of them.
- **Policy matrix (20 invocations, edit at 11):** direct 8776.59/7221.42 ms; never 0.99×/0.95×;
  always 4.03×/3.19×; auto-v1 3.55×/2.84×; auto **3.54×/2.73×**. Auto ties Phase 2H's policy; it
  does not beat it. Always wins on this long, fully eligible matrix.
- **zlib v1.3.1 session:** direct 6781.17/6606.07 ms; auto **1.20×/1.07×** net; always 1.71×/1.82×
  slower; never 0.98×/0.95×. Compression hits 24–28 ms vs ~380 ms native; decompression stays
  ineligible (`lseek` on inherited fd 0).
- **Differential fuzzer:** 45 cases × seeds 7 and 11, **0 incorrect hits**, 45/45 ok each.

## Open correctness and security risks

1. **Fixed allocator key removes per-process secrecy — contained, not solved.** Double-free
   detection still works; a heap-write attacker can forge a tcache entry with the published key.
   Phase 2I compared derived and fresh-random keys against glibc 2.39 and retained the fixed key
   because neither improves in-process secrecy and fresh randomness makes reuse impossible. The
   contract stays opt-in and is not a sandbox. See `PHASE2I_ALLOCATOR_KEY_DECISION.md`.
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

1. Model `lseek` on an inherited, seekable stdin descriptor as a recorded offset dependency; this
   unlocks `./minigzip -d` and filter pipelines and is the cheapest remaining win.
2. Handle `setresuid`/`setresgid` with `-1` arguments as exact no-op queries (including the `-1`
   failure case) so test binaries can be classified; keep everything else refused.
3. Do not derive the allocator key; the decision record explains why. Revisit only if key secrecy
   inside the traced process becomes a requirement, which would mean not reusing those runs.
4. Replace the constant 3-invocation horizon with a measured, per-identity invocation-rate estimate
   before claiming the adaptive policy is better than `auto-v1`; the current matrix shows a tie.
5. Model `/proc/self/maps` for `grep`, finish the musl/static allocator matrix, and add a
   Landlock-capable CI job; `PROVEN` stays blocked until then.

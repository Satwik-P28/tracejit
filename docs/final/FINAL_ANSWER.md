# Final answer — mandate §18 checklist

Evaluated tree: **origin/main `827b7763a73cddda4e3a99c9883fbae4b18d87d2`** (after PR #30).  
Release packaging branch: `cursor/final-adversarial-release-6ed7` (this document).  
Gates on that tip: `benchmarks/results/final_release/gates-summary.json` (fmt/clippy/tests/demo/modelcheck/K4/fuzz PASS).

---

## 1. Final SHA, branches, PRs

| Item | Value |
| --- | --- |
| origin/main (pre–TRA-29 packaging) | `827b7763a73cddda4e3a99c9883fbae4b18d87d2` |
| Release PR branch | `cursor/final-adversarial-release-6ed7` |
| PR #26 baseline/invariants | https://github.com/Satwik-P28/tracejit/pull/26 · merge `48899e667503` |
| PR #27 P0 process/TOCTOU | https://github.com/Satwik-P28/tracejit/pull/27 · merge `80edaa46aeb7` |
| PR #28 P0 restore durability | https://github.com/Satwik-P28/tracejit/pull/28 · merge `026e660f6722` |
| PR #29 P1 §§6–10 | https://github.com/Satwik-P28/tracejit/pull/29 · merge `bb4302fccaf7` |
| PR #30 P1 §§11–14 | https://github.com/Satwik-P28/tracejit/pull/30 · merge `827b7763a73c` |
| TRA-29 release docs PR | opened from this branch (see PR link after create) |

---

## 2. Changes by subsystem

| Subsystem | Paths | Change / rationale |
| --- | --- | --- |
| Trace / classify | `crates/tracejit-trace/src/linux.rs` | P0 refuses: O_TMPFILE, fcntl SETFL; RENAME_EXCHANGE UNKNOWN retained |
| Core hit path | `crates/tracejit-core/src/lib.rs` | Pre-restore guard recheck; interrupted restore-intent refuse HIT; TRACEJIT_TEST_* excluded from identity |
| Cache restore | `crates/tracejit-cache/src/lib.rs` | Per-pid restore-intent; soft rollback clear; dead-pid detection; single-path rename atomic only |
| Effects / CEGAR | `crates/tracejit-effects/src/cegar.rs` | Input-driven refine; never auto-deploy |
| Modelcheck | `scripts/modelcheck/check_state_machines.py` | + `restore_intent` IntentRefuseHit |
| Census / measure | `benchmarks/realworld/census.py`, `scripts/final_p1_measure.py` | ≥25 workflows; four e2e objectives |
| Docs | `docs/final/*` | BASELINE → P0/P1 packages → this FINAL_ANSWER |

Before: transparent reuse with soft restore rollback but shared-intent races / weaker process refuses. After: fail-closed P0 process+restore, measured P1 package, assurance matrix — without claiming multi-file atomicity or novelty.

---

## 3. Remaining defects / rejected approaches

| Severity | Item | Status |
| --- | --- | --- |
| High (known limitation) | Validate→restore TOCTOU residual after recheck | Documented; not “fixed” |
| High (limitation) | Hard-kill mid-restore mixed workspace | Intent refuses next HIT; no journal repair |
| Medium | `libsqlite3-sys` RUSTSEC-2026-0459 | Deferred dependency bump |
| Medium | Census eligibility 1/32 under native defaults | Honest boundary (randomness/clock) |
| — | Selective seccomp-BPF tracing | Deferred (§6 obligation) |
| — | Typed dependency DAG validator | Design only (§7) |
| Rejected | Bandit default admission; controlled Python on main; eBPF trusted logger; Firebuild/ccache code import; mtime-only hits; auto-deploy CEGAR | Recorded |

---

## 4. Coverage table

| Gate | Result on `827b776` / cited tip | Artifact |
| --- | --- | --- |
| Independent Obs oracle | PASS (integration seed-7 path) | linux_integration `phase_k2_oracle` |
| Modelcheck | PASS (+ restore_intent) | `final_release` / modelcheck |
| Differential fuzz | seed 29: 120 ok, **0 incorrect hits** | `final_release/differential-seed29.json` |
| Fault injection K4 | soft PASS; hard-kill Obs correct, HIT refused | `phase_k4_restore_fault.sh` |
| Compatibility census | 32 attempted, 1 reused | `final_p1/census/` |
| Certificate tests | 10 passed (prior assurance) | `final_p1_assurance/` |
| Miri / cargo-fuzz / TLC | **not run** | claims blocked for those tools |

---

## 5. HIT / DEOPT / EXECUTED

From `benchmarks/results/final_p1/e2e.json` (measured on tip `026e660`, still current product semantics on `827b776`):

| Counter | Value |
| --- | ---: |
| `kind` Reused (HIT) | **140** |
| `kind` Executed | **113** |
| `kind` Deoptimized | **0** (this e2e set) |
| `cache_decision` Skipped (admission) | **37** |

False-hit finding (historical, fixed): `renameat2(RENAME_EXCHANGE)` — now UNKNOWN / never reused (PR #18 / retained).  
Demo on `827b776`: mutation path prints **DEOPT** (expected).

---

## 6. Quantitative results (with CIs where recorded)

| Experiment | Result | Provenance |
| --- | --- | --- |
| Hit floor `plain_file_read` DIRECT vs warm | 0.384 ms vs 5.725 ms (warm **loss**) | `final_p1/e2e.json` n=30 bootstrap 95% CI |
| Throughput `c-transform` DIRECT vs warm | 32.662 ms vs 4.403 ms (~**7.4×**) | same |
| Session cumulative short ETL | TraceJIT 166 ms vs DIRECT 41 ms (**loss**) | same |
| Concurrency 8 workers | all_success; Reused 6 / Executed 2 | same |
| Census eligibility | **1/32** (`gzip-compress-stdout`) | `final_p1/census/` |
| Admission CurrentAuto regret | 49e6 ns preferred vs Always/Never | `final_p1/admission-eval.txt` |
| Make/Ninja identical rerun | graph tools faster; TraceJIT correct on mtime/corrupt | `phase_k8/` @ `364331b` |

No synthetic-only flagship; short-command losses retained.

---

## 7. Provenance

| Field | Value |
| --- | --- |
| Revisions | main `827b776`; e2e measured `026e660`; assurance `1d78029` |
| Host | Linux 6.12.113+ x86_64, 4 CPU, ext4 — `final_release/provenance.txt` |
| Scripts | `demo.sh`, `final_p1_measure.py`, `census.py`, `phase_k4_restore_fault.sh`, `modelcheck`, `differential/fuzz.py` |
| Fixtures | `tests/fixtures/*`, `docs/research/cegar/*.json`, `benchmarks/workloads/c-transform` |

---

## 8. Prior-art matrix

See `docs/final/PRIOR_ART_IMPLEMENTATION_MATRIX.md` (commit/file/license). Firebuild proprietary and ccache GPL-3 **not imported**. strace selective BPF / rr replay **rejected** as TraceJIT architecture.

---

## 9. Novelty assessment

Flagship engineering story: **fail-closed observable-equivalence enforcement for transparent whole-command reuse**, with adversarial false-HIT → fix, independent oracle, modelcheck, crash fault injection, and measured negatives (`docs/research/NOVELTY_MATRIX.md`, K10/K11).

**Not claimed:** inventing command caching, CEGAR theory, CAS, seccomp/Landlock, or peer-reviewed publication / production adoption.

Rejected hypotheses: bandit default; controlled-runtime “make Python reusable” on main; drop fsync for speed; selective tracing without complete-event proof.

Threats to validity: single-host measurements; census tool availability; SQLite advisory open; competitor arms skipped when tools absent.

---

## 10. Docs / demo / application materials

| Doc | Path |
| --- | --- |
| README | `README.md` (updated pointers) |
| Executive summary | `docs/final/EXECUTIVE_SUMMARY.md` |
| Technical report | `docs/research/TRACEJIT_TECHNICAL_REPORT.md` + final packages |
| Claims ledger | `docs/research/CLAIMS_LEDGER.md` |
| Artifact evaluation | `docs/final/ARTIFACT_EVALUATION.md` |
| Application materials | `docs/focus/APPLICATION_MATERIALS.md` |
| Runnable demo | `./scripts/demo.sh` |

---

## 11. Falsifiable correctness-contract stop line

TraceJIT is useful because it turns “maybe this command is pure” into a **testable refuse-or-reuse decision** under an explicit Obs contract—without requiring a declared build graph.

It is difficult because the kernel boundary is incomplete (vDSO, races, unmodeled syscalls), multi-file restore is not a transaction, and performance wins on long CPU work coexist with systematic losses on short commands.

**Where the contract stops (falsifiable):**

> If a dependency or effect is outside the modeled taxonomy, or any guard fails, or seccomp/Landlock were not installed when `PROVEN` is claimed, or a dead-pid restore-intent remains after hard kill, TraceJIT **must not** expose a `Reused` HIT.  
> Conversely, a warm HIT is only claimed when classification is `GUARDED`/`PROVEN`, every guard and stream verification passes, and restore completes without error—**pathname-visible Obs**, not inode identity, not multi-file atomic visibility to concurrent observers, and not immunity to post-recheck TOCTOU.

A single synthetic 100× microbench would not satisfy this release bar; the shipped evidence pairs speedups with refusals, DEOPT demos, and open limitations.

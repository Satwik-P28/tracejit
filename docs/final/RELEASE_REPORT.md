# TraceJIT final stabilization — release report

1. **Final commit SHA and PR links.** Final SHA: _fill after merge_. Pre-merge tip for this PR: `7b9e7ca` (main after [#35](https://github.com/Satwik-P28/tracejit/pull/35)). Stabilization PRs: [#33](https://github.com/Satwik-P28/tracejit/pull/33) CI/fd9, [#34](https://github.com/Satwik-P28/tracejit/pull/34) audit deps, [#35](https://github.com/Satwik-P28/tracejit/pull/35) warm-hit profile (measurement-only), this docs/gates PR. Main CI on `7b9e7ca`: [run 43681932897](https://github.com/Satwik-P28/tracejit/actions/runs/43681932897) success.

2. **Errors fixed.** Restore-intent / fd9 / starttime CI flakes (#33). Actionable `rusqlite`/`tempfile` advisories (#34). Warm-HIT destination-match restore skip prototyped then **withdrawn** (#35): under `relatime`, consuming outputs yields **0/40** skips; synthetic ~5.2→3.4 ms not a product win (`benchmarks/results/final_stab_pr3/skip_rate_study.json`).

3. **Tests passed, failed, or skipped.** Recorded in `benchmarks/results/final_stab_pr4/gates/GATES_SUMMARY.md`. Passed: fmt, clippy `-D warnings`, `cargo test --workspace`, linux_integration (incl. K2 oracle), release build, `cargo audit` (clean), demo, modelcheck, K4 restore fault, certificate + CEGAR unit tests, differential fuzz seeds 7/11/29, phase_d seeds 7/11, CLI doctor/help/refine, public install smoke (v0.1.1 assets). **Not run:** dedicated metamorphic harness (none in repo; multi-seed differential used). **Failed (permission):** enable branch protection — GitHub API **403**.

4. **Security status.** `cargo audit` clean on tip (`gates/cargo_audit.log`). Certificates still refuse `FullEquivalenceProof`. Residual validate→restore TOCTOU after recheck; hard-kill mid-restore not crash-atomic (`SAFETY.md`).

5. **Before/after performance.** No safe material warm-HIT opt landed. Phase medians (c-etl @ `4ffde9a`, product ≡ `ed3bd39`): cas_restore **1.16 ms**, guard_validation **0.43 ms**, sqlite_query **0.17**, decode **0.13**, sqlite_open **0.08**, stdio_replay **0.008** (`warm_hit_profile_breakdown.md`). Mandate §4 on same product tip (`mandate_s4/`): c-transform warm **5.303 ms** vs direct **32.524 ms**; `/bin/true` warm **4.475** vs direct **0.351**; gzip warm Reused **4.805**; ETL warm **4.332**; session TraceJIT **177 ms** vs direct **35 ms**; concurrency 8 workers ok; census **1/32**. Nothing deferred.

6. **Remaining limitations.** Multi-output hard-kill non-atomic; TOCTOU residual; short-command floor; census 1/32; selective tracing / typed DAG deferred. Branch protection unset (403).

7. **Jane Street FOCUS readiness.** Two resume bullets + ≤100-word FOCUS text in `docs/focus/APPLICATION_MATERIALS.md`, tip `7b9e7ca`, verified evidence only. Demo: `./scripts/demo.sh` PASS.

# TraceJIT claims ledger

Status labels (Part XXII §58): **implemented+verified** | **implemented but not fully verified** | **experimental** | **rejected** | **deferred** | **blocked**.

Inspected tip: `364331b904d41de3feb7defae152ec0e50112e0e` (Phase K7 #24 merged; K8–K14 package in flight). Evidence paths are repository-relative unless noted.

| Feature / claim | Status | Evidence |
| --- | --- | --- |
| Whole-command reuse only for `GUARDED`/`PROVEN` | implemented+verified | `cache_eligible`; linux_integration; SAFETY.md |
| Fail-closed on `UNKNOWN`/`NONDETERMINISTIC`/`EMPIRICALLY_STABLE` | implemented+verified | effects classifier; fixtures `cases.json` |
| Synchronous guards before any cached byte exposure | implemented+verified | core hit path; EXECUTION_EQUIVALENCE.md |
| `PROVEN` requires installed seccomp + Landlock ABI 3+ | implemented+verified | sandbox; `proven-reuse PASS` on Landlock hosts |
| Bounded multi-candidate retention (default 8) + A/B/A | implemented+verified | cache schema v2; Phase 3A/G A/B/A results |
| Stream verify before output mutation | implemented+verified | core `run`; Phase 3A/3B corruption tests |
| Inherited fd > 2 preflight refuse | implemented+verified | Phase 3G; integration regressions |
| `/dev/null` read/seek fstat identity | implemented+verified | Phase 3F/3C; fixtures |
| Descriptor enumeration fail-closed; `dup2(fd,fd)`; forget dirent on reuse | implemented+verified | PR #8; linux_integration |
| Post-`Cache::open` inherited-fd re-scan | implemented+verified | PR #11 |
| Anonymous `MAP_SHARED` / hardlink create → `UNKNOWN` | implemented+verified | Phase C; fixtures |
| Hit-path typestate / expose-after-restore | implemented+verified | Phase C |
| Differential + adversarial + property tests | implemented+verified | Phase D harnesses; `phase_d_verification` |
| Reuse certificates + verifier (no full-proof claim) | implemented+verified | `certificate.rs`; REUSE_CERTIFICATES.md |
| CEGAR-shaped refinement workflow + DirectoryOpened cycle | implemented+verified | `refinement.rs`; CEGAR_REFINEMENT.md |
| Analytical admission model + offline policy compare | implemented+verified | `admission_research.rs`; ADMISSION_POLICIES.md |
| Production `--admission auto` | implemented+verified | Phase 2H/2J/G ablations; keeps short ETL off cache |
| Stream-hash CAS staging; single-fd meta+hash; candidate LIMIT; precomputed identity JSON | implemented+verified | Phase F; `benchmarks/results/phase_f/` |
| Competitive Phase G suite (make/simple-CAS/direct) | implemented+verified | `phase_g_evaluation.py`; `benchmarks/results/phase_g/` |
| Fast guard mode | experimental | opt-in; Phase G strict vs fast |
| EWMA / confidence-bound admission policies | experimental | offline only; production unchanged |
| TLA+ `reuse_hit.tla` | experimental | typestate sketch; not fully verified vs binary |
| Controlled Python / allocator contracts on main | rejected | #9/#10; counterexamples |
| Epoll create-only model on main | rejected | #7 incomplete obligations |
| Two-stage candidate retrieval on main | rejected | #6; no general win |
| Bandit as default admission | rejected | Phase E held-out matrix |
| Drop staging fsync / sync=NORMAL / metadata hash cache / skip guard re-hash | rejected | Phase F; D-B7 |
| `getrusage` ignore/whitelist refinement | rejected | Phase E |
| New product syscall compatibility admits | deferred | Phase E explicit non-goal that phase |
| Durable multi-file restore journal | deferred | D-B2 accepted limitation |
| Crash-atomic / inode-preserving multi-output restore | deferred / limitation | documented; not claimed |
| Full-system formal proof / `FullEquivalenceProof` | blocked | non-goal; certificates refuse |
| Bind-mount `/dev/null` substitution test | blocked | `unshare -m` EPERM (D-B9) |
| Hardware PMU / perf attribution | blocked | tools absent on eval host |
| Matched Firebuild / sccache numbers | blocked | not installed on K8 host — skipped, not invented |
| Ninja competitive arm (bzip2 build/edit) | implemented+verified | K8 `phase_k8_competitive.py`; identical-rerun win for ninja; WRONG on mtime/corrupt |
| ccache as transparent command-cache baseline | rejected as comparison | compiler wrapper; not an applicable arm for bzip2 Obs reuse |
| Phase K false-HIT `renameat2` exchange refuse | implemented+verified | #18; `PHASE_K1_EQUIVALENCE_ATTACK.md` |
| Independent Obs oracle (no shared Rust crates) | implemented+verified | #19; `benchmarks/oracle/independent_obs.py` |
| Hit-path + restore-crash external modelcheck | implemented+verified | #20; not a binary proof |
| Restore fault injection (soft rollback+retrace) | implemented+verified | #21; hard-kill non-atomic limitation retained |
| Input-driven CEGAR refine (never auto-deploy) | implemented+verified | #22; `tracejit refine` |
| Certificate StrictCas CAS digest mode | implemented+verified | #23; still refuses `FullEquivalenceProof` |
| Staging `sync_data` + SQL `prepare_cached` | implemented+verified | #24; measured before/after in `phase_k7/` |
| Drop CAS/`put_bytes` fsync for speed | rejected | Phase F / K7 |
| Offline admission prefers `CurrentAuto` | implemented+verified | K9 re-eval regret 49e6 ns; matches Phase E |
| Bandit / ConfidenceBound as production default | rejected | K9; prefer_simpler |
| Flagship: fail-closed Obs-equivalence reuse | implemented+verified | K11; not a peer-reviewed novelty claim |
| Peer-reviewed publication / production adoption | rejected as claim | no evidence |

Quantitative performance claims must cite the commit and file that produced them (see technical report §§14–17). Do not paste a new number without harness provenance.

# Phase K14 — Final professional research package

Date: 2026-11-14  
Main tip at package authoring: `364331b904d41de3feb7defae152ec0e50112e0e`  
Auditor: independent Phase K stream (`bc-bfd27a09-d08a-5ab4-bf28-cbc51b277fee`)

## 1. Repository status

| Item | Value |
| --- | --- |
| Base tip for K8–K14 | `364331b` — Merge #24 (K7) |
| K0–K1 | Merged #18 `94d714d` |
| K2 | Merged #19 `72d451d` |
| K3 | Merged #20 `4cc4b63` |
| K4 | Merged #21 `10e2d68` |
| K5 | Merged #22 `f148228` |
| K6 | Merged #23 `aa3a186` |
| K7 | Merged #24 `364331b` |
| K8–K14 | This focused research PR (docs + harness + measured artifacts) |

## 2. Flagship (K11)

Fail-closed observable-equivalence for transparent whole-command reuse, adversarially demonstrated (false HIT → fix) and backed by independent oracle, modelcheck, and crash fault injection. See `PHASE_K11_FLAGSHIP_CONTRIBUTION.md`.

## 3. Correctness package

| Work | Status | Evidence |
| --- | --- | --- |
| False-HIT `renameat2` exchange + related Obs refuses | implemented+verified | K1 |
| Independent Obs oracle | implemented+verified | K2 `benchmarks/oracle/independent_obs.py` |
| Hit-path / restore-crash modelcheck | implemented+verified (model ≠ binary proof) | K3 |
| Restore fault injection | implemented+verified (soft); hard-kill limitation | K4 |
| Input-driven CEGAR refine (no auto-deploy) | implemented+verified | K5 |
| Certificate StrictCas | implemented+verified | K6 |
| Differential / adversarial / concurrency | implemented+verified | Phase D (prior) |

## 4. Performance & competition

| Work | Status | Evidence |
| --- | --- | --- |
| Staging `sync_data` + `prepare_cached` | implemented+verified (small wins) | K7 `benchmarks/results/phase_k7/` |
| Competitive re-eval with ninja measured | measured | K8 `benchmarks/results/phase_k8/` |
| Short-command loss | retained negative | K8 ETL |
| Make/Ninja identical-rerun win | retained negative | K8 |
| Make/Ninja stale WRONG vs TraceJIT ok | retained positive correctness | K8 |

## 5. Admission & novelty

| Work | Status | Evidence |
| --- | --- | --- |
| Offline admission-eval prefers CurrentAuto | confirmed | K9 regret 49e6 ns |
| Bandit / ConfidenceBound as default | rejected / tied→simpler | K9 |
| Novelty matrix | documented | `docs/research/NOVELTY_MATRIX.md` |
| External-review objections | documented | K12 |

## 6. Claims ledger

Updated in-repo: `docs/research/CLAIMS_LEDGER.md` (Phase K rows). Status labels follow Part XXII §58.

## 7. Remaining limitations (do not erase)

1. Validate→restore TOCTOU  
2. Multi-output restore not crash-atomic / not inode-preserving  
3. Short-command floor; large hash+restore losses  
4. Certificates ≠ full Obs proofs  
5. Firebuild/sccache unmatched (absent)  
6. No peer-reviewed publication; no production-adoption claim  

## 8. Reproduction

```bash
git checkout 364331b   # or this PR tip after merge
cargo build --workspace --release
python3 benchmarks/repos/phase_k8_competitive.py
./target/release/tracejit admission-eval
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo test -p tracejit-cli --test linux_integration -- --nocapture
```

## 9. Audit index (store + repo)

Repo `docs/audits/PHASE_K*.md` mirrored under  
`/cursor/stores/bc-1512ce33-58c8-4b56-83c5-eee0b6222d6a/docs/audits/`.

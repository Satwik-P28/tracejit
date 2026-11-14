# Phase K11 — Flagship contribution

## Selection

**One flagship:** Fail-closed observable-equivalence for transparent whole-command reuse on unmodified Linux processes — infer effects, classify conservatively, reuse only under synchronous guards, and treat false-positive HIT as the primary defect class.

## Why this one

Across Phase K, the strongest *verified* contribution is not a micro-optimization or an offline research widget:

1. **Adversarial disproof → product fix (K1):** `renameat2(RENAME_EXCHANGE)` produced a demonstrated false-positive warm HIT (paths/contents diverged from native Obs). Fixed by fail-closed `UNKNOWN` (+ related Obs holes). Evidence: `docs/audits/PHASE_K1_EQUIVALENCE_ATTACK.md`, integration regression.
2. **Independent Obs oracle (K2):** CLI-only Python oracle without shared Rust crates — reduces “we tested ourselves with ourselves.”
3. **Typestate modelcheck (K3):** Hit-path expose order + restore-crash soft/hard properties checked by an external checker against TLA+ sketches.
4. **Crash-recovery fault injection (K4):** Soft failures rollback+retrace without exposing partial Obs; hard-kill limitation documented, not papered over.
5. **Supporting research kept honest:** CEGAR refine never auto-deploys (K5); certificates refuse full proofs / StrictCas is optional (K6); perf changes measured and never drop CAS `sync_all` durability (K7).

## What is *not* the flagship

| Candidate | Why not selected |
| --- | --- |
| Competitive speed vs Make/Ninja | K8 confirms **loss** on identical rerun |
| Admission bandits | **Rejected** as default (K9) |
| CEGAR engine | Useful workflow; no academic novelty claim |
| Certificates / StrictCas | Valuable hardening; not Obs equivalence |
| Staging `sync_data` / `prepare_cached` | Small measured wins only |

## Honest negatives retained with the flagship

- Short-command floor (ETL warm slower than direct).
- Large-file hash+restore can lose to direct copy.
- Make/Ninja identical-rerun wall time far cheaper when the graph is correct.
- Validate→restore TOCTOU remains.
- Multi-output restore is not crash-atomic / not inode-preserving.
- Native census still mostly non-reusable (clocks/randomness/identity).

## One-sentence claim (safe)

TraceJIT reuses an unmodified Linux command’s outputs only when a fail-closed effect model and synchronous guards say the observable dependencies still hold — and Phase K demonstrated that this bar catches real false-HIT bugs rather than merely documenting them.

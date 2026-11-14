# Phase K5 — Real CEGAR refinement engine

Date: 2026-11-14  
Base: `10e2d68` (post K4)  
Branch: `cursor/phase-k5-cegar-engine-7fee`

## Goal

Replace “more hardcoded refinement examples” with an **input-driven** counterexample-guided
refinement engine that never auto-deploys product classification changes.

## Delivered

| Piece | Path |
| --- | --- |
| Engine | `crates/tracejit-effects/src/cegar.rs` |
| CLI | `tracejit refine --input …` |
| Fixtures | `docs/research/cegar/*.json` |
| Spec update | `docs/research/CEGAR_REFINEMENT.md` |

## Properties checked

1. **Input-driven:** distinct CEs classify to distinct `HoleKind` via the same `refine()`.
2. **Fail closed:** unmodeled flags / nondeterminism / Obs divergence → `KeepFailClosed`.
3. **No auto-deploy:** even after `--retest-pass`, status is `VerifiedOfflineNotDeployed`.
4. **Unsafe sketches rejected:** ignore/whitelist → `RejectedUnsafe`.
5. **Historical over-abstraction:** directory mtime CE proposes `DirectoryOpened` sketch only.

## Non-claims

- Does not claim CEGAR novelty.
- Does not admit new syscalls on main.
- Does not close validate→restore TOCTOU.

## Validation

```bash
cargo test -p tracejit-effects --lib cegar
cargo build -p tracejit-cli
./target/debug/tracejit refine --input docs/research/cegar/rename_exchange.json
```

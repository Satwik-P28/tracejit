# P1 §11 — CEGAR refine (falsification-first)

Date: 2026-11-14  
Tip base: `bb4302fccaf780d53287dde557f984adc2615870`  
Engine: `crates/tracejit-effects/src/cegar.rs` · CLI: `tracejit refine`  
Raw: `benchmarks/results/final_p1_assurance/refine-*.json`

## Loop (implemented)

observe → abstract → counterexample → minimize → propose → offline retest → **accept or reject**

Automates **proposal only**. There is no path that mutates production classification from `refine`.

| Deployment status | Meaning |
| --- | --- |
| `BlockedPendingOfflineRetest` | Proposal recorded; not deployed |
| `VerifiedOfflineNotDeployed` | Offline retest attached; **still not deployed** |
| `RejectedUnsafe` | Ignore/whitelist / unsafe sketch refused |

## Measured on this tip

```bash
cargo test -p tracejit-effects --lib cegar   # 6 passed
./target/release/tracejit refine --input docs/research/cegar/rename_exchange.json --json
./target/release/tracejit refine --input docs/research/cegar/directory_mtime.json \
  --retest-pass --retest-notes 'historical Phase 2E' --json
./target/release/tracejit refine --input docs/research/cegar/openat2_resolve.json --json
```

| Fixture | Hole | Deployment |
| --- | --- | --- |
| `rename_exchange.json` | `UnsoundAdmit` | `BlockedPendingOfflineRetest` |
| `directory_mtime.json` (+ retest) | `OverAbstraction` | `VerifiedOfflineNotDeployed` |
| `openat2_resolve.json` | `UnmodeledSurface` | `BlockedPendingOfflineRetest` |

All three: `safety_ok=true`. None auto-deploy.

## Metamorphic family inventory (design + fixtures)

Families called for by the mandate; status is **coverage of the research loop**, not a claim that every family has a green product admit:

| Family | Status |
| --- | --- |
| Same name / different resource | Covered by path-identity guards + CE fixtures |
| Same resource / different bytes | Content guards; differential fuzz |
| Same bytes / changed metadata | Directory mtime CE → OverAbstraction sketch (not deployed) |
| Same timestamp / changed bytes | Fail-closed content hash (not mtime-only) |
| Failed syscall / errno | Unmodeled / failed FD paths refuse |
| Symlink reparent | Cache restore symlink substitution tests |
| Rename exchange | Fixture + product UNKNOWN refuse |
| Hardlink alias | Modeled / guarded paths in product |
| Stdout redirection / FD aliasing | Inherited-fd refuse; stream model |
| Partial restoration | Restore-intent refuse HIT (P0 §5) |
| Signal interleavings / concurrent edits | Concurrent IT + chaos; residual TOCTOU documented |

Train/dev/held-out: CE JSON fixtures under `docs/research/cegar/` are the **held-out research corpus**; product regressions stay in `linux_integration` / unit tests. Oracle (`benchmarks/oracle/`) does not import TraceJIT validators.

## Novelty

**No academic CEGAR novelty claim.** This is an engineering workflow analogy (`docs/research/NOVELTY_MATRIX.md`).

## Deferred

- Auto-minimizing filesystem trees beyond step-string heuristics
- Automatic product patches from proposals
- Expanding eligibility from OverAbstraction sketches without new oracle+chaos coverage

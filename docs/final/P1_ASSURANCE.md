# P1 §12 — Assurance case / modelcheck / fuzz correlation

Date: 2026-11-14  
Tip: `bb4302fccaf780d53287dde557f984adc2615870` (+ this branch’s modelcheck extension)  
Raw: `benchmarks/results/final_p1_assurance/{modelcheck.txt,differential-seed28.json,certificate-tests.txt}`

## State machines ↔ code

| Machine | Model | Invariants | Code / tests |
| --- | --- | --- | --- |
| Hit-path typestate | `docs/research/formal/reuse_hit.tla` | `Safety`: expose ⇒ guards∧streams∧restore | `tracejit-core` hit path / `reuse_hit` ordering |
| Multi-output restore | `docs/research/formal/restore_crash.tla` | SoftFailSafe, ExposeSafe, KillNotExpose | `tracejit-cache::restore_outputs` + K4 harness |
| Restore-intent refuse | Python checker `restore_intent` | IntentRefuseHit / no partial HIT expose | `has_interrupted_restore` + core refuse (TRA-26) |

Checker: `scripts/modelcheck/check_state_machines.py` (no TLC required). Optional TLC cfg: `reuse_hit.cfg`.

## Measured RESULT (this host)

```text
reuse_hit states=9 violations=0
restore_crash states=14 violations=0
restore_crash mixed_kill_states=2 (limitation; must not expose)
restore_intent states=5 legal_states=4 legal_violations=0 planted_illegal=1
RESULT phase-k3-modelcheck PASS
```

## Fuzz / property / certificate correlation

| Gate | Command | Result |
| --- | --- | --- |
| Differential Obs fuzz | `python3 benchmarks/differential/fuzz.py --seed 28` | **120 ok, 0 incorrect hits** |
| Certificate structural + StrictCas | `cargo test -p tracejit-core --lib certificate` | **10 passed** |
| Independent oracle | `benchmarks/oracle/independent_obs.py` (prior K2) | retained; not re-run as binary proof here |

## Tooling status (honest)

| Tool | Status on this host |
| --- | --- |
| Python exhaustive modelcheck | **run** |
| TLC | not required; cfg present |
| Loom | **not introduced** (deferred; no new concurrent Rust algorithm in this PR) |
| proptest/quickcheck | existing crate tests; no new property crate in this PR |
| Miri | **not run** (environment) |
| cargo-fuzz / libFuzzer | **not run**; differential seed fuzz used instead |
| ASan/UBSan on C fixtures | **not run** this package |

## Non-claims

- Not full binary verification.
- Mixed kill states remain a modeled limitation (workspace may mix; must not expose as HIT).
- Power-loss ≠ SIGKILL (unchanged).

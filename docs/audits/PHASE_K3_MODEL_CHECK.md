# Phase K3 — Model-check dangerous state machines

Date: 2026-11-14  
Models: `docs/research/formal/reuse_hit.tla`, `docs/research/formal/restore_crash.tla`  
Checker: `scripts/modelcheck/check_state_machines.py` (no TLC required)

## Machines

### 1. Hit-path typestate (`reuse_hit`)

States: Idle → Discovered → GuardsPassed → ArtifactsVerified → Restored → Exposed  
(or Rejected on any failure).

**Invariant `Safety`:** `exposed ⇒ guards_ok ∧ streams_ok ∧ restore_ok ∧ state=Exposed`.

Maps to `crates/tracejit-core/src/lib.rs::reuse_hit`.

### 2. Multi-output restore (`restore_crash`)

Phases: Validate → Stage → Backup → Apply → Done | RolledBack | Killed.

**Invariants:**

- `SoftFailSafe` — injected soft failure rolls workspace to caller tags; not exposed.
- `ExposeSafe` — exposure only after all outputs applied.
- `KillNotExpose` — hard kill between renames never exposes Obs.

The model **admits** mixed workspace states under `Killed` (limitation). Product recovery is re-execution, not a journal (Phase K4).

## Results (this host)

```text
$ python3 scripts/modelcheck/check_state_machines.py
reuse_hit states=9 violations=0
restore_crash states=14 violations=0
restore_crash mixed_kill_states=2 (limitation; must not expose)
RESULT phase-k3-modelcheck PASS
```

## Non-claims

- Not a full-system proof.
- TLC cfg (`reuse_hit.cfg`) is optional; the Python checker is the required gate for this phase.
- Does not close validate→restore TOCTOU against external mutators.

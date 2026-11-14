# Phase K4 — Restoration / crash-recovery fault injection

Date: 2026-11-14  
Harness: `scripts/phase_k4_restore_fault.sh`  
Hooks: `TRACEJIT_TEST_RESTORE_FAIL_PATH`, `TRACEJIT_TEST_RESTORE_PAUSE_PATH` in `tracejit-cache`

## Problem

`restore_outputs` stages then renames. A soft failure after partial apply rolls back from
backups (unit-tested). A **hard kill** between renames can leave a mixed workspace; there is
**no durable journal**. V1 recovery is **re-execution** (or a later successful restore).

## Fault injection

| Hook | Effect |
| --- | --- |
| `TRACEJIT_TEST_RESTORE_FAIL_PATH=<abs>` | Fail before apply of that path; rollback applied outputs; CLI retraces |
| `TRACEJIT_TEST_RESTORE_PAUSE_PATH=<abs>` | Sleep 30s before apply; harness may SIGKILL |

Unit tests (`failure_during_a_later_replacement_rolls_the_first_one_back`) prove soft rollback
without CLI retrace.

## Harness expectations

1. Soft fail → decision ≠ `Reused`; final Obs matches native after retrace.
2. Hard kill mid-pause → workspace may mix; next run yields correct Obs.

## Non-claims

- Not crash-atomic multi-output restore.
- Not inode-preserving.
- Env hooks must stay unset in production use.

## Model link

`docs/research/formal/restore_crash.tla` / Phase K3 checker: `KillNotExpose`, `SoftFailSafe`.

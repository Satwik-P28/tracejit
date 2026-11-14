# P0 §§3–4 — process semantics + resource identity / TOCTOU

Date: 2026-11-14  
Branch tip measured with this document’s PR.  
Base: final adversarial baseline `docs/final/BASELINE.md`.

## Principle

False HIT = critical. Minimal safe refuse only. Preserve `renameat2(RENAME_EXCHANGE)` UNKNOWN refuse.

## §3 Adversarial process-semantics findings

| Class | Pre-fix behavior | Action | False HIT? |
| --- | --- | --- | --- |
| `renameat2(RENAME_EXCHANGE)` | UNKNOWN + never HIT (Phase K1) | **Preserve** regression | Was YES; fixed |
| `O_TMPFILE` | Fail-closed via side paths (`non-file output` / later `linkat`) without naming O_TMPFILE | **Explicit UNKNOWN** in `open_pending` | No demonstrated HIT; incorrect model risk |
| `fcntl(F_SETFL)` and other mutators | Catch-all `PendingSyscall::None` | **UNKNOWN** except documented GET queries + existing DUPFD/SETFD | No demonstrated HIT on final-content Obs; OFD/alias risk |
| `fcntl(F_GETFL/F_GETFD/…)` | None | Keep None | n/a |
| `copy_file_range` / unlisted syscalls | Default unmodeled → UNKNOWN | Keep; fixture census | No |
| Hardlink `link`/`linkat` | UNKNOWN | Preserve | n/a |

### Fixtures added

- `otmpfile_is_unknown_and_never_reused`
- `fcntl_setfl_is_unknown_and_never_reused`
- Existing `renameat2_exchange_is_unknown_and_never_reused` retained

## §4 Resource identity / validate→restore TOCTOU (D1)

### Approaches compared

| Option | Description | Status |
| --- | --- | --- |
| **A** | Current guarded mutable-path mode with documented race | Still default contract; residual window honest |
| **B** | Immutable input snapshot / mount namespace / content-backed staging | **Deferred** — needs isolation of all deps + output semantics; not shipped |
| **C** | Fail-closed concurrent-mutation detection | **Partial ship**: pre-restore guard **recheck** before any workspace mutation |

### What shipped (C, narrow)

After first `validate_all`, CAS stream verify, and inherited-offset probe — and **before** `restore_outputs` — TraceJIT runs `validate_all` again. Failure → skip candidate / retrace (no output mutation from that candidate).

Test hook (unset in production): `TRACEJIT_TEST_PRE_RESTORE_MUTATE_PATH=<abs>` overwrites that path immediately before the recheck so CI can prove fail-closed behavior without a flaky external race. `TRACEJIT_TEST_*` keys are excluded from cache lookup identity and environment discovery so harness hooks can actually reach the hit path (same class of fix needed for K4 restore fault env hooks).

Fixture: `toctou_pre_restore_recheck_deoptimizes_instead_of_false_hit`.

### What is still not claimed

- Residual TOCTOU after the final recheck and during multi-output restore.
- Fanotify/inotify completeness.
- Crash-atomic multi-output restore (still §5 / D2).
- Inode-preserving restore.

## Non-claims

- No semantic broadening of reuse eligibility.
- No benchmark wins asserted in this PR.
- Research branches #6/#7/#9/#10 untouched.

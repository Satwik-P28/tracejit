# P0 §5 — Multi-output restoration, durability, crash recovery

Date: 2026-11-14  
Tip base: `origin/main` after PR #27 (`80edaa4`).

## Five distinct guarantees (not interchangeable)

| # | Guarantee | V1 TraceJIT status |
| ---: | --- | --- |
| 1 | **Atomic replacement of one pathname** | **Supported** via `rename(2)` of a staged temp over the destination (same directory). Staged data is `sync_data`'d; parents are fsynced before apply. |
| 2 | **Recoverability after process death / power loss** | **Partial.** Soft failure rolls back from in-memory backups. Hard kill mid-apply may leave a mixed workspace. A durable **restore-intent** marker forces the next run to **refuse HIT** and re-execute. Not a power-loss proof; SIGKILL ≠ power fail. |
| 3 | **Atomic visibility of a whole multi-file set** to concurrent observers | **Not claimed.** Sequential renames are visible mid-apply. |
| 4 | **Inode / hardlink / metadata identity preservation** | **Not claimed** for destinations (pathname-visible CAS restore). Backup hardlinks preserve the *pre-restore* inode only for soft rollback. |
| 5 | **All-or-nothing external side effects** | Soft path: yes (rollback). Hard kill: no. Intent prevents advertising a HIT after interruption. |

Rename of multiple files is **not** a multi-file transaction.

## Shipped restricted protocol

1. Validate output preconditions.
2. Stage every CAS object into the destination parent (hash-verify while copying; `sync_data`).
3. Fsync distinct parent directories.
4. Backup existing destinations (hardlink temps) for soft rollback.
5. Write durable per-pid `restore-intent.v1.<pid>.json` under the cache root (intent + dir sync).
6. Apply renames/deletes one by one.
7. On soft failure: rollback applied outputs, clear **this** pid's intent, return `Err` (core retraces; **never** `Reused`).
8. On full success: clear this pid's intent, return `Ok` (only then may core expose HIT).
9. On hard kill after step 5: that pid's intent remains → next `Cache::open` treats **dead-pid** intents as interrupted; core **refuses HIT** and executes cleanly. Live peer intents do not block concurrent HIT restores.

## Fault injection

| Hook | Role |
| --- | --- |
| `TRACEJIT_TEST_RESTORE_FAIL_PATH` | Soft fail before apply of that path |
| `TRACEJIT_TEST_RESTORE_PAUSE_PATH` | Sleep before apply (SIGKILL harness) |
| Unit: leftover intent on open | Detect + consume |

Harness: `scripts/phase_k4_restore_fault.sh` (still valid; intent adds fail-closed HIT refuse after kill).

## Explicit non-claims / deferred

- No durable multi-file journal that repairs user files after kill.
- No inode-preserving restore.
- No fanotify completeness.
- No claim that kill tests prove power-loss durability.
- Full recoverable transaction protocol (locks, ENOSPC/EIO matrix, GC) remains **deferred / experimental** if pursued later on an isolated branch.

## Principle

**Never ship an apparently successful HIT that left partially restored outputs.** Soft path enforces this by rollback+error. Hard-kill path never returns HIT from the killed process; the intent marker blocks the next HIT until a clean execution.

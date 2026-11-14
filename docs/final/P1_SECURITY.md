# P1 §13 — Security hardening + hostile cache input

Date: 2026-11-14  
Tip base: `bb4302fccaf780d53287dde557f984adc2615870`  
Raw: `benchmarks/results/final_p1_assurance/{cargo-audit.txt,certificate-tests.txt}`

## Threat model (separated)

| Class | In scope for V1 hardening | Out of scope / limited |
| --- | --- | --- |
| Accidental corruption | Yes — CAS digest, StrictCas, corrupt-object refuse | |
| Same-user concurrent processes | Yes — SQLite busy, restore-intent per-pid, UnsafeRoot races | Cross-process TOCTOU on user files remains |
| Malicious artifacts in cache dir | Yes — structural cert checks, hash verify, symlink root refuse | No cryptographic signing of certificates |
| Symlink swaps on restore paths | Yes — `symlink_metadata` prechecks; rename replaces dirent | External mutator after last check (TOCTOU) |
| Environment / secrets | Env is part of identity; not a secret vault | Do not store credentials in cache by design of workloads |
| Untrusted executable | Executable identity hashed; refuse if mismatch | Does not sandbox the *caller* |
| Cross-user adversary | **Separate**: V1 assumes same-user cache trust boundary | No claim against hostile multi-user shared cache |
| Landlock/seccomp | Required for `PROVEN` only | **Not** complete isolation / not a full TCB proof |

## Audited controls (code-correlated)

| Control | Location |
| --- | --- |
| Temp staging via `NamedTempFile` + `persist` in destination parent | `tracejit-cache` |
| Cache root must be real directory (not symlink) | `prepare_root` |
| CAS `CorruptObject` on digest mismatch | `get_bytes` / stage |
| Certificate forge / ineligible reuse / missing CAS | K6 + `verify_certificate[_strict]` |
| Inherited fds > stdin refuse reuse | `tracejit-core` |
| Restore-intent refuse after hard-kill mid-apply | TRA-26 |
| `RENAME_EXCHANGE` / unmodeled flags UNKNOWN | tracer classification |

## `cargo audit` (this host)

```text
libsqlite3-sys 0.30.1  RUSTSEC-2026-0459  medium  → upgrade to >=0.39.0
rustix 1.1.5           RUSTSEC-2026-0486  unsound warning → >=1.1.6
```

**Decision this PR:** record findings; **defer** rusqlite/`libsqlite3-sys` major bump (workspace pin `rusqlite 0.32`) to a focused dependency PR with full gate re-run. Do not claim a clean audit.

## Hostile inputs exercised

- Certificate hostile JSON matrix (unit): forge FullEquivalenceProof, drop CAS, empty limitations, legacy artifact — rejected.
- Corrupt CAS bytes under correct name — StrictCas / CorruptObject.
- Symlink substitution before restore — unit refused.
- Differential fuzz seed 28 — 0 incorrect hits.

## Non-claims

- No claim Landlock+seccomp = complete isolation.
- No claim certificates are signatures.
- No claim audit is clean while RUSTSEC-2026-0459 remains.

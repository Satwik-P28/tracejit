# Reuse certificates

## Status

**Phase E (implemented+verified)** — structural certificate + independent verifier with unit tests and CLI.  
**Phase K6 (implemented+verified)** — security assessment + optional StrictCas mode against a live cache.

## What a certificate is

`tracejit.reuse-certificate.v1` records, for one decision:

- contract id (or native `None`)
- record / candidate id and lookup key
- classification and cache decision
- guards + pass/fail evidence and optional `GuardReport`
- content identities (stdout/stderr/exit/output hashes)
- descriptor obligations (inherited streams; fds > 2 refused)
- CAS object refs
- restore preconditions (artifact version, create flags)
- explicit limitations

## Claim strength

| Level | Meaning |
| --- | --- |
| `CheckableEvidence` | Fields are present and typed |
| `CheckedByVerifier` | `verify_certificate` / StrictCas consistency checks passed |
| `FullEquivalenceProof` | **Never** emitted or granted in V1 |

The verifier rejects malformed/inconsistent evidence (ineligible class on `Reused`, missing CAS hashes, legacy artifact version on reuse, `FullEquivalenceProof` claims, empty limitations).

## Verification modes

| Mode | API / CLI | Extra checks |
| --- | --- | --- |
| Structural | `verify_certificate` / `verify-certificate` | Field consistency only |
| StrictCas | `verify_certificate_strict` / `verify-certificate --strict` | CAS objects exist in the cache and digest-match |

StrictCas strengthens **artifact integrity**. It does not re-run guards, close TOCTOU, or grant `FullEquivalenceProof`. See `docs/audits/PHASE_K6_CERTIFICATE_SECURITY.md`.

## Independent verification and mutable state

Re-running the verifier (or production guards) still samples the **same mutable filesystem** the hit path samples. Certificates do **not** close validate→restore TOCTOU and do not prove Obs equivalence. See `CertificateLimitations` notes embedded in every certificate. The embedded `claim_strength` bit is not a signature.

## API / CLI

- Library: `tracejit_core::{issue_certificate, verify_certificate, verify_certificate_strict, seal_certificate, parse_certificate}`
- Hit path: optional write when `TRACEJIT_CERTIFICATE_PATH` is set
- `tracejit certify [execution_id] [--output PATH] [--json]`
- `tracejit verify-certificate PATH [--strict] [--json]`

## Mapping to EXECUTION_EQUIVALENCE.md

Certificates document what the validator established for a hit; they must not claim more than that document’s Obs contract.

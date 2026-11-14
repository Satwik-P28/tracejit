# Reuse certificates (Phase E)

## Status

**implemented+verified** — structural certificate + independent verifier with unit tests and CLI.

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
| `CheckedByVerifier` | `verify_certificate` consistency checks passed |
| `FullEquivalenceProof` | **Never** emitted or granted in V1 |

The verifier rejects malformed/inconsistent evidence (ineligible class on `Reused`, missing CAS hashes, legacy artifact version on reuse, `FullEquivalenceProof` claims, empty limitations).

## Independent verification and mutable state

Re-running the verifier (or production guards) still samples the **same mutable filesystem** the hit path samples. Certificates do **not** close validate→restore TOCTOU and do not prove Obs equivalence. See `CertificateLimitations` notes embedded in every certificate.

## API / CLI

- Library: `tracejit_core::{issue_certificate, verify_certificate, seal_certificate, parse_certificate}`
- Hit path: optional write when `TRACEJIT_CERTIFICATE_PATH` is set
- `tracejit certify [execution_id] [--output PATH] [--json]`
- `tracejit verify-certificate PATH [--json]`

## Mapping to EXECUTION_EQUIVALENCE.md

Certificates document what the validator established for a hit; they must not claim more than that document’s Obs contract.

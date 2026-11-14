# Phase K6 — Certificate security assessment

Date: 2026-11-14  
Base: `f148228` (post K5)  
Branch: `cursor/phase-k6-certificate-security-7fee`

## Threat model (adversary controls certificate JSON)

| Attack | Structural verifier | StrictCas (`--strict`) | Notes |
| --- | --- | --- | --- |
| Forge `FullEquivalenceProof` claim | **Rejected** | **Rejected** | Never granted |
| `Reused` + ineligible class | **Rejected** | **Rejected** | |
| Drop stdout from `cas_objects` | **Rejected** | **Rejected** | |
| Empty `limitations.notes` | **Rejected** | **Rejected** | |
| Legacy artifact version on reuse | **Rejected** | **Rejected** | |
| Claim `CheckedByVerifier` without checks | Accepted if fields consistent | Accepted only if CAS also matches | Claim bit is not a signature |
| Point hashes at missing CAS blobs | Passes structural | **Rejected** | Stronger mode |
| Corrupt CAS bytes under correct name | Passes structural | **Rejected** (`CorruptObject`) | |
| TOCTOU on workspace after verify | Not closed | Not closed | Documented limitation |
| Replay certificate for different machine | Not closed | Bound to local cache contents only | |

## Stronger mode implemented

`verify_certificate_strict(cert, &Cache)` / CLI `tracejit verify-certificate PATH --strict`

- Runs all structural checks.
- For every `cas_objects` entry: `Cache::get_bytes` (presence + digest).
- Report `mode = StrictCas`.
- Claim strength still at most `CheckedByVerifier` — **never** `FullEquivalenceProof`.

## Non-claims

- No cryptographic signature / Merkle proof over the certificate.
- StrictCas is artifact integrity, not Obs equivalence.
- Does not re-run guards or close validate→restore TOCTOU.

## Validation

```bash
cargo test -p tracejit-core --lib certificate
cargo clippy -p tracejit-core -p tracejit-cli --all-targets --all-features -- -D warnings
```

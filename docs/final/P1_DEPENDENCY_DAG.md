# P1 §7 — Dependency DAG / validator design

Date: 2026-11-14  
Tip: `026e660` lineage (see package commit in raw artifacts).

## Current V1 validator (production)

Guards are a **flat, typed list** compiled from the effect trace (`tracejit-guards`). On hit lookup, every guard runs synchronously before any CAS restore / stdio replay. Fail ⇒ DEOPT / refuse HIT. There is no shared cross-command validation cache that can survive unobserved mutable changes.

## Hypothesis (research)

Recording a **typed dependency DAG** with provenance could make validation cheaper via:

- node type (positive path, negative absence, executable identity, env, cwd, FD-derived)
- validation cost estimate and short-circuit order (reject-fast first)
- exact fingerprint per node
- dedupe of common immutable inputs across candidates **only** when a trustworthy change mechanism pins immutability
- parallel checks for independent nodes

Buck2 DICE value-equality/version ideas apply only when versions come from a trustworthy change channel. ccache/sccache/Nix/Bazel/Firebuild contracts differ; TraceJIT does **not** claim architectural equivalence.

## Alternatives evaluated (design-level)

| Alternative | Safety posture | Status |
| --- | --- | --- |
| Baseline strict full hash (current default) | Sound default | **Kept** |
| BLAKE3 streaming verify on CAS restore | Sound; already used | Kept |
| Cached hash of immutable/snapshot-pinned objects | Sound only under advertised pin contract | **Deferred** (opt-in contract, not silent default) |
| Stat-first reject-fast precheck | OK as reject-only; never accept on mtime alone | **Allowed as precheck only**; mtime-only acceptance **rejected** |
| Merkle/chunk hashing for mutable files | False-negative risk | **Deferred / not default** |
| Selective output materialization / no-op restore | Lazy verify must not expose unverified bytes | Research only; current path verifies then restores |
| Shared cross-command validation summaries | Must not survive unobserved mutation | **Not shipped** |

## Production change in this PR

**None** to validator semantics. This document freezes the design boundary so later incremental revalidation work cannot silently weaken default Obs.

## Deferred implementation

- Typed DAG IR + ordered short-circuit evaluator behind tests
- Parallel independent-node validation
- Advertised read-only/content-addressed workload contract (explicit, not default)

## Non-claims

- No claim that TraceJIT implements Buck2 DICE.
- No mtime-only hits.
- No lazy exposure of unverified output bytes.

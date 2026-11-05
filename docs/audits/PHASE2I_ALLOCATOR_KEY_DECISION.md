# Phase 2I — allocator-key security decision record

Status: **fixed key retained, documented and contained**. No derived key is implemented.

Scope: the opt-in `tracejit.allocator-entropy.v1` contract, which controls exactly one audited
glibc call site. It is not a general-purpose entropy source and not a security sandbox.

## What the code actually does

`crates/tracejit-effects/src/lib.rs` holds `AllocatorEntropyProfile` entries keyed by the ELF build
ID of the executing glibc. The accepted build in this worktree is
`a4a7992a8e66555c8141ab2a08a8465ff6e0ea65`, with the audited call at resume offset `0xa9e89`,
destination `0x20b178`, and pre-call signature `0f 05 48 8d 5d d0 48 83 f8 08`. An unknown build
ID, a mismatched signature, or a changed offset is refused; the contract never guesses its way
through a different libc.

## Evidence from glibc 2.39 `malloc/malloc.c`

The key is `tcache_key`, initialised once per process by `tcache_key_initialize` from the `TLS`
entropy source. The source comments state that the value "does not really have to be a
cryptographically secure random number … only needs to be arbitrary enough". The key participates
in exactly two places:

- `tcache_put` writes it into the freed chunk's `key` field.
- `tcache_get_n` clears the field on allocation.
- `_int_free` scans the tcache list for the chunk and, on membership, aborts with
  `free(): double free detected in tcache 2`.

Consequences that matter for this decision:

1. A key collision is not a correctness failure. The abort path depends on the chunk being present
   in the list, not on the key value being unique. A collision can only cost an extra list scan in
   the `tcache_get_n`/`tcache_put` fast path.
2. The key is not a secret in the threat model the mitigation addresses: the check is an integrity
   check on the free list, not authentication against an attacker who can already write the heap.
3. The native value is per-process TLS randomness. Reproducing it is precisely what makes reuse
   possible; preserving native randomness and reusing output are mutually exclusive for this call.

## Options considered

### 1. Fixed controlled key (current)

- Memory hardening: the published key means an attacker with a heap write can forge a tcache entry
  that passes the key check, so per-process key secrecy is lost inside the contract.
- Double-free detection: preserved. `_int_free` still aborts on list membership; the integration
  test `allocator_double_free_detection_survives_the_contract` exercises it.
- Collisions: harmless for correctness, at worst a list scan.
- Predictability: fully predictable by design.
- Secret management: none.
- Cross-process reuse: the point of the contract; identical output across executions.
- Cache identity: the contract name and profile build ID are part of the identity and the guard.
- Observational equivalence: **not** claimed. Reuse is reproducible *within the declared contract*,
  and the report says so on every controlled run.
- Portability: one audited glibc build. Unknown builds are refused.
- Compatibility: works with stock glibc 2.39 on this host; not tested on other versions.

### 2. Key derived from a secret and authenticated execution identity

This would compute the key from the cache identity and a per-installation secret, usually via a KDF.

- Memory hardening: marginally better than a public constant against an attacker who does not know
  the secret; identical to the fixed key for any attacker who can read the process (the key must be
  materialised in the child's memory either way).
- Double-free detection: unchanged (list membership).
- Collisions: same order of harmlessness.
- Predictability: predictable to anyone who can read the cache or the secret; the child can always
  be made to reveal the value.
- Secret management: adds a key file, rotation, permissions and a new failure mode (missing or
  corrupt secret). `TRACEJIT_CACHE_DIR` alone would no longer reproduce a run.
- Cross-process reuse: works only while the secret is stable; rotating it silently invalidates every
  entry, and two users sharing a cache cannot share entries.
- Cache identity: the secret must become part of the identity, or entries produced under different
  secrets would collide.
- Observational equivalence: still not established; the derived value is a new observable.
- Portability/compatibility: the same narrow profile; strictly more moving parts.

No in-process secrecy is gained, because the value must exist in the traced process regardless. The
only added protection is against an attacker who can read the cache but not the process — a threat
the current experiment does not claim to defend against.

### 3. Fresh OS randomness per execution

- Memory hardening: native behaviour.
- Double-free detection: identical to native.
- Collisions: negligible.
- Predictability: none.
- Secret management: none.
- Cross-process reuse: **impossible**. Two runs observe different keys, so the trace cannot be
  replayed and the output cannot be reproduced; every controlled run would become ineligible.
- Cache identity: incompatible with reuse by construction.
- Observational equivalence: would require proving that the key never affects any observable effect.
  A finite set of equal outputs cannot establish that; the key is reachable from the heap and can be
  printed by the program. No noninterference argument strong enough for V1 exists here.
- Portability: same profile.

Fresh randomness is therefore only meaningful if the contract stops trying to reuse allocator-key
runs at all, i.e. it becomes "native execution with a note", not an accelerator.

## Decision

Retain option 1. The fixed key is a deliberate, opt-in weakening of one hardening property in
exchange for reproducibility. It is contained by:

- explicit `--contract allocator-entropy-v1` opt-in, never the default;
- an exact glibc build-ID, offset and signature check, with refusal on any mismatch;
- the contract name recorded in identity, guard and report;
- a report reason that says reuse is reproducible within the contract, not equivalent to native;
- preserving `never` (default) as the conservative native path;
- no claim that controlled entropy is a sandbox, and no `PROVEN` status.

Revisit only if a real threat model requires key secrecy inside the traced process. In that case the
right change is to stop reusing allocator-initialisation runs, not to derive a key that the child can
still read.

## Reproducing the evidence

```bash
# The audited build and the contract tests
cargo test -p tracejit-cli --test linux_integration allocator_entropy_contract_reuses_a_glibc_tool
cargo test -p tracejit-cli --test linux_integration allocator_double_free_detection_survives_the_contract
cargo test -p tracejit-cli --test linux_integration a_contract_does_not_absorb_application_randomness

# glibc source used for the reading
apt-get source glibc   # or the matching 2.39 tarball; see malloc/malloc.c: tcache_key_initialize,
                       # tcache_put, tcache_get_n, _int_free
```

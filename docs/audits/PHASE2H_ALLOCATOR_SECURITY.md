# Phase 2H: security analysis of deterministic allocator initialisation

Verdict: injecting a fixed allocator key does **not** change normal allocation behaviour, and glibc's
double-free detection still fires (verified end to end). It does, however, remove the per-process
secrecy of the tcache key, which is a hardening property that only matters under an existing heap
write primitive. The contract stays opt-in, is documented as not equivalent to native execution, and
is unsuitable for untrusted or CPU-time-sensitive programs. A per-identity derived key is the safer
alternative and is the recommended next correction.

## What the value is used for

glibc's tcache stores an eight-byte `tcache_key` in each freed chunk. On `free`, when the chunk is
already the tcache head, `_int_free` compares the stored key with `tcache_key`; equality raises
`free(): double free detected in tcache 2` and aborts. The key is initialised once, from
`getrandom(8, GRND_NONBLOCK)`, in `tcache_key_initialize` from `ptmalloc_init`.

Consequences of a fixed, publicly known value:

| Property | Effect |
| --- | --- |
| normal allocation/free | none; the key is written and compared, never interpreted as a pointer or size |
| double-free detection | still works: the same fixed key is written to the chunk and compared on the second free |
| tcache poisoning resistance | reduced: the secret key is what makes a forged freed chunk hard to construct; a published constant can be written by an attacker who already has a heap write |
| cross-process linkability | the same key in every process under the contract; a leak from one process applies to another |
| reproducibility | the point of the contract; identical commands produce identical allocator state |

This is a real but conditional weakening: it presupposes memory corruption. It is not a reason to
reject the contract for deterministic offline tools, and it is a reason to forbid making it a
default for untrusted programs.

## Tests

`allocator_double_free_detection_survives_the_contract` compiles a program that frees the same
pointer twice, runs it natively (aborts), then runs it under the contract. The exit status is still
non-zero and glibc's diagnostic still appears, so the injected key neither hides the error nor turns
the abort into a silent success. The differential fuzzer exercises ordinary allocations of many
sizes in every `sed`/`gzip`/`wc`/`md5sum`/`base64`/`tr` run with no allocator failure observed.

Degenerate keys are not replayable: the guard refuses `0` and `u64::MAX` records, and the profile
requires the exact audited value, so a record cannot smuggle a different key.

## Alternatives considered

1. **Per-identity derived key** (recommended): derive the eight bytes from the cache identity
   (contract, executable hash, argv, library build ID) instead of a global constant. Reproducible
   for the same command, different across programs, no published constant. The record already
   stores the value, and the guard can require a non-degenerate derived value, so the change is
   local to key derivation. Not implemented in this phase.
2. **Zero key / disable tcache**: zero can collide with zeroed user data and is weaker; disabling
   tcache changes performance and is not reproducible across tunables. Rejected.
3. **Leave the kernel call and record the value**: the value would differ per run, so reuse would
   need to treat it as an external input (record/replay), which is a different, much larger
   mechanism. Rejected for this contract.
4. **`LD_PRELOAD`**: cannot intercept the internal call (no PLT); rejected by evidence.

## Limits

- Not a sandbox and not isolation; Landlock/`PROVEN` remains unverified (see below).
- Not for cryptographic randomness: those calls target application buffers and are refused.
- Not for untrusted programs: a fixed key weakens a hardening measure and the contract is opt-in.
- Not free of allocator-behaviour differences in principle: the key is the only changed input, and
  the tested programs show none.

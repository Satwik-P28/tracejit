# Phase 2G: the two execution contracts

TraceJIT now has exactly two execution modes. Neither is a sandbox, and neither claims equivalence
to arbitrary native execution.

## Contract 1: native guarded execution (unchanged)

No environmental nondeterminism is controlled. `getrandom`, clocks, process identity, resource
counters, network and mutable system information stay ineligible, as do pipes, descriptors and
`/proc/self/*` observations that cannot be replayed. A record made in this mode has
`contract: null` and can never be reused by a contracted run, because the contract id is part of the
lookup key and of the stored record.

## Contract 2: `tracejit.allocator-entropy.v1`

### What is fixed

Exactly one thing: the runtime's own allocator-entropy probe. At the syscall-entry stop, when all of
the following hold, the tracer suppresses the kernel call and returns the contract's fixed eight
bytes (`0x9e37_79b9_7f4a_7c15`) as if `getrandom` had succeeded.

| Admission condition | Why |
| --- | --- |
| syscall is `getrandom` | nothing else is transformed |
| `length == 8` and `flags == GRND_NONBLOCK` | the runtime's probe shape; a blocking application request is not admitted |
| the instruction pointer is in an executable file-backed mapping | the caller is code in a shared library |
| the destination is in a private writable mapping | it is not shared memory or a file mapping |
| the destination offset lies inside that same library's `PT_LOAD` with `PF_W` | the address belongs to the library's data/`.bss` by its own ELF layout, not merely by a mapping name |
| the issuing module is not `/proc/<pid>/exe` | for a static program, runtime and application code share one module, so the check could not distinguish an allocator key from an application buffer; contract v1 is for dynamically linked runtimes |

The ELF check is why the implementation does not compare pathnames for the destination: glibc's
`.bss`, where the tcache key lives, is mapped anonymously by the loader and has no pathname.

### What is recorded and guarded

The effect stores the library path, its content hash, the call-site module offset, length, flags,
the fixed value and the contract id. The guard re-hashes the library, requires the implemented
contract id, the admitted shape and the contract value, and refuses otherwise. A record whose value,
shape or contract was tampered with is not replayable. The library hash is what makes a changed libc
invalidate the entry.

### What is not controlled

Address-space layout, clocks, PIDs, resource usage, `sysinfo`/`sched_getaffinity`, application
randomness, network responses, `/proc/self/maps`, external service data. Any of those still makes the
execution ineligible. The contract therefore does not make a program deterministic in general; it
removes one specific, mechanically identified runtime-internal input.

### Non-equivalence statement

A result recorded under the contract is reproducible **under that contract**, for that library build
and that admitted call shape. It is not presented as equivalent to native execution: the report
carries the contract id in `contract`, and its reasons include "reuse is reproducible within that
contract, not equivalent to native execution". Native and controlled entries never share a cache
identity (tested both directions).

### Why not `LD_PRELOAD`

glibc's internal calls do not go through the PLT, so a preloaded `getrandom` does not intercept
`tcache_key_initialize`; the detbox/DetFlow project records the same limitation for libc
interposition. Ptrace sees the syscall regardless of the caller, which is why the contract is
implemented there.

## Comparison with existing deterministic-execution systems

| System | Mechanism | Scope | Relation to this work |
| --- | --- | --- | --- |
| **Hermit / Detcore** | ptrace (Reverie) plus a virtualised environment; controls scheduling, time, random bytes, PIDs, file metadata, CPUID; record/replay for external inputs | whole-program determinism, including concurrency | far broader. It explains nondeterminism rather than allowing a narrow allow-list; it also controls scheduling, which TraceJIT does not. Its guarantee is a deterministic replay of a whole execution, not caching under a per-effect guard |
| **DetTrace** | ptrace, reproducible container, sequentialises system calls | whole-container reproducibility (12,130 Debian builds) | same direction and cost profile (3.49x on IO-heavy builds); TraceJIT instead caches and reuses, so the trace cost is amortised |
| **rr** | ptrace record/replay for debugging | faithful replay of one execution | opposite product: it records nondeterminism to reproduce it, not to skip work |
| **Firebuild** | intercepts and hashes inputs, refuses nondeterminism by contract | build caching | closest philosophy; TraceJIT differs by modelling effects and guarding them instead of refusing the program |

What is new here is only the narrow, mechanically checked entry into the allocator's own entropy.
It is not a general determinism system and does not claim Hermit's guarantees.

## What the contract is not

- It is **not a security sandbox**. Isolation guarantees are those of the surrounding execution; the
  Landlock `PROVEN` path is still unverified on this host.
- It does **not** weaken cryptographic randomness in general-purpose programs: a crypto request has
  an application buffer, not a runtime data segment offset, so it is refused.
- It is **not** a global whitelist of `getrandom`: the default mode is unchanged, the admission is
  per-call and mechanically checked, and every other randomness source remains ineligible.

## Verified by tests

| Test | Guarantee supported |
| --- | --- |
| `allocator_entropy_contract_reuses_a_glibc_tool` | `sed` becomes `Guarded`, reuses, invalidates on input change, and native mode does not reuse the controlled entry |
| `a_contract_does_not_absorb_application_randomness` | an application's own `getrandom(1, 0)` stays `Nondeterministic` under the contract |
| `controlled_entropy_guard_requires_the_recorded_runtime_and_shape` | changed runtime hash, contract id, value or shape is refused |
| `contract_check.py` | four tools: direct-output equality over three native runs, reuse, input change, environment change, native/controlled separation |
| `workflow.py` | four-command workflow: every step is a hit with direct-equal bytes |

Repeated output equality is not treated as proof of semantic equivalence; the guarantee each test
supports is the one named, and the broader claim is scoped to "reproducible under this contract".

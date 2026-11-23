# allocator-entropy-v1: correctness argument and profile specification

This document states what the contract claims, the assumptions it rests on, how an admission is
justified, and how to add a build. It is deliberately narrower than "the execution is
deterministic": the claim is that one specific runtime-internal entropy read is fixed and cannot
reach an observable.

## 1. The contract

`tracejit.allocator-entropy.v1` (`tracejit_effects::ALLOCATOR_ENTROPY_CONTRACT`):

> The C runtime's allocator initialises an internal key by asking the kernel for eight bytes with
> `GRND_NONBLOCK`, writing them directly into a static variable of the runtime library. Under this
> contract the tracer supplies a fixed value instead, and records that it did so. An execution
> recorded under the contract is reproducible under the contract. It is not claimed to be equivalent
> to native execution.

The value is `ALLOCATOR_ENTROPY_VALUE = 0x9e3779b97f4a7c15`. It never leaves the runtime's
allocator state: the tracer writes it into the destination the syscall named, and the guard checks
that the destination is the runtime library's own writable data.

Admitted regardless of contract? No. The syscall decoder gates on `length == 8 && flags == GRND_NONBLOCK`
first, then on `allocator_entropy_site(pid, rip, buffer)`. Only a `--contract` run reaches the second
gate at all; without a contract the observation stays `Nondeterministic`.

## 2. What makes an observation admissible

Seven conditions, all checked against the live process at record time and re-checked against the
library image at reuse time:

| # | condition | how it is checked |
|---|---|---|
| 1 | the request is the allocator's probe | `length == 8`, `flags == GRND_NONBLOCK`, exactly |
| 2 | the caller is a shared library, not the program | `rip` is in an `r-x` mapping whose path is absolute and differs from `/proc/<pid>/exe` |
| 3 | the buffer is the library's own writable data | the buffer's mapping is private and writable **and** `buffer - load_base` falls inside a `PT_LOAD` with `PF_W` (the loader maps `.bss` anonymously, so the mapping has no pathname — the ELF fact is what decides) |
| 4 | the call site is the audited one | `build_id` is in `ALLOCATOR_ENTROPY_PROFILES` **and** `rip - load_base == profile.site_offset` |
| 5 | the library encodes what the profile claims | `audited_allocator_site` decodes the image: `mov $318,%eax` immediately before the `syscall`, the exact adjacency `mov $1,%edx; mov $8,%esi; lea disp32(%rip),%rdi`, and that the `lea`'s effective address equals `profile.destination_offset` |
| 6 | the destination the record names is that buffer | `destination_offset == site.buffer_offset` |
| 7 | the library has not changed since recording | `hash_file(library) == expected` (BLAKE3, whole file) |

Conditions 1–4 and 6–7 are the pre-existing rule. Condition 5 is new in Phase Z: it turns the
profile's destination from an assertion into a machine-checked consequence of the image. A profile
whose offsets have drifted from the code it names now fails closed at both ends.

Ambiguity is refused, not resolved: a window containing two candidate `lea ...(%rip),%rdi`
instructions, or a request whose immediates are reordered, yields `None`, which the caller treats as
"not admitted" and falls through to the ordinary `Nondeterministic` classification.

## 3. Correctness argument

**Claim.** If an execution `E` is recorded under the contract on a library `L` and later replayed with
every guard passing, then the replayed stdout, stderr, exit status and output files equal what `E`
produced, and every entropy observation the replay would have made is either the same fixed value or
was not admissible at record time.

*Argument.*

1. *The fixed value is the only difference from native execution in the entropy dimension.* `E`
   observed exactly one kind of entropy under the contract: a `getrandom` of eight bytes with
   `GRND_NONBLOCK` that satisfied conditions 1–5. Every other entropy source (`getrandom` of any
   other shape, clocks, `getpid`/`gettid`, `sysinfo`, `getrusage` outside an audited compiler) stays
   an ordinary effect and makes `E` ineligible. This is a property of the decoder, not of a
   post-hoc filter: `decode_entry` emits `ControlledRandom` only inside the shape gate, and
   `EffectProperties` marks the resulting `Read` as guardable-but-contract-bound.
2. *The value cannot reach a buffer the program owns.* By condition 3 the destination is inside `L`'s
   writable `PT_LOAD`, and by condition 5 the destination is the one the code loads into `rdi`
   immediately before the syscall. The kernel (or the tracer substituting for it) writes eight bytes
   there and nowhere else; the syscall's other arguments are `length=8` and `flags=GRND_NONBLOCK`.
   The only other writer of that address is the same function's short-read fallback, which derives a
   key from `CLOCK_MONOTONIC` and the stack when the read is not exactly eight bytes — and every
   audited build is checked to contain that fallback immediately after the `cmp $0x8,%rax; je`
   (condition 5's tail check).
3. *What the value can influence is the allocator's own state.* `tcache_key` is used to perturb
   safe-linking pointers. Fixing it changes heap layout; it does not change what the program is
   asked to compute. That is exactly the contract's declared limitation, and records from the
   contract are never mixed with native records (`RunReport.contract`, `ExecutionIdentity`, and the
   `--contract` key on the cache row).
4. *Replay does not re-execute the command.* A hit restores recorded stdout/stderr/outputs after the
   guards pass. The guards are state predicates on the recorded dependencies; condition 7 makes the
   runtime library itself one of them, so a different runtime build (or a modified one at a different
   path) cannot be silently substituted. A record whose `build_id` is not in the table is refused
   outright, even if every other field matches.
5. *Admission is per build, not per shape.* A shared library that issues the identical eight-byte
   probe is refused unless its build ID is audited (adversarial case `unaudited-library-probe`), and
   a record naming another build's site is refused (`a_record_naming_another_builds_site_is_refused`).
   This is why the rule cannot be "ignore any `getrandom` from libc".

The argument is conditional on the record having been produced by the tracer (the cache is not
adversarially writable in the threat model — corruption detection is a separate mechanism, exercised
by `corrupt-cache-object` and the Phase X1 regressions).

## 4. Versioning

The versioned unit is a **profile**, keyed by GNU build ID:

```rust
pub struct AllocatorEntropyProfile {
    pub build_id: &'static str,          // hex, as `readelf -n` prints it
    pub site_offset: u64,                // resume offset: two bytes past the `syscall`
    pub destination_offset: u64,         // the buffer, relative to the load base
    pub site_signature: &'static [u8],   // the bytes at `site_offset - 2`
}
```

`ALLOCATOR_ENTROPY_PROFILES` is the admitted set. Currently:

| build | distribution | syscall | resume | destination |
|---|---|---|---|---|
| `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` | 2.39-0ubuntu8.9 | `0xa9e87` | `0xa9e89` | `0x20b178` |
| `8cebda42d140fc2b09639f8b13a5d5f2e617ef09` | 2.39-0ubuntu8.12 | `0xa9e67` | `0xa9e69` | `0x20b178` |

Both carry the same audited tail `0f 05 48 8d 5d d0 48 83 f8 08`.

The contract id does **not** change when a build is added: the claim is unchanged, and every record
names its build. It would change if the fixed value, the request shape, or the admissible
destination semantics changed.

## 5. Adding a build

Manual steps, in order. Each one is a refusal point, so a mistake fails closed.

```bash
# 1. Compare the candidate against an already-audited build.
python3 scripts/phase_z_profile_audit.py compare \
    --reference /path/to/audited/libc.so.6 \
    --candidate /path/to/candidate/libc.so.6 \
    --json /tmp/diff.json --markdown /tmp/diff.md
# Require: one site with "audited_probe_shape": true; "identical": true for the audited
# function; the same destination; no new getrandom site.

# 2. Read the distribution changelog for the builds between the two, and confirm none of them
#    touches malloc, tcache, or getrandom.

# 3. Derive and verify the profile fields from the image itself.
python3 scripts/phase_z_profile_audit.py verify --image /path/to/candidate/libc.so.6 \
    --site-offset <resume> --destination-offset <buffer> --signature <bytes>
# `profile_matches: true` is required.

# 4. Add the entry to ALLOCATOR_ENTROPY_PROFILES and run the derivation test against the image.
TRACEJIT_AUDIT_LIBC=/path/to/candidate/libc.so.6 \
    cargo test -p tracejit-effects -- --ignored audited_sites_match_a_reference_library --nocapture

# 5. Run the gates, and confirm the contract tier actually obtains hits on a host with that build.
```

A profile may only be added when steps 1–4 hold. If the function is *not* instruction-identical, the
profile is not the answer: a separate contract revision is required, because the request shape or the
fallback would have changed.

## 6. Regenerating evidence

| artifact | command |
|---|---|
| build-to-build comparison | `scripts/phase_z_profile_audit.py compare …` |
| where the entropy comes from | `scripts/phase_z_provenance.py --summary -- <command>` |
| environment fingerprint | `benchmarks/phase_z/harness.py fingerprint --json …` |
| pinned sessions | `benchmarks/phase_z/harness.py session --invocations 48 --json …` |
| non-compiler workloads | `benchmarks/phase_z/harness.py workloads --json …` |
| adversarial corpus | `benchmarks/phase_z/adversarial.py --json …` |
| compatibility census | `benchmarks/realworld/census.py --contract allocator-entropy-v1` |

The harness records a fingerprint (kernel, CPU, libc build ID and digest, loader, every toolchain
build ID, the TraceJIT binary digest, the pinned environment variables, the corpus digest) beside
every result, and `--compare-to` refuses a comparison whose pinned fields disagree.

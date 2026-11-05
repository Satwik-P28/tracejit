# Phase 2H: hardening `tracejit.allocator-entropy.v1`

Verdict: the Phase 2G rule was a *pattern*, not a call site. It accepted any shared library that
requested eight non-blocking bytes into its own writable `PT_LOAD`, which is exactly the broad
heuristic the contract must not rely on. It now admits one audited build, one instruction offset,
one destination offset and the audited instruction bytes, and refuses everything else.

## What changed

The admission rule is now a **call-site profile**:

```rust
AllocatorEntropyProfile {
    build_id,            // GNU build ID of the runtime library
    site_offset,         // resume offset of the syscall stop (libc+0xa9e89)
    destination_offset,  // the runtime's tcache_key (libc+0x20b178)
    site_signature,      // bytes covering the `syscall` and what follows
}
```

The tracer requires all of:

1. `getrandom` with `length == 8` and `GRND_NONBLOCK`;
2. the instruction pointer in an `r-x` file-backed mapping of a library that is not the executable;
3. `ip - load_base == profile.site_offset` — measured, not derived. On x86-64 the tracer's stop is
   the byte after the two-byte `syscall`, so the audited resume offset is `0xa9e89`;
4. `buffer - load_base == profile.destination_offset`, and the destination inside that library's
   private writable `PT_LOAD` (the `.bss` tail is mapped anonymously, so ELF layout is the proof);
5. the library's GNU build ID in the audited table;
6. the audited bytes at `site_offset - 2` (`0f 05 48 8d 5d d0 48 83 f8 08`), read from the file;
7. the library content hash recorded for the guard.

The record carries `build_id`, `site_offset` and `destination_offset`, and the guard repeats checks
2–6 against the *current* library, so a replaced or rebuilt libc cannot be replayed. Records written
before the profile existed have empty fields and are refused rather than reinterpreted.

## Audit findings

- **Instruction offsets.** The syscall is at `libc+0xa9e87`; `strace` reports the return address
  `0xa9e89`, which is what the tracer sees. An earlier profile using `0xa9e87` refused every call
  (observed as `NONDETERMINISTIC`); the corrected profile matches and the contract evidence names
  the same offset the record does.
- **Calling sequence.** `malloc+0x215` calls the initialiser at `libc+0xa9e50`, which loads
  `&tcache_key` with `lea 0x161316(%rip)` → `0x20b178`, sets the "initialised" byte at `0x20b188`,
  and only then performs the syscall.
- **Writable destination.** `0x20b178` is inside the writable `PT_LOAD` of libc; the mapping is
  private and anonymous because it is `.bss`. Both the audited offset and the ELF segment are
  checked, so a different data symbol cannot be substituted.
- **Build identity.** `libc` build ID `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` (Ubuntu 24.04
  glibc 2.39). `ld.so` is `0d77dbd4379bf0b5af3e05be7fb6af1e4cea7c96` and is never the admitting
  module: no loader-issued `getrandom` is observed.
- **ASLR.** Load bases vary per run; the profile is expressed in module-relative offsets, and the
  record stores the library path and hash, so a randomised base neither breaks nor widens it.
- **Other functions in the same library.** Only this site is admitted. A different `getrandom` in
  libc — or in any other library — has a different offset or a different build, or fails the
  signature; all are refused.
- **Malicious or accidental look-alikes.** A library with the same shape but another build ID is
  refused before any memory check. Copying glibc's bytes and note would make it glibc.
- **Multiple calls, threads and forks.** The profile is per call site; a second call from the same
  site is admitted again and collapsed into one dependency. A thread or fork inherits the mapped
  library and uses the same site. If glibc does not call it again, no effect is recorded; if it
  does, the same guard covers it.
- **Return-value and memory-write correctness.** The tracer forces `ENOSYS` (`orig_rax = u64::MAX`),
  writes the eight bytes with `process_vm_writev` (falling back to `ptrace::write`), sets `rax = 8`
  and resumes. No kernel random value is produced, so the value and the return value agree.

## Coverage of the audit

Tests: `controlled_entropy_guard_requires_the_recorded_runtime_and_shape` (runtime hash, contract
id, value, shape, unknown build, degenerate values), `allocator_entropy_contract_reuses_a_glibc_tool`
(end-to-end reuse, invalidation, native/controlled separation),
`a_contract_does_not_absorb_application_randomness` (application buffer refused), the differential
fuzzer (look-alike scenarios), and the unaffected 16-workload suite.

This is audited coverage of the builds and scenarios listed, not a proof about arbitrary libc
builds; unknown builds are refused, which is the point.

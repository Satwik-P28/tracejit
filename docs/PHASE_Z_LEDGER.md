# Phase Z hypothesis ledger

Every entry was tested on this host with the scripts in `benchmarks/phase_z/` and
`scripts/phase_z_*`. "Rejected" means the evidence was against it, not that it was hard.

## Accepted

| hypothesis | evidence | what shipped |
|---|---|---|
| **H1. The 8.12 build is behaviourally equivalent at the audited call site.** | The audited function decodes to the *same* instruction stream in both builds once code addresses, encodings and RIP-relative displacements are normalized (`identical: true`, ratio 1.0). Same destination `0x20b178`, same 8-byte `GRND_NONBLOCK` request, same clock fallback on a short read. The changelog's 8.10–8.12 patches are in `libio`, `resolv`, `elf/dl-load.c`, `nscd`, `powerpc`, `iconvdata` — none in malloc. | second `AllocatorEntropyProfile` entry |
| **H2. Deriving the destination from the image is stronger than asserting it.** | `audited_allocator_site` re-derives `0x20b178` from the `lea`'s RIP-relative displacement in both images. Synthetic-image tests show it refuses a displaced buffer, a reordered request, a changed syscall number, an ambiguous window, and a profile that asserts a destination the code does not encode. | tracer and guard both call it |
| **H3. A guard-side derivation is enough to make a new build reviewable.** | 9 host-independent regressions in `phase_z_tests.rs` exercise the positive path and every single-field mutation. | `phase_z_tests.rs` |
| **H4. Compiler reuse is restored, and the replay is semantically correct.** | 103.7 → 45.2 ms, object byte-identical to native. Sessions 1.81× (27) and 2.91× (48) with every arm's objects byte-identical. | production commit |
| **H5. Non-compiler workloads can gain substantially.** | `sed` 11.02×, `sort --parallel=1` 8.29×, `gzip -9` 3.80×, all with byte-identical outputs and 2–6 ms of hashing/restore inside 50–152 ms commands. | shortlist in the report |
| **H6. A fingerprint-and-refuse harness makes cross-environment comparison impossible by accident.** | `--compare-to` refuses when any pinned field differs (kernel, CPU, libc build ID, loader, toolchain build IDs, TraceJIT digest, environment). | `benchmarks/phase_z/harness.py` |
| **H7. An independent observer reproduces the tracer's attribution.** | `phase_z_provenance.py` identifies the same site (`libc+0xa9e69`), destination (`libc+0x20b178`) and shape for all three compiler processes, and classifies application entropy as `other`. | script + report §4 |

## Rejected

| hypothesis | why it was rejected |
|---|---|
| **R1. Recognize the allocator probe across builds without a build-specific profile.** | The recognizable part (instruction shape) is the part an attacker or an unrelated library can reproduce: an unaudited `.so` with a constructor doing `getrandom(&k, 8, GRND_NONBLOCK)` matches the shape exactly and must still be refused. Recognising "any library doing this" is the broad rule the mission forbids. Build-specific profiles plus a derived check keep the decision reviewable. |
| **R2. Relax the `CLONE_FILES` rule so threaded `sort`/`xz` become eligible.** | It would admit descriptor-flag questions whose answer belongs to another thread. Out of scope for a contract-eligibility phase and not needed for the primary objective. |
| **R3. Model `fcntl(F_GETFL)` on inherited descriptors to reach `tar`, `python`, `xz`, `make`.** | The flags of an inherited descriptor belong to whoever started us; answering them from a record is exactly the class of mistake the rule prevents. Rejected without a sound model. |
| **R4. Ignore `CLOCK_REALTIME` so `awk` becomes eligible.** | `awk`'s realtime read is a genuine input; fixing it is a different contract with a different claim. |
| **R5. Widen `compiler-runtime-v1` to admit compiler provenance for non-compilers.** | The profile is an exact binary path + build ID; a non-compiler would have no profile, and inventing one on the strength of "it is deterministic in practice" is the empirically-stable tier the project refuses to reuse. |
| **R6. Drop `accessed_ns` from metadata guards to recover `objcopy`/`strip`/`unzip` hits.** | It is a real observation: a metadata-only guard without it would accept a rewrite the command could have seen. The fix is field-precise guards, not a weaker one, and it is a separate phase. |
| **R7. Keep the old 10-byte signature comparison and add only a build ID.** | It works, but it makes every future admission a byte-offset guess. The derived check costs ~40 lines and is testable without a runtime image. |
| **R8. Compare against `ccache`/`sccache` in this environment.** | Not installed, no root, no package manager, no cmake to build them. Reporting Phase W's numbers here would compare machines, which the mission forbids. `make` is measured with its real invocation count (9 compiles, not 27). |
| **R9. Measure the compiler session with 24 functions per unit.** | First attempt: native was 87 ms per compile, the trace premium could not be repaid, and TraceJIT was 0.62× — a true measurement of the wrong workload. Re-ran at 220 functions per unit, matching Phase W, and reported that instead. |
| **R10. Treat "eligible" as "usable" for `wc`/`sha256sum`.** | Both hit correctly and both are *slower* than native (0.15×, 0.29×) because compute is below the ~10 ms hit floor. Reported as rejected rather than folded into the shortlist. |

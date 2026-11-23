# Phase Z: runtime-contract portability, independent benchmarking, correctness

Branch `research/phase-z`, cut from `main` at `6bab00b`. Production change in one commit; evidence in
the rest. No release was tagged and nothing was merged.

*Read with `docs/PHASE_Z1_AUDIT.md`, which re-derives the contract from glibc's source and corrects
two claims in this report: `tcache_key` does not feed safe-linking, and fixing it does not change
heap layout. The admission rule and the measured results below are unaffected.*

Phase Y ended with a negative result: the allocator-entropy contract was pinned to a single glibc
build, that build had been superseded, and real compiler workloads no longer reached a hit. The
question here was narrower and harder than "add the new build ID": *can another build be admitted on
evidence rather than on a byte-offset guess, and does the resulting reuse hold up under an
independent oracle?*

The answer is yes, with a proof that is stronger than the one it replaces: the destination the
contract fixes is now **derived from the runtime library's own instruction stream** at both record
time and guard time, not asserted by a constant. Everything below is measured on this host and
reproducible from the scripts in the branch.

## 1. Starting point

| | |
|---|---|
| `main` at start | `6bab00bff96f6b461b65874ba3152178f8fea79a` (merge of PR #41) |
| Phase X1 baseline for comparisons | the same commit, built as `/tmp/tj-z-baseline-target/release/tracejit` |
| Post-merge CI before this phase | run #263 on `6bab00b`, success |

## 2. Runtime identities examined

| artefact | identity |
|---|---|
| glibc, audited by Phase Q–X | `2.39-0ubuntu8.9`, build `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` |
| glibc, installed here and on CI runners | `2.39-0ubuntu8.12`, build `8cebda42d140fc2b09639f8b13a5d5f2e617ef09` |
| dynamic loader | `ld.so` build `231ab65dd867a89dce29cb958fd5ca50abb1aa34` |
| compiler driver | `/usr/bin/x86_64-linux-gnu-gcc-13` build `9ac130c81c026cf6204ff71a70b526667a09122f` |
| `cc1` | build `32e37dd731113376ea74086d0a292046e09c1e92` |
| `as` | build `7fc854c85861e94ccc8725eb40d0cddd3d61fab9` |
| `ld` / `collect2` | builds `1d35d587…` / `33c97059…` |

The three compiler binaries are unchanged from the audited `compiler-runtime-v1` profiles, so the
compiler contract was never the stale part. Only the libc profile was.

The 8.9 image was obtained for comparison from the Ubuntu primary archive
(`libc6_2.39-0ubuntu8.9_amd64.deb`) and unpacked into `/tmp`; it was never installed, never replaced
the running library, and never entered a traced process.

## 3. What the failure actually was

`tracejit run --contract compiler-runtime-v1 -- gcc -O2 -c a.c -o a.o` on this host before the
change:

```
{"cache_decision":"Executed","classification":"Nondeterministic",
 "reasons":["process read randomness via getrandom"], ...}
```

Three processes (driver, `cc1`, `as`), one `getrandom` each, all of the same shape:

```
getrandom("\x5e\x7c\xa5\x05\x86\xda\x52\x94", 8, GRND_NONBLOCK) = 8
```

so the request-shape gate (`8` bytes, `GRND_NONBLOCK`) passed and the refusal came from a single
place: `allocator_entropy_profile("8cebda42…")` returned `None`. The first unabsorbed syscall after
admission is `getrusage(RUSAGE_SELF)` (98) from the driver, which the compiler contract admits only
for an audited binary path, and then `futex` traffic from the tracer's own bookkeeping — neither is
the blocker.

Attribution of that probe is the subject of §4.

## 4. Independent provenance

`scripts/phase_z_provenance.py` is a separate ptrace observer. It shares no code with the tracer: it
stops each task at syscall entry with `PTRACE_GET_SYSCALL_INFO`, reads the instruction pointer and
the 18 bytes at it from the task's memory, resolves the mappings that contain the pointer and the
destination, and classifies the observation. Symbol names are printed for orientation and are never
used for admission.

For `gcc -O2 -c a.c -o a.o` it reports three observations, one per process:

| pid | module+offset | nearest symbol (not authoritative) | length/flags | destination | checks | class |
|---|---|---|---|---|---|---|
| driver | `libc.so.6+0xa9e69` | `timer_settime+0x1079` | 8 / `GRND_NONBLOCK` | `libc+0x20b178` (anonymous writable tail) | 1111111 | `runtime-internal-probe` |
| `cc1` | same | same | same | same | 1111111 | `runtime-internal-probe` |
| `as` | same | same | same | same | 1111111 | `runtime-internal-probe` |

The checks are, in order: caller is a shared library (not the program's own text), call site is in an
executable mapping, destination is in the *library's* writable `PT_LOAD` (an ELF fact, because the
loader maps `.bss` anonymously so the destination has no pathname), destination mapping is private
writable, request is eight non-blocking bytes, the instruction tail matches, the call returned 8.

The same observer on an application that reads entropy classifies it differently: a program calling
`getrandom(buf, 16, 0)` shows the *public wrapper* site `libc+0x48864` with a `[stack]` destination
(`1 1 0 1 0 0 0` → `other`), and CPython's `os.urandom(24)` shows `libc+0x48864` into an anonymous
heap mapping → `other`. That is the distinction the contract needs, produced by a mechanism the
contract does not share.

## 5. Build-to-build comparison

`scripts/phase_z_profile_audit.py compare --reference <8.9> --candidate <8.12>` produced
`docs/PHASE_Z_GLIBC_DIFF.md` and `benchmarks/results/phase_z/glibc-diff.json`. Findings:

- Both images have exactly **three** `getrandom` syscall sites. Two are the public wrappers, at the
  **same file offsets** in both builds (`0x48862`, `0x4889b`) — proof the shift does not start
  before them. One is the allocator probe.
- The allocator probe is the only site with the audited shape in either build, and its destination
  is `libc+0x20b178` in both.
- The function containing it is **instruction-for-instruction identical** once code addresses, raw
  encodings and RIP-relative displacements are normalized to their resolved targets
  (`identical: true`, sequence ratio 1.0, zero differences on either side). It moved from
  `0xa9e50` to `0xa9e30`.
- The shift is `−0x20` from `_IO_file_attach` (0x92430 → 0x92410) onward; the last dynamic symbol
  whose address is unchanged is `_IO_file_fopen` at `0x91cb0`.
- The changelog (`/usr/share/doc/libc6/changelog.Debian.gz`) lists 8.10–8.12 as security updates in
  `libio/fileops.c` (CVE-2026-18374), `resolv/resolv_conf.c`, `elf/dl-load.c`, `nscd`,
  `sysdeps/powerpc` and `iconvdata`. The source package's patch series contains exactly one patch
  against `malloc/malloc.c` (`CVE-2026-0861.patch`), and it touches only `_int_memalign`'s
  alignment-overflow check; nothing in the series mentions `tcache`, the key initializer, or
  `getrandom`. (Phase Z's first draft said "no malloc change"; that was wrong in the small.
  `docs/PHASE_Z1_AUDIT.md` §3 has the source-level audit.)

So the byte shift is a downstream layout effect of the libio fix, and the allocator code itself is
the same instructions. That is what admits the build.

## 6. The production change

Two commits' worth of design, delivered as one reviewable commit:

1. **Admit the build.** `ALLOCATOR_ENTROPY_PROFILES` gains a second entry:
   `8cebda42…`, resume offset `0xa9e69`, destination `0x20b178`, same audited bytes. The 8.9 entry
   is untouched.
2. **Derive the call site instead of asserting it.** `tracejit_effects::audited_allocator_site`
   decodes the library image and returns what the code *encodes*: the syscall number
   (`mov $318,%eax`), the exact adjacency `mov $1,%edx; mov $8,%esi; lea disp32(%rip),%rdi`, the
   buffer's effective address computed from its own RIP-relative displacement, and the audited tail.
   It refuses when a window holds two candidate buffer loads, when the displacement lands anywhere
   but `destination_offset`, or when the request shape is reordered. Both the tracer (record time)
   and the guard (reuse time) call it, so the profile's destination is now cross-checked against the
   image on **both** sides.

`doctor` reports the host's status directly:

```
runtime        allocator-entropy-v1 audited (8cebda42d140fc2b09639f8b13a5d5f2e617ef09)
```

and says `unavailable (unaudited libc <build id>)` otherwise, so a runner update is visible instead
of looking like an unexplained refusal.

What did **not** change: the contract id, the fixed value, the request-shape gate, the build-ID
pinning, the existing 8.9 profile, every non-entropy rule, and native execution. Records from the
two builds cannot be mixed: a record names its `build_id` and is refused by any other profile.

The correctness argument and the profile specification are in `docs/PHASE_Z_CONTRACT.md`.

## 7. Results: compiler reuse is restored

Paired single command (`gcc -O2 -c a.c -o a.o`, one cold run then five warm runs, same cache, final
binary):

| | cold | warm hit (median of 5) |
|---|---|---|
| wall time | 103.7 ms (104–162 ms across builds) | **45.2 ms** (45.1–63.1) |
| decision | `Executed`, `Guarded` | **`Reused`**, all guards passed, `Guarded` |
| object | `3e8b58af…` | `3e8b58af…` — byte-identical to native |

Sessions (`benchmarks/phase_z/harness.py session`, 3 units × 220 functions, edits at rounds 3,6 and
7,12 to match Phase W's schedules; every arm's final objects compared byte-for-byte against a native
build of the final sources):

| session | native | TraceJIT | speed-up | decisions |
|---|---|---|---|---|
| 27 invocations | 13.813 s | **7.613 s** | 1.81× | 3 traces, 18 hits, 6 deopts |
| 48 invocations | 24.523 s | **8.440 s** | 2.91× | 3 traces, 39 hits, 6 deopts |

Per-compile inside a hit round: 60–64 ms against 508–510 ms native (≈8×). The deoptimisations are
exactly one per unit per edit (6 in both sessions) and the recorded cause is a guard failure on the
edited header, which is the intended behaviour.

`make` on the same schedule: 4.614 s / 4.626 s with only **9** actual compiler invocations — it wins
by not compiling, not by caching, and the harness reports the invocation count rather than hiding it.
`ninja` is not installed here. `ccache` and `sccache` are **not installed and cannot be installed**
(no root, no package manager access, no cmake to build ccache), so no same-environment comparison
against them is claimed; Phase W's numbers for them were measured on a different environment and are
not comparable.

## 8. Results: newly eligible workloads

`benchmarks/realworld/census.py` (32 requested, 30 attempted) and `census_v03.py` (20 held out),
contract tier `allocator-entropy-v1`, same host, same run parameters, baseline binary vs phase-Z
binary:

| census | baseline `main` | phase Z | newly eligible |
|---|---|---|---|
| original (30 attempted) | 1 reused | **7 reused** (8 eligible) | +6 |
| held out (20 attempted) | 0 reused | **7 reused** (10 eligible) | +7 |
| native tier, no contract | 1 | 1 | 0 (unchanged, by design) |

Newly eligible on the original census: `objcopy-strip-unneeded`, `bzip2-compress-stdout`,
`sed-rewrite-stdout`, `wc-line-count`, `sha256sum-blob`, `openssl-sha256`, `od-hex-prefix`.
On the held-out census: `strip-binary`, `objdump-disassemble`, `readelf-header`, `nm-symbols`,
`unzip-extract`, `iconv-transcode`, `base64-encode`, `md5sum`, `cut-columns`, `comm-sorted`
(ten eligible, seven obtained a hit).

The native tier is unchanged at 1/30 — the change admits *no* execution outside the declared
contract. That is the gate this phase had to pass and it did.

Two caveats, both recorded rather than smoothed over:

- `objcopy-strip-unneeded` is eligible but did not obtain a hit on the second run: `objcopy` `stat`s
  its input before reading it, and the metadata guard includes `accessed_ns`. This is the limitation
  `PROJECT_STATE.md` already documents for `strip`/`objcopy`/`unzip`, not a new defect.
- The census runs the *allocator* contract only, so the compiler workloads in it still report
  `unmodeled syscall 98` (`getrusage`); compiles need `compiler-runtime-v1`, which is measured in §7.

## 9. Results: non-compiler workloads

`benchmarks/phase_z/harness.py workloads` — deterministic corpus, 5 measured rounds, output files
removed before every measured invocation, per-hit phase timings from `TRACEJIT_PHASE_TIMING`:

| workload | native | warm hit | speed-up | verdict |
|---|---|---|---|---|
| `sed` numeric normalisation, 2 MB | 133.0 ms | 12.1 ms | **11.02×** | keep |
| `sort --parallel=1 -S 256M` | 142.2 ms | 17.2 ms | **8.29×** | keep (see below) |
| `gzip -9 -n -k` on 2 MB | 51.8 ms | 13.6 ms | **3.80×** | keep |
| `sha256sum` on 2 MB | 3.7 ms | 10.3 ms | 0.36× | reject — compute is below the ~10 ms hit floor |
| `wc -l` | 1.4 ms | 8.4 ms | 0.17× | reject — same |
| `awk` sum | 25.2 ms | — | — | ineligible: reads `CLOCK_REALTIME` |
| `sort` with default threads | 89.3 ms | — | — | ineligible: `CLONE_FILES` sharing is not modelled |
| `tar -cf` | 30.4 ms | — | — | ineligible: `fcntl(F_GETFL)` on inherited fds 0–2 |
| `python3 -m json.tool` | 115.7 ms | — | — | ineligible: same inherited-descriptor query |

Shortlist: three workloads where cached execution is 4–11× faster than recomputation, all with
byte-identical outputs. The hashing/restoration split is small relative to the saved computation:
`sed` 10.86 MB hashed in 3.94 ms by 105 guards plus 3.27 ms of restore inside a 133.0 ms command;
`sort` 15.31 MB in 5.99 ms by 99 guards plus 6.27 ms inside 142.2 ms; `gzip` 6.46 MB in 2.06 ms by 36
guards plus 6.00 ms inside 51.8 ms.

`sort`'s speed-up required `--parallel=1`: with threads it is ineligible for a reason that has
nothing to do with entropy. That is reported as a workload adjustment, not a contract change.

## 10. Correctness

### 10.1 Admission-rule regressions (new, host-independent)

`crates/tracejit-guards/src/phase_z_tests.rs` assembles the audited instruction sequence into a
synthetic library file, records a guard against it, and breaks exactly one thing per test: a
displaced buffer load, a different length, a missing `GRND_NONBLOCK`, a reordered request, a changed
syscall number, a changed tail, an ambiguous buffer-load window, a profile asserting a destination
the code does not encode, a record naming another build's site, an unknown build, a foreign
contract, a wrong shape, a destination the library does not encode, a changed library hash, a value
the contract did not supply, and duplicate/foreign profile entries. 9 tests, all passing, no host
dependency — the positive path runs on any machine.

`crates/tracejit-effects` adds 6 unit tests for the derivation itself (accept, framework of the
negative cases, and a test that keeps the `8`/`1` constants and the instruction bytes from drifting
apart), plus an ignored `audited_sites_match_a_reference_library` that re-derives the destination
from any image handed to it by `TRACEJIT_AUDIT_LIBC`. Both real images were checked with it:

```
RESULT …/2.39-0ubuntu8.9/libc.so.6  build a4a7992a… buffer 0x20b178 length 8 flags 1
RESULT /usr/lib/…/libc.so.6         build 8cebda42… buffer 0x20b178 length 8 flags 1
```

### 10.2 Adversarial corpus

`benchmarks/phase_z/adversarial.py` — 16 cases, each comparing a warm TraceJIT run against an
independent native execution of the same command (stdout, stderr, exit status, and every file in the
working directory):

| case | expectation | observed |
|---|---|---|
| baseline `sed` | reusable | `Reused` |
| application entropy → stdout | refused | `Ineligible` (randomness) |
| application entropy → filename | refused | `Ineligible` (randomness) |
| application entropy seeds a PRNG | refused | `Ineligible` (randomness) |
| two threads | no incorrect reuse | `Ineligible` (clone sharing) |
| two children | no incorrect reuse | `Ineligible` (randomness) |
| **unaudited shared library issuing the same 8-byte `GRND_NONBLOCK` probe** | refused | `Ineligible` |
| crash during startup | no incorrect reuse | `Ineligible` |
| audited build loaded from a copy | reusable | `Reused` |
| compiler replaced at the same path | no incorrect reuse | `Ineligible` (path-pinned profile) |
| inherited descriptor | no incorrect reuse | `Skipped`: "inherited descriptor 3 beyond stdin is not modelled" |
| record under another contract | refused | `Executed` (no cross-contract reuse) |
| loader path changed between record and replay | no incorrect reuse | `Executed` (environment identity) |
| corrupt cache object | refused | `Executed` (re-traced) |
| recording killed at 40 ms of ~130 ms | no incorrect reuse | `Executed` (no partial record) |

**0 incorrect hits.** The unaudited-library case is the sharpest one: a `.so` with a constructor that
does exactly `getrandom(&probe_key, 8, GRND_NONBLOCK)` is *not* admitted, because admission is the
audited build's instruction sequence, not the shape of the request.

### 10.3 Existing gates

| gate | result |
|---|---|
| `cargo fmt --all -- --check` | clean |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | clean |
| `cargo test --workspace` | **261 passed, 0 failed, 1 ignored** (was 253) |
| `linux_integration` | 75/75 at `--test-threads` 1, 2, 8, and at the default |
| differential fuzz, seed 29 | 120 ok, **0 incorrect hits** |
| model check | `RESULT phase-k3-modelcheck PASS` |
| restore fault injection | soft-fail and hard-kill both `PASS` |
| `cargo audit` | exit 0, no advisories |
| release build | clean |

The integration suite now exercises the *audited* branch on this runner: its guard is
`allocator_entropy_profile(build_id).is_none()`, so with 8.12 admitted the compiler and `sed`/`tr`
contract tests take the reuse path instead of the refusal path. The profile is therefore covered by
a successful HIT in CI, which is what the phase required before calling it verified.

## 11. Remaining assumptions

1. **The probe's value cannot escape.** True because the kernel writes into `tcache_key` in the
   library's `.bss` and the only other writer is the same function's clock-derived fallback for a
   short read; verified per build by the derived-instruction check and per record by the
   destination/writable-segment check at trace time.
2. **Fixed entropy cannot change a defined observable.** The key is stored in the `key` field of a
   chunk being freed into a thread cache and compared there by `_int_free`'s double-free heuristic;
   that is the whole of its use. It does **not** seed safe-linking (links are masked with the
   chunk's own address, which is ASLR-derived) and it selects no allocation, so fixing it moves no
   heap object and changes no address. The only memory whose contents change is the second word of
   a freed chunk's user area, which `tcache_get_n` zeroes on allocation; a defined program cannot
   read it before writing it. Reading the value requires undefined behaviour (freed or
   uninitialized memory) or a forged chunk, which the contract excludes
   (`docs/PHASE_Z_CONTRACT.md` §3.1). The claim remains reproducibility *within* the contract, not
   native equivalence.
3. **The instruction-level equivalence is evidence, not a proof of semantic equivalence.** Two
   functions that decode to the same instructions after relocation normalization are the same code
   with respect to everything the CPU sees; the assumption is that objdump's decoding is complete,
   which is why the guard also pins the build ID and refuses on ambiguity.
4. **A future build needs a new audit.** Nothing here identifies the sequence *without* a build
   entry. A cross-build recognizer was considered and rejected (§12).
5. **`accessed_ns` in metadata guards** still makes `objcopy`/`strip`/`unzip`-shaped commands lose
   their hit on the second run. Unchanged from previous phases.
6. **No competitor comparison on this host.** `ccache`/`sccache` are unavailable; `make` is measured
   and its invocation count is reported.

## 12. Hypotheses: accepted and rejected

See `docs/PHASE_Z_LEDGER.md`. In summary: accepted the build-specific profile plus derived call-site
verification, and a second audited build; rejected cross-build pattern recognition, relaxing the
`CLONE_FILES` rule to reach `sort`, admitting `fcntl(F_GETFL)` on inherited descriptors to reach
`tar`/`python`, ignoring realtime clocks to reach `awk`, widening the contract to admit compiler
provenance for non-compilers, and removing the `accessed_ns` metadata field.

## 13. Verdict and next phase

The primary objective is met: compiler workloads are eligible again on the current glibc, reuse is
restored with byte-identical objects, and the admission rule is *stronger* than before because the
destination is derived from code rather than asserted. Thirteen workload instances on two independent
censuses became eligible, none outside the contract. No incorrect HIT was found by any of the 16
adversarial cases, 120 differential fuzz cases, 261 unit/integration tests, the model check, or the
fault-injection probes.

Next phase should attack the *blockers* rather than the entropy surface, in this order: (a)
`fcntl(F_GETFL)` on inherited descriptors, which alone blocks `tar`, `python`, `xz`, `make`-driven
pipelines and most packaging work; (b) `CLONE_FILES`-sharing threads, which blocks `sort`, `xz -T`,
and every parallel tool; (c) `accessed_ns` in metadata guards, which silently costs the hit for
`strip`/`objcopy`/`unzip`. Those three are worth more eligible workloads than any further entropy
work, and none of them requires weakening anything.

## 14. Artifacts

| path | what it is |
|---|---|
| `crates/tracejit-effects/src/lib.rs` | `audited_allocator_site`, the second profile, derivation tests |
| `crates/tracejit-guards/src/phase_z_tests.rs` | 9 host-independent admission regressions |
| `crates/tracejit-guards/src/lib.rs` | guard calls the derivation instead of comparing a signature |
| `crates/tracejit-trace/src/linux.rs` | tracer calls the same derivation |
| `crates/tracejit-core/src/lib.rs`, `crates/tracejit-cli/src/main.rs` | `doctor` runtime-contract line |
| `scripts/phase_z_provenance.py` | independent ptrace provenance analyzer |
| `scripts/phase_z_profile_audit.py` | build-to-build audit, profile generation and verification |
| `benchmarks/phase_z/harness.py` | fingerprint, pinned sessions, workload measurements |
| `benchmarks/phase_z/adversarial.py` | 16-case independent adversarial corpus |
| `docs/PHASE_Z_GLIBC_DIFF.md` | generated build-to-build comparison |
| `docs/PHASE_Z_CONTRACT.md` | correctness argument and versioned profile specification |
| `docs/PHASE_Z_LEDGER.md` | accepted/rejected hypotheses |
| `benchmarks/results/phase_z/` | raw JSON for every number above |

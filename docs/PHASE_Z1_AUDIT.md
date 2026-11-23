# Phase Z1: security and semantic audit of `allocator-entropy-v1`

Branch `research/phase-z`, PR #42, starting head `87c175c`. This phase re-derives the contract from
glibc's own source instead of from the earlier summary of it, corrects two claims that were wrong,
adds the allocator-behaviour regressions the review called for, and re-runs every gate.

**Outcome.** No defect was found in the admission rule or in the tracer's substitution. Two
statements in Phase Z's documentation were wrong and are corrected here: the key does **not**
perturb safe-linking and does **not** change heap layout. The contract is narrowed accordingly, its
exclusions are now explicit, and the claim it supports is stated as three separately qualified
claims (A, B, C) rather than one.

## 1. Source of truth

| artifact | identity |
|---|---|
| upstream source | `glibc-2.39.tar.xz` from `ftp.gnu.org`, unpacked to `/tmp/glibc-src` (read only) |
| Ubuntu source package | `glibc_2.39-0ubuntu8.12.debian.tar.xz` from Launchpad (138 patches, read only) |
| audited runtime A | `libc6_2.39-0ubuntu8.9_amd64.deb`, build `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` |
| audited runtime B | installed `2.39-0ubuntu8.12`, build `8cebda42d140fc2b09639f8b13a5d5f2e617ef09` |

Neither image was installed, loaded, or modified. The 8.9 `.deb` was fetched from
`launchpad.net/ubuntu/+archive/primary/+files/libc6_2.39-0ubuntu8.9_amd64.deb` and unpacked with
`dpkg -x`; its ELF build ID was checked before use.

## 2. What glibc actually does with `tcache_key`

`malloc/malloc.c:3128` declares `static uintptr_t tcache_key;`. The comment above
`tcache_key_initialize` (2.39, lines 3130–3138) says the value "does not really have to be a
cryptographically secure random number. It only needs to be arbitrary enough so that it does not
collide with values present in applications", and that a collision "could cause a degradation in
performance since the entire list is checked".

There are exactly four code sites, and only two roles:

| site | line | what it does with the key |
|---|---|---|
| `tcache_key_initialize` | 3140–3151 | **writes** it: `__getrandom_nocancel_nostatus(&tcache_key, sizeof, GRND_NONBLOCK)`; if that is not exactly 8 bytes, two `random_bits()` stores combine into it |
| `tcache_put` | 3157–3167 | **reads** it: `e->key = tcache_key;` into the chunk being freed (inlined at four call sites: 3958, 4015, 4143, 4549) |
| `tcache_get_n` | 3174–3191 | **clears** the field on allocation: `e->key = 0;` |
| `_int_free` | 4525–4552 | **compares** it: `if (e->key == tcache_key) { walk the list; abort on membership }` |

That is the whole of the key's use. Two consequences the earlier documentation got wrong:

**Safe-linking does not use the key.** `malloc/malloc.c:329` defines
`PROTECT_PTR(pos, ptr) = ((pos >> 12) ^ ptr)` where `pos` is the address of the pointer field. The
masking factor is the ASLR-randomised heap address, not `tcache_key`. The binary confirms it: at
`libc+0xab73b` the tcache link is masked with `shr $0xc,%rax; xor %rax,%r15`, while the key is
loaded separately at `libc+0xab74a` and stored into the chunk's `key` field.

**The key does not affect heap layout.** It is not an input to any allocation decision: `tcache_put`
and `tcache_get_n` use counts and list heads, and `_int_free`'s comparison only decides whether to
*scan* a list. A fixed key therefore produces the same chunk sizes, the same order, the same
addresses.

What does change is the content of one word: `tcache_put` writes `tcache_key` into the freed
chunk's `key` field (`chunk + 0x10 + 8` on x86-64 — `next` is the first word of the user area,
`key` the second), and `tcache_get_n` zeroes it before the chunk is handed out. On the audited
build the kernel's eight bytes go straight into that field, so under the contract every freed tcache
chunk in the process holds the same public constant in that word.

### 2.1 Attribution in the two binaries

Symbols cannot establish this (the slot is a stripped static), so attribution is by *all uses of the
slot*. In both audited images, `0x20b178` — the destination the profile names — has exactly eight
static references:

| offset (8.12) | instruction | role |
|---|---|---|
| `0xa9e3b` | `lea 0x161336(%rip),%rdi` | initializer: syscall buffer |
| `0xa9e99` | `mov %r12,0x1612d8(%rip)` | initializer: clock fallback, low half |
| `0xa9eba` | `mov %r12,0x1612b7(%rip)` | initializer: clock fallback, high half |
| `0xab2a2` | `mov …,%r11; cmp %r11,0x18(%rsi)` | `_int_free`: the double-free comparison |
| `0xab408` | `mov …,%rdx; mov %rdx,0x18(%rsi)` | `tcache_put` (path 1) |
| `0xab74a` | `mov …,%r15` (stored later) | `tcache_put` (path 2) |
| `0xabe50` | `mov %r10,0x18(%rdx)` | `tcache_put` (path 3) |
| `0xabf50` | `mov %r14,0x18(%rcx)` | `tcache_put` (path 4) |

One write target plus two fallback stores, one comparison, four stores — the set the source
predicts, and nothing else. The same eight references, at the same shifted offsets, exist in 8.9.
A slot used for anything else (a seed feeding `malloc`'s choices, a layout input) would show uses
that are not in this set.

## 3. The 8.9 → 8.12 delta, re-checked at source level

Phase Z's report said "no malloc change" between the two builds. That was wrong in the small: the
8.12 source package carries one patch against `malloc/malloc.c`, `CVE-2026-0861.patch`
("memalign: reinstate alignment overflow check"). It changes `_int_memalign` only:

```c
-  if (nb == 0)
+  if (nb == 0 || alignment > PTRDIFF_MAX)
```

Nothing in the series mentions `tcache`, `tcache_key`, `_int_free`, `tcache_put`, or `getrandom`
(`grep -rl tcache_key debian/patches` returns nothing). So the audited function is unpatched
upstream code in both builds, which is what the instruction-identity result in
`docs/PHASE_Z_GLIBC_DIFF.md` shows independently. The −0x20 shift starts at `_IO_file_attach`, in
the libio fix, before malloc's text.

## 4. The contract as three claims

Phase Z's documents assert one thing ("the execution is reproducible under the contract") built on
several steps. Separating them makes the failure modes visible, and each is now independently
testable.

### Claim A — the new runtime has an audited equivalent entropy-initialization call site

*Statement.* In build `8cebda42…`, the `getrandom(8, GRND_NONBLOCK)` issued from libc writes into
`libc+0x20b178`, and the function issuing it is instruction-for-instruction identical to the one
audited in `a4a7992a…` once code addresses and RIP-relative displacements are normalised.

*Evidence.* `docs/PHASE_Z_GLIBC_DIFF.md` (sequence ratio 1.0, zero differences either side); the
derivation re-run on both real images prints the same buffer, length and flags
(`cargo test -p tracejit-effects -- --ignored audited_sites_match_a_reference_library`, run for
each `TRACEJIT_AUDIT_LIBC`); the eight-reference table in §2.1.

*Qualification.* This is equivalence of the *code that issues the call* and of the *slot it writes*.
It is not a proof that the surrounding allocator is inert: the allocator differs from 8.9 in
`_int_memalign` (§3), which the contract does not touch. The claim supports admitting the call site;
it says nothing about native equivalence.

### Claim B — the tracer substitutes the intended fixed value at that call site

*Statement.* For an admitted observation the tracer prevents the kernel from producing a value
(`orig_rax = u64::MAX` at the entry stop, so the kernel returns `ENOSYS`), writes
`ALLOCATOR_ENTROPY_VALUE` into the recorded buffer at the exit stop, and returns `length` as the
syscall result.

*Evidence.* `crates/tracejit-trace/src/linux.rs` (entry injection, exit substitution,
`write_process_bytes`), and the end-to-end tests: the double-free path shows glibc consumed eight
bytes and continued down the success branch; a failure to write aborts the trace rather than
proceeding.

*Qualification.* The tracer audits the library **file** (build ID, derived instruction bytes, whole
-file hash) and checks the *executing* `rip - base` and destination offset, but it does not read the
executing code bytes out of the process's memory. A runtime library replaced on disk after the
process mapped it would be audited as the file while a different mapping executes. Closing that
needs a `process_vm_readv` of the signature at `rip - 2`; it is recorded as a limitation (§7), not
claimed as covered.

### Claim C — replaying a recorded execution remains valid under the declared controlled contract

*Statement.* A cache hit restores the recorded outputs only after every guard passes, and the
runtime library is one of those guards, so a replay cannot silently use a different runtime.

*Evidence.* The guard checks contract id, request shape, build ID membership, recorded
site/destination, the derived site from the library file, the recorded value, and the whole-file
hash; `phase_z_tests.rs` breaks each of those one at a time. Stale records fail closed: a record
naming the 8.9 site is refused against an 8.12 file, because re-deriving from the file disagrees
before the hash is even consulted.

*Qualification.* Validity is *within the contract*: the outputs are the bytes that execution
produced under the same fixed key, not the bytes a native run would produce. §3.1 of
`docs/PHASE_Z_CONTRACT.md` now states the three excluded program classes (uninitialized/freed reads,
forged allocator metadata, programs that parse allocator internals). No claim of native equivalence
is made, and no report text says otherwise.

## 5. Security implications of a fixed `tcache_key`

| property | native | under the contract |
|---|---|---|
| double-free detection (same thread, chunk still in tcache) | aborts on list membership | **unchanged** — same abort, byte-identical message |
| double-free detection (chunk already reallocated) | heuristic misses | unchanged |
| tcache-poisoning resistance | key is per-process and unguessable | **weakened**: the key is a published constant, so a forged entry that satisfies the check is trivial for anyone with a heap write |
| cross-process linkability | key differs per process | all contract runs share one value; a leak applies everywhere |
| heap addresses, layout, allocation order | ASLR | unchanged |
| allocator diagnostics | glibc strings | unchanged (tested byte-for-byte) |
| uninitialized/freed memory content | varies per run | stable, contract-specific |

The weakening is conditional on an attacker already having a heap write primitive, and the contract
is opt-in, is never `PROVEN`, and is documented as unsuitable for untrusted programs. It is a
deliberate trade for reproducibility, and the report reason on every controlled run says so.

## 6. Implementation audit findings

| area | finding |
|---|---|
| build-ID verification | profile lookup is exact-string; unknown build refuses at both ends. Build ID is a claim carried by a file — a re-signed or re-patched file could carry the same ID. The record's whole-file hash is what pins content for replay (§7.2). |
| RIP-relative destination | computed from the `lea` displacement, not compared with a constant; `buffer_offset != profile.destination_offset` refuses. Both real images derive `0x20b178`. |
| syscall argument validation | request decoded from the *subject process's* registers must be `length == 8 && flags == GRND_NONBLOCK`; the library's encoded `mov $8,%esi` / `mov $1,%edx` are compared byte-exactly before the site is admitted. |
| instruction decoding | byte patterns, not a disassembler (§6.1). Exact `mov $318,%eax` adjacency, exact `syscall` + tail signature, exact `mov $1,%edx; mov $8,%esi; lea` order. |
| ambiguity | a second candidate `lea` in the 48-byte window returns `None`; the tracer then treats the call as ordinary entropy and the run becomes ineligible. Tested with a decoy that points at the *correct* destination (`a_decoy_buffer_load_in_the_window_is_refused_rather_than_chosen`). |
| ELF writable-segment validation | destination must lie in a `PF_W` `PT_LOAD` of the issuing library and be in a private writable mapping; `.bss` is mapped anonymously, so the ELF check is what decides. |
| tracer memory writes | `process_vm_writev`, falling back to chunked `ptrace::write`; any short write is an error, never a partial substitution. |
| return-value substitution | `rax = length` at the exit stop, after the bytes are in place. |
| guard reconstruction | re-reads the library file, re-derives the site, compares the recorded destination with the derived one, then compares the recorded file hash. |
| library replacement | covered by the hash guard; the record cannot be replayed against a different file. |
| multiple processes | the site audit runs per observation against `/proc/<pid>/maps`; each child's own mapping, base and destination are used. Four concurrent exec'd children are admitted and replayed correctly (`allocator_contract_handles_concurrent_initialization`). |
| multiple threads | per-thread state; thread creation without `CLONE_FILES` sharing is admitted, sharing is refused as before. The key is initialised once per process, so there is no cross-thread substitution race. |
| cache-record compatibility | no record field changed in this phase; a record is self-describing (contract, build ID, site, destination, hash, value), so old records are judged on their own contents. |
| old 8.9 profile | still admitted: synthetic-image tests cover both profiles, and the real 8.9 image re-derives `0x20b178` from its own bytes. A record from the old profile is refused against a new-build file. |

### 6.1 Why the byte scan is safe despite not being a disassembler

The window is the 48 bytes before `mov $318,%eax`. A match inside an immediate or data byte is
possible in principle. It cannot produce an unsafe admission, because admission requires *all* of:
the match count to be exactly one, the displacement to resolve to the profile's destination, the
neighbouring `mov $1,%edx; mov $8,%esi; lea` to be the immediately preceding 13 bytes in that
order, the exact `mov $318,%eax`, the exact `syscall` and tail signature, and the build ID to name
an audited profile. A decoy that also points at `0x20b178` makes the count two, which refuses.

## 7. Remaining limitations

1. **Executing bytes vs file bytes.** The tracer audits the library on disk. A file replaced after
   mapping (deleted or overwritten while the process runs) is audited as the new file while the old
   mapping executes. Requires an attacker who can rewrite a system library mid-run; recorded, not
   fixed.
2. **Build ID does not prove content.** A file can carry an audited build ID and differ elsewhere.
   At record time the driver would still admit it if the audited function is intact, and the record
   would then pin *that* file's hash. Replay can never switch to another file, and a modified
   audited function is refused, but the audit is not a signature check. Pinning canonical package
   digests would close it and is the recommended follow-up.
3. **Programs outside the guarantee.** Uninitialized/freed memory reads, forged allocator metadata,
   and programs that parse allocator internals (see `docs/PHASE_Z_CONTRACT.md` §3.1). Undetectable
   from outside.
4. **Fixed key weakens tcache poisoning resistance** inside the contract (§5).
5. **No `ccache`/`sccache` comparison**: neither is installable in this environment (no root, no
   package manager, no cmake), so no cross-tool number is claimed. `make` is measured with its real
   invocation count.

## 8. Adversarial outcomes

All run on this host, `gcc`/`cc` 13.3, glibc 8.12, `--contract allocator-entropy-v1`.

### 8.1 Allocator behaviour (new, `linux_integration`)

| case | result |
|---|---|
| double free, tcache enabled | native and contract stderr **byte-identical** (`free(): double free detected in tcache 2`), both exit 134 |
| double free, tcache disabled (`tcache_count=0`) | byte-identical (`double free or corruption (fasttop)`), both exit 134 |
| misaligned free (`free(p + 8)`) | byte-identical (`free(): invalid pointer`), both exit 134 |
| 64 allocations across 8 size classes, half freed, re-malloc'd, realloc'd, `calloc` zero-check | stdout identical to native; second run `Reused` |
| four `fork`+`exec` children initialising concurrently | `Guarded`, all four output files correct; replay `Reused` and restores all four |
| application `getrandom(1, 0)` from its own stack | `Nondeterministic`, not reused |
| **unaudited `.so` constructor issuing `getrandom(&k, 8, GRND_NONBLOCK)` into its own BSS** | **`Nondeterministic`** while the same `sed` without the preload is `Guarded` |
| record under `allocator-entropy-v1`, replay attempt under `compiler-runtime-v1` | not reused (contract is part of the identity) |

The diagnostic comparison is only meaningful because both sides used the same tunables: the
integration harness sets `glibc.malloc.tcache_count=0`, so the first version of this test compared a
tcache double free against a fastbin double free and reported a difference that had nothing to do
with the contract. The test now runs both paths explicitly.

### 8.2 Admission rule (host-independent, `phase_z_tests.rs`, 13 tests)

Admitted: synthetic images for **both** audited profiles. Refused: displaced buffer, displaced
syscall number (318→319), decoy buffer load pointing at the right destination, another build's
site, unknown build, foreign contract, wrong shape, destination the library does not encode, wrong
value, changed file, duplicate profile, and the "same build ID, different bytes" pair described in
§7.2 (stale record refused; record made from the new bytes admitted and pinned).

### 8.3 Differential and end-to-end

`phase_d.py --seed 29 --cases 120`: **0 incorrect hits**, 0 discover mismatches
(`benchmarks/results/phase_z1/fuzz-29/`).

## 9. Verified performance

Same host as Phase Z (2 vCPU EPYC 7003, kernel 6.1.102, glibc 8.12), same pinned corpus, release
build of this head. `benchmarks/results/phase_z1/`.

| measurement | native | TraceJIT | ratio |
|---|---|---|---|
| single `gcc -O2 -c` cold / warm (median of 5) | 103.3 ms | **47.8 ms** (47.5–55.9) | 2.16× on a hit |
| 27-invocation session (3 units, 220 functions, edits at rounds 3,6) | 14.508 s | **7.920 s** | **1.83×** |
| 48-invocation session (edits at 7,12) | 25.835 s | **9.164 s** | **2.82×** |
| 27-invocation cold round (3 compiles, first trace) | 1.575 s | 2.256 s | 0.70× (tracing premium) |
| 48-invocation cold round | 1.653 s | 2.177 s | 0.76× |
| `make` on the same schedules | — | 4.975 s / 4.897 s with 9 compiles | skips work rather than caching |

Every arm's final objects are byte-identical to a native build of the final sources. Decisions:
3 executed (first trace), 18 / 39 reused, 6 deoptimised (one per unit per edit, guard failure on
the edited header). Per-compile inside a hit round: 76.1 ms / 63.4 ms against 536 / 537 ms native.

Cold-start cost is real and is reported rather than hidden: the first round of a session is slower
than direct compilation because it pays for tracing, and it only repays when later invocations
repeat.

## 10. Commits and CI

| item | value |
|---|---|
| PR | [#42](https://github.com/Satwik-P28/tracejit/pull/42) (`research/phase-z` → `main`) |
| Phase Z production change | `7f013a5` |
| Phase Z evidence | `87c175c` |
| Phase Z1 (this audit) | see `git log` on the branch; the doc is committed with the code it describes |
| CI on the Phase Z1 head | recorded in `PROJECT_STATE.md` and in the PR |

## 11. Reproduce

```bash
# Source-level audit (read only)
curl -sSLO https://ftp.gnu.org/gnu/libc/glibc-2.39.tar.xz && tar xf glibc-2.39.tar.xz
grep -n tcache_key glibc-2.39/malloc/malloc.c          # 3 sites + declaration
sed -n '320,335p;4520,4555p' glibc-2.39/malloc/malloc.c # PROTECT_PTR, double-free check

# Every use of the audited slot in each binary
objdump -d --no-show-raw-insn /usr/lib/x86_64-linux-gnu/libc.so.6 | grep 20b178

# Admission
cargo test -p tracejit-guards --lib phase_z
TRACEJIT_AUDIT_LIBC=/path/to/libc.so.6 \
  cargo test -p tracejit-effects -- --ignored audited_sites_match_a_reference_library --nocapture

# Allocator behaviour end to end
cargo test -p tracejit-cli --test linux_integration allocator -- --nocapture --test-threads=1

# Performance
python3 benchmarks/phase_z/harness.py session --invocations 48 --scenario edits --edit-rounds 7,12 \
  --json benchmarks/results/phase_z1/session-48.json
```

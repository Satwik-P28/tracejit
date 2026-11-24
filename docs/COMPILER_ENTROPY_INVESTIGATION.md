# Compiler entropy investigation: why gcc reuse is intermittent

Phase AA1 measured that nominally identical `gcc -c` invocations are classified
`Guarded` about 94–98 % of the time and refused the rest. This document
establishes the mechanism, the probability, the destination of the random bytes,
and why no contract admits them.

Evidence: `benchmarks/results/phaseab/entropy_*.json`,
`entropy_predict.json`; harnesses `benchmarks/phase_ab/entropy_probe.py`,
`entropy_study.py`, `entropy_predict.py`.

## 0. Verdict

The refusal is **not** a harness artefact, **not** a tracer defect, and **not**
the glibc allocator seed that Phase AA1 assumed. It is glibc's temporary-name
generator:

```
gcc driver (make_temp_file) -> libc mkstemps -> __gen_tempname
    -> clock_gettime(CLOCK_MONOTONIC) + stack word -> rejection sample
    -> getrandom(stack_buffer, 8, GRND_NONBLOCK)     [~4.45 % of calls]
```

The bytes become six characters of a **temporary file name** (`/tmp/ccXXXXXX.s`).
That is application-visible entropy, so refusal is correct and was retained. The
instability is a property of the program, not of TraceJIT's classification.

## 1. Provenance

Native execution under `strace -f -k`, no TraceJIT in the loop, 30 trials of
`gcc -cc-small-tu` (a 400-function translation unit with six generated headers):

* every trial contains exactly three `getrandom` calls at libc offset `0xa9e69`,
  reached from `malloc+0x215` — the audited glibc tcache seed, in the driver,
  `cc1` and `as`;
* a fourth call appears in a minority of trials. It is issued by the **driver**.
  The three tcache destinations all end in `b178` — the audited `tcache_key` at
  libc offset `0x20b178` — while the fourth call's destination is a **stack
  address** (`0x7ff…`), which is what makes it a different effect;
* its stack trace is `libc getrandom+0x14 ← libc+0x66b4e ← gcc+0x43d334`, and
  `gcc+0x43d334` is the return address of `call mkstemps@plt`.

The symbol `tempnam` that `strace` prints is a nearest-symbol guess: `tempnam`'s
declared size ends at `0x6668c`, so `0x66b4e` belongs to an unnamed internal
function. Disassembling that range shows the exact sequence the call comes from:

```
66b3b: lea    -0x58(%rbp),%rdi     ; stack buffer
66b3f: mov    $0x1,%edx            ; GRND_NONBLOCK
66b44: mov    $0x8,%esi            ; 8 bytes
66b49: call   getrandom
66b4e: cmp    $0x8,%rax
```

and the branch that reaches it:

```
66afe: xor    -0x48(%rbp),%r13     ; stack word xor clock-derived value
66b10: mov    $0xb504f32d,%eax
66b15: add    %rax,%r13
66b2c: mov    $0x1,%r9d            ; "can use getrandom"
66b32: cmp    %r13,%rax            ; rax = 0xf49998db0aa753ff
66b35: jae    66aa4                ; below the threshold: no syscall
```

`0xf49998db0aa753ff` is a rejection-sampling bound for the modulo-31 conversion
of the value into filename characters.

```
P(draw >= bound) = (2**64 - 0xf49998db0aa753ff) / 2**64 = 0.04453
```

That is the measured rate, and it explains the intermittency exactly: the draw is
a function of a monotonic-clock reading and an uninitialised stack word, so it is
not reproducible between processes.

## 2. Presence and refusal are the same event

`entropy_study.py` interleaves two counters over the same workload and machine:
presence (the command runs natively under `strace`, no TraceJIT in the loop) and
classification (TraceJIT cold traces with the compiler contract). 1,000 trials
each, `gcc-cc-small-tu`:

| Counter | Measurement |
| --- | --- |
| Runs containing `getrandom` at all | 1000/1000 (three tcache seeds) |
| Runs with an *extra stack-destination* call (native) | 29/1000 = 2.9 % (26 runs ×1, 3 ×2) |
| TraceJIT cold traces refused (`Nondeterministic`) | **57/1000 = 5.7 %** (95 % CI 4.3–7.1 %) |
| Read effects in refused runs | 305 (55 runs) or 306 (2 runs); accepted runs are exactly 304 |
| Processes per run | 3 in every trial |

Every refusal carries exactly as many extra unabsorbed reads as there were
draws, which is the fingerprint of this single mechanism rather than a family of
intermittent defects.

The two rates differ for a reason worth stating: under the compiler contract
TraceJIT *supplies* `clock_gettime(CLOCK_MONOTONIC)`, so the value that is
rejection-sampled against `0xf49998db0aa753ff` is a function of the
uninitialised stack word alone instead of clock-plus-stack. The result is still
pseudo-uniform across processes, and the measured contract rate is 5.7 %, not the
4.45 % of the unmodified glibc draw. **The number to use for a TraceJIT build is
the measured contract rate (5.7 %).** The 1.3-point gap is not a defect and not
evidence of a second mechanism; it is the contract changing one input of the
sample.

## 3. Why refusal is correct

The value's destination is not a private runtime table. It is written to a stack
buffer, converted to characters and used as a pathname. Therefore:

* the name is a real filesystem effect outside the workspace (`/tmp/ccXXXXXX.s`);
* the name can reach `stderr` (assembler errors reference their input file);
* with `-save-temps` the temporary is a retained output, not a transient;
* nothing in the trace proves the name is unreachable from covered observations.

The allocator-entropy contract admits a `getrandom(8, GRND_NONBLOCK)` only when
the instruction pointer and the destination both lie in the *same audited shared
library*, the destination is the library's own `.bss` key at the profiled offset,
and the instruction bytes re-derive that destination. The temp-name draw fails
every one of those conditions: its destination is a stack address, its caller is
glibc code invoked by the *application*, and the value is not confined to a hash
seed. Extending the contract to it would be exactly the "treat getrandom as
ignorable" change the safety model forbids.

**Decision: strict refusal retained. No admission change.**

## 4. Safe remedies evaluated

### A. Preserve refusal, quantify and predict — adopted

No product change. The refusal probability is now known (4.45 % per temp-name
call), the build-level consequence is computable, and a static predictor exists.

`entropy_predict.py` reads only the ELF dynamic symbol table:

| Executable | temp-name import | entropy import | Predicted |
| --- | --- | --- | --- |
| `/usr/bin/gcc-13` | `mkstemps` | `getentropy` | 4.45 % per invocation |
| `/usr/bin/readelf` | — | — | 0 % |
| `/usr/bin/python3` | — | `getrandom` | refused whenever that path runs |
| `/usr/libexec/…/cc1` | — | — | 0 % |

The predictor is an estimate, not an admission rule: static linking, a direct
`syscall(318, …)`, a plugin, or another library are invisible to it. Its purpose
is a deterministic pre-build statement ("this build will probably lose N traces
to a temp-name draw") instead of a mysterious mid-build refusal.

For a 32-translation-unit build (`benchmarks/phase_ab/build_integrity.py`) the
contract-rate model predicts `1 - (1 - 0.057)**32 = 84.7 %` of builds losing at
least one trace. The measured Lua builds lost 1 of 32 and 1 of 32 invocations on
their first full compile (3.1 % in each) and recovered to 32/32, 31/32 and 31/32
on later full recompiles. A refused invocation is not fatal: the command runs
natively, and the next invocation of the same command has a 94.3 % chance of
recording. Two of 96 first-compile invocations is at the low end of a 5.7 %
process (p ≈ 0.12 under a binomial model), which is expected for three builds and
is reported rather than smoothed away.

### B. Narrow audited compiler contract — rejected

To admit the draw, a contract must justify replacement semantics for a value that
becomes a pathname. That requires proving the name is absent from stdout,
stderr, every restored file, and every retained temporary — for every compiler
version, flag set and error path. It cannot be proved from the recorded trace,
and a byte-for-byte agreement over a sample is not a proof. Additionally, the
draw happens *before* anyone knows whether the compile will succeed, so a
"successful compiles only" argument is unavailable at admission time.

Rejected. `tests` now pin the boundary: `application_stack_entropy_is_never_admitted_by_a_contract`
asserts that the exact admitted request shape issued from application code into a
stack buffer stays `Nondeterministic` under both contracts.

### C. Preflight eligibility assessment — adopted as an estimate

Implemented as the static predictor above. It is useful for explaining a build,
not for changing a decision, and its blind spots are documented in its output.

### D. Remove the temp file (`gcc -pipe`) — measured, rejected

`-pipe` removes the `.s` temporary, so `mkstemps` is not called. It produces a
byte-identical object (verified: `sha256` equal for the small TU), so it looks
like a clean workaround. **It does not work**: with `-pipe`, `cc1` and `as`
exchange data over a pipe, `fstat` on that pipe reports buffered byte counts that
depend on scheduling, and TraceJIT classifies the execution `Unknown`:

```
unmodeled successful syscall 5: fstat on pipe descriptor 1 reports buffered byte
counts, which depend on scheduling
```

Measured: 100/100 refused with `-pipe`, versus 8/100 without it. The workaround is
worse than the problem. (This is also a useful independent confirmation that the
classifier refuses scheduling-dependent observations rather than luck.)

## 5. Adversarial validation

| Case | Result |
| --- | --- |
| Randomness reaching object bytes | refused (`getrandom` fixture, `urandom`) |
| Randomised temporary filenames | refused (`tempfile_creation`: `getrandom` + `mkstemp`) |
| Application stack-buffer `getrandom(8, GRND_NONBLOCK)` under both contracts | refused — new regression |
| Direct `getrandom` import in a tool (`python3`) | refused |
| Multiple compilation processes | refused at the drawing process only; the others stay guardable |
| Failed entropy syscall (`GRND_NONBLOCK` short read) | the fallback path is also entropy; refused |
| Library replacement / unaudited build | refused (Phase Z profile lookup + build-id) |
| Modified compiler / plugin | not admitted; the destination test is per-library and per-offset |
| Interrupted tracing | no record is stored; the next run is a cold trace |
| Records from earlier versions | deserialize strictly; no contract is inferred |

## 6. What this does not explain

* Why the *driver* draws 0.5–3 ms after start is a scheduling question, not an
  admission one; no claim is made about which allocation size triggers obstack
  growth.
* The stack word that mixes into the draw is uninitialised memory at `-0x48(%rbp)`;
  its value is not controllable, which is exactly why the draw is not reproducible.
* Other toolchains were not probed. The mechanism is glibc's, so any program that
  calls `mkstemps`/`mkstemp` on this glibc build can draw, and every one of them
  will be refused whenever it does.

## 7. Consequence for measurement

A benchmark row must treat a classification refusal as an expected outcome, not a
lost sample: Phase AA1 already records refused timing attempts and retries once.
This phase adds the measured rate and the predictor so a refusal can be reported
as "expected 4.45 % per compiler invocation" instead of "the harness is flaky".

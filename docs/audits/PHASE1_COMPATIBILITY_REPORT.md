# Phase 1 real-world compatibility report

What TraceJIT V1 actually does on recognizable developer workloads, measured on
one Linux x86_64 host. Nothing here is tuned: the tracer was not changed to make
a workload pass, and every refusal is reported rather than excluded.

## Headline

**0 of 9 workloads were reusable. All 9 were refused.** No execution failed, and
after the executor fix described below, output equivalence passed for all 9 — so
every refusal is TraceJIT's conservative classification, not a broken workload.

That is the honest Phase 1 compatibility state: on this host, V1 has no
real-world reuse to demonstrate. The value of this section is the ranked list of
*why*, measured rather than guessed.

## Method

- Harness: `benchmarks/realworld/census.py` (`--runs 5 --warmups 1`).
- Binary: `target/release/tracejit`, built from the worktree at commit
  `6358522e2eee7b8aa7f59acca88e061f72166d8e` **plus** the uncommitted Phase 1
  fixes in this branch (the working tree was dirty; `census.json` records
  `working_tree_dirty: true`). The binary used for the census contained the
  `argv[0]` fix (reliability audit D6).
- Per workload: run the command directly, then under TraceJIT with a fresh cache
  per sample, then compare exit status, stdout, stderr and the SHA-256 of every
  declared output.
- Workloads execute in a scratch directory outside the repository.
- `GLIBC_TUNABLES=glibc.malloc.tcache_count=0` and `MALLOC_ARENA_MAX=1` are set so
  glibc does not draw allocator entropy or query CPU count; that is workload
  environment, not a classifier exception.
- A tool that is absent, or present but lacking a required capability, is
  recorded as `blocked_missing_tool` and excluded from the rate. None were
  blocked this run: 9 requested, 9 attempted.

Denominator, stated explicitly: **attempted = every requested workload whose
required tools were present and whose direct execution succeeded**. Eligibility
rate = reused / attempted = **0.000**.

## Workload results

Timings are medians of 5 measured runs after 1 warmup, on a 2 vCPU VM; they are
noisy at the millisecond scale and are reported for scale only. "Cold" is a
traced run with an empty cache.

| Workload | Class | Command (short form) | Direct | Traced cold | TraceJIT class | Deps | Outputs | Reuse | Equivalence |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| `cc-compile-fixture` | compiler | `cc -O2 -Wall -Wextra -c tests/fixtures/fixture_driver.c -o …/fixture.o` | 119.184 ms | 412.469 ms | `UNKNOWN` | 1230 | 2 | no | PASS |
| `cc-compile-large` | compiler | `cc -O2 -Wall -Wextra -c …/source.c -o …/source.o` | 46.000 ms | 125.930 ms | `UNKNOWN` | 237 | 2 | no | PASS |
| `shell-pipeline` | shell | `sh -c "awk … \| sort \| uniq -c \| awk …"` | 3.727 ms | 38.768 ms | `UNKNOWN` | 81 | 1 | no | PASS |
| `python-csv-json` | python | `python3 …/etl.py …/sales.csv …/customers.csv …/report.json` | 27.627 ms | 108.364 ms | `NONDETERMINISTIC` | 175 | 1 | no | PASS |
| `python-csv-json-seeded` | python | same with `PYTHONHASHSEED=0` | 27.482 ms | 110.550 ms | `NONDETERMINISTIC` | 175 | 1 | no | PASS |
| `awk-codegen` | codegen | `sh -c "awk -f …/codegen.awk …/schema.tsv > …/generated.h"` | 2.001 ms | 19.634 ms | `NONDETERMINISTIC` | 32 | 1 | no | PASS |
| `groff-manpage-html` | documentation | `sh -c "groff -Tutf8 -man …/census.1 > …/census.out"` | 15.188 ms | 57.617 ms | `UNKNOWN` | 115 | 1 | no | PASS |
| `pil-image-transform` | image | `python3 …/image_transform.py …/source.png …/transformed.png` | 68.210 ms | 253.096 ms | `UNKNOWN` | 410 | 1 | no | PASS |
| `cc-syntax-only-lint` | lint | `cc -fsyntax-only -Wall -Wextra -Werror tests/fixtures/fixture_driver.c` | 35.418 ms | 306.155 ms | `UNKNOWN` | 1137 | 0 | no | PASS |

Two conventions in that table matter:

- `groff` is run with `-Tutf8`, not `-Thtml`: this host's `groff` is installed
  without the `html` device (`groff: fatal error: cannot load 'DESC' description
  file for device 'html'`). The harness probes `html`, then `utf8`, then `ascii`,
  and records `blocked_missing_tool` if no device works. That is a host
  limitation, not a TraceJIT refusal.
- `cc-syntax-only-lint` reports 0 restorable outputs because `cc` writes to
  `/dev/null`, which the tracer refuses to treat as an output file (see C8).

### The pre-fix result that mattered most

`pil-image-transform` did **not** produce a valid comparison before reliability
audit D6 was fixed:

| | exit | stdout | output hash | writes | outputs |
| --- | ---: | --- | --- | ---: | ---: |
| direct | 0 | destination path | `9051d93b033ab24a…` | n/a | n/a |
| traced, pre-fix | 1 | empty | absent | 0 | 0 |
| traced, post-fix | 0 | destination path | `9051d93b033ab24a…` | 2 | 1 |

`resolve_executable` canonicalized the interpreter symlink and rewrote `argv[0]`,
so the traced process ran from a different installation (`sys.prefix=/usr`)
without Pillow in its module search path. This is a compatibility result *and* a
correctness defect; it is written up as D6 in
[PHASE1_RELIABILITY_AUDIT.md](PHASE1_RELIABILITY_AUDIT.md). The equivalence
check caught it because the harness fails loudly on a mismatch.

## Ranked blockers

Ranked by *utility* — how much useful developer work each pattern unblocks —
rather than raw frequency alone. Frequencies come from `census.json`
(`reason_counts` per workload) and are printed with the ranking.

| Rank | Blocker | Workloads | Raw occurrences | Why it ranks here |
| ---: | --- | ---: | ---: | --- |
| 1 | Interpreter/runtime startup non-determinism: `getrandom`, `clock_gettime` (monotonic + realtime), `getpid`/`getppid`/`gettid` | 3 | 12 | Blocks **every** CPython, `awk`, and `sh` command regardless of what it computes. Test runners, linters, code generators, build scripts and any Makefile recipe live behind this. Highest utility, hardest to make sound — these reads are genuinely non-deterministic. |
| 2 | Unguardable successful `access()` checks (`faccessat2` 439 plus the access-check refusal) | 4 | 28 | Blocks the entire compiler class (`cc -c`, `cc -fsyntax-only`), which is core to a build-cache use case. |
| 3 | `pipe2` (293) | 5 | 5 | Blocks every shell pipeline, and compilers use pipes internally to drive `cc1`. Modeling it needs an IPC soundness argument, not just a table entry. |
| 4 | I/O on an unclassified descriptor (`read from unclassified fd 3`) | 4 | 8 | Same class as the pipes above: the fd is real and the read is observable, but its provenance is not tracked. |
| 5 | `epoll_create1` (291) | 1 | 1 | The **sole** blocker for the Pillow workload. CPython imports `selectors` at startup, so this refusal attaches to most Python programs that touch sockets or subprocess pipes — i.e. most real ones. |
| 6 | `fstat` (5) | 1 | 2 | A legacy `stat` variant. Cheap to map onto the metadata dependency the tracer already records for other stat calls. Likely to appear in much more than `groff`. |
| 7 | Non-file output (`/dev/null`) | 1 | 1 | `cc -fsyntax-only` and many compiler/lint invocations write to `/dev/null`. Always empty on read, so it is discardable rather than unsafe. |
| 8 | Failed descriptor operation (`close(-1)` with `EBADF`) | 1 | 1 | Has no observable effect at all; it blocks the shell pipeline as a second reason. Cheapest sound fix on this list. |
| 9 | `getrusage` (98) | 2 | 2 | Compiler runtimes read their own resource usage. Note this is *scheduling-dependent*, so it must stay `NONDETERMINISTIC`; modeling it improves the accuracy of the refusal reason, not eligibility. |

Summary of the two dimensions for the same run:

- Blocking *categories* by number of workloads: unguardable `access()` 4,
  unclassified descriptor 4, clock 3, process identity 3, randomness 3, failed
  fd operation 1, unrestorable output 1.
- Unmodeled syscalls by number of workloads: `pipe2` 5, `faccessat2` 3,
  `getrusage` 2, `epoll_create1` 1, `fstat` 1.

## Per-workload refusal detail

Every refusal, in TraceJIT's own words (counts are occurrences):

- **`cc-compile-fixture`** — 8 × `successful access check cannot be guarded
  exactly`, 2 × `read from unclassified fd`, 2 × unmodeled `pipe2`,
  1 × unmodeled `faccessat2`, 1 × unmodeled `getrusage`.
- **`cc-compile-large`** — identical reason multiset.
- **`shell-pipeline`** — 3 × unmodeled `pipe2`, 1 × `failed fd operation on -1 is
  not modeled (errno 9)`.
- **`python-csv-json`** — 2 × clock read (monotonic, realtime), 1 × process
  identity, 1 × randomness. Setting `PYTHONHASHSEED=0`
  (`python-csv-json-seeded`) changed nothing: the remaining `getrandom` is glibc
  and interpreter startup entropy, and `gettid` still runs while the interpreter
  binds its main thread.
- **`awk-codegen`** — 1 × clock, 2 × process identity, 1 × randomness, all from
  `sh`/`awk` startup.
- **`groff-manpage-html`** — 3 × `read from unclassified fd`, 2 × unmodeled
  `fstat`, 1 × unmodeled `pipe2`, 1 × `successful access check cannot be guarded
  exactly`.
- **`pil-image-transform`** — 1 × unmodeled `epoll_create1`, nothing else. With
  the D6 fix this workload is one syscall away from being classifiable.
- **`cc-syntax-only-lint`** — 11 × `successful access check cannot be guarded
  exactly`, 1 × `non-file output cannot be restored: /dev/null`, 1 ×
  unclassified descriptor, 1 × unmodeled `pipe2`, 1 × unmodeled `faccessat2`.

## Interpretation

1. **The refusals are conservative, not wrong.** Every reason recorded is a real
   observable that V1 cannot yet guard exactly. None of them is a whitelist
   candidate: `getrandom`, clocks and process identity are genuinely
   non-deterministic, and `access()` is a real dependency.
2. **The compile/build story needs exact `access()` guarding and pipe modeling,**
   not tolerance for unmodeled syscalls. `faccessat2` appears in every compiler
   workload, and the access-check refusal accounts for 28 of the 41 recorded
   refusal occurrences.
3. **The interpreter story is the largest class and cannot be solved by
   whitelisting.** Anything that starts CPython, `awk` or `sh` currently pays a
   refusal that has nothing to do with the user's computation. Sound progress
   here means either proving that a specific entropy read does not reach the
   output, or pinning the runtime's entropy sources with an explicit, guarded
   determinism profile — a research question, not a table entry.
4. **Two of the blockers are nearly free to fix soundly** (`close(-1)` returning
   `EBADF`, and `/dev/null` as a discardable write). They are small, but they are
   also the ones with no safety argument to make.
5. **V1's honest position today: `PROVEN`-class reuse for whole commands is
   demonstrable only on the synthetic C workloads,** where the tracer was
   designed to succeed. Real developer toolchains are out of reach until at
   least ranks 1–3 are addressed.

## Reproducing

```bash
cargo build --workspace --release
python3 benchmarks/realworld/census.py --runs 5 --warmups 1 \
  --output-dir benchmarks/results/phase1
```

`benchmarks/results/phase1/census.json` holds every per-workload record,
including the exact command, the raw per-sample timings in nanoseconds, the
refusal reasons, and the observation hashes. `census.md` is the human-readable
form. The harness exits non-zero when a workload fails, an unexpected result
appears, or an output-equivalence check fails.

## Limitations of this census

- One host, one kernel, 2 vCPUs, no Landlock (audit host limitation), 5 measured
  runs per workload. Timing medians are indicative, not precise.
- Classification reasons are reported as TraceJIT emits them; where a workload
  has several independent reasons the list order is not a priority ranking.
- `cc` is GCC on this host; Clang, `pandoc`, ImageMagick, `m4`, `bison`, `flex`,
  `cppcheck` and `shellcheck` are not installed, so those variants were not
  exercised. This is recorded as missing tooling, not as compatibility.
- The census measures classification and eligibility. It does not attempt to
  prove that a *refused* workload would have been unsafe to reuse; the refusals
  are TraceJIT's, and V1's rule is to refuse.

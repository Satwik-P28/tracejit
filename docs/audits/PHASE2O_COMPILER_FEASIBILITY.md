# Phase 2O: compiler reuse feasibility and competitive performance

Base `89f5d56`. Host Ubuntu 24.04, Linux 6.1.102, 8 vCPU, GCC 13.3.0, binutils 2.42.
Binary under test: `target/release/tracejit`, SHA-256 `b72a0242d08c30288395b3e570d7ba67a75bfbc7ba66d48c5f642933c57dfd5e`. ccache 4.10.2 and sccache
0.8.2 were installed as static release binaries into `~/.local/bin` (no root available).

## 1. Correctness and CI status

Local gate: `cargo fmt --all -- --check`, Clippy `-D warnings`, and `cargo test --workspace`
(114 tests, including the new compiler-runtime guard test) pass. `tracejit doctor` still reports
`landlock no`, `proven no`; `PROVEN` stays blocked and the enforcement paths are untouched.
The Phase 2N differential fuzzer, ptrace, filesystem and descriptor suites are unchanged.

**CI is BLOCKED, not green.** The branch is not pushed (no authorization), so the only run is
[42319563118](https://github.com/Satwik-P28/tracejit/actions/runs/42319563118) at `c7f2c68`.

## 2. Competitive baseline (six real zlib 1.3.1 translation units)

Every arm compiles the same file, flags, output path and include tree. Warm arms repeat the
identical command five times; medians. Session 1 shown; session 2 (reversed order) agrees within
noise. Raw data in `benchmarks/results/phase2o/compiler-baseline.json`.

| File | native | ccache warm | sccache warm | TraceJIT cold | TraceJIT repeat |
| --- | --- | --- | --- | --- | --- |
| compress.c | 35.7 | 3.6 | 7.6 | 208.9 | 247.6 (Executed) |
| adler32.c | 77.8 | 3.9 | 7.5 | 273.6 | 320.3 (Executed) |
| crc32.c | 114.8 | 4.3 | 9.7 | 376.8 | 380.9 (Executed) |
| trees.c | 250.9 | 4.2 | 8.3 | 478.6 | 497.3 (Executed) |
| inflate.c | 400.8 | 4.5 | 8.3 | 660.1 | 687.4 (Executed) |
| deflate.c | 413.7 | 3.9 | 7.3 | 644.2 | 665.4 (Executed) |

All arms: **byte-identical objects** (`artifact_match: true`, 24/24).
Cold TraceJIT costs 173-259 ms over native (1.6x for the largest translation unit, 5.9x for the
smallest). This harness did **not** reproduce reuse: every repeat executed, so its repeat column is
an execution cost, not a hit cost. The separate verification scenario below did reuse.

## 3. Complete compiler effect map

`strace -f` attribution plus `tracejit analyze --json` for `gcc -O2 -I. -c deflate.c`:

| Effect | Where | Count | Character |
| --- | --- | --- | --- |
| `getrusage(RUSAGE_SELF)` | `as` | 1 | variable every run (utime); drives `--stats` only |
| `getrandom(8, GRND_NONBLOCK)` | gcc, cc1, as | 1 each | variable; glibc allocator probe at an audited site |
| `sysinfo` | cc1 | 3 | variable (freeram/loads); feeds GGC heap heuristics |
| `prlimit64` | gcc/cc1/as | 3/6/2 | stable inherited limits: STACK, AS, RSS, NOFILE |
| clock reads | gcc/cc1 | vDSO | realtime/monotonic; invisible natively, redirected to syscalls by tracing |
| temp file | gcc | 1 | `/tmp/ccXXXXXX.s`, random name, deleted after `as` |
| outputs | as | 1 | `.o`; natively byte-identical across runs |

No `getpid`/`getppid`/`gettid` in a compile. `fstat` on pipe descriptors is unmodelled and is why
`-pipe` is refused: pipe buffered-byte counts depend on scheduling.

## 4. Controlled-execution prototype

`--contract compiler-runtime-v1` (`tracejit.compiler-runtime.v1`), opt-in and part of the cache
identity. It fixes only the incidental observations above, for an exact audited toolchain:

- `getrusage(RUSAGE_SELF)` in `/usr/bin/x86_64-linux-gnu-as` (build `7fc854c8...`): zeros, 144 bytes.
- `sysinfo` in `/usr/libexec/gcc/x86_64-linux-gnu/13/cc1` (build `32e37dd7...`): fixed 16 GiB
  total, 8 GiB free, 112 bytes.
- monotonic/realtime clocks in gcc (`9ac130c8...`) and cc1: zero timespecs.
- the existing audited allocator probe (glibc build `a4a7992a...`, fixed site) stays the only
  `getrandom` answered; application buffers and other lengths remain nondeterministic.
- `prlimit64` queries and the driver's own stack-limit raise are process-local for audited
  binaries; the inherited limits are recorded in `RuntimeIdentity`.

Audit is by `/proc/<pid>/exe` path **and** GNU build ID, cached per trace. Anything else fails
closed: no control is applied, the effect stays ordinary, and the execution is refused. Guards
reject a wrong contract, an unaudited build, an observation the profile does not admit, a wrong
shape or value, and a changed binary. No syscall is globally whitelisted.

**Changed contract, stated plainly:** `as --stats` timings and `__DATE__`/`__TIME__` become fixed
epoch values; `sysinfo` changes GGC heuristics, not codegen. This is reproducible under the
contract, not equivalent to native execution. Native mode is unchanged.

Guard-layer work this required: dropping `FileMetadata` pre-state for paths the command writes
(otherwise the second run sees the object the first run created); recording directory metadata as
`DirectoryOpened` (identity and permissions, not timestamps, because the compile mutates its temp
and output directories); identifying allocator probes under the allocator contract ID; and
preventing a JSON reporting panic when a guard embeds an absent-fingerprint `i128::MIN` sentinel.

## 5. Adversarial correctness

Controlled verification scenario (fresh cache, output outside the source tree), `gcc -O2 -c`:

| Check | Result |
| --- | --- |
| cold then repeat | `Reused` for compress.c, adler32.c, trees.c; 235 to 68, 294 to 76, 506 to 81 ms |
| object equality | byte-identical to native in every arm |
| header edit | deoptimized, recompiled, artifact equals native |
| compiler flag change | different identity, executed |
| failed compilation | TraceJIT exit 1, native exit 1 |
| 4 concurrent cold compiles | all correct, no cache lock error |

**Limitation, reported as prominently as the positive result:** the benchmark harness (same output
path reused for six files, cache inside that directory) produced **no hits at all**, and an
in-tree source/header/output scenario failed to re-hit even after recompilation. The remaining
failure is a guard over a directory associated with the command's own output. Reuse is therefore
demonstrated, but not yet established as generally reproducible across build layouts.

## 6. Economics and go/no-go

Hit cost in the working scenario is 68-81 ms, dominated by hashing the three toolchain binaries
(~32 MB) plus CAS restore. ccache's hit is 3-5 ms, sccache's 7-10 ms. Cold tracing adds 173-259 ms.
Break-even needs two identical compilations; an edit-build loop invalidates on every edit, so
cumulative developer time saved is **approximately zero**, and even a perfect hit is 15-20x slower
than ccache.

**Decision: NO-GO for compiler acceleration as a shipped feature.** The architecture can reach
`GUARDED` on real `cc -c` and reuse it in controlled conditions, but it cannot compete with
specialist caches, and its guard model needs transient-path handling that this phase did not
finish. The contract remains experimental and opt-in; default behaviour, classifiers and `PROVEN`
gating are unchanged.

## 7. Alternative workload (Part G)

`gcc -E`, `gcc -S`, `as` and `gcc -c` were all measured; they share the same guard blockers, and
none was selected. The workload that does pay remains whole-command deterministic utilities
(Phase 2N: zlib `auto` 1.185x/1.198x). No new subsystem was invented to avoid the negative result.

## 8. Reproduce

```bash
cargo build --release --workspace
# competitor baselines (ccache/sccache on PATH, zlib 1.3.1 at /tmp/ccbench/zlib-1.3.1)
python3 benchmarks/repos/compiler_baseline.py benchmarks/results/phase2o/compiler-baseline.json
python3 benchmarks/repos/compiler_hits.py benchmarks/results/phase2o/compiler-hits.json
# controlled reuse: two invocations of the same command
TRACEJIT_CACHE=/tmp/tjc ./target/release/tracejit run --contract compiler-runtime-v1 --json -- \
  gcc -O2 -I/tmp/ccbench/zlib-1.3.1 -c /tmp/ccbench/zlib-1.3.1/compress.c -o /tmp/out.o
```

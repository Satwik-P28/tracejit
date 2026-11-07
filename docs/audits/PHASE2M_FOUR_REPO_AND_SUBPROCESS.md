# Phase 2M: four-repository matrix and the subprocess-wrapping experiment

Commit `f5a9486` (seccomp fix) is the measured implementation; release binary
`b0576fb19473ab15d5c0197b30f39934ab6ad86b86a976b403f2d33868250560`. Host: Linux 6.1.102, 8 vCPU,
glibc 2.39, gzip 1.12, make 4.3. Contract `tracejit.allocator-entropy.v1`, workload
`phase2k-v1`, three sessions (`a`, `b`, `c`), each with a pristine `git archive` per policy.

## Complete matrix

Totals are the whole developer session (configure/build/rebuild/edits/test plus the project's own
tool). Every policy produced every artifact correctly (`valid: true` in all 60 policy runs); the
following is therefore a performance result, not an availability result.

### Session A

| Repository | direct | never | auto-v1 | always | auto |
| --- | --- | --- | --- | --- | --- |
| zlib 51b7f2a | 2815.71 ms | 2755.34 (1.022x) | 2458.86 (1.145x) | 12060.42 (0.233x) | 2902.85 (0.970x) |
| bzip2 6a8690f | 3568.10 | 6203.68 (0.575x)\* | 4274.05 (0.835x) | 5344.77 (0.668x) | 3655.80 (0.976x) |
| libpng ed217e3 | 10402.78 | 10160.31 (1.024x) | 10208.25 (1.019x) | 37681.98 (0.276x) | 10443.41 (0.996x) |
| lz4 5ff8396 | 15647.19 | 17043.24 (0.918x) | 17293.59 (0.905x) | 21417.77 (0.731x) | 16676.54 (0.938x) |

### Session C

| Repository | direct | never | auto-v1 | always | auto |
| --- | --- | --- | --- | --- | --- |
| zlib | 2644.64 | 2944.33 (0.898x) | 2233.33 (1.184x) | 5684.55 (0.465x) | **2253.88 (1.173x)** |
| bzip2 | 3531.31 | 3717.29 (0.950x) | 3592.70 (0.983x) | 5178.01 (0.682x) | 3603.30 (0.980x) |
| libpng | 9514.86 | 9800.04 (0.971x) | 9704.39 (0.980x) | 31851.07 (0.299x) | 10306.42 (0.923x) |
| lz4 | 15820.40 | 15898.61 (0.995x) | 16206.78 (0.976x) | 20475.44 (0.773x) | 15828.69 (0.999x) |

`\*` Session A's bzip2 `never` arm is itself contaminated (see below), so its 0.575x is not a policy
cost.

### Session B (contaminated, retained deliberately)

| Repository | direct | never | auto-v1 | always | auto |
| --- | --- | --- | --- | --- | --- |
| zlib | 2770.45 | 2912.52 (0.951x) | 5408.71 (0.512x) | 10043.74 (0.276x) | 5809.79 (0.477x) |
| bzip2 | 3533.97 | 8117.47 (0.435x) | 3554.12 (0.994x) | 4951.49 (0.714x) | 3828.81 (0.923x) |
| libpng | 9617.70 | 10872.25 (0.885x) | 10113.86 (0.951x) | 38112.51 (0.252x) | 10999.99 (0.874x) |
| lz4 | 14976.54 | 18228.56 (0.822x) | 15617.37 (0.959x) | 20360.32 (0.736x) | 15830.71 (0.946x) |

Why B is labelled contaminated rather than reported: `never` performs no tracing and no caching, so
it must track `direct` within noise. In B's bzip2 arm the identical `build` phase took 3748.62 ms
versus 1274.61 ms for `direct`; in B's zlib arm the `test` phase took 165.30 ms versus 15.35 ms.
Both are external load on a shared 8-vCPU VM, and they inflate whatever policy shares the window.
Sessions A and C show no such inversion (`never` 0.898-1.024x) and are the primary result.

## What actually reused

| Repository | auto / auto-v1 decision | Reuse |
| --- | --- | --- |
| zlib | `./minigzip` and `./minigzip -d` → `Reused`/`Guarded`; `make -j1` → `Skipped`/`Unknown` | compression + decompression |
| bzip2 | `./bzip2 -9 -c` and `./bzip2 -d -c` → `Reused`/`Guarded`; `make -j1` → `Skipped` | compression + decompression |
| libpng | `./pngtest pngtest.png` → `Skipped`/`Unknown` under auto (7 ms command) | none under auto; `always` reuses it |
| lz4 | `./programs/lz4 -1/-d` → `Skipped`; under `always` `Ineligible`/`Nondeterministic` | none |

Refused commands: `make` and every `configure`/build recipe remain `Unknown`/`Nondeterministic`, so
no build step is cached in any policy. lz4 remains `NONDETERMINISTIC` (monotonic clock), and
`always` therefore pays a trace for nothing.

Cold tracing overhead (`always` − `direct`): session C zlib +3039.91 ms, bzip2 +1646.70 ms, libpng
+22336.21 ms, lz4 +4655.04 ms. First-run overhead of `auto` versus `direct` is mixed and small
relative to the build: zlib −390.76 ms (C) / +87.14 ms (A), bzip2 +72.0 / +87.7 ms, libpng
+791.56 / +40.63 ms, lz4 +8.29 / +1029.35 ms. Invalidation is driven by the edit phases; each
policy re-executes the affected steps and zlib's `./minigzip` records deoptimise on the
`relevant-edit` phase and become reusable again afterwards (the existing deopt/reuse tests cover the
mechanism).

**Result: zlib is the only repository where a policy beats direct, and the win is policy-sensitive: `auto-v1` is 1.145x in A and 1.184x in C, while `auto` is 0.970x in A and 1.173x in C.** bzip2
reuses both directions but nets 0.976-0.980x because its ~3 s build dominates. libpng's `auto`
is 0.92-1.00x because the only eligible command is 7 ms. lz4 cannot reuse at all. `always` is
0.23-0.77x everywhere except the small zlib session. These negatives are the finding, not an
accident of selection.

Limitations: 8 vCPU shared VM (session B demonstrates the noise ceiling); peak RSS still
unavailable (`/usr/bin/time` absent, no cgroup); `configure` for zlib/libpng is the project's own
script, not autoconf; the workload revision is unchanged from Phase 2K so the numbers are
comparable, but they are not a claim about any other host.

## Subprocess-wrapping experiment

Workload: a pristine zlib 1.3.1 tree plus five 2.39 MB deterministic data bundles, compressed by the
standard pattern rule `data/%.bin.gz: data/%.bin` running `$(COMPRESS) -n -9 -c < $< > $@`. `-n`
makes archives byte-comparable; without it gzip embeds each arm's own input mtime and the arms look
different for a reason unrelated to caching. No corpus project gzips per file through its own
Makefile (bzip2's `test` target compresses ~50 KB samples; libpng's `dist-gzip` is one gzip through a
pipe), so this is the real-world pattern applied to a real tree, which the workload record states.

Harness `benchmarks/repos/subprocess_wrap.py`, two sessions, each arm with a fresh cache:

| Arm | Session A | Session B | Artifacts | Exit status |
| --- | --- | --- | --- | --- |
| A native `make` | 685.53 ms | 674.83 ms | reference | 0 |
| B wrapped recipe child | **597.15 ms (1.148x)** | **574.41 ms (1.175x)** | equal | 0 |
| C whole-command `tracejit run -- make` | 797.41 ms (0.860x) | 801.43 ms (0.842x) | equal | 0 |
| D specialist cache | not applicable | not applicable | — | — |

D is not applicable: no installed cache serves gzip; ccache/sccache target compilers, which TraceJIT
refuses, so a specialist arm could not perform equivalent work. `ccache`/`sccache` are absent.

Checks:

- **Cache hits**: the first repeat is a trace (0 HIT), the second repeat is 5/5 `HIT`s in both
  sessions; the cached pass costs 52.16/40.02 ms against 226-232 ms native, i.e. 4.4-5.7x for that
  pass. Net saving is ~12 ms per child (`per_child_overhead_ms` −11.88/−12.42).
- **First-run overhead**: +30.37 ms (A) / +23.76 ms (B) for `auto`, which measures before tracing.
- **Artifacts**: all arms byte-identical after `-n`; the archive inventory is identical across arms.
- **Invalidation**: appending to `bundle-2.bin` changes exactly `bundle-2.bin.gz`; the next build
  re-executes that child (4 HIT, 1 MISS after the measurement SKIP), and the following build is
  4 HIT + 1 MISS again only because the mutated identity was re-traced once.
- **Environment**: a changed `TZ` produces five measurement `SKIP`s, never a stale hit.
- **Parallel**: `make -j4` with four concurrent wrapper processes completes with no `database is
  locked` error and 4 HITs + 1 measurement on the warm pass (125/140 ms), versus 245/226 ms for the
  whole-command arm.
- **Exit status / stderr**: wrapped `gzip` on a missing input returns the same status (1) as native
  and reproduces gzip's stderr verbatim; TraceJIT's own summary is additive.
- **Per-input probes**: a probe with a *different* stdout target was admitted for measurement
  (`Skipped`), so probes are not used as evidence; the in-build HIT counts are.

**Decision: weak-to-modest and not worth building transparent interception.** The mechanism works and
is sound for this shape, but the end-to-end gain is 1.15-1.18x in a workload where *every* child is
eligible and expensive by compression standards (~46 ms native, ~30 ms hit). A real build spends
almost all its time in refused `cc`/`make` children, where wrapping buys nothing and adds ~12-30 ms
per child. Transparent `execve` interception would add pipe, signal, shared-descriptor and
parallel-ordering hazards for a saving bounded by the eligible minority. The smallest sound next
step, if this is pursued, is an explicit `tracejit wrap` recipe helper that consults the existing
admission estimate and only wraps commands whose measured native runtime is well above the hit
floor (≳200 ms), with the existing guard contract unchanged; it is not implemented here.

## Release gate

Unchanged blockers, split by kind:

- **Correctness**: none new. The 14-workload fidelity matrix and the vfork/descriptor suites still
  pass. Subprocess reuse remains unbuilt, so its correctness surface is not applicable.
- **Environment**: `PROVEN` remains **BLOCKED** (`landlock no`, LSM `capability,selinux`); the CI
  `proven yes` gate cannot pass on this host and was not weakened.
- **Performance**: only zlib benefits reproducibly (1.17x); bzip2 is neutral-to-negative, libpng
  neutral, lz4 ineligible. Not a general accelerator.
- **Usability**: preview is not ready as a general tool. The CI rerun on the fixed commit requires an
  authorized push; that is the only outstanding verification item in this phase.

## Reproduce

```bash
cargo build --workspace --release
python3 benchmarks/repos/real_sessions.py --session a --repos zlib,bzip2 \
  --output-dir benchmarks/results/phase2m/sessions
python3 benchmarks/repos/real_sessions.py --session a --repos libpng,lz4 \
  --output-dir benchmarks/results/phase2m/sessions
python3 benchmarks/repos/subprocess_wrap.py --session a
```

Raw data: `benchmarks/results/phase2m/sessions/session-{a,b,c}.json`,
`benchmarks/results/phase2m/subprocess/session-{a,b}.json`.

# Non-compiler workloads: eligibility and economics

The frozen Phase AA corpus is compiler-heavy: of 59 workloads, 22 are compilers,
linkers, archivers or build systems. This phase asks whether TraceJIT has a
useful, *measured* niche outside that family, and answers with 16 authentic
configurations, real third-party programs, pinned inputs and repeated-invocation
sessions.

Headline: **yes, a narrow one.** Deterministic, expensive, repeat-generated
artifacts compressed with `bzip2`/`gzip` are reused correctly and save 65-85 % of
a 25-invocation session, breaking even at the second invocation. Tiny commands
(`readelf`, `sha256sum`, `base64`, `objcopy`, `strip`) are *dominated* by
TraceJIT's warm-hit floor and are reported as losses.

## 1. Prior art, and what is actually different

| System | Mechanism | Scope | Where TraceJIT differs |
|---|---|---|---|
| **Firebuild** | Intercepts libc (and qemu-user for static binaries), caches command outputs, replays when parameters/environment match; automatic command selection with shortcutting | General build accelerator; "any deterministic command" | TraceJIT *refuses* on observed nondeterminism and unmodelled effects, revalidates dependency guards at hit time, and treats "cannot prove" as no-reuse. Firebuild is broader and more mature; it is not installed here and **was not measured head-to-head** |
| **Rattle** | `fsatrace`-based dependency recording; forward build system with speculation; "assumes commands are deterministic" | Whole build scripts | TraceJIT keeps a per-command classification and refuses instead of assuming determinism; no speculation |
| **Bazel / remote action cache** | Explicit, declared action graph and inputs; content-addressed outputs | Builds described in BUILD files | No declaration needed: TraceJIT discovers inputs by observation. Bazel is sound by declaration, TraceJIT by classification |
| **Nix** | Pure derivations; inputs hashed into store paths | Package builds | Same: declaration versus discovery |
| **ccache / sccache** | Compiler wrappers; preprocessor output as key | Compilers only | Compiler-only, and the stale-archive semantics differ (see `OUTPUT_RESTORE_SEMANTICS.md`) |
| **Content-addressed data pipelines** | Explicit dataset/version keys | Data engineering stacks | Requires a pipeline framework and declared edges; TraceJIT works on an unmodified command line |

What is **not** claimed: syscall-based dependency discovery, whole-command
caching or memoisation are not novel. The contribution under test is *fail-closed
reuse* - refuse on `Unknown`/`Nondeterministic`, revalidate guards at hit time,
and never expose a partial result - applied to ordinary commands.

## 2. Corpus

`benchmarks/phase_ac/noncompiler.py` defines 16 configurations across five
families. Inputs are generated deterministically (a 256 KiB slice of the zlib
1.3.1 ChangeLog, a 2 MiB xorshift blob, 200k text lines, and a copy of a real
system binary); every command is a stock distro program. Each configuration is
run in a native twin and a traced twin, cold and warm, under three policies
(`native`, `allocator-entropy-v1`, `compiler-runtime-v1`), and compared with the
independent oracle.

## 3. Eligibility (measured)

`benchmarks/results/phaseac/noncompiler_probe.json`, 16 configurations x 3
policies:

| Configuration | Family | native | allocator-entropy-v1 | compiler-runtime-v1 | Warm reuse correct |
|---|---|---|---|---|---|
| gzip -9 -n -c text -> stdout | compression | `Guarded` | `Guarded` | `Guarded` | yes (even native) |
| gzip -9 -n -k -f 2 MiB blob | compression | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| bzip2 -9 -k -f 2 MiB blob | compression | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| objcopy --strip-unneeded | binutils | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| strip --strip-unneeded -o | binutils | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| objdump -d | binutils | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| readelf -h | binutils | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| nm --defined-only | binutils | `Nondeterministic` | `Guarded` | eligible, **no hit** | n/a |
| sed substitution, 200k lines | data | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| sha256sum of a binary | tooling | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| base64 of a binary | tooling | `Nondeterministic` | `Guarded` | `Guarded` | yes |
| xz -6 blob | compression | `Unknown` | `Unknown` | `Unknown` | refused |
| sort 200k lines | data | `Unknown` | `Unknown` | `Unknown` | refused |
| awk reduction | data | `Nondeterministic` | `Nondeterministic` | `Nondeterministic` | refused |
| perl reduction | data | `Nondeterministic` | `Nondeterministic` | `Nondeterministic` | refused |
| tar -cf | packaging | `Unknown` | `Unknown` | `Unknown` | refused |

10 of 16 configurations reuse correctly. Refusals are structural, not
timestamp-related: `xz`/`tar` query `fcntl` on inherited descriptors, `sort`
reads `sched_getaffinity`/`prlimit`, `awk`/`perl` read the clock and
`getrandom`, and none of those are made eligible by any contract.

The native refusals of the reusable commands are `getrandom` reads from the glibc
allocator's own key - exactly what `allocator-entropy-v1` exists for. That
contract is **not compiler-specific**: it names the allocator's `GRND_NONBLOCK`
probe and its fixed replacement value, which is why applying it to `gzip` is a
declared, auditable choice rather than a loophole. `gzip -n -c` reuses with no
contract at all.

## 4. Economics (measured)

`benchmarks/results/phaseac/noncompiler_session.json`. `direct` is the median of
five clean native invocations; `cold` is the first traced run; `hit` is the
median of five warm runs; break-even is the smallest `n` with
`n*direct > cold + (n-1)*hit`. Sessions are real repeated executions against
fresh caches, not extrapolations.

| Configuration | Policy | direct | cold | hit | break-even | n=3 | n=10 | n=25 | cache |
|---|---|---|---|---|---|---|---|---|---|
| bzip2 -9, 2 MiB | allocator-entropy-v1 | 214 ms | 310 ms | 20 ms | **1.5** | +48 % | +78 % | **+85 %** | 2.5 MB |
| gzip -9, 2 MiB | allocator-entropy-v1 | 62 ms | 101 ms | 19 ms | **1.9** | +22 % | +56 % | **+65 %** | 2.2 MB |
| sed, 200k lines | allocator-entropy-v1 | 78 ms | 246 ms | 25 ms | **4.1** | -29 % | +35 % | **+51 %** | 5.7 MB |
| gzip -9 -n -c, 256 KiB text | native (no contract) | 7.2 ms | 30 ms | 5.1 ms | **11.9** | -105 % | -7 % | **+37 %** | 0.1 MB |
| objcopy --strip-unneeded | allocator-entropy-v1 | 5.1 ms | 48 ms | 47 ms | none | -421 % | -293 % | -286 % | 1.3 MB |
| strip --strip-unneeded | allocator-entropy-v1 | 4.9 ms | 56 ms | 42 ms | none | -431 % | -367 % | -306 % | 1.3 MB |
| readelf -h | allocator-entropy-v1 | 1.8 ms | 34 ms | 33 ms | none | -1059 % | -691 % | -640 % | 0.2 MB |
| sha256sum | allocator-entropy-v1 | 3.5 ms | 39 ms | 14 ms | none | -588 % | -410 % | -369 % | 0.3 MB |
| base64 | allocator-entropy-v1 | 4.1 ms | 57 ms | 15 ms | none | -641 % | -318 % | -313 % | 1.7 MB |

Read across:

* **Winners** are commands whose native runtime is tens to hundreds of
  milliseconds: compression and large text transforms. Their warm hit is 5-20 ms
  of restore plus guard validation, so two invocations already repay the cold
  premium, and 25 invocations save most of the work.
* **Losers** are commands whose whole native runtime is a few milliseconds. The
  warm-hit floor (~15-50 ms here, dominated by process startup, guard validation
  over the executable and inputs, and restoring a multi-megabyte output) exceeds
  the work being avoided. Restoring a 1.3 MB stripped binary costs more than
  stripping it. These are reported as losses, not hidden: 5 of the 9 measured
  configurations lose at every session length.
* **Admission matters more than caching.** The `auto` admission policy exists to
  avoid this class of loss; these measurements were taken with `always` so the
  loss is visible rather than masked.
* Cache cost is 0.1-5.7 MB per configuration, roughly the size of the outputs
  plus one copy of the streams.

## 5. Refusals as results

Six of sixteen configurations refuse, and they are not near-misses:

* `xz -6` and `tar -cf` issue `fcntl(F_GETFD/F_GETFL)` on inherited descriptors
  0/1/2, which TraceJIT cannot guard. These are the two most obvious "expensive
  deterministic data tool" candidates, and neither is usable in V1.
* `sort` reads `sched_getaffinity` and `prlimit`, which makes its output depend on
  host configuration.
* `awk` and `perl` read the clock and `getrandom` during interpreter startup.

`nm` is `Guarded` but did not hit on its warm run; it is recorded as
`eligible_but_no_hit` and contributes no claimed saving (cause not isolated - see
`METADATA_GUARD_CORRECTNESS.md` §6).

## 6. Niche ranking

Scored 1-5 (5 best) against the mission's criteria, using only measured evidence:

| Criterion | Compression (bzip2/gzip) | Large text transform (sed) | Binutils on small files | Scientific/data (xz, sort, awk) |
|---|---|---|---|---|
| Native compatibility | 4 (needs allocator contract for file output; text stdout needs none) | 4 | 4 | 1-2 (refused) |
| Correctness confidence | 5 (oracle-clean, 9-mutation matrix clean) | 5 | 4 (`nm` did not hit) | n/a |
| Net performance | **5** (+65-85 % at n=25, break-even ~2) | 4 (break-even ~4) | 1 (dominated) | n/a |
| Ease of adoption | 4 (prefix a command; no build changes) | 4 | 3 | n/a |
| Advantage over existing tools | 3 (Firebuild could do this; no specialist cache exists for bzip2) | 3 | 1 | n/a |
| Repeat frequency | 4 (release artifact regeneration, CI matrix recompression) | 3 | 3 | 3 |
| Operational risk | 4 (no downstream mtime consumer; stale-archive hazard not reachable) | 4 | 2 (wasted time) | 5 |

**Recommendation.** Position TraceJIT's non-compiler niche as *read-only,
deterministic artifact regeneration of moderate cost*: repeated compression or
text transformation of already-produced inputs, where the same command runs 3-100
times against identical inputs and no downstream mtime-driven build step consumes
the output. `bzip2`/`gzip` on a multi-megabyte artifact is the reference case:
break-even at invocation 2, +85 % at 25, oracle-clean, no contract needed for the
stdout form.

**Do not** position it for: filesystem inspection and rewriting of small binaries
(hit floor exceeds the work), `xz`/`tar`/`sort`/`awk`/`perl` (refused), or any
workflow that feeds restored outputs to a make-style mtime comparison without the
workaround in `OUTPUT_RESTORE_SEMANTICS.md`.

## 7. Limits of this study

* One host, one libc, one toolchain; numbers are per-configuration medians of
  five, not bootstrap intervals. The direction (2-16x) is far outside any
  plausible noise; the exact percentages are not portable.
* Firebuild, Rattle and Bazel were **not** run. The advantage column is
  architectural, not measured. A head-to-head on the same three winning
  configurations is the obvious next experiment (see `PHASE_AC_REPORT.md`).
* The corpus is non-compiler, but it is still a corpus of Unix filters. Nothing
  here demonstrates scientific-computing or bioinformatics eligibility; those
  candidates (`numpy`, `pyarrow`, interpreter startups) were either unavailable
  or refused for the same inherited-descriptor and interpreter-runtime reasons as
  `python-csv-json` in the frozen corpus.
* Storage cost was measured, but cache *eviction* was not: there is no prune
  policy in V1, so a long-lived cache grows by roughly the output size per
  distinct command.

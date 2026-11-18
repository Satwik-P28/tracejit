# Phase V: workload economics, contract compatibility, and bottleneck evidence

Baseline: `main` = `cb4783f10bc4de0c8b7cf269121cfd83710730df` (merge of PR #39), CI run
[#245](https://github.com/Satwik-P28/tracejit/actions/runs/44242710251) green.
Candidate: `research/phase-v`, production code unchanged, `target/release/tracejit` =
`31898b97e5d8c427773930469d795a097de2d654b684017e55974bd2edcf2c64` (byte-identical to `main`).

Everything below is measured on this host (Linux 6.1.102, x86_64, 8 vCPU, 15 GiB), with paired
measurements (native and traced interleaved in randomized order, 15 pairs per workload), medians
and p95 in `benchmarks/results/phasev/economics-baseline.json`.

## 1. Method

`benchmarks/phase_v/economics.py` builds real inputs (a 600-function translation unit, 8 MiB of
data, 300k text lines, a 64 KiB slice) and measures, for each real command line:

* `direct` – the command run natively;
* `cold` – first TraceJIT run (trace + record + guards);
* `warm` – a run against a complete record (HIT).

Every warmed run is checked for a HIT, identical program stdout, identical exit status and an
identical content hash of every produced file. Break-even is
`k* = (cold − warm) / (direct − warm)`.

`benchmarks/phase_v/session.py` measures a repeated three-unit C rebuild: a shared header changes
at configured rounds, which is what an incremental build sees.

## 2. Native eligibility (no contract)

| command | class | first refusal |
| --- | --- | --- |
| `gzip -9 -c` | Guarded → Reused | — |
| `cc -O2 -c` | Unknown | `getrusage` (unmodeled) |
| `sort` | Unknown | `clone` (threads) |
| `sed`/`awk`/`cut`/`wc`/`cat`/`uniq`/`head`/`md5sum`/`bzip2` | Nondeterministic | `getrandom` |
| `tar` | Unknown then Nondeterministic | `F_GETFD` on stdio, then `getrandom` + `CLOCK_REALTIME` |
| `sha256sum` | Nondeterministic | `getrandom` |
| `cp` | Unknown | `copy_file_range` → `EOPNOTSUPP` |
| `grep`/`cmp` | Unknown | `/proc/self/maps` (process-relative procfs) |
| `xz` | Unknown | status-flag change on a shared pipe description |
| `tr` (pipe stdin) | Unknown | unclassified stdin |

The dominant native barrier is not a syscall model gap: it is `getrandom`, which stock coreutils
reaches through the C runtime's allocator. That is exactly what the controlled-entropy contract
addresses, and nothing else in this list is a candidate for silent suppression — clocks,
`/proc/self/maps`, thread creation and shared pipe descriptions are genuine dependencies.

## 3. Contract-tier eligibility

| workload | contract | class | second run |
| --- | --- | --- | --- |
| `cc -O2 -c unit.c -o unit.o` | `compiler-runtime-v1` | Guarded | Reused |
| `sha256sum`, `md5sum`, `sed`, `wc` | `allocator-entropy-v1` | Guarded | Reused |
| `strip -o` | `allocator-entropy-v1` | Guarded | Deoptimized (`atime` guard) |
| `tar -cf`, `sort` | either | Unknown | Ineligible |

`tar` stays ineligible because it reads `CLOCK_REALTIME` and `getrandom` outside the audited
allocator site; that is a correct refusal, not a model gap to paper over.

## 4. End-to-end economics

| workload | contract | direct | warm HIT | cold | hit/direct | k* | 50-repeat saving |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cc -O2 -c` (1.5 s TU) | compiler | 1536.95 ms | 115.14 ms | 1756.41 ms | 7.5 % | **1.15** | +69.4 s |
| `gzip -9 -c` 8 MiB | none | 229.88 ms | 264.46 ms | 576.62 ms | 115 % | none | −2.0 s |
| `sed s/a/b/g` 8 MiB | allocator | 65.90 ms | 395.55 ms | 728.99 ms | 600 % | none | −16.8 s |
| `sha256sum` 8 MiB | allocator | 14.19 ms | 41.68 ms | 51.81 ms | 294 % | none | −1.4 s |
| `md5sum` 8 MiB | allocator | 18.14 ms | 30.74 ms | 77.89 ms | 170 % | none | −0.7 s |
| `wc -c` 8 MiB | allocator | 1.44 ms | 24.76 ms | 30.64 ms | 1717 % | none | −1.2 s |
| `gzip -9 -c` 64 KiB | none | 5.03 ms | 14.08 ms | 22.87 ms | 280 % | none | −0.5 s |

Only compute-heavy commands clear the fixed cost. The hit path pays ~7–15 ms of fixed overhead
plus full content re-hashing of every guarded input (~5 ms/MiB measured on `sha256sum`/`wc`), and
materializing outputs of several MiB costs 30–330 ms. A command that only moves bytes therefore
loses on a hit; a command that computes for a second wins by 13×.

## 5. Session economics (what a build actually sees)

`benchmarks/phase_v/session.py`, three translation units per round,
`--contract compiler-runtime-v1`:

| schedule | invocations | direct | traced | speedup | decisions |
| --- | --- | --- | --- | --- | --- |
| 9 rounds, header edit at 3 and 6 | 27 | 13.662 s | 12.434 s | **1.10×** (9.0 %) | 3 Executed, 12 Reused, 12 Deoptimized |
| 16 rounds, header edit at 7 and 12 | 48 | 23.822 s | 13.758 s | **1.73×** (42.2 %) | 3 Executed, 33 Reused, 12 Deoptimized |

Object files are byte-identical to the native build in both runs.

The difference between 1.10× and 1.73× is one structural cost, not noise: **a mutation costs two
full deoptimizations.** After an edit, the first run deopts and re-executes (its recorded output
pre-state was the object produced before the edit); the second run deopts again because the object
on disk is now the one the *first* run produced, while the fresh record still describes the older
pre-state; only the third run hits. This is inherent to guarding output pre-state soundly — the
record cannot claim a pre-state the observed run did not start from — but it means the workload is
only profitable when mutations are rare relative to repeats.

## 6. Rejected experiment: admitting `fcntl(F_GETFD)` on stdio

GNU `tar` refused every native run because of `fcntl(fd, F_GETFD)` on descriptors 0–2, a query
that returns only `FD_CLOEXEC`. Trial implementation: admit the query for stdio and record the
three bits in `RuntimeIdentity` (cache schema 2 → 3), so the observation is validated on each hit.

Measured result: **no workload became reusable.** After the admission, `tar` advanced to the next
genuine barrier (`getrandom` and `CLOCK_REALTIME`) and stayed `Nondeterministic`; no other command
in the corpus changed class. The change also bumps a cache schema, which invalidates every
existing record. Per the decision gate (meaningful net savings on an independent workflow, no
operational cost without benefit) the experiment was reverted; `main` production code is
unchanged in this branch.

## 7. Bottleneck list, ranked by measured effect

1. **Full input content hashing on the hit path** (~5 ms/MiB): dominates every byte-moving
   workload and explains why `wc -c` on 8 MiB costs 17× its direct time.
2. **Output materialization** (30–330 ms for multi-MiB stdout): dominates `sed`, `gzip` and any
   producer writing megabytes.
3. **Fixed warm-hit overhead** (~7 ms floor, ~15 ms with dependencies): sets the smallest command
   size that can ever be profitable.
4. **Two deoptimizations per mutation**: sets the repeat count a workflow needs per edit.
5. SQLite lookup, record decode and guard validation are each ≪1 ms and were not worth touching.

## 8. Correctness

No production change, so the safety contract is exactly `main`'s. Executed on this branch:
`cargo test --workspace --no-fail-fast` (224 tests, 0 failed), Linux integration 69/69 (including
the child-local descriptor regressions from PR #39), object-file equality checks against native
execution in both session runs, and the HIT-content equality checks in every economics workload.
`target/release/tracejit` is byte-identical to `main`.

## 9. Decision

No Phase V optimization passes the promotion gate: the only measured win (`cc` under
`compiler-runtime-v1`, 13×) already exists in `main`, and no modification produced a reproducible
end-to-end improvement on a real workflow. Production stays unchanged. A v0.3 release is **not**
justified on performance grounds; the honest summary is that the useful, currently-available
workflow is compile-heavy commands under the compiler contract, with a repeat-to-mutation ratio
above roughly 6.

Reproduce with:

```bash
python3 benchmarks/phase_v/economics.py --output /tmp/economics.json --reps 15
python3 benchmarks/phase_v/session.py --rounds 16 --edit-rounds 7,12 --output /tmp/session.json
```

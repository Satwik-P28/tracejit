# Validated replay performance and lower bounds (Phase AE)

Question: how much of a large-artifact HIT is hashing, how much is restoration and presentation,
and how close is the current implementation to what a *verified* replay must cost? The answer
comes from TraceJIT's own disjoint phase timers, not from attributing the whole hit to hashing.

Harness: `benchmarks/phase_ae/replay_profile.py`; raw output
`benchmarks/results/phaseae/replay_profile.json`. Cases use a 100 MiB compressible text prefix
and a 100 MiB incompressible prefix derived from the pinned Linux 6.6.50 archive (see
`docs/ARTIFACT_BENCHMARKS.md` for the corpus and digests). Each phase is the median of five
replays; `present` is the write of cached stdout to the caller's descriptor.

## 1. Where the time goes

| case | HIT total | guard validation | stdio replay | present | cas restore | startup + decode + sqlite |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gzip text 100 MiB → stdout (output 19.9 MB) | **79.8 ms** | 39.4 | 19.2 | 12.8 | 0.0 | 4.2 + 1.7 |
| gzip incompressible 100 MiB → stdout (output 100 MiB) | **257.8 ms** | 38.8 | 86.1 | 57.5 | 0.0 | 2.8 + 1.6 |
| gzip text 10 MiB → **file** (output 2.8 MB) | **22.5 ms** | 8.0 | 0.0 | 0.0 | 10.0 | 4.7 + 1.7 |
| sha256sum 100 MiB | **52.0 ms** | 46.5 | 0.0 | 0.0 | 0.0 | 7.2 + 1.9 |

Reading of the table:

* **Input hashing is 47–49 % of a compressible-text HIT and 15 % of the incompressible one.**
  In the incompressible case the dominant costs are reading and verifying a 100 MiB cached
  output (86.1 ms) and streaming it (57.5 ms).
* **Filesystem restoration is not hashing.** For the 10 MiB file-output case, guard validation
  is 8.0 ms and the staged write/verify/rename/sync path is 10.0 ms.
* **Durability is not on the stdout path.** `cas_restore` is zero when no files are restored;
  the durability barriers live only in the file-restoration path, where they cost ~10 ms for a
  2.8 MB output.
* **Startup is now the floor for small artifacts**: 4.2–7.2 ms of a 52 ms hash-only HIT is
  TraceJIT's own process start, the SQLite open and the record decode.

## 2. The practical floor for verified replay

Baselines measured on the same host with the same 100 MiB input
(`replay_profile.json → bounds`):

| operation | measured | rate |
| --- | ---: | ---: |
| sequential read (`dd` bs=1M, page cache warm) | 16.8 ms | 6.25 GiB/s |
| memory copy (5×100 MiB, `-O2`) | 23.9 ms | 4.40 GiB/s |
| `dd` write + `fdatasync` (100 MiB) | 302.7 ms | 0.35 GiB/s |
| `fsync` of a dirty 4 KiB page (median) | 0.69 ms | — |
| BLAKE3 over the recorded input, taken from `guard_validation_ns` (100 MiB / 39.4 ms) | 39.4 ms | ≈2.54 GiB/s |

The hash rate is derived from the product's own phase timer, not from a separate BLAKE3
microbenchmark: that is the number a change would have to move, and it includes the syscall and
file-inspection work around the hash. It is about 1.7× slower than `memcpy` on this host,
consistent with a portable BLAKE3 build without SIMD dispatch tuned for this CPU.

A verified replay of a 100 MiB artifact therefore cannot cost less than:

```
hash(input)  + read(cached output) + hash(cached output) + write(caller)
   ~39 ms        ~17 ms               ~39 ms (100 MiB)      ≥ 17 ms
```

i.e. ≈95 ms for the incompressible case before any allocation or synchronisation. The measured
HIT is 257.8 ms: the extra ≈160 ms is `stdio_replay` bookkeeping and boxing of a 100 MiB object
plus a 57.5 ms pipe write, both of which run *after* verification. For the compressible-text
case the floor is ≈39 + 3 + 8 + 3 ≈ 53 ms against a measured 79.8 ms.

## 3. Opportunities investigated and rejected

| candidate | why it was considered | why it is not adopted |
| --- | --- | --- |
| fused hashing and copying (hash while writing to the caller) | could remove one full pass over the output | the fused write would expose unverified bytes before their hash is known. Prohibited by the contract: no cached byte may become externally visible before every guard passes. |
| streaming cached bytes with a hash trailer | would remove the 100 MiB buffering and halve peak RSS | same objection: the caller has already consumed unverified bytes by the time the check fails. |
| `mmap` the cached object and hash in place | could avoid one copy | measured `memcpy` (23.9 ms) is not the bottleneck; `stdio_replay` (86.1 ms) is dominated by read+hash, so mmap would save at most the read half and risks `SIGBUS` on truncation. Not worth a new failure mode. |
| faster BLAKE3 (SIMD dispatch) | the hash rate is ~1.7× below memcpy | plausible 10–20 ms saving on a 100 MiB HIT. Not attempted here: it is a dependency/feature-builder change, and it must be measured against a rebuilt artifact first. Recorded as the single justified future optimisation. |
| metadata-only fast path that skips re-hashing when `(inode,size,mtime)` matches | this is exactly what Firebuild does | it weakens the guard: a same-size rewrite with a restored mtime would pass. TraceJIT's `same-timestamp rewrite` regression exists because that case was already a defect once. Rejected on correctness. |
| caching verified guard results between runs | large potential saving: skip 39 ms of hashing | invalidation is undecidable without re-reading the input; any cache of "this content hash was valid at T" is a weaker contract. Rejected. |
| removing the `present` copy for large outputs | `present` is 57.5 ms | the copy is the exposure step; it cannot be removed while verification precedes exposure. |

## 4. Peak memory, defined

`replay_profile.py` runs each measurement in a fresh wrapper process that spawns exactly one
TraceJIT invocation and reads `getrusage(RUSAGE_CHILDREN).ru_maxrss`; the reported value is the
maximum over that run and its descendants, not over the harness.

| case | peak child RSS |
| --- | ---: |
| gzip text 100 MiB → stdout (19.9 MB output) | 26.9 MB |
| gzip incompressible 100 MiB → stdout | 110.1 MB |
| gzip text 10 MiB → file | 11.8 MB |
| sha256sum 100 MiB (no output) | 11.4 MB |

Memory tracks the largest verified object, which is exactly the output for stdout replays.
Firebuild peak RSS was not captured by this harness and is not claimed here; Phase AD's
`artifact_scale` table quotes ≈107 MB for Firebuild on 100 MiB rows from a different harness.

## 5. Promotion gate verdict

No production change is proposed or made in this phase.

* The measured HIT cost is within 1.5× (compressible text) and 2.7× (incompressible) of a floor
  that already includes full input and output verification.
* The only candidate that could close that gap without weakening a guard is a faster BLAKE3
  build (SIMD dispatch), worth an estimated 10–20 ms per 100 MiB HIT. It changes no contract,
  but it is a dependency change that has not been measured end-to-end, so it does not yet
  satisfy "measurably benefits authentic workloads with a confidence interval".
* Every other candidate either exposes unverified bytes, weakens guard semantics, or moves the
  cost into memory.

**Conclusion: the implementation is close to its practical verified-replay bound. Stop
optimising the replay path and keep the integrity guarantee.**

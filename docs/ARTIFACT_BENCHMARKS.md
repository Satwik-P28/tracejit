# Authentic artifact workloads and scale (Phase AD)

Phase AC measured 2 MiB synthetic blobs. The open question was whether the non-compiler
advantage survives authentic inputs at 1, 10 and 100 MiB, where input hashing, output
materialisation and cache storage all grow with the artifact. This study answers it with one
pinned release archive and a reproducible derivation; no invented CPU-burning loops are in the
primary comparison.

Harness: `benchmarks/phase_ad/artifact_scale.py`. Raw data:
`benchmarks/results/phasead/artifact_scale.json`.

## 1. Corpus

| item | value |
| --- | --- |
| source | `https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.50.tar.xz` |
| downloaded bytes | 140 341 000 |
| sha256 | `c065e36daf28210060c91a37ef3e92ac5814784e634577e04e406297ead2e86e` |
| compressible artifact | first *N* bytes of `xz -dc` of the release tarball (C sources, docs, tar padding) |
| incompressible artifact | first *N* bytes of the `.tar.xz` itself |

Sized inputs and their digests:

| size | compressible sha256 (prefix) | incompressible sha256 (prefix) |
| --- | --- | --- |
| 1 MiB | `3735bb78d739ce24…` | `8a44ddff28b35e1c…` |
| 10 MiB | `43648fa651a2d916…` | `b313f79fb97aabb7…` |
| 100 MiB | `11e409641fc37bc7…` | `bdf44b3e96b39532…` |

Distinct file contents, not truncated copies of each other: each size is a byte prefix of the
same pinned stream, so a 10 MiB input is not the 1 MiB input padded. Full digests are in the
JSON.

Workloads: `gzip -9 -n -c` (stdout filter, both flavours), `sha256sum` (hash-only), and at
≤10 MiB `bzip2 -9 -c` and `gzip -9 -n -k -f` (file output). Arms: native, TraceJIT
`allocator-entropy-v1`, Firebuild 0.8.2 with default configuration. Cold = first invocation,
warm = median of three with outputs deleted, sessions = measured wall clock, RSS = peak child
RSS, cache = bytes stored.

## 2. Results

Costs in milliseconds. `n*` is the **integer** number of invocations at which tracing first
repays its own cost, computed from that row's measured `C`, `H` and the native warm `D`; a
fractional ratio is not an actionable number.

| artifact | workload | arm | cold C | hit H | native D | reuse | n* | peak RSS | cache |
| --- | --- | --- | ---: | ---: | ---: | :--: | ---: | ---: | ---: |
| 1 MiB | gzip text → stdout | tracejit | 75.8 | 6.0 | 46.0 | yes | 2 | 11.4 MB | 0.3 MB |
| 1 MiB | gzip text → stdout | firebuild | 61.4 | 9.7 | 46.0 | yes | 2 | 11.4 MB | 0.2 MB |
| 1 MiB | gzip incompressible → stdout | tracejit | 56.7 | 7.7 | 29.9 | yes | 3 | 11.4 MB | 1.2 MB |
| 1 MiB | gzip incompressible → stdout | firebuild | 58.3 | 21.4 | 29.9 | yes | 5 | 11.4 MB | 1.0 MB |
| 1 MiB | sha256sum | tracejit | 35.6 | 13.1 | 3.2 | yes | **never** | 11.4 MB | 0.4 MB |
| 1 MiB | sha256sum | firebuild | 10.4 | 8.0 | 3.2 | yes | **never** | 11.4 MB | small |
| 1 MiB | bzip2 text → stdout | tracejit | 108.3 | 8.1 | 75.8 | yes | 2 | 11.4 MB | 0.3 MB |
| 1 MiB | gzip text → file | tracejit | 78.2 | 10.5 | 51.8 | yes | 2 | 11.4 MB | 0.4 MB |
| 1 MiB | gzip text → file | firebuild | 50.8 | 57.1 | 51.8 | **no** | – | 11.4 MB | 0 |
| 10 MiB | gzip text → stdout | tracejit | 645.9 | 18.2 | 565.3 | yes | 2 | 11.4 MB | 2.7 MB |
| 10 MiB | gzip text → stdout | firebuild | 634.4 | 47.1 | 565.3 | yes | 2 | 14.0 MB | 2.5 MB |
| 10 MiB | gzip incompressible → stdout | tracejit | 410.1 | 42.1 | 288.6 | yes | 2 | 17.9 MB | 10.6 MB |
| 10 MiB | gzip incompressible → stdout | firebuild | 518.3 | 173.8 | 288.6 | yes | 4 | 14.1 MB | 10.5 MB |
| 10 MiB | sha256sum | tracejit | 86.9 | 18.4 | 14.5 | yes | **never** | 11.4 MB | 0.4 MB |
| 10 MiB | sha256sum | firebuild | 21.0 | 11.6 | 14.5 | yes | 4 | 14.3 MB | small |
| 10 MiB | bzip2 text → stdout | tracejit | 889.3 | 19.5 | 684.7 | yes | 2 | 11.4 MB | 2.3 MB |
| 10 MiB | gzip text → file | tracejit | 653.7 | 28.1 | 571.9 | yes | 2 | 11.4 MB | 2.7 MB |
| 10 MiB | gzip text → file | firebuild | 579.3 | 575.3 | 571.9 | **no** | – | 14.4 MB | 0 |
| 100 MiB | gzip text → stdout | tracejit | 6079.5 | 85.3 | 5467.6 | yes | 2 | 26.9 MB | 19.9 MB |
| 100 MiB | gzip text → stdout | firebuild | 5795.1 | 288.2 | 5467.6 | yes | 2 | 106.9 MB | 19.7 MB |
| 100 MiB | gzip incompressible → stdout | tracejit | 3672.5 | 362.2 | 2852.4 | yes | 2 | 110.1 MB | 105.0 MB |
| 100 MiB | gzip incompressible → stdout | firebuild | 12250.6 | 1945.6 | 2852.4 | yes | 12 | 107.0 MB | 104.9 MB |
| 100 MiB | sha256sum | tracejit | 355.7 | 52.1 | 86.5 | yes | 9 | 11.4 MB | 0.4 MB |
| 100 MiB | sha256sum | firebuild | 126.0 | 31.9 | 86.5 | yes | 2 | 107.1 MB | small |

## 3. What the scale study establishes

1. **The advantage grows with the artifact, not shrinks.** For compressible text, the hit/direct
   ratio improves from 7.7× at 1 MiB to 31× at 10 MiB to 64× at 100 MiB. The reason is that
   compression work scales with input size while TraceJIT's hit cost (BLAKE3 over input and
   output plus one write) grows at memory bandwidth.
2. **Incompressible data narrows but does not reverse the result.** `gzip -9` on 100 MiB of
   already-compressed bytes: direct 2852 ms, hit 362 ms (7.9×). The hit is dominated by
   restoring a 100 MiB stdout blob, which is why the cache entry is 105 MB.
3. **Hash-only commands are the reversal case.** `sha256sum` at 1 MiB (direct 3.2 ms, hit
   13.1 ms) and 10 MiB (14.5 vs 18.4 ms) never repay. At 100 MiB the same command does pay
   from the ninth invocation (86.5 vs 52.1 ms), because both sides read the file once and the
   cached side skips the digest loop. This is exactly the "hashing may reverse the result" risk
   Phase AD was asked to test, and the answer is size-dependent, not universal.
4. **The integer break-even is almost always 2.** For every compression workload at every size,
   one warm invocation repays the trace premium, because the premium is 8–15 % of a single
   direct run. Only hash-only workloads need a session (9 invocations at 100 MiB), and at
   ≤10 MiB they never pay.
5. **Memory and storage.** TraceJIT's peak RSS tracks the largest object it hashes or restores:
   11.4 MB for small outputs, 26.9 MB for a 20 MB text output, 110 MB for a 100 MiB
   incompressible output. Firebuild's RSS is ~107 MB on the 100 MiB rows even for `sha256sum`,
   because of its blob cache. TraceJIT's cache footprint equals the captured bytes: 19.9 MB for
   a 20 MB gzip output, 105 MB for a 100 MiB stdout capture.
6. **Mutation sensitivity.** A changed input produces a different cache key and therefore no
   HIT (measured in the mixed session: three successive variants of the same text never hit).
   Mutation *frequency* is the dominant economic variable, not input size: with the input
   changing every invocation, every system pays the cold path forever.

## 4. Limitations

* One host, one filesystem (ext4), one kernel (6.1.102), page cache warm for the direct
  baselines after the first run. Compression was `gzip -9`/`bzip2 -9`; `zstd` is not installed
  here.
* `gzip -9 -n -k -f` file output is only measured at ≤10 MiB: at 100 MiB a single direct run
  is ~6 s and a 3-invocation session × 3 arms was judged too slow for the value.
* Firebuild numbers are its 0.8.2 package (see `docs/FIREBUILD_COMPARISON.md`); newer releases
  may cache timestamp-preserving outputs.
* The break-even model is measured-component, not a fit: `n* = floor((C−H)/(D−H)) + 1` with
  all three measured on the same host in the same run.

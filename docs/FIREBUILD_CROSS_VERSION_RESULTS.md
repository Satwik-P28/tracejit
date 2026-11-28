# Firebuild cross-version results (Phase AE)

Two Firebuild versions were exercised on the same host and the same workloads as TraceJIT:
**0.8.2** (the distribution package that Phase AD measured) and **0.8.6.2** (the newest
release tag at the time of this phase). This document records how each binary was obtained and
verified, what changed between them, and the resulting verdict.

## 1. Builds, pinned and verified

### 1.1 Firebuild 0.8.2 — distribution package, user-space extraction

| item | value |
| --- | --- |
| source | `http://archive.ubuntu.com/ubuntu/pool/multiverse/f/firebuild/firebuild_0.8.2-1_amd64.deb` |
| `firebuild_0.8.2-1_amd64.deb` sha256 | `e8ed7bfd868e33d965d1378e40cfa8d20f2ab154b9fc889b5aecdd958a7987e3` |
| `libfirebuild0_0.8.2-1_amd64.deb` sha256 | `64268359d59abfc1e30c0be700ef9b28f080a2afe0db8119b7452435d82b41e1` |
| `libconfig++9v5_1.5-0.4build2_amd64.deb` sha256 | `2fd37b216b8c8a44e0117f5845ed536ac5cf33ab82eb6165abd136bdfa8bdc78` |
| installed binary sha256 | `cffadc1609425775fcacc51f8d5fbd811b229fd0ddf89ab9a0efc7e87000f510` |
| installed interceptor sha256 | `05d9aece2b9925b757bc61e24c4ba179ed476a2fd4e05c568a6d27730cb89d16` |
| reported version | `Firebuild 0.8.2` |

Extracted with `dpkg-deb -x` into a private prefix; no root, no system install. The measured
binary digest matches Phase AD's recorded digest, so the historical baseline is the same build.

### 1.2 Firebuild 0.8.6.2 — source build, pinned tarball

Upstream publishes **no prebuilt artifacts** for 0.8.6.2 (release assets are the source
`.tar.gz`/`.zip` only), so the newer arm had to be built. The exact recipe used here:

| item | value |
| --- | --- |
| source | `https://github.com/firebuild/firebuild/archive/refs/tags/v0.8.6.2.tar.gz` |
| build | CMake + Ninja; host `gcc 13.3.0`; `-Wno-error=effc++` (GCC's `-Weffc++` fires inside the system `tsl-hopscotch-map` headers, which upstream builds with clang) |
| dependencies | `libconfig++-dev`, `libxxhash-dev`, `libjemalloc-dev`, `libelf-dev`, `libtsl-hopscotch-map-dev`, `zlib1g-dev`, `libzstd-dev`, extracted from the Ubuntu noble archive into a private prefix (no root) |
| resulting supervisor sha256 | `8c895da049adcae026a99ac7d208a5691d0f92047fb932680f820938afc930e3` |
| resulting interceptor sha256 | `35cbc7ed82f0d24e16b0ccab1029503cfa09f3299491277bcd44b064b5cd7024` |
| reported version | `Firebuild 0.8.6.2` |

The runner must use the **build-tree** binary (`build/src/firebuild/firebuild`): the installed
binary resolves its interceptor by bare library name (`config.cc:519-546`), and without an
installed library path the child fails `LD_PRELOAD` silently. That trap produced a false
"no reuse" in one early probe run and is the reason the harness records
`LD_PRELOAD cannot be preloaded` from child stderr.

The binary digest differs from the one recorded in the earlier Phase AE run
(`d646a662…`), which was built with clang. A source build of this project is not bit-reproducible
across compilers, so **the pinned identity is the source tarball plus the build recipe, and each
report must name its own binary digest.** It is not evidence of two different source trees.

## 2. Behavioural differences between 0.8.2 and 0.8.6.2

From `benchmarks/results/phaseae/matrix.json` and `policy_probe.json`:

| behaviour | 0.8.2 | 0.8.6.2 | note |
| --- | --- | --- | --- |
| `gzip -9 -n -k` (output mtime preserved) | not cached (`Hits: 0/1` forever) | **cached and reused** | fixes the Phase AD "cannot cache artifact producers" limitation for this class |
| `bzip2 -9 -k` (output mtime preserved) | not cached | not cached | `-d shortcut` says `Changing file timestamps is not supported` |
| `gzip -9 -n -c` stdout | reused | reused | unchanged |
| `sed` (default config) | refused (`Uncacheable: 1`) | refused | still in `processes.skip_cache` |
| `sha256sum` | reused | reused | both slower than native at this size |
| `date +%s`, `time.time_ns()` | replayed, stale | replayed, stale | `ignore-time-queries` quirk |
| same config with `ignore-time-queries` removed | command executed, never cached | same | quirk is disableable in both |
| corrupted cached stdout blob | replayed corrupted | replayed corrupted | no integrity verification in either |

## 3. Definitive competitive matrix (n = 25 invocations, cold-inclusive sessions)

Medians of five randomized paired repeats; `cold` means a brand-new cache per session, so the
first trace, later reuse and any refusals are all charged to the arm. Milliseconds.

| workload | native | TraceJIT (`allocator-entropy-v1`) | Firebuild 0.8.2 | Firebuild 0.8.6.2 default | 0.8.6.2 tuned |
| --- | ---: | ---: | ---: | ---: | ---: |
| bzip2 -9 -k, 1 MiB incompressible | 2846.7 | **545.3** | 2976.9 | 3119.4 | 3065.6 |
| gzip -9 -n -k, 1 MiB incompressible | 882.7 | 425.0 | 1154.6 | **254.7** | 243.4 |
| gzip -9 -n -c, 1.2 MiB text | 1856.3 | **276.9** | 299.9 | 268.0 | 260.7 |
| sed over 200k lines | 1824.1 | 885.8 | 2071.2 | 2113.9 | **561.4** |
| sha256sum, 1 MiB | **94.5** | 377.2 | 282.1 | 247.9 | 217.8 |

Per-invocation medians with 95 % bootstrap intervals, and the reuse classification, are in
`economics.json`; the classification at n=25 is:

| workload | both reuse | only TraceJIT | only Firebuild | neither |
| --- | --- | --- | --- | --- |
| bzip2-file | — | TraceJIT (`tj-ae`) | — | — |
| gzip-file | TraceJIT + Firebuild ≥ 0.8.6.2 | — | — | — |
| gzip-stdout | TraceJIT + both Firebuild versions | — | — | — |
| sed-lines | TraceJIT + Firebuild **tuned only** | — | — | — |
| sha256sum | both, but neither is profitable | — | — | — |
| gzip-mutating (input changes every 3rd run) | both (on the unchanged windows) | — | — | — |

Only the "both reuse" rows support a replay-engine performance comparison; the "only
TraceJIT" row is a statement about applicability, not speed.

## 4. What survives as a competitive claim

1. **Applicability, not speed, on timestamp-preserving outputs.** Firebuild 0.8.6.2 replays
   `gzip -k` and is 1.67× faster than TraceJIT at it. It still refuses `bzip2 -k`, where
   TraceJIT replays 24 of 25 invocations and is 5.6× faster than Firebuild's re-execution.
2. **Contract.** Default Firebuild replays clock-dependent output; TraceJIT refuses it under
   every policy. Firebuild's strict configuration refuses to cache such commands, so the
   difference is a configuration-dependent contract, not a defect that Firebuild cannot avoid.
3. **Cache integrity.** Firebuild replays a corrupted cached blob (measured, five arms);
   TraceJIT refuses the object and re-executes.
4. **Replay cost on large stdout.** TraceJIT's validated replay of a 100 MiB text artifact was
   measured at 79.8 ms (Phase AE per-phase profile) against Firebuild's 288.2 ms in the
   Phase AD harness. The two numbers come from different harnesses and should be re-measured
   together before being quoted as a head-to-head.

The Phase AD headline "TraceJIT wins the artifact-producing niche outright" is **withdrawn**:
it wins on the part of that niche Firebuild still refuses, and loses on the part it now
supports.

## 5. Reproduction

```bash
# 0.8.2 (no root)
curl -fsSLO http://archive.ubuntu.com/ubuntu/pool/multiverse/f/firebuild/firebuild_0.8.2-1_amd64.deb
curl -fsSLO http://archive.ubuntu.com/ubuntu/pool/multiverse/f/firebuild/libfirebuild0_0.8.2-1_amd64.deb
dpkg-deb -x firebuild_0.8.2-1_amd64.deb fb082/prefix
dpkg-deb -x libfirebuild0_0.8.2-1_amd64.deb fb082/prefix

# 0.8.6.2 (source, pinned)
curl -fsSL -o fb.tar.gz https://github.com/firebuild/firebuild/archive/refs/tags/v0.8.6.2.tar.gz
cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-Wno-error=effc++ ... && ninja
# run the build-tree binary, not the installed one

# measurements
python3 benchmarks/phase_ae/competitive_matrix.py \
  --arms native,tj-ae --workloads bzip2-file,gzip-file,gzip-stdout,sed-lines,sha256sum \
  --sizes 2,3,10,25,100 --modes cold,steady --repeats 5 \
  --firebuild-binary /path/to/build/src/firebuild/firebuild \
  --firebuild-conf  /path/to/build/etc/firebuild.conf --firebuild-version 0.8.6.2 --tuned ...
python3 benchmarks/phase_ae/economics.py --markdown
python3 benchmarks/phase_ae/firebuild_policy_probe.py --firebuild ... --conf ... --label fb862-default
```

Capability skips: none of these need Landlock, seccomp or root. Firebuild refuses to cache
processes whose files live under `$TMPDIR`, so the harness keeps every workspace outside it.

# Competitive evidence audit (Phase AE)

Purpose: decide, from primary sources and measurements, what TraceJIT may claim against
Firebuild — and retract the parts of Phase AD that the evidence does not support. Every
statement below is either a code reference in a pinned Firebuild source tree or a number
produced by a harness in `benchmarks/phase_ae/`.

## 1. What Phase AD claimed and what is actually true

| Phase AD statement | Status in AE | Evidence |
| --- | --- | --- |
| "Firebuild's fingerprint is the lookup key and no independent validation pass over the recorded inputs was found" | **Retracted.** Firebuild validates every recorded input before applying a shortcut. | `src/firebuild/execed_process_cacher.cc:1164-1236` (`pio_matches_fs`) walks every recorded input and calls `HashCache::file_info_matches`; `src/firebuild/hash_cache.cc:402-490` compares type, size, mode and the content hash when the record carries one. |
| "Firebuild reuses clock-dependent output because of a quirk" | **Confirmed, and refined.** The quirk is named, documented and disableable (`ignore-time-queries`). Disabling it does not deoptimise the reuse, it makes the process uncacheable. | `src/firebuild/message_processor.cc:1349-1356`; measured in `policy_probe.json`: `clock_date` reuses under default config, and under a config with the quirk removed both runs are `executed` with `Newly cached: 0.00 kB`. |
| "Firebuild 0.8.2 cannot cache timestamp-preserving file outputs" | **Version-specific, as Phase AD suspected.** 0.8.6.2 caches `gzip -9 -n -k`, and still refuses `bzip2 -9 -k`. | `matrix.json` `fb082-*` vs `fb862-*` rows; refusal reason captured verbatim: `Changing file timestamps is not supported` (`-d shortcut`, 0.8.6.2). |
| "Firebuild's cache has no post-storage integrity pass" | **Confirmed by experiment.** A one-byte corruption of the cached stdout blob is replayed, exit 0, bytes differ from a fresh execution. | `policy_probe.json` → `cache_corruption` for all five Firebuild arms; TraceJIT's paired result in `tracejit_integrity.json`. |
| "TraceJIT validates more than Firebuild" | **Narrowed.** Firebuild's input validation is content-hash based at reuse: a same-size rewrite with the original mtime restored is *detected*. TraceJIT differs in the contract (clock/entropy refusal), in refusing to expose unverified cache objects, and in which outputs it can replay. | `policy_probe.json` → `same_mtime_rewrite` decisions `executed → hit → executed` on every arm. |

Consequence: the correct framing is **two engines with different contracts and different
supported output classes**, not "validated versus unvalidated reuse".

## 2. Firebuild's reuse path, from source

1. **Fingerprint** (`execed_process_cacher.cc:321-427`): XXH3-128 over a version seed, ignore
   locations, initial working directory, argument vector, fingerprintable environment, the
   executable/executed path, libraries (each with its content hash), umask and inherited file
   descriptors. The hash cache supplies executable and library hashes.
2. **Candidate lookup** (`:1251-1254`): `obj_cache->list_subkeys(fingerprint)`; each subkey is a
   recorded variant for the same fingerprint.
3. **Dependency validation** (`:1286` → `pio_matches_fs` → `hash_cache->file_info_matches`):
   for every recorded input path — plus recorded "path does not exist" entries — type, size,
   mode and hash are compared with the recorded `FileInfo`. Output writability preconditions
   are checked too (`:1213-1234`).
4. **Apply** (`shortcut.cc` / `blob_cache.cc:441+`): streams and file contents are replayed
   from blobs; blobs are addressed by hash but are **not re-hashed while being applied** (the
   corruption experiment shows the consequence).

Two details matter for the comparison and were not established in Phase AD:

* the recorded input *hash* is genuine content, not just metadata, so ordinary content changes
  are caught even if mtime is preserved;
* the in-memory hash cache does skip re-hashing when `(inode, size, mtime)` is unchanged, but
  that cache is per supervisor process, so the first time a path is validated in a new run it
  is hashed. (This is why the same-mtime rewrite is detected.)

## 3. Measured contract differences

From `benchmarks/results/phaseae/policy_probe.json` (five arms; each case in a fresh cache):

| case | 0.8.2 default | 0.8.2 strict | 0.8.6.2 default | 0.8.6.2 strict | 0.8.6.2 tuned |
| --- | --- | --- | --- | --- | --- |
| `date +%s` second run | reused, stale value | executed | reused, stale value | executed | reused, stale value |
| `python3` `time.time_ns()` | reused, stale value | executed | reused, stale value | executed | reused, stale value |
| `gzip -9 -n -k` | executed | executed | **reused** | reused | reused |
| `bzip2 -9 -k` | executed | executed | executed | executed | executed |
| `sed` over 200k lines | refused (`skip_cache`) | refused | refused | refused | **reused** |
| same-size, same-mtime rewrite | executed after rewrite | same | same | same | same |
| mtime-only change | reused (content equal) | same | same | same | same |
| one corrupted blob byte | replayed corrupted bytes | same | same | same | same |

"executed" for a clock command under the strict configuration means Firebuild refused to
*cache* it (`Newly cached: 0.00 kB`), which is the correct behaviour under its own contract.
The retained defect is the default: a command whose entire output is a clock read is replayed.

TraceJIT's paired integrity result (`tracejit_integrity.json`): a one-byte corruption of the
stored stdout object makes the next run report `MISS` (not a hit) and produce byte-identical
output to a native execution; `served_corrupted_bytes: false`.

## 4. Verdict on each competitive claim

| claim | verdict |
| --- | --- |
| "TraceJIT is faster than Firebuild on repeated compression" | **False as a general claim.** At n=25 cold-inclusive sessions, gzip -9 -k over a 1 MiB incompressible blob: native 882.7 ms, TraceJIT 425.0 ms, Firebuild 0.8.6.2 254.7 ms. Firebuild is 1.67× faster than TraceJIT on this workload. |
| "TraceJIT covers artifact producers Firebuild cannot cache" | **True but narrower than Phase AD.** 0.8.6.2 caches `gzip -k`; it still refuses `bzip2 -k` (`Changing file timestamps is not supported`). bzip2 -9 -k, n=25 cold session: native 2846.7 ms (109.7 ms/invocation), TraceJIT 545.3 ms (14.9 ms/invocation, 24 of 25 reused), Firebuild 0.8.2 and 0.8.6.2 no reuse at all (2976.9–3131.5 ms). |
| "TraceJIT's replay is faster on large stdout artifacts" | **Marginal and size dependent.** 1.2 MiB text stdout, per-invocation: TraceJIT 6.56 ms vs Firebuild 7.47 ms (12 %). 100 MiB profile (`VALIDATED_REPLAY_PERFORMANCE.md`): TraceJIT 79.8 ms vs Firebuild 288.2 ms measured in Phase AD's harness (not re-measured with the Phase AE per-invocation accounting). |
| "Firebuild performs unvalidated reuse" | **False.** Retracted; see §1. |
| "TraceJIT never exposes bytes that failed verification" | **Supported for the tested path.** Corrupted-object experiment: no hit, correct output. |
| "TraceJIT refuses what Firebuild replays" | **True for clocks and allocator entropy under the default configurations.** It is a contract difference, not a bug in either system. |

## 5. Harness defects corrected in this phase

1. **Cache state and session totals.** Phase AD populated the cache before timing and called
   the result a session. `competitive_matrix.py` now has two explicit modes: `cold` (brand-new
   cache per session, every invocation measured) and `steady` (population outside the timer,
   labelled steady state). Session totals never include a pre-populated cache in `cold`.
2. **Decision provenance.** Every invocation records the engine's own decision for *that*
   invocation (`tracejit-report`, or Firebuild's `-s` trailer with `stats_parsed` asserted).
   `check_row()` rejects a hit without a decision, a hit without restoration evidence, a row
   without output verification, and a cold session that starts with a hit.
3. **Output verification.** Every invocation's stdout and output files are compared to an
   independently computed native oracle for the input variant that was actually on disk.
4. **Break-even arithmetic.** `floor((C-H)/(D-H)) + 1` is wrong when the ratio is an exact
   integer. `break_even()` uses `ceil((C-H)/(D-H))` with a floor of 2; the exact-ratio and
   round-up cases are pinned by tests. Phase AD's own table contained a 1 MiB incompressible
   gzip row with `n*=3` while its prose claimed every compression workload pays at the second
   invocation — the row is right and the prose was wrong.
5. **Cache footprint.** Measured per arm, per invocation, from that arm's own storage directory
   (Firebuild: its per-arm `$HOME/.cache/firebuild`; TraceJIT: `TRACEJIT_CACHE_DIR`), including
   nested files. Firebuild at n=25: gzip-file 1.05 MB, sed 5.40 MB, gzip-stdout 0.25 MB;
   TraceJIT: 1.16 MB, 5.70 MB, 0.35 MB.
6. **Peak memory definition.** `replay_profile.py` spawns a fresh wrapper that runs exactly
   one TraceJIT invocation and reads `getrusage(RUSAGE_CHILDREN).ru_maxrss`, i.e. the maximum
   over that run and its descendants. Firebuild peak RSS was **not** captured there and is not
   claimed.
7. **Instrumentation separation.** The per-invocation matrix runs plain mode (no `--json`
   report, no phase timing); the phase profile runs with `TRACEJIT_PHASE_TIMING` and is used
   only for attribution. Timing and attribution are never quoted as the same measurement.

## 6. Artefacts

* Harness: `benchmarks/phase_ae/competitive_matrix.py`, `economics.py`, `firebuild_policy_probe.py`,
  `tracejit_integrity_probe.py`, `test_accounting.py`.
* Raw: `benchmarks/results/phaseae/matrix.json` (798 rows, 5 repeats, 8 arms),
  `economics.json`, `policy_probe.json`, `tracejit_integrity.json`.
* Historical Phase AD raw results are untouched under `benchmarks/results/phasead/`.

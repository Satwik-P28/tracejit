# Competitive evaluation (Phase AA)

## Tools examined

| Tool | Role | Available | Version pinned for comparison | Note |
| --- | --- | --- | --- | --- |
| ccache | compiler cache | no | 4.9.1 | absent from this image; no root and no prebuilt static archive. Recorded as unavailable, never scored as slower. |
| sccache | compiler cache | no | 0.8.2 | absent from this image; no root and no prebuilt static archive. Recorded as unavailable, never scored as slower. |
| ninja | build scheduler | no | 1.11.1 | absent from this image; no root and no prebuilt static archive. Recorded as unavailable, never scored as slower. |
| firebuild | process-level build accelerator | no | 0.9.0 | absent from this image; no root and no prebuilt static archive. Recorded as unavailable, never scored as slower. |
| zstd | compression tool | no | 1.5.5 | absent from this image; no root and no prebuilt static archive. Recorded as unavailable, never scored as slower. |
| hyperfine | independent timing harness | yes | 1.19.0 | present and used |
| perf | hardware counters | no | (kernel-tools) | absent from this image; no root and no prebuilt static archive. Recorded as unavailable, never scored as slower. |

ccache, sccache, ninja, firebuild, perf and zstd are absent. No relative-speed claim is made about them: an uninstalled or differently configured tool cannot be compared fairly.

## Ineligible command: what tracing costs when it is refused

`make-build` is refused by TraceJIT on this host. Running it through the wrapper costs 460.1 ms per invocation extra (85.28 ms native vs 545.35 ms traced).

That is the price of attempting to trace a command that is then refused, not a cache result.

## Scheduler versus traced cache, same command

`gcc -O2 -I /tmp/tracejit-realworld-v2/vendor/zlib-1.3.1 -c /tmp/tracejit-realworld-v2/vendor/zlib-1.3.1/adler32.c -o adler32.o (real Makefile rule for adler32.o)`, correct sha256 `dbc636068b611e09…`.

| Situation | make | TraceJIT |
| --- | --- | --- |
| output absent, rebuild | executed, 1162.8 ms total | 897.2 ms total, decisions ['Reused', 'Reused', 'Reused'] |
| output present, rerun | skipped, 28.1 ms total | 963.4 ms total, decision Reused |
| corrupted output | skipped, left corruption (**True**) | Reused, mechanism **restored from cache**, correct after (**True**) |

Corrupting an output retraces for tools that read the existing output (gzip -f, bzip2 -f, objcopy, strip) and restores for tools that only create it (gcc). Both are correct; only the cost differs. Verified across the corpus's output_corruption decisions.

A scheduler that skips work is not doing the same job as a cache that restores verified bytes, and a row that says `executed` is not a restoration result.

## Hyperfine cross-check (independent wall clock)

```json
{
  "available": true,
  "ok": true,
  "results": [
    {
      "command": "gzip -6 -n -c corpus.txt",
      "mean_s": 0.0057963994800000005,
      "median_s": 0.00617305568,
      "stddev_s": 0.0008131750545788675,
      "min_s": 0.004496767180000001,
      "max_s": 0.0066861101800000005
    },
    {
      "command": "env TRACEJIT_CACHE_DIR=/tmp/tracejit-aa-competitive-iw01yl4z/hyperfine-cache /workspace/chats/c69de0f336cb908256cb2092/target/release/tracejit run --json -- gzip -6 -n -c corpus.txt",
      "mean_s": 0.02381384548,
      "median_s": 0.02435309218,
      "stddev_s": 0.0029613189414087874,
      "min_s": 0.01753508118,
      "max_s": 0.02769882518
    }
  ],
  "note": "hyperfine runs through a shell, so its absolute numbers include shell overhead"
}
```

## Cache relocation

TraceJIT hashes the inherited environment into the cache key, and TRACEJIT_CACHE_DIR is part of that environment: moving a cache directory invalidates every record in it. Measured directly in Phase AA.

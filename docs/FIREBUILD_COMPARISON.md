# Firebuild comparison (Phase AD)

Question: does TraceJIT's non-compiler niche survive contact with the closest competing
system, on the same host, with the same pre-states? This document records the installation,
the architecture and guarantee differences that were verified from source, the head-to-head
measurements, and the resulting competitive position. It is written to be falsifiable: every
number comes from `benchmarks/phase_ad/firebuild_compare.py` and
`benchmarks/results/phasead/firebuild_compare.json`.

## 1. Installation (user space, no root)

Firebuild 0.8.2, the version packaged for Ubuntu 24.04 (noble), was extracted from the
distribution debs into a private prefix. No root, no system install, no PPA.

| component | package | sha256 |
| --- | --- | --- |
| binary | `firebuild_0.8.2-1_amd64.deb` | `e8ed7bfd868e33d965d1378e40cfa8d20f2ab154b9fc889b5aecdd958a7987e3` |
| interceptor | `libfirebuild0_0.8.2-1_amd64.deb` | `64268359d59abfc1e30c0be700ef9b28f080a2afe0db8119b7452435d82b41e1` |
| runtime dep | `libconfig++9v5_1.5-0.4build2_amd64.deb` | `2fd37b216b8c8a44e0117f5845ed536ac5cf33ab82eb6165abd136bdfa8bdc78` |
| runtime dep | `libjemalloc2_5.3.0-2build1_amd64.deb` | from `mirror.jmu.edu` |

Installed binary digest (measured): `cffadc1609425775fcacc51f8d5fbd811b229fd0ddf89ab9a0efc7e87000f510`.
Setup cost: two `dpkg-deb -x` extractions plus `LD_LIBRARY_PATH` and an explicit
`-c .../etc/firebuild.conf`. Every arm got its own `$HOME`, because Firebuild's cache lives at
`$HOME/.cache/firebuild`; that isolates arms without guessing an undocumented config key.

Verified working: the second identical invocation of `sh -c 'echo hi > out.txt'` reports
`Hits: 1 / 1 (100.00 %)` and restores the file. Firebuild 0.8.2 writes its `-s` statistics to
**stdout**, so the timed runs never request them (they would corrupt a filter's output); the
statistics are read from a separate, untimed run.

## 2. What Firebuild does, from its own source

* **Interception.** `libfirebuild.so` is injected with `LD_PRELOAD` and interposes libc and
  syscalls (`README.md`; `src/firebuild/config.cc:480-486`). Statically linked binaries cannot
  be intercepted by the 0.8.2 interceptor.
* **Process tree.** Every intercepted process becomes a node in a supervisor-side tree; each
  node gets a fingerprint from its executable, arguments, environment and the observed state
  of the files it used.
* **Dependencies.** Inputs are fingerprinted by content (hash cache) plus the stat attributes
  Firebuild tracks; reads of files under `read_only_locations` (`/usr`, `/lib`, …) are hashed
  without delaying the child.
* **Outputs.** Writes are recorded as file records plus content blobs
  (`execed_process_cacher.cc:780-870`), bounded by `max_entry_size = 250 MB` and
  `max_cache_size = 5 GB` in the shipped config.
* **Reuse.** A "shortcut" replays the recorded process's effects — streams and file contents —
  without executing it. There is no independent validation pass over the recorded inputs at
  reuse time: the fingerprint *is* the lookup key.
* **Inherited descriptors.** Firebuild keeps per-process `FileFD` objects with open flags
  (`src/firebuild/file_fd.h`, `process.cc`), because it must emulate the program's own
  `fcntl` behaviour while replaying. It does not treat a descriptor query as a separate
  guarded dependency; it reproduces the program's recorded behaviour.
* **Timestamps and clocks.** The shipped config enables the `ignore-time-queries` quirk
  (`src/firebuild/message_processor.cc:1164-1168`): clock queries are ignored when deciding
  whether a process may be reused.

## 3. Guarantee differences (measured, not assumed)

| property | TraceJIT (native policy) | TraceJIT (`allocator-entropy-v1`) | Firebuild 0.8.2 |
| --- | --- | --- | --- |
| clock-dependent output | refused (`process read system clock: realtime`) | refused | **reused** by default: `date +%s` and `python3 -c 'time.time_ns()'` both report `Hits: 1/1` and replay the earlier value |
| allocator entropy (glibc malloc) | refused (`process read randomness via getrandom`) | admitted under an audited contract | ignored/absorbed by the interceptor |
| file-output command that sets its output timestamps | admitted | admitted, 10–20× faster than direct | **not cached at all** (see §5) |
| output mutation between runs | guarded, deoptimises | guarded, deoptimises | fingerprint mismatch (re-executes) |
| cache-object validation | every cached object is hashed/validated before exposure | same | blob is read by hash; no post-storage integrity pass was found |
| unsupported syscalls | classified `Unknown` → refused | same, plus contract fixes | interposed or ignored by quirk |

The clock row is the single most important difference. It is not a benchmark artefact:
Firebuild's own configuration calls `ignore-time-queries` a quirk, and the measured behaviour
is that a command whose *entire output* is a clock reading is replayed from cache. TraceJIT
refuses that workload under every policy. A user who wants a stale `date +%s` replayed is
better served by Firebuild; a user who wants "the cached bytes are what a fresh execution
would have produced" is not.

## 4. Same-host results

Four workloads, four arms, identical workspaces and command lines; outputs deleted before each
invocation in both systems. TraceJIT is timed in plain mode (its `--json` report serialises
multi-megabyte stdout as a byte array and would be charged to the product). Medians over five
warm runs; sessions are wall-clock totals in milliseconds.

| workload | arm | cold | warm | reused | cache | 3 | 10 | 25 | 100 |
| --- | --- | ---: | ---: | :--: | ---: | ---: | ---: | ---: | ---: |
| bzip2 -9, 2 MiB file output | native | 218.7 | 232.3 | – | – | 649 | 2259 | 5822 | |
| | tracejit (native) | 302.5 | 309.1 | no | 4.6 MB | 956 | 3102 | 7716 | |
| | tracejit (allocator) | 314.2 | 20.0 | yes | 2.6 MB | 62 | 198 | 519 | |
| | firebuild | 231.0 | 228.9 | **no** | 0 | 680 | 2302 | 5750 | |
| | firebuild (tuned) | 236.0 | 229.5 | **no** | 0 | 709 | 2287 | 5782 | |
| gzip -9, 2 MiB file output | native | 56.7 | 56.6 | – | – | 179 | 601 | 1559 | |
| | tracejit (allocator) | 94.7 | 19.1 | yes | 2.2 MB | 60 | 207 | 499 | |
| | firebuild | 63.2 | 68.4 | **no** | 0 | 219 | 668 | 1715 | |
| gzip -9 -n -c, 256 KiB text | native | 7.6 | 9.0 | – | – | 27 | 92 | 231 | 918 |
| | tracejit (allocator) | 27.6 | 5.0 | yes | 0.12 MB | 15 | 47 | 126 | 486 |
| | firebuild | 14.2 | 6.0 | yes | 0.03 MB | 19 | 62 | 154 | 622 |
| | firebuild (tuned) | 16.0 | 6.6 | yes | small | 19 | 61 | 149 | 639 |
| sed, 200k lines → stdout | native | 101.2 | 73.7 | – | – | 216 | 733 | 1822 | 7359 |
| | tracejit (allocator) | 310.1 | 22.8 | yes | 5.7 MB | 67 | 222 | 702 | 2548 |
| | firebuild | 83.5 | 93.1 | **no** (default `skip_cache`) | 0 | 292 | 903 | 2120 | 8451 |
| | firebuild (tuned) | 96.1 | 17.6 | yes | small | 58 | 175 | 467 | 1982 |

`firebuild (tuned)` clears `processes.skip_cache`, whose shipped default names `sed`, `cp`,
`cat`, `head`, `tail`, `grep`, `tr`, `cut`, `dd`, `touch`, … ("we could cache these but prefer
not to"). That is Firebuild's own default policy, not a defect; the tuned arm exists to keep
the comparison about engines as well as defaults.

## 5. Why Firebuild does not cache the file-output arms

The file-output rows are a measured limitation, not a configuration mistake, and it was
isolated with a controlled pair:

1. A 60-line C program copies a file and does nothing else → Firebuild reuses it (`Hits: 1/1`).
2. The *same program* additionally calls `futimens` on its output → Firebuild never caches it
   (`Misses: 1` on every repetition, `Newly cached: 0.00 kB`).

`gzip -k`, `bzip2 -k` and `objcopy` all set the output's mtime; all three reproduce the second
behaviour. Firebuild 0.8.6's release notes list "Shortcut `touch -r` and similar operations",
which is consistent with this being fixed after 0.8.2 — so the correct statement is:
**Firebuild 0.8.2, the version packaged for this distribution, cannot reuse commands that
preserve timestamps on their outputs.** That is precisely the class TraceJIT handles at 3–20×
the direct cost (2 MiB gzip 3.0×, 2 MiB bzip2 11.6×, 10 MiB gzip 20.3×).

Workspace location matters and was corrected before the final run: Firebuild refuses to cache
a process whose inputs or outputs are under `$TMPDIR` unless they are also under the process
tree's top directory (`execed_process_cacher.cc:588-603`, 845). An earlier version of this
harness ran in `/tmp` and would have manufactured a competitor failure; the reported runs use
a workspace outside `$TMPDIR`.

## 6. Positioning

1. **Is TraceJIT faster on any matched real workload?** Yes, on file-output artifact producers
   (`bzip2 -9`: 519 ms vs 5750 ms for 25 invocations; `gzip -9`: 499 vs 1715), and on large
   stdout artifacts at 10–100 MiB (85 ms vs 288 ms per hit at 100 MiB; see
   `docs/ARTIFACT_BENCHMARKS.md`). Firebuild is faster on cheap stdout filters where its
   default policy caches. At 256 KiB text stdout TraceJIT's hit is 5.0 ms against Firebuild's
   6.0 ms; at 1 MiB incompressible stdout it is 7.7 ms against 21.4 ms; at 100 MiB text stdout
   it is 85.3 ms against 288.2 ms. TraceJIT's advantage grows with the artifact, because
   Firebuild's replay scales with the blob while TraceJIT's BLAKE3 validation of the same bytes
   is cheaper than Firebuild's copy-and-fsync path.
2. **Does TraceJIT offer a distinct correctness capability?** Yes: it refuses clock-dependent
   and entropy-dependent observations that Firebuild absorbs by quirk, and it validates every
   guard before exposing cached bytes. Firebuild's contract is "deterministic commands"; it
   enforces that by assumption and quirk, not by per-execution validation.
3. **Is that capability worth its cost?** Only where the workload is expensive relative to the
   validation: compression/archive generation at ≥1 MiB. For sub-10 ms filters TraceJIT's own
   ground truth (hit 5.0 ms vs direct 7.6 ms) leaves almost nothing to sell.
4. **Does Firebuild dominate the niche?** Not on this host and version: it cannot cache
   timestamp-preserving file outputs at all, and on 100 MiB artifacts TraceJIT's hit is 3.4×
   faster. It does dominate cheap stdout filters with default configuration.
5. **What remains genuinely unexplored?** A correctness-preserving *validated* cache at
   Firebuild's hit cost: TraceJIT's guard/restore path costs 85 ms for a 100 MiB output, of
   which most is content hashing; Firebuild's unvalidated replay costs 288 ms because of its
   blob handling. Neither system demonstrates validated reuse at memcpy speed.

Verdict: no domination, a real and complementary niche, and a measurable correctness
distinction. TraceJIT should claim the artifact-producing niche and the fail-closed contract,
not general-purpose build acceleration.

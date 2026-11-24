# Output-integrity economics: what the repair is worth in a real build

A pinned project (Lua 5.4.6, 34 translation units, 32 in `liblua.a`), built by its
own Makefile, under four arms with byte-identical sources and flags. Twelve
mutation schedules, every arm's artifacts compared against a clean native
reference of the same source state. Evidence:
`benchmarks/results/phaseab/build_integrity.json`; harness
`benchmarks/phase_ab/build_integrity.py`; summariser
`benchmarks/phase_ab/summarize_build.py`.

Arms: `native` (direct `gcc -O2 -c` loop, no make), `make` (the project
Makefile), `ccache` 4.10.2 (`CCACHE_DIR` isolated per arm), `tracejit`
(`CC=tracejit run --contract compiler-runtime-v1 -- gcc`, so each *compiler
invocation* is wrapped, never `make` itself).

## 1. Timing: what each cache is actually worth

Warm = every object deleted, every compile re-issued, no input changed. Medians
of repeated full builds on this host.

| Arm | Cold (empty cache) | Warm full rebuild | Objects from cache |
| --- | ---: | ---: | --- |
| `make` / `native` (no cache) | 7.37–8.20 s | 7.29–8.20 s | — |
| `ccache` 4.10.2 | 8.99 s | **0.19 s** | 32/32 |
| TraceJIT (compiler contract) | 15.3–16.8 s | **3.20 s** | 32/32 |

Per full 32-unit rebuild TraceJIT saves 4.1 s against make and costs 3.0 s more
than ccache. Against a single compile the same ratio holds (7.5× vs 108×,
Phase AA1). Cold tracing is expensive: 15.5 s against 7.4 s, because every
invocation is traced once.

One refused invocation appears in the cold build (`Nondeterministic`, 1/32) and
one in another full rebuild (31/32 hits): that is the temp-name draw of
`docs/COMPILER_ENTROPY_INVESTIGATION.md` at the predicted 4.45 %.

## 2. What each tool promises, and what it does not

| Tool | Decides to act on | Guarantees about an output it did not produce | Repairs a corrupted output it is not consulted about |
| --- | --- | --- | --- |
| `make` | dependency rules and **timestamps** | nothing | no |
| `ccache` | a compiler invocation that actually happens | returns bytes it verified against its own hash | no (not consulted) |
| TraceJIT | a wrapped command that actually happens | restores only after its recorded dependency guards pass, and re-hashes each CAS object | no (not consulted) |

The important consequence: **no tool repairs an artifact that the build system
does not ask it to rebuild.** In the corruption schedules, `make` considered
`lstrlib.o` current (it was newer than its source), issued no compile, and all
three caching arms left the corrupted object in place — `make` in 4–39 ms,
`ccache` and TraceJIT identically. The "integrity" comparison is only meaningful
in the schedule where the compiler runs.

## 3. The schedules, and what happened

Thirty-two units; `bad` counts artifacts that differ from the clean reference.

| Schedule | make | ccache | TraceJIT | Artifacts correct? |
| --- | ---: | ---: | ---: | --- |
| clean build (cold cache) | 7.37 s | 8.99 s | 15.3 s | all arms |
| no-change rebuild | 4.9 ms (no compile) | 3.6 ms | 3.9 ms | all arms |
| warm full rebuild | 7.29 s | 0.19 s | 3.20 s | all arms |
| single source edit | 538 ms | 79 ms | 853 ms (recompiled, no hit: the guard is the input) | all arms |
| shared header edit | 7.76 s | 1.10 s | 16.1 s (one miss + one refusal, rest retraced) | all arms |
| deleted object | 1.73 s | 37.8 ms | 127 ms (1 hit) | all arms |
| corrupted object, then make | 39 ms | 31 ms | 31 ms | **all arms leave it corrupted** |
| corrupted object, forced rebuild | 610 ms | 37.3 ms | 110 ms (1 hit) | object correct in all arms |
| corrupted object, same timestamps, then make | 4.7 ms | 3.9 ms | 5.7 ms | **all arms leave it corrupted** |
| same, forced rebuild | 543 ms | 39.3 ms | 105 ms (1 hit) | object correct in all arms |
| input edit → revert (content restored) | 531 + 541 ms | 69 + 31 ms | 795 + 849 ms | all arms; every arm recomputed |
| cache restart | 4.6 ms | 4.0 ms | 4.0 ms | all arms |
| partial output deletion (`liblua.a`) | 36 ms (ar only) | 31 ms | 29 ms | all arms |
| repeated session (5× one object deleted) | 577 ms each | 33–36 ms | 82–123 ms, 1 hit each | all arms |

Two results deserve to be stated plainly:

1. **A cache only repairs what it is asked to produce.** Make's timestamp rule
   decides that; neither ccache nor TraceJIT changes it. TraceJIT's advertised
   integrity advantage is therefore *not* visible in an ordinary Make build.
2. **Reuse can leave an archive stale where a recompile would not.** After
   TraceJIT restored the correct `lstrlib.o` (1 hit, 110 ms), the object carried
   its recorded — older — mtime, so `ar u`/make saw `liblua.a` as newer and did
   not replace the corrupted member. The object was right; the archive still held
   the corrupted bytes. With `ccache`, the restored object is written fresh
   (newer than the archive), so the archive is updated. This is a real,
   reproducible consequence of timestamp-preserving restoration, and it makes
   TraceJIT *worse* than recompiling for archive-producing builds.

The correction is not "always rewrite timestamps": replaying recorded metadata is
part of the restore contract, and Obs explicitly excludes timestamps from what
reuse must preserve. The sound options are (a) restore to the current time for
outputs whose recorded mtime is older than a dependent product, which is not
observable to TraceJIT, (b) document that a restored output must be treated as
"unchanged" by timestamp-driven build systems, or (c) recommend `make -B`/
`touch` after suspected corruption. Phase AC should pick one; this phase records
the behaviour and does not change restoration.

## 4. The integrity premium

Let `c` be TraceJIT's extra hit cost over ccache (~60 ms per compiler
invocation, ~3.0 s per 32-unit rebuild), `p` the probability that a build
contains a corrupted artifact that the build system *would not* rebuild, and `R`
the cost of discovering and repairing it later.

* If the artifact is not rebuilt, no tool repairs it: TraceJIT's advantage is 0,
  so the premium is `−c` per build.
* If the artifact is rebuilt, TraceJIT and ccache both return verified bytes:
  the advantage over ccache is again 0, so the premium is `−c`.
* The only case where TraceJIT can act and ccache cannot is a workflow with no
  compiler cache at all, where the comparison is against recompiling: there the
  hit saves ~0.4 s per unit and the repair is a side effect of the same hit.

Formally, for a Make-driven build the expected value of choosing TraceJIT *over
ccache* for integrity is `p · (P(repair anyway | TraceJIT) − P(repair anyway |
ccache)) · R − c = 0 − c < 0`. Integrity does not pay for itself as an
increment over an existing compiler cache.

That is the honest answer to "how much is the verification worth": in the build
class where a competitor exists, it is worth less than the time it costs, and it
can leave a *stale archive* that a recompile would have replaced.

## 5. Where the capability is still real

* A repeated **direct** invocation with no build system and no compiler cache:
  TraceJIT restores verified bytes for any command, not only compilers. Measured
  earlier in the corpus at 7–34× on compute-heavy commands.
* Non-compiler commands (`gzip`, `sed`, `sort`, `tar`, `objdump`): ccache and
  make cannot memoize them at all; the restored bytes are verified by hash.
* A guard failure is refused *before* any destination is mutated (Phase AA1's
  staged restore), so a wrong reuse cannot produce a mixed workspace; that is a
  safety property, not a speed one.

None of those needs the "repairs corruption" framing. The defensible claim is
"guarded, verified whole-command reuse", not "output integrity repair".

## 6. Reproducing

```bash
python3 benchmarks/phase_ab/build_integrity.py \
  --tracejit target/release/tracejit \
  --ccache /path/to/ccache \
  --source /path/to/lua-5.4.6.tar.gz \
  --output benchmarks/results/phaseab/build_integrity.json
python3 benchmarks/phase_ab/summarize_build.py \
  benchmarks/results/phaseab/build_integrity.json <scratch-dir>
```

The harness extracts the pinned tarball (sha256 in the JSON), builds a native
reference, runs every scenario for every arm in a fresh byte-identical copy of
the tree, records TraceJIT's own decision for every compiler invocation (and
ccache's own hit/miss counters), and compares every `.o` and every archive
member against the reference.

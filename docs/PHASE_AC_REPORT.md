# Phase AC report

Correctness recovery, output-restoration semantics, metadata guards, a
non-compiler workload study, and concurrent-cache safety.

## 1. Commits

| Stage | Commit |
|---|---|
| Starting research head (Phase AB, PR #44) | `c187cc2c765b2fd5297a33c6407683e5ad555446` |
| Production main the branch is based on | `fd6d0041ae731784c5e9453bff8accca96791ca1` |
| Harness correctness fix (twin metadata) | `be70ce8` |
| Harness regressions + missing validation statuses | `e3d3aae` |
| Cache: deterministic prune-versus-restore tests (production code) | `832358b` |
| Phase AC experiment harnesses and raw measurements | `94ce5ce` |
| This report and the remaining documents | the documentation commit that contains this file |

No product behaviour changed for eligibility, classification, guards, restore
semantics or admission. The only non-test production edit is a test-only fault
hook in `crates/tracejit-cache` (a no-op outside test builds) plus five
regression tests.

## 2. PR #44 status

Open, unmerged. The last externally verified run
([45430554122](https://github.com/Satwik-P28/tracejit/actions/runs/45430554122))
had `smoke` failing on `tar-create`/`cold_mismatch`; that failure is explained
and fixed here (§3). The PR is **not** merged by this phase for two reasons: the
exact-head CI run on this work has not been observed (no authenticated GitHub
access from this environment - `gh` is not logged in and no token is available),
and the release-readiness verdict is unchanged (§16).

## 3. Root cause of the `tar-create` cold mismatch

A benchmark-fixture defect, not a product defect. `qualify` built its two twins
with two separate `corpus.prepare` calls; the bytes were identical but each write
carried a different wall-clock mtime, and `tar -cf` serialises member mtimes into
the archive. Twins prepared inside the same second matched; twins straddling a
second boundary produced different-but-correct archives. The pre-state gate could
not see it because it compares the oracle's *covered* fields, where timestamps are
deliberately advisory.

Measured with the shipped sequence (`benchmarks/phase_ac/tar_mismatch.py`): **81
of 120 runs (67.5 %) mismatched**; every mismatch occurred when input mtimes
differed (51 of 51 staggered trials) and none when they were equal (0 of 9); the
only covered difference was the archive `entry`, and the only differing tar
header field was `mtime`. A native-versus-native control (no TraceJIT at all)
reproduced the same divergence, which proves the effect is independent of traced
execution.

## 4. Was it corrected?

Yes, by fixing the comparison, not by weakening it:

1. prepare the native twin once and clone it with metadata preserved
   (`prepare_twins`), so both twins are identical in every field a program can
   read, while keeping each workload's intended timestamp relationships;
2. gate every row on a metadata-sensitive pre-state comparison
   (`prestate_metadata_mismatch`), so this class of fixture defect fails where it
   is created rather than three steps later;
3. add the missing statuses to the validation contract and schema.

After the fix: **0 of 200** compared runs mismatched. The real CI smoke step,
run locally at this head (`--mode both --policies native,compiler-runtime-v1
--splits dev --reps-scale 0.25`), exits 0, validates, and reports 42 rows =
10 reused / 30 refused / 2 tool-unavailable with **0 cold mismatches and 0
incorrect hits**. Permanent regression: `TwinsShareMetadata` in
`benchmarks/realworld_v2/test_harness.py`.

## 5. Output-restoration semantics

* What is promised: nothing about timestamps (`SAFETY.md`), while the oracle scores
  content/mode/type/link grouping and treats timestamps as advisory.
* What is implemented: exact replay of ownership, mode, atime and mtime for
  regular-file outputs; a record missing either timestamp fails closed.
* Conclusion: timestamp-exact restoration is an **implementation choice**, not a
  documented promise - and it is observable.
* Measured observability: a fixture printing its own output's mtime gets a
  replayed stdout that names the restored mtime (consistent); simulating a fresh
  timestamp on the same hit leaves stdout naming 1795557277 while the file says
  1795557279 (2 s divergence).

Policies evaluated: A preserve (kept), B fresh mtime (rejected - it makes a
replayed observation describe a workspace that no longer exists), C declared
invalidation (no consumer exists), D dependency-graph validation (cannot be made
sound for arbitrary commands), E opt-in build-integration mode (rejected for
V0.3; documented as the only defensible route if demand appears). No semantic
change was merged.

## 6. Stale-archive regression outcome

Reproduced deterministically on **Lua 5.4.6** and **zlib 1.3.1** with the
reachable cache shape (a flags flip over an unchanged tree; a source rewrite
changes `ctime` and correctly deoptimises): the traced rebuild is a **HIT**, the
restored object's bytes are identical to the native object, `make` prints
`is up to date`, `ar` does not run, and the archive keeps the other object
(first differing byte 40). The native control runs `ar` and the archive matches.

Permanent regression: `benchmarks/phase_ac/stale_archive.py --expect documented`
exits non-zero if any of that changes. The limitation and the tested workaround
(touch restored outputs / force the dependent step / cache the whole build) are in
`docs/OUTPUT_RESTORE_SEMANTICS.md` and `docs/LIMITATIONS.md`.

## 7. Metadata-guard changes and soundness evidence

No guard was relaxed. The audit found that every guarded field is observable
(type, mode, size, links, owner, timestamps, inode/device), that ptrace cannot
prove which fields a process read, and that the one sound relaxation already
exists (a paired content hash may absorb metadata drift only when mode, uid and
gid are unchanged).

Adversarial matrix (`benchmarks/phase_ac/metadata_guards.py`, `gzip -9 -c`):
9 mutations, 8 deoptimisations, 1 control hit, **0 incorrect hits**, every
post-mutation observation equal to native. The decisive case: an mtime-only change
on an input deoptimises, and it must, because `gzip` without `-n` writes the
input's mtime into its output header - a "content-equal is enough" guard would
have produced a wrong result.

## 8. Native eligibility before and after

Unchanged, as expected with no guard change:

| Population | Rows | Reused | Refused | Other |
|---|---|---|---|---|
| Frozen corpus baseline (`results/phaseaa1`) | 177 | 28 (15.8 %) | 129 (72.9 %) | 15 tool-unavailable, 5 eligible-no-hit |
| Dev split at this head, both policies | 42 | 10 | 30 | 2 tool-unavailable |
| Phase AC non-compiler corpus | 16 configs | 10 configs reusable | 6 configs refused | 1 eligible-no-hit |

## 9. Useful non-compiler workloads

10 of 16 authentic configurations reuse correctly with real tools and pinned
inputs: `gzip` (stdout and file forms), `bzip2`, `objcopy`, `strip`, `objdump`,
`readelf`, `sed`, `sha256sum`, `base64`. `gzip -9 -n -c` reuses under the
**native** policy with no execution contract at all.

Refused: `xz`, `tar` (inherited-descriptor `fcntl`), `sort` (affinity/`prlimit`),
`awk`, `perl` (clock and `getrandom`). `nm` was eligible but did not hit; cause
not isolated and no saving claimed.

## 10. Actual cumulative savings

Measured sessions against fresh caches, outputs deleted before each invocation:

| Configuration | Policy | break-even | n=3 | n=10 | n=25 |
|---|---|---|---|---|---|
| bzip2 -9, 2 MiB | allocator-entropy-v1 | 1.5 | +48 % | +78 % | **+85 %** (5.50 s -> 0.97 s) |
| gzip -9, 2 MiB | allocator-entropy-v1 | 1.9 | +22 % | +56 % | **+65 %** (1.53 s -> 0.55 s) |
| sed, 200k lines | allocator-entropy-v1 | 4.1 | -29 % | +35 % | **+51 %** (1.91 s -> 1.02 s) |
| gzip -9 -n -c, 256 KiB text | native (no contract) | 11.9 | -105 % | -7 % | +37 % (197 ms -> 158 ms) |

Dominating losses, reported rather than omitted: `objcopy`, `strip`, `readelf`,
`sha256sum`, `base64` are 2-16x slower per hit than native because the 15-50 ms
warm-hit floor exceeds a 2-5 ms command; no break-even exists for them.

## 11. Competitor comparisons

* **ccache**: Phase AB measured a warm 32-unit `make` at 190 ms with ccache versus
  3.20 s with TraceJIT. ccache wins compiler builds; that result is unchanged and
  is not retracted here.
* **Firebuild / Rattle / Bazel / Nix**: compared architecturally, **not measured**.
  Firebuild is the closest system (automatic caching of arbitrary commands) and a
  head-to-head on the three winning configurations is the single highest-value
  missing experiment. No claim of superiority is made.
* **Specialist caches** for `bzip2`, `gzip`, `sed` do not exist, which is why that
  niche is interesting at all.

## 12. Cache concurrency outcomes

The prune-versus-restore window is now deterministically testable via a test-only
hook that mutates a CAS object after its descriptor is open. Five permanent tests:

| Case | Outcome |
|---|---|
| pruned before open | `CorruptObject` -> retrace, destination untouched |
| deleted after open | restore succeeds with the **verified** bytes (unlinked inode) |
| truncated after open | `CorruptObject` -> retrace, destination untouched |
| replaced with different bytes after open | `CorruptObject` -> retrace |
| 4 concurrent restores of one record | all succeed with the cached bytes |

`phase_k4_restore_fault.sh` PASS on both scenarios (soft fail rolls back and
retraces; hard kill mid-apply is refused on the next run and recovers by
re-executing). Model checking: `reuse_hit` 9 states / `restore_crash` 14 states /
`restore_intent` 5 states, 0 violations. No storage-layer redesign.

## 13. Incorrect HITs

**Zero** across every measurement in this phase: the metadata matrix (9 cases),
the twin experiments (200 + 120 runs), the recovered smoke gate (42 rows), the
non-compiler probe (48 policy-cells) and its sessions. The single
"eligible but no hit" (`nm`) is a missed hit, not an incorrect one.

## 14. Full correctness gates

Run at this head:

| Gate | Result |
|---|---|
| `cargo fmt --all -- --check` | pass |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | pass |
| `cargo test --workspace` | pass (40 + 5 + 1 + 85 + 6 + 1 + 1 + 23 + 39 + 54 + 4 + 21 tests; 1 ignored) |
| `cargo test -p tracejit-cli --test linux_integration` | **85/85** |
| `crates/tracejit-cache` restoration suite | **40/40**, including 5 new concurrency tests |
| `scripts/modelcheck/check_state_machines.py` | PASS (0 violations) |
| `scripts/phase_k4_restore_fault.sh` | PASS (soft fail + hard kill) |
| Harness self-tests (`test_harness.py`) | 33/33 |
| Real-world smoke (`runner.py`, dev, both policies) | exit 0, artifact validates, 0 cold/mutation mismatches, 0 incorrect hits |
| Metadata adversarial matrix | 0 incorrect hits |
| Stale-archive regression (`--expect documented`) | pass on Lua and zlib |

Not run or not verifiable here, stated plainly: exact-head GitHub CI (no
credentials), `cargo audit` and the differential fuzzer / Phase W1 / Phase X / Phase Z
harness scripts were not re-run in this phase because no dependency, guard or
runtime-contract code changed (their Phase AB results stand at `c187cc2`, and the
only production edit since is a test-only hook plus tests). `PROVEN`/sandbox paths
still SKIP on this host (no Landlock), unchanged from Phase AB.

## 15. Paper-readiness verdict

**B - a narrow paper on fail-closed whole-command reuse.** The defensible
contribution is the refusal discipline plus measured economics and a heavily
tested failure surface, not a novel caching mechanism and not a general systems
result. There is no head-to-head against Firebuild, no cross-distribution
replication, and the compatibility census covers a minority of commands; each is
named in `docs/PHASE_AC_PAPER_READINESS.md` as work a reviewer would reject
without.

## 16. Release-readiness verdict

**Not qualified for a v0.3 prerelease.** Unchanged from Phase AB, and for the same
blockers plus new information: eligibility is still 28/177 on the frozen corpus;
the version label still describes post-beta code; the validate-to-restore TOCTOU
window is untouched. Phase AC adds a *measured* non-compiler niche (which is
genuinely new and positive) and removes a blocking benchmark failure, but it also
adds a documented semantic limitation (mtime-driven build steps) and confirms that
five of nine representative non-compiler configurations are economically
dominated. No release was published.

## 17. Three highest-value remaining engineering tasks

1. **Head-to-head against Firebuild** on the three winning non-compiler
   configurations, including cold overhead, warm latency and any case where
   Firebuild's optimistic caching replays something TraceJIT refuses. Without it,
   the advantage claim is architectural only.
2. **Close the inherited-descriptor refusal** (`fcntl` on fd 0/1/2) that blocks
   `xz`, `tar`, `zip`, CPython and Node. It is the single largest eligibility
   class in both corpora; a sound guard for a *shared* open file description is
   the hard part, and it must not be solved by ignoring the flags.
3. **Reduce the warm-hit floor** (15-50 ms here) or make admission price it
   correctly. It is the reason small commands are dominated, and it determines
   whether the non-compiler niche widens beyond multi-megabyte artifacts. The
   Phase AB phase-timing data is the place to start; the destination-match
   shortcut was already measured and rejected, so this needs a new idea rather
   than a re-run.

## 18. Primary success condition

Met, narrowly and with measurement: `bzip2 -9` on a 2 MiB artifact (and `gzip -9`,
and `sed` on 200k lines) is a genuine real-world non-compiler workload that
TraceJIT reuses **correctly** (oracle-clean, no incorrect hits) and
**economically** (+85 % over a 25-invocation session, break-even at the second
invocation) under a clearly specified execution contract
(`allocator-entropy-v1`, which fixes the glibc allocator's own entropy probe and
nothing else). `gzip -9 -n -c` achieves a smaller but contract-free version of the
same result.

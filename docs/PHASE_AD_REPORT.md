<!-- Historical record. Superseded by docs/FINAL_CORRECTNESS_CONTRACT.md and
     docs/PHASE_AF_REPORT.md. Statements below about the absence of a Landlock-capable
     environment are host-specific and were true of the hosts named here; a later host in this
     project reports Landlock ABI 8 and the enforcement lifecycle was qualified there. -->

# Phase AD report — competitive validation, descriptor semantics, economic admission

Branch `research/phase-ad`, based on the verified Phase AC head `3f054ed` because PR #44 is
still an unmerged draft (see item 2). Nothing in this phase is merged, released or published.

## 1. Starting and ending commits

| | commit |
| --- | --- |
| start (Phase AC head, branch point) | `3f054ed00031706c64f29b85e00f9e8b1e888069` |
| Phase AC production base | `be70ce8`, `e3d3aae`, `832358b`, `94ce5ce`, `3f054ed` (all on `research/phase-ab`) |
| Phase AD commits | recorded in the final push; `git log 3f054ed..research/phase-ad` |

`origin/main` advanced to `68ba406` independently of this branch while Phase AC was still
unmerged; `research/phase-ad` deliberately does **not** include those commits, so it preserves
the Phase AC corrections it depends on instead of silently dropping them.

## 2. PR #44 status

Open, **draft**, unmerged. Head `3f054ed`, 9 commits, push CI green on that exact head (smoke,
correctness). It is not mergeable from this environment: `gh` is unauthenticated and no token
is available, and the branch is a draft. Its body is still Phase AB-era text. Phase AD therefore
builds on the verified head and does not bypass branch protection.

## 3. Firebuild installation and execution status

Installed and working. Firebuild **0.8.2** from the Ubuntu 24.04 multiverse packages, extracted
into a user prefix with `dpkg-deb -x` (no root): `firebuild` sha256
`e8ed7bfd…a7987e3`, `libfirebuild0` sha256 `64268359…b41e1`, plus `libconfig++9v5` and
`libjemalloc2`. Measured binary digest `cffadc16…f510`. Verified caching: second identical
`sh -c 'echo hi > out.txt'` reports `Hits: 1/1` and restores the file. Two setup traps were
found and fixed in the harness: Firebuild writes `-s` statistics to **stdout**, and it refuses
to cache processes whose files are under `$TMPDIR` (the first harness draft ran in `/tmp` and
would have manufactured a competitor failure). Newer 0.8.6.1 exists; not installed because a
source build needs a toolchain this host does not have and a cross-version comparison would not
be same-binary.

## 4. Competitive performance results

Same host, same pre-states, one workspace per arm, outputs deleted before each invocation.
Wall-clock milliseconds, medians over five warm runs; TraceJIT timed in plain mode.

| workload | native | TraceJIT (allocator) | Firebuild 0.8.2 | Firebuild tuned |
| --- | ---: | ---: | ---: | ---: |
| bzip2 -9, 2 MiB file output — 25 runs | 5822 | **519** | 5750 (no reuse) | 5782 (no reuse) |
| gzip -9, 2 MiB file output — 25 runs | 1559 | **499** | 1715 (no reuse) | 1712 (no reuse) |
| gzip -9 -n -c, 256 KiB text — 100 runs | 918 | 486 | 622 | 639 |
| sed 200k lines — 100 runs | 7359 | 2548 | 8451 (skipped by default) | **1982** |
| gzip -9 -n -c, 100 MiB text — hit cost | 5467 | **85.3** | 288.2 | – |
| gzip -9 -n -c, 100 MiB incompressible — hit | 2852 | **362.2** | 1945.6 | – |

TraceJIT wins the artifact-producing niche outright (Firebuild 0.8.2 cannot cache a command
that sets its output's timestamps), wins on large stdout artifacts, and loses nothing on the
small filter where Firebuild's default config caches: 486 vs 622 ms over 100 invocations.
When Firebuild is explicitly configured to cache `sed`, it beats TraceJIT (1982 vs 2548), which
is reported as a win for the competitor.

## 5. Differences in correctness guarantees

* **Clock-dependent output.** Firebuild's shipped `ignore-time-queries` quirk makes it reuse
  `date +%s` and `python3 -c 'time.time_ns()'` with `Hits: 1/1`, replaying the earlier value.
  TraceJIT refuses both under every policy. This is a contract difference, not a bug in either
  system: Firebuild assumes determinism, TraceJIT verifies it.
* **Allocator entropy.** Firebuild absorbs it; TraceJIT refuses natively and admits only under
  the audited `allocator-entropy-v1` contract.
* **Timestamp-preserving outputs.** Firebuild 0.8.2 does not cache them (isolated with a
  controlled C-program pair differing only by one `futimens` call); TraceJIT caches them with
  full guards.
* **Validation.** TraceJIT re-validates every recorded input before exposing cached bytes;
  Firebuild's fingerprint is the lookup key and no independent validation pass was found.

## 6. Descriptor-guard correctness and eligibility outcomes

Reproduced from stock binaries: `tar` issues `F_GETFD` on fds 0/1/2 (inherited) and then
`F_GETFL`/`F_SETFD` on descriptors it opened; `xz` issues the same `F_GETFD` set plus
`F_GETFL`/`F_SETFL` on its own pipe pair and on inherited stdout. TraceJIT refuses the
descriptor queries and the status-flag changes.

A narrow, sound promotion (`F_GETFD` on inherited descriptors is self-determined because
`FD_CLOEXEC` is descriptor-local and cleared by `exec`; refused when `CLONE_FILES` shares the
table) was implemented, unit-tested and then measured against the frozen census: **0 of 48
eligibility cells changed**. `tar` remains `Nondeterministic` for a realtime clock read and an
unmodelled socket control even with `--mtime`, `--owner`, `--group` pinned; `xz` remains refused
for its pipe status-flag toggles. The change was **reverted** and a unit test now pins the
retained refusal. No new HITs, no compatibility gain, no correctness relaxation.

## 7. Admission-policy results

24-step mixed session (repeated compression, cheap filter, cheap hash, large transform,
changing inputs, permanently ineligible command, one-shot), two repeats, total wall clock:

| arm | total (ms) | HITs |
| --- | ---: | ---: |
| direct | 1638.8 / 1564.1 | – |
| `never` | 1663.3 / 1745.1 | 0 |
| `always` | **1229.3 / 1240.2** | 14 |
| `auto` (default) | 1284.7 / 1292.3 | 4 |
| `auto-v1` | 1279.7 / 1322.9 | 4 |
| retrospective oracle (unattainable) | 653.5 / 631.0 | 14 |

`always` is 3.4–4.2 % better than the default because the threshold rejects 7.6 ms filters;
the default is 25–180 ms better than `never` and avoids the trace premium on one-shots. No
production change: the gap is small and one-host, and an uncertainty-aware policy needs session
history the schema does not keep. Admission never changed a correctness outcome.

## 8. Authentic artifact workload performance

Corpus: Linux 6.6.50 release archive (sha256 `c065e36d…2e86e`, 140 341 000 bytes), sized
prefixes at 1/10/100 MiB in compressible and incompressible flavours. Hit costs:

| workload | 1 MiB | 10 MiB | 100 MiB |
| --- | ---: | ---: | ---: |
| gzip text → stdout (hit vs native) | 6.0 vs 46.0 | 18.2 vs 565.3 | 85.3 vs 5467.6 |
| gzip incompressible → stdout | 7.7 vs 29.9 | 42.1 vs 288.6 | 362.2 vs 2852.4 |
| bzip2 text → stdout | 8.1 vs 75.8 | 19.5 vs 684.7 | not measured |
| gzip text → file | 10.5 vs 51.8 | 28.1 vs 571.9 | not measured |
| sha256sum | 13.1 vs 3.2 (loss) | 18.4 vs 14.5 (loss) | 52.1 vs 86.5 (win) |

Peak RSS 11.4 MB for small outputs, 26.9 MB for a 20 MB text output, 110 MB for a 100 MiB
incompressible output; cache footprint equals captured bytes (19.9 MB / 105 MB).

## 9. Break-even thresholds across artifact sizes

Integer invocation counts (`n* = floor((C−H)/(D−H)) + 1`), not fractional ratios:

| workload | 1 MiB | 10 MiB | 100 MiB |
| --- | ---: | ---: | ---: |
| gzip text → stdout | 2 | 2 | 2 |
| gzip incompressible → stdout | 3 | 2 | 2 |
| bzip2 text → stdout | 2 | 2 | – |
| gzip text → file | 2 | 2 | – |
| sha256sum | never | never | 9 |

Every compression workload repays its trace premium at the second invocation at every size. The
reversal is hash-only work below ~10 MiB, where the hit re-hashes what the command would have
hashed and adds startup.

## 10. TOCTOU findings

The validation-to-restore window is unchanged and still open. The implemented second pass
catches a mutation before it (deterministic injection test passes); no userspace-only mechanism
closes the window against an uncooperative writer. Snapshotting redefines the observable state
rather than closing the race; fd pinning misses in-place rewrites; a cooperative lock is not a
guarantee. A namespace/Landlock freeze is the only complete option and is unavailable here:
`/sys/kernel/security/lsm` reports `capability,selinux` — **no Landlock** — so `PROVEN` remains
unattainable on this host.

## 11. Additional-environment reproduction status

Not achieved. All measurements are from one host: Linux 6.1.102, glibc 2.39, ext4,
x86-64, gcc 13.3.0. GitHub Actions (ubuntu-latest) runs the smoke and correctness gates on the
pushed head and is **supplementary** evidence, not independent third-party reproduction. No
Firebuild comparison, Landlock enforcement or model-check run was attempted elsewhere.

## 12. Incorrect HIT count

**Zero.** Every arm of every experiment was checked against an independent oracle (stdout,
stderr, exit status and workspace tree digest against a native run): Firebuild comparison 20/20
rows correct, artifact scale 30/30 rows correct, admission session all HITs guarded, descriptor
census unchanged, smoke corpus 0 incorrect. The stale-archive regression and the metadata matrix
from Phase AC still pass. No counterexample was removed or weakened.

## 13. Full correctness gates

Run at the final head: `cargo fmt --check`, `cargo clippy --workspace --all-targets
--all-features -D warnings`, `cargo test --workspace`, `linux_integration` (85 tests),
`tracejit-cache` (40 tests incl. fault injection), `test_harness.py` (33), `check_state_machines.py`,
`phase_k4_restore_fault.sh` (both scenarios), `validate.py` on the frozen smoke output, and the
fresh smoke reproduction. `cargo audit` is not installed on this host and is **not** claimed.
Fresh-checkout reproduction is delegated to CI: the workflow builds from scratch and runs the
same commands.

## 14. Accepted and rejected optimisations

Accepted: none in production code. The phase adds harnesses, measurements and documents only.

Rejected with evidence:

| candidate | why rejected |
| --- | --- |
| `F_GETFD` on inherited descriptors → `None` | sound but inert: 0/48 census cells changed; reverted, unit test pins refusal |
| `F_GETFL`/`F_SETFL` on inherited or internal pipes | shared, externally mutable status flags; scheduling-visible; refused |
| modelling `tar`'s clock read | no clock contract exists; `--mtime` does not remove the read |
| metadata-preserving clone / relaxed metadata guards | Phase AC: unjustifiable field precision |
| snapshotting inputs to close TOCTOU | redefines observable state; doubles hit cost |
| cooperative `flock` mode | not a guarantee; new failure mode |
| changing the default admission policy to `always` | 4 % gain on one session vs trace premium on one-shots; unproven |

## 15. Paper-readiness verdict

**B** — a narrow, defensible fail-closed reuse paper with new, same-host competitive evidence
and a genuine scale study. Not a general build-accelerator paper: cheap filters and one-shots
are losses and must be stated in the abstract.

## 16. v0.3 release-readiness verdict

**Not qualified.** Compatibility is unchanged (28/177 frozen rows reuse, no new eligible
configuration), the TOCTOU window is open, `PROVEN` is unenforced on this host, one host and one
Firebuild version are measured, and no independent environment exists. What improved is the
*evidence*: a defensible niche, a measured competitor boundary, integer break-evens, and an
admission cost model.

## 17. Three most valuable remaining tasks

1. **Landlock/namespace-enforced execution path** on a host that can actually install it:
   unlocks `PROVEN`, narrows the TOCTOU window, and is the prerequisite for any stronger claim.
2. **A validated replay fast path** that reaches memcpy-scale hit cost: 85 ms per 100 MiB hit is
   dominated by hashing and restoration; caching verified guard results between runs (with
   invalidation on metadata change) is the only route to beating unvalidated replay.
3. **Cross-version Firebuild comparison (≥0.8.6.1) plus a second host**: the timestamp-output
   limitation is version-specific and may already be fixed; a two-version, two-host table would
   make the competitive claim durable instead of a snapshot.

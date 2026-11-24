# Phase AC: paper readiness

Written as if for systems-conference review: what the evidence supports, what it
does not, and which of the four candidate contributions this project can actually
defend.

## 1. Problem statement

Build and data pipelines repeat identical commands on immutable inputs. Existing
acceleration either requires declared dependency graphs (Bazel, Nix), works only
for compilers (ccache, sccache), or assumes the command is deterministic and
caches anyway (Rattle, Firebuild). None of them offer a general answer to: *may
this command's result be reused at all, and how do we fail when the answer is
unknown?*

TraceJIT's claim is narrower and harder: observe an unmodified Linux command,
classify it, and reuse its whole observable result **only** when classification
and guards make that sound - refusing otherwise, and never exposing a partial
result.

## 2. Threat model

In scope: command nondeterminism (clocks, randomness, process identity, mutable
system information, network); input mutation between runs; concurrent cache
mutation and process death mid-restore; cache-object corruption; environment and
runtime drift; multiple outputs, deletions, symlinks and hard links; metadata
that programs read.

Out of scope, and stated as such: hidden userspace channels that never cross a
syscall; kernels whose ptrace/seccomp/Landlock behaviour differs from the
interfaces assumed; multi-user cache sharing (the cache is not confidential);
multi-file atomic visibility; inode-preserving restore; build-system dependency
graphs.

## 3. Observable-equivalence boundary

Reuse replays, for a whole command: exit status, stdout, stderr, and the
workspace post-state restricted to path set, file type, regular-file content,
permission bits, symlink targets, hard-link grouping, and deletions. For
regular-file outputs TraceJIT also replays ownership and both timestamps, which
is *more* than the oracle scores; that asymmetry is analysed in
`OUTPUT_RESTORE_SEMANTICS.md` and is a real limitation for mtime-driven build
steps.

Metadata of *inputs* is guarded conservatively (full fingerprint plus a content
hash in strict mode); a paired content hash can absorb timestamp drift only when
mode, uid and gid are unchanged. The measured consequence is that an mtime-only
change on an input deoptimises even when content is identical - which is what
makes a metadata-serialising tool (`gzip` without `-n`) correct.

## 4. The mechanism, exactly

1. Trace the command with `ptrace`; record modelled syscalls, file content
   hashes, and output artifacts.
2. Classify: `PROVEN`/`GUARDED` may reuse; `UNKNOWN`, `NONDETERMINISTIC`,
   `EMPIRICALLY_STABLE` may not. Every unmodelled successful syscall is a
   refusal, not a warning.
3. Contract (optional, declared): fix one audited nondeterminism source - the
   glibc allocator's 8-byte `GRND_NONBLOCK` probe, admitted only when the call
   site, the destination mapping and the library image all match a profile - or
   the audited GCC 13.3.0 runtime observations. Contract records are never mixed
   with native ones.
4. On a hit: validate guards once immediately before restore; verify stdout and
   stderr stream objects; stage and digest-verify every output object; write a
   durable restore intent; rename with rollback.
5. On any failure: retrace, or refuse. Never a partial result.

## 5. Correctness assumptions (not proofs)

* ptrace/seccomp/Landlock behave as the interfaces claim; Landlock ABI >= 3.
* BLAKE3 and SQLite do not silently corrupt a record that later rehashes
  successfully.
* No concurrent writer mutates an input between guard validation and restore
  completion.
* The operator does not depend on an unmodelled channel.
* For a content-addressed object, POSIX unlink semantics keep an open descriptor
  readable.

Evidence: 85/85 Linux integration tests, 40 cache tests, model checking of
`reuse_hit` (9 states), `restore_crash` (14 states) and `restore_intent`
(5 states), fault-injection harnesses, and a 9-mutation adversarial metadata
matrix - **0 incorrect hits** in every measurement this phase (frozen corpus,
non-compiler corpus, metadata matrix).

That is test-and-model-check evidence, not a formal proof, and this document does
not claim one.

## 6. Methodology and reproducibility

* Frozen corpus with pinned upstream inputs (`benchmarks/realworld_v2`), twin
  directories, an independent oracle that imports nothing from TraceJIT, and a
  harness whose own self-tests prove the oracle rejects wrong replays.
* Paired timing on randomized order; bootstrap CIs; raw nanosecond samples kept.
* New this phase: a metadata-sensitive pre-state gate that caught a fixture
  defect (the `tar-create` mismatch) before it could be misread as a product bug.
* Reproduction: `benchmarks/realworld_v2/README.md` for the corpus;
  `benchmarks/phase_ac/*.py` for the four new experiments; every claim in this
  phase's documents names the JSON that supports it, and every experiment is
  deterministic enough to be re-run from a fresh checkout.

## 7. Compatibility census (measured)

| Population | Rows | Reused | Refused | Not measurable |
|---|---|---|---|---|
| Frozen corpus, all splits and policies | 177 | 28 (15.8 %) | 129 (72.9 %) | 15 tool-unavailable, 5 eligible-but-no-hit |
| Frozen corpus, tier A / allocator contract | 49 | 10 (20.4 %) | 37 | 1 |
| Frozen corpus, tier A / compiler contract | 49 | 17 (34.7 %) | 30 | 1 |
| Non-compiler corpus, 16 configurations | 48 policy-cells | 10 configurations reusable | 6 configurations refused | 1 config eligible-but-no-hit |

The census is the honest headline: TraceJIT is usable for a minority of ordinary
commands, and the dominant refusal causes are structural (inherited-descriptor
`fcntl`, clocks, `getrandom`, affinity/`prlimit`), not tunable.

## 8. Performance economics (measured)

* Compiler workloads: Phase AB established cold overhead and warm-hit deltas;
  this phase adds nothing there.
* Non-compiler winners: `bzip2 -9` on 2 MiB breaks even at invocation 1.5 and
  saves 85 % of a 25-invocation session; `gzip -9` 65 % at break-even 1.9;
  `sed` over 200k lines 51 % at break-even 4.1; `gzip -n -c` text 37 % at
  break-even 11.9 with **no contract**.
* Non-compiler losers: five configurations where the warm-hit floor
  (15-50 ms) exceeds the whole native runtime (2-5 ms), 2-16x slower at every
  session length. Reported, not hidden.
* Whole-build economics (Phase AB): warm `make` 190 ms with ccache versus 3.2 s
  with TraceJIT at 32/32 hits - i.e. for compiler builds TraceJIT is *not*
  competitive and does not claim to be.

## 9. Negative findings

1. `tar-create` cold mismatch: benchmark fixture timestamps, not a product bug
   (`PHASE_AC_COLD_MISMATCH_AUDIT.md`).
2. Timestamp-exact restore makes build systems that compare mtimes skip archive
   updates (`OUTPUT_RESTORE_SEMANTICS.md`); no safe general fix; documented
   workaround.
3. Field-precise metadata guards cannot be proved sound; the conservative guard
   is load-bearing (an mtime-only input change legitimately changes `gzip`'s
   output).
4. `xz`, `tar`, `sort`, `awk`, `perl` are refused, which removes most
   "data-engineering" candidates from the niche.
5. Small binutils commands are dominated by the warm-hit floor.
6. `nm` is eligible but did not hit; cause not isolated.

## 10. Verdict

**B - a narrower paper on fail-closed whole-command reuse**, not a general
systems paper.

Why B:

* The defensible contribution is the *refusal discipline plus measured
  economics*: a classification that refuses unmodelled effects, a contract
  mechanism with a machine-checked admission argument, a cache whose failure
  modes are among the most heavily tested parts of the system, and an honest
  census showing where that pays and where it does not.
* It is not A: there is no novel mechanism at the scale a general systems paper
  needs (Firebuild already caches arbitrary commands; Rattle already discovers
  dependencies), and the compatibility census is a minority of commands.
* It is not C alone: the negative results are strong, but they are stronger as
  the evaluation section of a paper that also has a working, measured win
  (`bzip2`/`gzip`, compiler contracts) than as a standalone negative-results paper.
* It is not D: the engineering is far enough along - 85 integration tests, model
  checking, fault injection, reproducible benchmarks, two independent real
  projects - that "no publishable contribution" would be wrong.

What a reviewer would reject today, and what to do about it:

1. **No head-to-head against the closest system.** Firebuild was not run. Without
   it, "advantage over existing tools" is architectural. This is the single
   highest-value experiment.
2. **One host, one libc, one toolchain.** No cross-distribution or kernel-version
   evidence; the entropy story in particular is glibc-version specific.
3. **No workload where TraceJIT is the only option.** The winning non-compiler
   cases are ones a general build cache could also serve; the differentiating
   property (fail-closed refusal) is a *safety* claim, and safety claims need
   adversarial evidence at a scale this phase only begins (9 mutations, 5
   concurrency cases).
4. **Timing without confidence intervals** in the non-compiler study (medians of
   five); the frozen corpus has CIs, the new corpus does not.

## 11. What would change the verdict

* A measured win over Firebuild on the same configurations, or a workload class
  where Firebuild's optimistic caching produces a wrong result that TraceJIT
  refuses. Either would justify A.
* Cross-distribution replication of the refusal/eligibility census, which would
  strengthen B substantially.
* A sound field-precise guard mechanism (proving which fields a process observed)
  would be a genuine mechanism contribution; nothing in this phase suggests one
  is close.

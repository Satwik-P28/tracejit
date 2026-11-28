# TraceJIT final research report (Phase AF)

Scope: close the research programme at `v0.3.0-alpha.1`. No new execution contracts, no new
architectural layer, no further phase. This report records what was verified, what changed, what
is still unknown, and where each number comes from.

| item | value |
| --- | --- |
| repository | `github.com/Satwik-P28/tracejit` |
| `main` at the start of this phase | `68ba4067afd4391c90af9a64ce0b43397438d504` |
| research head the phase builds on (PR #45) | `b81242d65e8a02bfe4459506a44b2eca566c5d89` |
| Phase AF branch | `research/phase-af` |
| proposed release | `0.3.0-alpha.1` (research prerelease, not published by this phase) |

---

## 1. Verified upstream evidence

All four workflows were read back from the GitHub API for head `b81242d` (not inferred from a
local run):

| workflow | run | event | conclusion |
| --- | --- | --- | --- |
| CI | `45573894337` | push | success (`validate`) |
| CI | `45573903654` | pull_request | success (`validate`) |
| Real-world benchmark v2 | `45573903647` | pull_request | success (`smoke`, `correctness`; `full` and `competitive` skipped by design) |
| Phase AE environment | `45573903708` | pull_request | success (`probe`) |

PR #45 is **open and draft**, head `b81242d`, base `68ba406`, one bot comment, no human review.
The important correction to Phase AE's §7 and §8 is that the hosted environment **is**
Landlock-capable: kernel `7.0.0-1017-azure`, Ubuntu 24.04.5, glibc 2.39-0ubuntu8.12, Landlock ABI
8, seccomp available, ptrace available. Phase AE's statement that no Landlock-capable environment
existed anywhere is withdrawn.

Two statements must be kept apart, and this report keeps them apart everywhere:

* **CI-hosted reproduction** — a vendor runner executing the project's own workflows. It is real
  execution on a second kernel and a second userland. It is *not* independent third-party
  reproduction.
* **Independent external reproduction** — a person outside this project, on their own hardware,
  following `docs/REPRODUCTION_PACKAGE.md`. **Not achieved.** No such run exists.

## 2. Enforcement qualification

Phase AE could not show an enforced reuse: its probe stopped after two invocations, and the two
invocations it used are the discovery run and the first enforced run. The PR body says so.

Two new pieces of evidence close that gap.

### 2.1 The lifecycle on a capable host

`benchmarks/phase_af/enforcement_lifecycle.py` walks seven steps per arm and asserts the outcome
that the host's capability requires, instead of logging it. Evidence:
`benchmarks/results/phaseaf/enforcement_lifecycle.json`, host kernel 7.0.0-38, Landlock ABI 8,
seccomp available, `doctor` reports `proven=true`.

Read-only arm (`sha256sum`, 1.6 MB corpus, `allocator-entropy-v1`):

| step | decision | class |
| --- | --- | --- |
| 1 discovery execution | `Executed` | `GUARDED` |
| 2 candidate recorded | 1 record, cache populated | — |
| 3 execution under installed policy | `Executed` | **`PROVEN`** |
| 4 classification | — | **`PROVEN`** |
| 5 reuse under enforcement | **`Reused`** | **`PROVEN`** |
| 6 input mutation | `Executed`, `Deoptimized`, new bytes | `GUARDED` |
| 7 re-execution under policy | `Executed` | `PROVEN` |

This is the first enforced HIT measured end to end: a `PROVEN` record created by an enforced
execution and then reused under `--enforce`, with the mutation step producing the new input's
bytes and never the old ones.

Producer arm (`gzip -9 -n -k -f`):

| step | decision | class |
| --- | --- | --- |
| 1 discovery execution | `Executed` | `GUARDED` |
| 2 guarded reuse (artifact removed) | **`Reused`** | `GUARDED` |
| 3 enforced execution | `Executed`, `Deoptimized` | `UNKNOWN` |
| 4 enforced reuse | `Executed`, `Deoptimized` | `UNKNOWN` |

The producer cannot be promoted. The reason is structural, not a missing feature in the harness:

* `policy_from_record` will not assemble a policy while a recorded output is absent, so the
  artifact must exist at candidate time;
* once it exists, `gzip` recreates it with `O_CREAT|O_EXCL`, which fails `EEXIST`, and a failed
  filesystem effect is not modelled, so the run is refused;
* the two requirements are contradictory for this command class.

A parent-directory `REMOVE_FILE|MAKE_REG` grant was implemented and measured to test whether the
Landlock side was the blocker. It was not: the run still fails on its own `EEXIST`, and the grant
widens the policy surface for no benefit. **Reverted**; the refusal is pinned by
`linux_integration::a_producer_that_replaces_an_existing_output_is_not_promoted`.

### 2.2 Permanent positive and negative policy tests

`crates/tracejit-sandbox` now has eight tests, all executed (none skipped) on the capable host:

| test | asserts |
| --- | --- |
| `supported_sandbox_enforces_declared_surface` | declared read allowed; `/etc/passwd` denied; socket denied; ptrace denied |
| `read_and_write_access_are_separate` | a read-only path rejects a write; a writable path accepts one |
| `unexpected_dependency_in_a_declared_directory_is_denied` | an undeclared neighbour of a declared path is unreachable |
| `policy_installation_failure_is_reported` | a policy naming an absent path returns a setup error, never `Ok` |
| `capability_mismatch_refuses_an_inexpressible_policy` | a network-permitting policy is refused |
| `seccomp_filter_alone_denies_its_forbidden_surface` | the filter installs with no ambient `no_new_privs` and denies socket/ptrace |
| `enforcement_refuses_when_landlock_is_absent` | partial enforcement fails closed (skips when Landlock is present) |
| `unsupported_or_partial_sandbox_cannot_prove` | capability reporting cannot claim proof it lacks |

Successful policy installation is never treated as equivalence: every message, and the
certificate text, says the sandbox constrains the child and is not an `Obs` proof.

### 2.3 Making `PROVEN` legible

The reuse path printed no class at all, so a user could reuse a `PROVEN` record without the report
saying the policy had been installed. The plain-mode report now prints
`classified     <class>` on a hit, and `linux_integration` asserts it. The explanation of
`PROVEN` is unchanged and unexpanded: policy installed, not equivalence.

## 3. Benchmark integrity corrections

### 3.1 The headline number

Recomputed from `benchmarks/results/phaseae/economics.json` (cold, `size=25`):

| arm | session total |
| --- | ---: |
| native | 2846.7 ms |
| TraceJIT (`allocator-entropy-v1`) | 545.3 ms |
| Firebuild 0.8.6.2 | 3119.4 ms |

`2846.7 / 545.3 = 5.220×`; `1 − 545.3/2846.7 = 80.84 %`. Phase AD's `5.6×` was arithmetic drift
and is superseded. Firebuild does not reuse this workload (both versions refuse: "Changing file
timestamps is not supported"), so this is an **applicability** result, not a matched replay-engine
comparison. `benchmarks/phase_af/build_tables.py --check` recomputes both quantities and fails if
a document drifts from them.

### 3.2 Break-even, defined four ways

The documents previously used one integer per workload without saying which quantity it was.

* first `n` at which cumulative cost **equals** native;
* first `n` at which cumulative savings are **strictly positive**;
* **measured** break-even at sampled session lengths (3, 10, 25);
* **model** break-even from one cold trace plus steady-state hits.

These differ by one invocation at minimum (at equality the saving is zero, not positive) and by
much more between model and measurement: at 1 MiB incompressible gzip the model gives 3 and the
measured session first shows a saving at 10. Every table in the paper states which of the four it
reports.

### 3.3 Instrumentation inside the timed interval

* **Firebuild.** The corrected harness runs `firebuild -s` to get per-invocation reuse decisions,
  so the statistics formatting and its stdout write are inside the measured interval. The
  statistic block is small (tens of bytes per run) and the write goes to a file or a pipe, but it
  is *not* free and it is part of the measured configuration. It is not subtracted, because
  removing it would remove the evidence that the invocation reused.
* **TraceJIT.** The timing arm runs plain mode; the `--json` channel is calibrated once outside
  the timer, because it serialises the entire cached stdout as a byte array (Phase AA1 measured
  that defect at up to 60 ms on a 70 ms hit). The plain-mode report writes one buffered block after
  the run, and the run's `stdout` is verified per sample; both are part of the measured
  configuration.
* Consequence: the earlier "10–15 % advantage on small stdout" is **not** asserted. The correct
  statement is the one in the claims ledger: TraceJIT was faster on that one 1.2 MiB stdout row,
  Firebuild was faster on file output and on tuned sed, and the intervals do not support a general
  narrow-margin claim.

### 3.4 The verified-replay estimate is a cost model, not a bound

Phase AE wrote that verified replay of 100 MiB "cannot cost less than ≈95 ms". That is wrong as
stated. The figure is a **serial sum of measured component costs** (read, hash, copy, write,
`fsync`) for one implementation that does not overlap them; reads, hashing, copying and writing can
overlap, and the recorded input size (100 MiB) differs from the produced output size (19.9 MB for
text, 100 MiB for incompressible data). It is an estimate used to explain where the measured
257.8 ms goes, not a physical or mathematical lower bound. Every document now says so, and replay
optimisation is not revisited.

## 4. The evaluation package

`benchmarks/phase_af/build_tables.py` regenerates the compatibility census, the competitive
session table, the session-economics table, the break-even table, the artifact-scale table, the
correctness/adversarial table, the capability matrix, and the accepted/rejected optimisation list
from committed JSON. `benchmarks/phase_af/test_tables.py` fails when an evidence file is missing,
when a table has an unknown cell, when the census no longer reconciles, or when the headline
arithmetic disagrees with the rows.

This phase also measured the artifact-scale table on a capable host rather than reusing Phase AD's
prose: `benchmarks/results/phaseaf/artifact_scale.json`, produced by
`benchmarks/phase_ad/artifact_scale.py` over the pinned Linux 6.6.50 release archive at 1 MiB and
10 MiB, `native` and `tracejit-ae` arms.

## 5. Correctness status

Zero incorrect HITs inside the declared contract across every measurement cited here: 798 matrix
rows `all_correct`, the policy probes, the integrity probe, the lifecycle arms, and the
adversarial suites. The counterexamples are retained and are part of the contract:

* the validation-to-restore race (stale bytes after a post-validation mutation);
* timestamp restoration and stale archive members;
* metadata-only observations that deoptimise where a build system would not.

`docs/FINAL_CORRECTNESS_CONTRACT.md` is now the single authority for these; `SAFETY.md`,
`README.md`, `SECURITY.md` and `docs/LIMITATIONS.md` were reconciled against it.

## 6. Version and packaging

`0.3.0-alpha.1` is prepared across `VERSION`, the Cargo workspace, the changelog, the release
notes, and the packaging scripts' version source. The published `v0.2.0-beta.1` tag and its
evidence are untouched. Qualification evidence, including the exact packaging commands, artifact
digests and installer results, is in `docs/RELEASE_QUALIFICATION_V03.md`. **Nothing was published:
the release is prepared for an explicit human decision.**

## 7. Gates: what ran, what did not

See `docs/RELEASE_QUALIFICATION_V03.md` §5 for the command-by-command record. In this environment
the workspace gates, the integration suite, the sandbox enforcement tests, the packaging and
fresh-install path, the claim-integrity tests and the table generation all ran. Not run here, and
not claimed: differential fuzzing, the TLA⁺ model check (`tla2tools` is not installed), Firebuild
re-measurement (no Firebuild on this host), and any workflow read back after this phase's last
push if the push could not be observed.

## 8. What remains unknown

1. **No independent external operator.** The CI environment is a second kernel and userland, not a
   third party. This is the single largest remaining gap and no amount of local work closes it.
2. **One performance host.** Every timing number is from one machine; CI runs correctness, not
   timing.
3. **The residual race.** No userspace-only mechanism both works and is economical. The prerelease
   states the assumption instead of claiming atomicity.
4. **Enforced promotion covers read-only commands, not producers.** The measured niche (artifact
   producers) is the class that `--enforce` cannot promote, for the structural reason in §2.1.
5. **Controlled execution is a 24.04 entitlement.** `allocator-entropy-v1` audits one glibc build.

## 9. Verdict

The research artefact is complete for its current scope: claims match evidence, the benchmark
ledger is recomputed rather than transcribed, enforcement has been exercised on a capable host
with both positive and negative tests, the counterexamples are disclosed, and the paper and
reproduction package exist. The honest description is a **narrow, fail-closed, correct-by-refusal
command cache for repeated generation of stable-input artifacts under controlled execution, with a
documented concurrent-mutation assumption**, not a general accelerator and not a compiler cache.

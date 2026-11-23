# Phase AB plan: from verified evidence to defensible usefulness

Derived only from the Phase AA1 dataset
(`benchmarks/results/phaseaa1/results.json`, commit `1c87e02`) and the Phase AA1
audit. No item below is justified by a synthetic benchmark, and none is a proposal
to raise a speedup number for its own sake. Each item states what it changes, what
it can and cannot make eligible, what it is expected to save, the correctness risk
it carries, and how it would be falsified.

Phase AB must keep the corpus, splits and protocol frozen. Re-running the same
workloads after a product change is the point; changing the workloads is not.

## Ordering

The ordering is by *decision value per unit of risk*, not by speedup:

1. **P1 — deterministic classification for entropy-touching compiler workloads.**
   Without it, timing evidence is not stable and users see random refusals.
2. **P2 — fixed hit overhead (decision persistence and startup).**
   It sets the floor that makes every sub-20 ms command a loss.
3. **P3 — guard-validation cost for compiler workloads.**
   The largest single component of the 60–70 ms compiler hit.
4. **P4 — the output-integrity niche, measured against ccache and make.**
   The only differentiator left after the ccache measurement.
5. **P5 — cache identity vs `TRACEJIT_CACHE_DIR` relocation.**
   A usability defect that silently voids all hits.
6. **P6 — restore/prune race test and TOCTOU statement.**
   Evidence for risks already documented.
7. **P7 — whole-build competitive experiment.**
   Not an optimisation: the experiment that decides whether P1–P3 matter.

---

## P1. Deterministic classification under `getrandom`

**Evidence.** `gcc-cc-small-tu` 94/100 `Guarded`, 6/100 `Nondeterministic`;
`zlib-compile-deflate` 98/100; `gcc-cc-heavy-tu` 100/100 in a focused probe but
refused once during a loaded timing run. The effect is `getrandom` at the gcc
driver's pid, sequence 57 of 323, before `cc1`/`as`. Two timing passes each lost a
different row to it.

**Change.** Not "model `getrandom`". Two candidate designs, to be evaluated:

* *Effect-level*: record the syscall's result and guard it, which is only sound if
  the returned bytes are provably confined to the driver's own hash seed and never
  reach an output. That requires provenance to the syscall result, which the
  current effect model does not carry.
* *Admission-level*: classify such a trace as reproducible under the declared
  compiler contract only when the entropy result is used solely for in-process
  hashing, and document the narrower claim. This is a contract extension, not a
  classifier relaxation.

If neither can be proven, the correct outcome is to keep refusing and to make the
refusal **predictable**: a deterministic pre-flight classification test that says
"this command will refuse on some runs" before a build starts, plus a benchmark
protocol that records a refusal as expected rather than as a lost row.

**Eligibility impact.** Up to 2 % of compiler invocations that currently refuse
would reuse; for `small-tu` at 6 %, up to 6 %. This is small in rate and large in
predictability.

**Expected saving.** A retrace of a 0.1–0.5 s compile at 2–6 % of invocations
averages 2–30 ms per invocation — comparable to the entire hit cost, which is why
this is first.

**Correctness risk.** High. The only unsound version is the tempting one that
treats `getrandom` as ignorable. Any change must be able to explain why two runs
with different kernel entropy produce identical covered observations; the
same-timestamp and rename-source counterexamples are the model for the proof
standard.

**Validation.** 1000-trial classification stability per affected workload; a
25-invocation build session repeated 20 times with the refusal count published; the
existing adversarial matrix; a new case asserting that a build whose entropy
reaches an output is still refused.

---

## P2. Fixed hit overhead: persistence and startup

**Evidence.** Persistence (`post_runtime_ns`) is 3.5–20.2 ms per hit and is
outside `runtime_ns`; process work before the core (`pre_runtime_ns`) is
6.5–16.4 ms. Combined they are 10–36 ms, which is why a 2.1 ms `readelf` hit costs
13.2 ms and a 6.2 ms `gzip` hit costs 8.1 ms.

**Change.** Two independent questions, to be measured separately:

* *Persistence*: is a synchronous decision write required on every hit, or can it
  be batched/omitted when the record is unchanged? Correctness requires that a
  crash cannot leave a record claiming a hit that never happened; the existing
  `restore_intent` machinery is the constraint to preserve.
* *Startup*: 6–16 ms for a binary that does a cache lookup is high. Profile it
  before changing anything; the likely components are dynamic linking, SQLite open,
  and the environment/identity hash.

**Eligibility impact.** None. This moves losses closer to break-even; it makes no
refused command eligible.

**Expected saving.** 5–20 ms per hit if persistence can be cut in half and startup
by a third. That would bring the floor from ~10–17 ms to ~8–13 ms and move
`gzip -6` (8.1 ms warm vs 6.2 ms direct) from 0.77× to roughly parity.

**Correctness risk.** Medium for persistence (durability and crash consistency),
low for startup. Any batching must keep "no record → no hit" and must not resurrect
a record after a failed restore.

**Validation.** Paired timing on the 20 timed rows; a process-kill test at each
persistence point; `restore_intent` state-machine model check; and the rule that a
hit is never counted unless the decision says `Reused`.

---

## P3. Guard-validation cost for compiler workloads

**Evidence.** The measured hit path inside `runtime_ns` is 53.9 ms of a 58.2 ms
runtime for `gcc-cc-heavy-tu`, 63.8 of 70.6 for `adler32`. Phase X already showed
107 MB hashed per compiler hit and rejected digest sharing as unsound.

**Change.** Not "share digests". The sound candidates are: field-precise metadata
guards (stop pinning `atime`, which the command's own read changes), deduplicating
the same file read under different guard kinds by *proving* the read is the same
range and the file is unchanged, and skipping validation of paths that the record
proves were not consulted. Each must be argued per guard kind.

**Eligibility impact.** None directly; it may convert `eligible_but_no_hit` rows
whose `atime` guard deoptimises (`gzip-9-file`, `strip-binary`, `objcopy-strip`)
into stable hits, which is 3 of the 5 no-hit cells.

**Expected saving.** 10–30 ms per compiler hit, i.e. up to 40 % of the hit cost,
and it attacks the 60–70 ms compiler floor that makes small translation units a
loss.

**Correctness risk.** High. Phase X's rejected digest-sharing experiment is the
cautionary case: a same-size rewrite inside one timestamp tick defeats digest
caching, and the counterexample is permanent. Every proposal needs the same
counterexample-based review.

**Validation.** `TRACEJIT_GUARD_PROFILE` byte counts before/after; the same-timestamp
regression; the W1 adversarial matrix; and a new test for whichever guard kind is
made field-precise.

---

## P4. The output-integrity niche, measured

**Evidence.** ccache 4.10.2 is 108× vs TraceJIT's 7.5× on a single compile, with a
14× cheaper hit. TraceJIT's remaining unique capability in this corpus is repairing
a corrupted or deleted output with verified bytes, which `make` and `ccache` do not
do (make skips; ccache is not consulted when the object exists).

**Change.** No product change required to *measure* it. Build the experiment:
a 25-step build, then (a) delete one object, (b) corrupt one object, (c) rewrite an
input header, (d) restore the earlier input state; run native, make, make+ccache,
and make through TraceJIT; report wall time and, for each arm, whether the final
artifacts are byte-identical to a clean build.

**Eligibility impact.** None.

**Expected saving.** Unknown, and that is the point: it is the only claim that could
justify TraceJIT next to ccache, and it has never been measured end to end on a real
build.

**Correctness risk.** None for the experiment. The product risk it exposes is the
TOCTOU window under concurrent modification.

**Validation.** Byte-identical final tree for every arm, plus a false-repair check
(corrupt an output while an input is also modified) and a check that a cache hit
never masks a stale input.

---

## P5. Cache identity and relocation

**Evidence.** `TRACEJIT_CACHE_DIR` is hashed into the execution identity, so moving
a cache produces zero hits (documented in Phase AA, unchanged).

**Change.** Exclude the cache location from the identity, or key records on a
stable cache id. The first is a one-line change with a compatibility question: an
old cache must not become wrongly eligible. The second preserves refusal for old
records.

**Eligibility impact.** Restores all previously recorded eligibility after a move;
zero effect on a fresh cache.

**Expected saving.** Total, for anyone who moves a cache: it turns 0 % hits into the
measured rate.

**Correctness risk.** Low if old records are invalidated explicitly; medium if the
identity is simply narrowed without a version bump.

**Validation.** Relocation test (record, move, hit), old-record refusal test, and a
full-corpus run with the cache under a different path.

---

## P6. Restore/prune race and TOCTOU evidence

**Evidence.** No test races a prune against a restore; 0 stale observations in 4
trials does not close the validate→restore window.

**Change.** Tests, not behaviour: a fault-injection harness that removes or
truncates a CAS object between validation and materialisation, and a statement in
`SAFETY.md` of exactly what a user is exposed to. If a test finds a non-fail-closed
path, fix that path in the same phase.

**Eligibility impact.** None.

**Expected saving.** None. This buys the right to claim "fails closed" as evidence.

**Correctness risk.** None to change; the risk is continuing to ship without the
test.

**Validation.** The new tests, plus the existing `restore_crash` model check with
its two mixed-kill states resolved or explicitly bounded.

---

## P7. Whole-build competitive experiment

**Evidence.** One translation unit is ccache's best case and says nothing about a
mutation-heavy build, where TraceJIT's whole-command view could matter.

**Change.** None. Run a 27–48 invocation build under native, make, make+ccache and
make through TraceJIT across four mutation schedules (no change, one header edit,
repeated edits, return to an earlier state), on one host, with all arms' final
trees verified.

**Why it is last.** It decides whether P1–P3 are worth doing at all; doing it first
would tempt the phase to optimise toward whichever schedule flatters TraceJIT.

**Validation.** Identical final tree across arms; decisions recorded; paired
ratios; ccache configuration published.

---

## Explicitly not planned

* Raising the synthetic `c-numeric` speedup. It is already 30× and no user has that
  command.
* Widening eligibility by adding syscall models that a benchmark likes. Phase AA's
  rule stands: a compatibility feature is justified by a user-visible class of
  commands, not by a corpus score.
* Publishing v0.3. Version labelling, CI verification and the TOCTOU statement are
  release gates, not research tasks.
* Deriving bottleneck percentages from the three spans. They are additive; the
  residual is published, not attributed by guess.

## Top three for Phase AB

1. **P1 — deterministic classification for entropy-touching compiler workloads**,
   because without it neither timing evidence nor user expectations are stable.
2. **P2 — fixed hit overhead**, because a 10–36 ms fixed cost makes every cheap
   command a loss regardless of how fast validation becomes.
3. **P4 — the output-integrity experiment**, because the ccache measurement removed
   the speed argument for compiler workloads and the integrity claim is now the only
   one that could justify the tool.

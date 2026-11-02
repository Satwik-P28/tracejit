# Phase 2D: certified effect noninterference — prior art, threat model, hypothesis

Question: can a command's use of a **dynamic value** be shown to be irrelevant to every externally
observable result, well enough to justify replaying a cached result? The motivating case is the GNU
assembler calling `getrusage(RUSAGE_SELF)` exactly once per compile.

No implementation is proposed here, and nothing in this document changes the classifier. `getrusage`
stays `NONDETERMINISTIC` and compilers stay refused.

## Evidence status of the prior-art claims

Two research passes were run. Many primary sources are PDFs that the tooling could not read, so the
following are marked accordingly and should not be cited as if read in full:

- **[read]** Rattle's README/Hackage page; Jane Street `incremental` interface docs and blog;
  Firebuild README and landing page; `rr` project page and the ATC'17 extended report on arXiv;
  Acar/Blume/Donham ESOP'07 abstract; the *Forward Build Systems, Formally* abstract.
- **[snippet only]** Weiser TSE'84; Korel–Laski; Agrawal–Horgan; Horwitz–Reps–Binkley; Tip's survey;
  Schwartz et al. S&P'10; Yan–Yin SoK; Austin–Flanagan; Acar's thesis; Castor.
- **[unverified]** **Riker**: the ATC'22 PDF could not be fetched (and it is ATC'22, not SEA as
  assumed in the brief). Its per-syscall nondeterminism policy is not established here.
  **Firebuild's** wiki pages on shortcuts and syscall classification were unreachable, so its
  handling of `getrusage` specifically is unverified. **Incr** exists as Jane Street's `Incremental`
  library; a separate "Incr thesis" was not located.

## Prior art, by what it actually guarantees

| System | Unit of reuse | Reuse test | Dynamic read policy | "This read didn't matter"? |
| --- | --- | --- | --- | --- |
| Rattle | whole command | fsatrace file read/write set unchanged | ignore by *assumption* ("providing that if it were deterministic it wouldn't be harmful"); `.rattle.hash` substitution for a shared cache | no — irrelevance is per-command |
| Firebuild | whole command + children | argv, env, observed file set; explicit shortcut eligibility | refuse by contract ("any deterministic command") | no — detection plus configuration |
| Riker | whole command, syscall-traced | observed interactions unchanged **[unverified]** | **[unverified]** | no evidence of a mechanism |
| Incr / `Incremental` | DAG node | `phys_equal` by default, user `set_cutoff` | outside its model (no input capture) | **yes, structurally**: unnecessary nodes are never computed; a cutoff stops propagation |
| `rr` | execution | replay of recorded syscall results | records and replays nondeterminism | no — proves path *identity*, the opposite direction |

Rattle states the position most usefully: reuse is sound "providing that if it were deterministic it
wouldn't be harmful", and commands that produce fresh entropy "aren't relied on" — a normative
assumption about the command's purpose, not an analysis of the value. Firebuild moves the same
assumption into documentation. Incr supplies the missing abstraction — value-level irrelevance with a
propagation cutoff — but explicitly disclaims knowledge of whether user functions have side effects.

From the analysis literature:

- **Dynamic slicing** is computed over one execution trace. Its guarantee is "these statements were
  in the causal chain of this value *on this run*", which is a statement about dependence, not about
  influence on the output, and it says nothing about other inputs.
- **PDG/SDG slicing** gives the right *shape* of proof — no path from the syscall's return to a sink
  — conditional on sound aliasing, a closed-world program model, and a summary of what the syscall
  writes. For a binary calling `getrusage`, the missing piece is the syscall effect model.
- **Dynamic taint** is sound for the explicit data channel of the observed path only under
  conditions that production tools violate by design: every source labelled, propagation closed
  under implicit flows through control dependence, and a fixed definition of "observable". Schwartz
  et al. formalized the semantics; Yan–Yin catalogued under-tainting.
- **Faceted / IFC** gives a real theorem (termination-insensitive noninterference), which explicitly
  does not cover timing — and resource-usage reads are exactly the ones most likely to influence
  timing.
- **Self-adjusting computation** has the only machine-checked statement of the form we want
  ("change propagation is identical to a from-scratch run"), but it is about an instrumented
  semantics of a program, not a shipped binary, and an unused read is not a first-class claim there.
- **Record/replay** provides the apparatus for a differential experiment (replay with perturbed
  syscall results) but not a proof: it shows the same inputs give the same execution, not that a
  different value cannot matter.

**Conclusion of the survey:** no system in this literature certifies that a specific dynamic read is
dead in a shipped binary. The nearest thing is an IFC/PDG argument conditional on a syscall effect
model, and the nearest empirical thing is perturb-and-replay.

## Threat model

Assets: cached stdout, stderr, exit status and output files. Adversary: any process that can change
state between validation and restore, plus the environment itself (clock, scheduler, kernel counters).

Assumptions under attack:

1. **A recorded value is a faithful summary of what the program observed.** Holds for content hashes;
   fails where a fingerprint is coarser or finer than the actual observation (see the directory
   finding in `PHASE2D_ATIME_ANALYSIS.md`, which is this assumption failing in the over-conservative
   direction).
2. **Unrecorded state cannot influence output.** This is what `getrusage` violates: the value *is*
   recorded as a nondeterministic read, and the question is whether it can be *proven* inert.
3. **Substitution preserves the observed value.** If a dynamic read were replaced by a constant, the
   program would take whatever path that constant implies; the reuse is sound only if no path from
   that value reaches an output.

Threats specific to any certificate: under-approximated sinks (a debug counter that is printed only
under `-v`), control dependence, and the timing channel.

## Five candidate approaches

1. **Controlled deterministic substitution under explicit restrictions.** Replace a dynamic read with
   a fixed value for the traced run. Cheap and testable; sound only if the value provably cannot
   reach an output, so it presupposes the analysis it is meant to substitute for. Rejected for this
   phase as a shortcut that would make the contract weaker without saying so.
2. **Dynamic taint / information flow.** Would require instrumenting the binary (or emulating it),
   labelling every byte the kernel writes including `errno` and control dependence, and fixing the
   sink set. Sound only under the conditions above, all of which are violated by ordinary
   implementations. Not attempted; scope is a research project in itself.
3. **Static or binary-level dependence analysis.** The only route to a *proof*, conditional on a
   syscall memory-effect model and complete sinks. For a 93 KB `as` binary this is a substantial
   analysis; the syscall model is the tractable half.
4. **Isolated interpreter/compiler execution profiles.** Treat `getrusage` as a *known-inert* call
   under a named profile with an explicit contract, and make the profile visible in the record and
   the decision. Honest about being an assumption; the risk is that a profile becomes a whitelist by
   another name if it is applied by syscall number rather than by argument and use.
5. **Hybrid: observation plus enforceable certificate.** Record perturbed-replay evidence per
   (program, syscall, argument) and admit reuse only when the evidence covers the observed call, with
   the certificate stored in the record. Empirical, not a proof, but falsifiable and auditable.

## Falsifiable hypothesis (narrow, not yet tested)

> For a fixed tool binary and a fixed set of arguments, if every field of the `struct rusage` returned
> by the single `RUSAGE_SELF` call is replaced by an adversarially chosen value — including
> monotonicity-breaking sequences across repeated calls — and the tool's stdout, stderr, exit status
> and output files are byte-identical across the whole matrix, then that call is inert *for those
> arguments*, and a record may carry an inert-read certificate naming the binary hash, the syscall,
> the argument, and the field matrix tested.

This is falsifiable: one differing output byte, or one field not covered by the matrix, refutes it
for that input. It is explicitly *not* a claim about other arguments, other binaries, or paths not
taken. [UNVERIFIED as a hypothesis: no matrix has been run at this commit. Phase 2C ran four
interventions — zeros, extreme values, a failing call, and `as --statistics` under two extremes —
which is a four-point sample of this matrix, not the matrix.]

## What would count as the research contribution

Not "we skip a syscall". The contribution would be: a record format and decision rule in which every
dynamic read is either replayed, refused, or admitted under a named, auditable, falsifiable
certificate — with the certificate's coverage visible in the decision, so that a reviewer can see
exactly which claim was made. Nothing in this phase demonstrates that; the mechanism and its evidence
do not yet exist.

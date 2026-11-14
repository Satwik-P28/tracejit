# CEGAR-inspired effect refinement

## Status

**Phase E (historical):** workflow types + registry + two recorded cycles with tests.  
**Phase K5 (engine):** input-driven refinement that consumes external counterexample JSON.
Does **not** claim CEGAR itself is novel.  
**rejected** — admitting `getrusage` as dead/ignorable; ignore/whitelist sketches.

## Loop

observe → abstract → counterexample → minimize → refine → retest

### Phase E record types

`tracejit_effects::{run_cycle, directory_opened_refinement, getrusage_refinement_rejected}` with
`proposal_is_safe` refusing “ignore/whitelist” acceptances.

### Phase K5 engine

`tracejit_effects::{refine, classify_hole, minimize, attach_retest, reject_if_unsafe_model}`

- Input: `CounterexampleInput` (title, steps, native/TraceJIT Obs summaries).
- Output: `RefinementProposal` with `HoleKind`, minimized steps, `ProposalAction`, and
  `DeploymentStatus`.
- **Never auto-deploys.** Status is only `BlockedPendingOfflineRetest`,
  `VerifiedOfflineNotDeployed`, or `RejectedUnsafe`.
- CLI: `tracejit refine --input PATH [--retest-pass] [--retest-notes TEXT] [--json]`

Example fixtures: `docs/research/cegar/*.json`.

```bash
cargo build -p tracejit-cli
./target/debug/tracejit refine --input docs/research/cegar/rename_exchange.json
./target/debug/tracejit refine --input docs/research/cegar/directory_mtime.json \
  --retest-pass --retest-notes 'historical Phase 2E'
```

## Registry

`phase_e_registry()` lists semantic entries for modeled classes touched by refinement work
(directory open, getdents, statfs, access, shared anon mmap, hardlink create, allocator
getrandom, clocks, fcntl, `/dev/null` lseek, getrusage). Registry `Nondeterministic` /
`Unknown` / `Unmodeled` statuses veto admit-shaped proposals.

## Worked cycles (Phase E, retained)

1. **DirectoryOpened** (`AcceptProposal`, retest passed historically in Phase 2E): Metadata
   over-abstraction → minimized CE (sibling create) → identity-only directory guard.
2. **getrusage** (`Reject`): perturbation stability on one `as` binary does not certify
   others; stays `NONDETERMINISTIC`.

The K5 engine reproduces these *from input JSON*, rather than as the only code path.

No new product compatibility weakenings in this phase.

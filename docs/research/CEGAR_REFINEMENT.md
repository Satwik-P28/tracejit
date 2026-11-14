# CEGAR-inspired effect refinement (Phase E)

## Status

**implemented+verified** — workflow types + registry + two worked cycles with tests.  
**rejected** — admitting `getrusage` as dead/ignorable.  
Does **not** claim CEGAR itself is novel.

## Loop

observe → abstract → counterexample → minimize → refine → retest

Implemented in `tracejit_effects::{run_cycle, directory_opened_refinement, getrusage_refinement_rejected}` with `proposal_is_safe` refusing “ignore/whitelist” acceptances.

## Registry

`phase_e_registry()` lists semantic entries for modeled classes touched here (directory open, getdents, statfs, access, shared anon mmap, hardlink create, allocator getrandom, clocks, fcntl, `/dev/null` lseek, getrusage).

## Worked cycles

1. **DirectoryOpened** (`AcceptProposal`, retest passed historically in Phase 2E): Metadata over-abstraction → minimized CE (sibling create) → identity-only directory guard.
2. **getrusage** (`Reject`): perturbation stability on one `as` binary does not certify others; stays `NONDETERMINISTIC`.

No new product compatibility weakenings in this phase.

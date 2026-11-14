---- MODULE reuse_hit ----
\* Thin formal model of TraceJIT DISCOVER → VALIDATE → RESTORE → REPLAY.
\* This is a readable state machine mapped to the Rust typestate in
\* crates/tracejit-core/src/lib.rs::reuse_hit. It is NOT a claim that TraceJIT
\* is fully verified.

EXTENDS Naturals, TLC

VARIABLES state, guards_ok, streams_ok, restore_ok, exposed

\* Rust mapping:
\*   DiscoverCandidate  ~ find_candidates + decode + cache_eligible
\*   GuardsPassed       ~ reuse_hit::GuardsPassed::admit
\*   ArtifactsVerified  ~ with_verified_streams + verify_inherited_stream_offsets
\*   Restored           ~ restore_outputs + apply_inherited_stream_offsets
\*   ExposableHit       ~ expose_after_restore
\*   Rejected           ~ continue to next candidate / retrace

TypeOK ==
  /\ state \in {"Idle", "Discovered", "GuardsPassed", "ArtifactsVerified",
                "Restored", "Exposed", "Rejected"}
  /\ guards_ok \in BOOLEAN
  /\ streams_ok \in BOOLEAN
  /\ restore_ok \in BOOLEAN
  /\ exposed \in BOOLEAN

Init ==
  /\ state = "Idle"
  /\ guards_ok = FALSE
  /\ streams_ok = FALSE
  /\ restore_ok = FALSE
  /\ exposed = FALSE

Discover ==
  /\ state = "Idle"
  /\ state' = "Discovered"
  /\ UNCHANGED <<guards_ok, streams_ok, restore_ok, exposed>>

PassGuards ==
  /\ state = "Discovered"
  /\ guards_ok' = TRUE
  /\ state' = "GuardsPassed"
  /\ UNCHANGED <<streams_ok, restore_ok, exposed>>

FailGuards ==
  /\ state = "Discovered"
  /\ guards_ok' = FALSE
  /\ state' = "Rejected"
  /\ exposed' = FALSE
  /\ UNCHANGED <<streams_ok, restore_ok>>

VerifyStreams ==
  /\ state = "GuardsPassed"
  /\ streams_ok' = TRUE
  /\ state' = "ArtifactsVerified"
  /\ UNCHANGED <<guards_ok, restore_ok, exposed>>

FailStreams ==
  /\ state = "GuardsPassed"
  /\ streams_ok' = FALSE
  /\ state' = "Rejected"
  /\ exposed' = FALSE
  /\ UNCHANGED <<guards_ok, restore_ok>>

Restore ==
  /\ state = "ArtifactsVerified"
  /\ restore_ok' = TRUE
  /\ state' = "Restored"
  /\ UNCHANGED <<guards_ok, streams_ok, exposed>>

FailRestore ==
  /\ state = "ArtifactsVerified"
  /\ restore_ok' = FALSE
  /\ state' = "Rejected"
  /\ exposed' = FALSE
  /\ UNCHANGED <<guards_ok, streams_ok>>

Expose ==
  /\ state = "Restored"
  /\ guards_ok = TRUE
  /\ streams_ok = TRUE
  /\ restore_ok = TRUE
  /\ exposed' = TRUE
  /\ state' = "Exposed"
  /\ UNCHANGED <<guards_ok, streams_ok, restore_ok>>

Next ==
  Discover \/ PassGuards \/ FailGuards \/ VerifyStreams \/ FailStreams
  \/ Restore \/ FailRestore \/ Expose

\* Safety: cached bytes are never exposed unless all three obligations succeeded.
Safety ==
  exposed => (guards_ok /\ streams_ok /\ restore_ok /\ state = "Exposed")

====

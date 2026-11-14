---- MODULE restore_crash ----
\* Multi-output restore under soft failure vs hard kill.
\* Soft failure (injected precondition): must roll back to the caller's workspace.
\* Hard kill between renames: may leave a mixed workspace (documented limitation).
\* Re-execution after mixed state must not silently serve a wrong Obs as a hit
\* without guards — modeled here as "next_run_safe" when mixed is detected or
\* destinations are re-validated.
\*
\* NOT a full-system proof. Maps to crates/tracejit-cache restore_outputs.

EXTENDS Naturals, Sequences, TLC

CONSTANTS Outputs  \* e.g. {"a", "b"}

VARIABLES
  phase,           \* "Validate" | "Stage" | "Backup" | "Apply" | "Done" | "RolledBack" | "Killed"
  applied,         \* subset of Outputs already renamed
  caller,          \* caller's bytes tag per output: "user" | "cached"
  workspace,       \* current tags
  exposed,         \* whether cached Obs was exposed to the caller
  kill_armed

TypeOK ==
  /\ phase \in {"Validate", "Stage", "Backup", "Apply", "Done", "RolledBack", "Killed"}
  /\ applied \subseteq Outputs
  /\ caller \in [Outputs -> {"user", "cached"}]
  /\ workspace \in [Outputs -> {"user", "cached"}]
  /\ exposed \in BOOLEAN
  /\ kill_armed \in BOOLEAN

Init ==
  /\ phase = "Validate"
  /\ applied = {}
  /\ caller = [o \in Outputs |-> "user"]
  /\ workspace = [o \in Outputs |-> "user"]
  /\ exposed = FALSE
  /\ kill_armed \in BOOLEAN

AdvancePrep ==
  /\ phase \in {"Validate", "Stage", "Backup"}
  /\ phase' = CASE phase = "Validate" -> "Stage"
               [] phase = "Stage" -> "Backup"
               [] OTHER -> "Apply"
  /\ UNCHANGED <<applied, caller, workspace, exposed, kill_armed>>

ApplyOne ==
  /\ phase = "Apply"
  /\ \E o \in Outputs \ applied :
       /\ applied' = applied \cup {o}
       /\ workspace' = [workspace EXCEPT ![o] = "cached"]
       /\ IF kill_armed /\ applied' # Outputs
            THEN /\ phase' = "Killed"
                 /\ exposed' = FALSE
                 /\ UNCHANGED <<caller, kill_armed>>
            ELSE IF applied' = Outputs
                   THEN /\ phase' = "Done"
                        /\ exposed' = TRUE
                        /\ UNCHANGED <<caller, kill_armed>>
                   ELSE /\ UNCHANGED <<phase, exposed, caller, kill_armed>>

SoftFailRollback ==
  /\ phase = "Apply"
  /\ applied # {}
  /\ applied # Outputs
  /\ ~kill_armed
  /\ phase' = "RolledBack"
  /\ workspace' = caller
  /\ applied' = {}
  /\ exposed' = FALSE
  /\ UNCHANGED <<caller, kill_armed>>

Next == AdvancePrep \/ ApplyOne \/ SoftFailRollback

\* Soft-fail safety: after rollback, workspace matches caller and nothing exposed.
SoftFailSafe ==
  phase = "RolledBack" => (workspace = caller /\ exposed = FALSE)

\* Exposure only after full apply.
ExposeSafe ==
  exposed => (phase = "Done" /\ applied = Outputs
              /\ \A o \in Outputs : workspace[o] = "cached")

\* Hard kill may mix; must not expose.
KillNotExpose ==
  phase = "Killed" => exposed = FALSE

====

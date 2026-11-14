#!/usr/bin/env python3
"""Phase K3 exhaustive checker for TraceJIT hit-path and restore-crash machines.

Does not require TLC. Enumerates the finite state machines described in
`docs/research/formal/reuse_hit.tla` and `restore_crash.tla` and checks the
documented safety invariants.

Exit 0 on pass.
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass
from typing import FrozenSet


# --- reuse_hit ---

HIT_STATES = (
    "Idle",
    "Discovered",
    "GuardsPassed",
    "ArtifactsVerified",
    "Restored",
    "Exposed",
    "Rejected",
)


@dataclass(frozen=True)
class HitState:
    state: str
    guards_ok: bool
    streams_ok: bool
    restore_ok: bool
    exposed: bool


def hit_init() -> HitState:
    return HitState("Idle", False, False, False, False)


def hit_successors(s: HitState) -> list[HitState]:
    out: list[HitState] = []
    if s.state == "Idle":
        out.append(HitState("Discovered", s.guards_ok, s.streams_ok, s.restore_ok, s.exposed))
    if s.state == "Discovered":
        out.append(HitState("GuardsPassed", True, s.streams_ok, s.restore_ok, s.exposed))
        out.append(HitState("Rejected", False, s.streams_ok, s.restore_ok, False))
    if s.state == "GuardsPassed":
        out.append(HitState("ArtifactsVerified", s.guards_ok, True, s.restore_ok, s.exposed))
        out.append(HitState("Rejected", s.guards_ok, False, s.restore_ok, False))
    if s.state == "ArtifactsVerified":
        out.append(HitState("Restored", s.guards_ok, s.streams_ok, True, s.exposed))
        out.append(HitState("Rejected", s.guards_ok, s.streams_ok, False, False))
    if s.state == "Restored" and s.guards_ok and s.streams_ok and s.restore_ok:
        out.append(HitState("Exposed", s.guards_ok, s.streams_ok, s.restore_ok, True))
    return out


def hit_safety(s: HitState) -> bool:
    if not s.exposed:
        return True
    return s.guards_ok and s.streams_ok and s.restore_ok and s.state == "Exposed"


def explore_hit() -> tuple[int, int]:
    seen: set[HitState] = set()
    stack = [hit_init()]
    violations = 0
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if not hit_safety(cur):
            violations += 1
        for nxt in hit_successors(cur):
            if nxt not in seen:
                stack.append(nxt)
    return len(seen), violations


# --- restore_crash ---

OUTPUTS = ("a", "b")


@dataclass(frozen=True)
class RestoreState:
    phase: str
    applied: FrozenSet[str]
    workspace: tuple[str, ...]  # parallel to OUTPUTS: "user"|"cached"
    exposed: bool
    kill_armed: bool


def ws_tuple(mapping: dict[str, str]) -> tuple[str, ...]:
    return tuple(mapping[o] for o in OUTPUTS)


def restore_init(kill_armed: bool) -> RestoreState:
    return RestoreState(
        "Validate",
        frozenset(),
        ws_tuple({o: "user" for o in OUTPUTS}),
        False,
        kill_armed,
    )


def restore_successors(s: RestoreState) -> list[RestoreState]:
    out: list[RestoreState] = []
    ws = {OUTPUTS[i]: s.workspace[i] for i in range(len(OUTPUTS))}
    if s.phase == "Validate":
        out.append(
            RestoreState("Stage", s.applied, s.workspace, s.exposed, s.kill_armed)
        )
    elif s.phase == "Stage":
        out.append(
            RestoreState("Backup", s.applied, s.workspace, s.exposed, s.kill_armed)
        )
    elif s.phase == "Backup":
        out.append(
            RestoreState("Apply", s.applied, s.workspace, s.exposed, s.kill_armed)
        )
    elif s.phase == "Apply":
        remaining = [o for o in OUTPUTS if o not in s.applied]
        for o in remaining:
            applied = set(s.applied)
            applied.add(o)
            ws2 = dict(ws)
            ws2[o] = "cached"
            if s.kill_armed and applied != set(OUTPUTS):
                out.append(
                    RestoreState(
                        "Killed",
                        frozenset(applied),
                        ws_tuple(ws2),
                        False,
                        s.kill_armed,
                    )
                )
            elif applied == set(OUTPUTS):
                out.append(
                    RestoreState(
                        "Done",
                        frozenset(applied),
                        ws_tuple(ws2),
                        True,
                        s.kill_armed,
                    )
                )
            else:
                out.append(
                    RestoreState(
                        "Apply",
                        frozenset(applied),
                        ws_tuple(ws2),
                        s.exposed,
                        s.kill_armed,
                    )
                )
        # soft fail rollback when partially applied and not kill-armed
        if s.applied and s.applied != frozenset(OUTPUTS) and not s.kill_armed:
            out.append(
                RestoreState(
                    "RolledBack",
                    frozenset(),
                    ws_tuple({o: "user" for o in OUTPUTS}),
                    False,
                    s.kill_armed,
                )
            )
    return out


def restore_invariants(s: RestoreState) -> list[str]:
    bad: list[str] = []
    if s.phase == "RolledBack":
        if s.workspace != ws_tuple({o: "user" for o in OUTPUTS}) or s.exposed:
            bad.append("SoftFailSafe")
    if s.exposed:
        if not (
            s.phase == "Done"
            and s.applied == frozenset(OUTPUTS)
            and all(v == "cached" for v in s.workspace)
        ):
            bad.append("ExposeSafe")
    if s.phase == "Killed" and s.exposed:
        bad.append("KillNotExpose")
    return bad


def explore_restore() -> tuple[int, int, list[str]]:
    seen: set[RestoreState] = set()
    stack = [restore_init(False), restore_init(True)]
    violations = 0
    samples: list[str] = []
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        bad = restore_invariants(cur)
        if bad:
            violations += 1
            samples.append(f"{cur} -> {bad}")
        for nxt in restore_successors(cur):
            if nxt not in seen:
                stack.append(nxt)
    return len(seen), violations, samples


# --- restore_intent (P0 §5 / TRA-26 correlation) ---
#
# After hard kill mid-apply, a durable per-pid restore-intent remains. The next
# Cache::open that observes a dead-pid intent must refuse HIT (core execute path)
# rather than expose a partial restore as Reused. Maps to:
#   crates/tracejit-cache::has_interrupted_restore / consume_interrupted_restore
#   crates/tracejit-core interrupted-restore refuse before candidate lookup


@dataclass(frozen=True)
class IntentState:
    writer_alive: bool
    intent_present: bool
    hit_allowed: bool
    exposed: bool


def intent_init() -> list[IntentState]:
    return [
        IntentState(True, False, True, False),
        IntentState(True, True, True, False),  # live peer writer: not interrupted
    ]


def intent_successors(s: IntentState) -> list[IntentState]:
    out: list[IntentState] = []
    if s.writer_alive and not s.intent_present:
        # Begin apply: write intent.
        out.append(IntentState(True, True, True, False))
    if s.writer_alive and s.intent_present:
        # Soft rollback / success clears intent.
        out.append(IntentState(True, False, True, False))
        # Hard kill: writer dies; intent remains.
        out.append(IntentState(False, True, False, False))
        # Live peer completes HIT expose only with clear intent path (model: no expose while intent own).
        out.append(IntentState(True, True, True, False))
    if (not s.writer_alive) and s.intent_present:
        # Next open: refuse HIT, consume intent, re-execute (no expose as HIT).
        out.append(IntentState(False, False, False, False))
        # Illegal: expose HIT while dead intent present.
        out.append(IntentState(False, True, True, True))
    return out


def intent_invariants(s: IntentState) -> list[str]:
    bad: list[str] = []
    # Dead writer + leftover intent ⇒ HIT must not be allowed / exposed.
    if (not s.writer_alive) and s.intent_present and (s.hit_allowed or s.exposed):
        bad.append("IntentRefuseHit")
    if s.exposed and (not s.writer_alive) and s.intent_present:
        bad.append("IntentNoPartialExpose")
    return bad


def explore_intent() -> tuple[int, int, int]:
    seen: set[IntentState] = set()
    stack = list(intent_init())
    violations = 0
    illegal_samples = 0
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        bad = intent_invariants(cur)
        if bad:
            violations += 1
            if "IntentRefuseHit" in bad or "IntentNoPartialExpose" in bad:
                illegal_samples += 1
        for nxt in intent_successors(cur):
            if nxt not in seen:
                stack.append(nxt)
    return len(seen), violations, illegal_samples


def main() -> int:
    hit_n, hit_v = explore_hit()
    print(f"reuse_hit states={hit_n} violations={hit_v}")
    res_n, res_v, samples = explore_restore()
    print(f"restore_crash states={res_n} violations={res_v}")
    for sample in samples[:5]:
        print("  ", sample)
    # Also confirm mixed kill states exist (limitation is real in the model).
    mixed = 0
    stack = [restore_init(True)]
    seen: set[RestoreState] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur.phase == "Killed" and len(set(cur.workspace)) > 1:
            mixed += 1
        for nxt in restore_successors(cur):
            stack.append(nxt)
    print(f"restore_crash mixed_kill_states={mixed} (limitation; must not expose)")
    intent_n, intent_v, intent_illegal = explore_intent()
    # The explorer includes illegal transitions as states that *violate* invariants;
    # we require that those violations are exactly the intentional counterexamples
    # (illegal expose paths), and that every reachable *legal* path has 0 violations
    # outside those planted illegal successors. Count legal states separately.
    legal_violations = 0
    legal_states = 0
    stack2 = list(intent_init())
    seen2: set[IntentState] = set()
    while stack2:
        cur = stack2.pop()
        if cur in seen2:
            continue
        seen2.add(cur)
        # Skip planted illegal expose nodes when tallying legal violations.
        planted_illegal = (
            (not cur.writer_alive) and cur.intent_present and cur.exposed
        ) or (
            (not cur.writer_alive)
            and cur.intent_present
            and cur.hit_allowed
            and cur.exposed
        )
        if planted_illegal:
            continue
        legal_states += 1
        if intent_invariants(cur):
            legal_violations += 1
        for nxt in intent_successors(cur):
            if nxt not in seen2:
                stack2.append(nxt)
    print(
        f"restore_intent states={intent_n} legal_states={legal_states} "
        f"legal_violations={legal_violations} planted_illegal={intent_illegal}"
    )
    ok = (
        hit_v == 0
        and res_v == 0
        and mixed > 0
        and legal_violations == 0
        and intent_illegal > 0
    )
    print(
        "RESULT phase-k3-modelcheck PASS"
        if ok
        else "RESULT phase-k3-modelcheck FAIL"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

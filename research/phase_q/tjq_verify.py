"""Independent plan verifier.

This module deliberately shares no cost arithmetic with the solvers: it recomputes the
objective from the guard list and the declared model, and it checks every structural
obligation a reordering must preserve. A plan that fails here is a correctness
violation, regardless of how good its objective value is.
"""

from __future__ import annotations

from dataclasses import dataclass

from tjq_model import CandidateModel, GuardInstance


@dataclass
class Verdict:
    ok: bool
    violations: list[str]
    recomputed_cost_ns: float | None


def verify_guard_order(
    inst: GuardInstance, order: list[int], claimed_cost_ns: float | None = None
) -> Verdict:
    violations: list[str] = []

    if sorted(order) != list(range(inst.n)):
        missing = set(range(inst.n)) - set(order)
        dupes = len(order) != len(set(order))
        extra = set(order) - set(range(inst.n))
        violations.append(
            f"not a permutation (missing={sorted(missing)}, extra={sorted(extra)}, dup={dupes})"
        )
        return Verdict(False, violations, None)

    pos = {gid: k for k, gid in enumerate(order)}

    # 1. metadata+content blocks must stay adjacent, in recorded order: validate_all
    #    shares one file descriptor across the pair, and the fallback semantics differ.
    for block in inst.blocks:
        positions = [pos[i] for i in block]
        if max(positions) - min(positions) != len(block) - 1:
            violations.append(f"block {inst.guards[block[0]].block} split: {positions}")
        elif positions != sorted(positions):
            violations.append(f"block {inst.guards[block[0]].block} reordered internally")

    # 2. order-dependent guards (inherited-stream offset application) keep their
    #    recorded relative order: the last one applied sets the shared fd offset.
    dependent = [i for i, g in enumerate(inst.guards) if g.order_dependent]
    seq = [pos[i] for i in dependent]
    if seq != sorted(seq):
        violations.append("order-dependent guards were reordered")

    # 3. cost must be recomputed from scratch, not trusted.
    recomputed = _recompute_guard_cost(inst, order)
    if claimed_cost_ns is not None:
        tol = max(1.0, 1e-9 * recomputed)
        if abs(recomputed - claimed_cost_ns) > tol:
            violations.append(
                f"claimed cost {claimed_cost_ns:.3f} != recomputed {recomputed:.3f}"
            )
    return Verdict(not violations, violations, recomputed)


def _recompute_guard_cost(inst: GuardInstance, order: list[int]) -> float:
    """Recompute E[cost] independently: direct loop over latent group states.

    Written without the model's vectorised helpers so a modelling bug cannot agree
    with itself. Singleton groups are marginalised because they touch one guard.
    """
    counts: dict[int, int] = {}
    for guard in inst.guards:
        counts[guard.group] = counts.get(guard.group, 0) + 1
    shared = sorted(g for g, c in counts.items() if c > 1)
    total = 0.0
    for mask in range(1 << len(shared)):
        prob_state = 1.0
        broken = set()
        for bit, gid in enumerate(shared):
            if mask >> bit & 1:
                prob_state *= inst.rho.get(gid, 0.0)
                broken.add(gid)
            else:
                prob_state *= 1.0 - inst.rho.get(gid, 0.0)
        if prob_state == 0.0:
            continue
        expected_paid = 0.0
        reach = 1.0
        for idx in order:
            guard = inst.guards[idx]
            expected_paid += reach * guard.cost_ns
            if counts[guard.group] > 1:
                if guard.group in broken:
                    reach = 0.0
                    break
                reach *= 1.0 - inst.background_prob
            else:
                fails = 1.0 - (1.0 - inst.rho.get(guard.group, 0.0)) * (
                    1.0 - inst.background_prob
                )
                reach *= 1.0 - fails
        total += prob_state * expected_paid
    return total


def verify_candidate_order(
    cand: CandidateModel, order: list[int], claimed_cost_ns: float | None = None
) -> Verdict:
    violations = []
    if sorted(order) != list(range(cand.m)):
        violations.append("candidate order is not a permutation")
        return Verdict(False, violations, None)
    recomputed = 0.0
    survive = 1.0
    for idx in order:
        recomputed += survive * cand.validate_ns[idx]
        survive *= 1.0 - cand.match_prob[idx]
    if claimed_cost_ns is not None and abs(recomputed - claimed_cost_ns) > 1e-6:
        violations.append(
            f"claimed cost {claimed_cost_ns:.3f} != recomputed {recomputed:.3f}"
        )
    return Verdict(not violations, violations, recomputed)


def verify_subset(n_items: int, subset: list[int]) -> Verdict:
    violations = []
    if len(set(subset)) != len(subset):
        violations.append("duplicate item in subset")
    if any(not (0 <= i < n_items) for i in subset):
        violations.append("subset index out of range")
    return Verdict(not violations, violations, None)


def verify_assignment(n_items: int, n_bins: int, assign: list[int]) -> Verdict:
    violations = []
    if len(assign) != n_items:
        violations.append("assignment length mismatch")
    if any(not (0 <= b < n_bins) for b in assign):
        violations.append("bin index out of range")
    return Verdict(not violations, violations, None)

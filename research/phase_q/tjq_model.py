"""Offline cost model for TraceJIT guard and candidate ordering.

The model never decides whether a guard may be skipped. It only decides the order in
which the same guards are validated, so every plan it produces validates a superset-
equivalent set of guards and the reuse decision is unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class Guard:
    gid: int
    name: str
    kind: str  # metadata | content | env | cwd | runtime | dir | stream | prestate
    cost_ns: float
    group: int
    # Guards in the same block must stay adjacent (metadata + content pair sharing an fd).
    block: int
    # Order-dependent guards must keep their recorded relative order.
    order_dependent: bool = False


@dataclass
class GuardInstance:
    """A guard set with a correlated invalidation model.

    Each guard belongs to one *dependency group* (a file, an executable, the runtime).
    A group is invalidated with probability rho (one latent event). When it is
    invalidated every guard of that group fails; guards of a valid group still fail
    independently with `background_prob` (spurious metadata races, permission change).
    """

    name: str
    guards: list[Guard]
    rho: dict[int, float]
    background_prob: float = 1e-4

    def __post_init__(self):
        self._by_id = {g.gid: g for g in self.guards}
        self._group_ids = sorted(self.rho)
        self._cost = np.array([g.cost_ns for g in self.guards], dtype=float)
        self._group = np.array([g.group for g in self.guards], dtype=int)
        self._bg = np.full(len(self.guards), self.background_prob, dtype=float)
        self._block_of = np.array([g.block for g in self.guards], dtype=int)
        # Groups holding more than one guard are genuinely correlated and must be
        # enumerated. A singleton group influences one guard only, so it enters the
        # expectation through its marginal probability and needs no enumeration.
        counts: dict[int, int] = {}
        for g in self.guards:
            counts[g.group] = counts.get(g.group, 0) + 1
        self._multi_groups = sorted(gid for gid, c in counts.items() if c > 1)
        if len(self._multi_groups) > 20:
            raise ValueError(
                f"{len(self._multi_groups)} correlated groups would need "
                f"2^{len(self._multi_groups)} enumeration terms"
            )
        self._single_fail = np.array(
            [
                1.0 - (1.0 - self.rho.get(g.group, 0.0)) * (1.0 - self._bg[i])
                for i, g in enumerate(self.guards)
            ]
        )
        self._is_multi = np.array(
            [g.group in set(self._multi_groups) for g in self.guards]
        )
        # pass_matrix[state, guard] is the probability the guard passes in that latent
        # group state. Deterministic 0 for an invalidated correlated guard. The exact
        # expectation is then a cumulative product along the plan, which keeps solver
        # evaluation cheap without approximating anything.
        states = 1 << len(self._multi_groups)
        pass_matrix = np.empty((states, self.n), dtype=float)
        for state in range(states):
            broken = {
                gid
                for bit, gid in enumerate(self._multi_groups)
                if state >> bit & 1
            }
            for i, g in enumerate(self.guards):
                if self._is_multi[i]:
                    pass_matrix[state, i] = 0.0 if g.group in broken else 1.0 - self._bg[i]
                else:
                    pass_matrix[state, i] = 1.0 - self._single_fail[i]
        self._pass_matrix = pass_matrix
        self._state_prob = np.array(
            [
                np.prod(
                    [
                        self.rho.get(gid, 0.0) if state >> bit & 1 else 1.0 - self.rho.get(gid, 0.0)
                        for bit, gid in enumerate(self._multi_groups)
                    ]
                )
                for state in range(states)
            ]
        )

    # ---- sizes -------------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.guards)

    @property
    def blocks(self) -> list[list[int]]:
        out: dict[int, list[int]] = {}
        for idx, g in enumerate(self.guards):
            out.setdefault(g.block, []).append(idx)
        return [out[k] for k in sorted(out)]

    @property
    def block_costs(self) -> np.ndarray:
        """Raw work in each block: the cost if every guard in it is validated."""
        return np.array([sum(self._cost[i] for i in b) for b in self.blocks])

    @property
    def block_expected_costs(self) -> np.ndarray:
        """Expected work to resolve a block under its fixed internal order.

        A metadata guard that fails means its content hash is never paid, so the sum of
        the block is an overestimate. This is the cost the ordering objective must use.
        """
        fail = self.marginal_failure_prob()
        out = []
        for block in self.blocks:
            survive = 1.0
            expected = 0.0
            for i in block:
                expected += survive * self._cost[i]
                survive *= 1.0 - fail[i]
            out.append(expected)
        return np.array(out)

    @property
    def block_fail_prob(self) -> np.ndarray:
        """Probability that at least one guard of the block fails.

        Guards inside a block usually share one dependency group, so their failures
        are perfectly correlated and the block fails with the group probability, not
        with the union of independent marginals.
        """
        out = []
        for block in self.blocks:
            groups = {self.guards[i].group for i in block}
            if len(groups) == 1:
                gid = next(iter(groups))
                survive = (1.0 - self.rho.get(gid, 0.0)) * (
                    1.0 - self.background_prob
                ) ** len(block)
            else:
                survive = 1.0
                for i in block:
                    survive *= 1.0 - self.marginal_failure_prob()[i]
            out.append(1.0 - min(1.0, survive))
        return np.array(out)

    # ---- marginal failure probabilities ------------------------------------
    def marginal_failure_prob(self) -> np.ndarray:
        p = np.empty(self.n)
        for i, g in enumerate(self.guards):
            p[i] = 1.0 - (1.0 - self.rho.get(g.group, 0.0)) * (1.0 - self._bg[i])
        return p

    # ---- exact expected cost ----------------------------------------------
    def expected_cost(self, order: list[int]) -> float:
        """Exact expected validation cost until the first failing guard (ns).

        E[cost] = sum_k c_k * P(all earlier guards pass). The survival product is
        computed per latent state and averaged with the state probabilities, so this
        is the exact expectation under the model, not a sample average, and costs
        O(2^G_multi * n).
        """
        idx = np.asarray(order, dtype=int)
        # Exclusive prefix product: guard k's cost is paid whenever every *earlier*
        # guard passed, whether or not guard k itself will fail.
        cumulative = np.cumprod(self._pass_matrix[:, idx], axis=1)
        survive_before = np.concatenate(
            [np.ones((cumulative.shape[0], 1)), cumulative[:, :-1]], axis=1
        )
        paid = survive_before * self._cost[idx]
        return float((paid.sum(axis=1) * self._state_prob).sum())

    def expected_cost_independent(self, order: list[int]) -> float:
        """Closed form when the only correlation is within a group (exact too)."""
        p = self.marginal_failure_prob()
        cost = 0.0
        survive = 1.0
        for idx in order:
            cost += survive * self._cost[idx]
            survive *= 1.0 - p[idx]
        return cost

    # ---- sample-average (SAA) objective used by heuristics -----------------
    def sample_scenarios(self, count: int, rng: np.random.Generator) -> np.ndarray:
        """Boolean [count, n] array: True where the guard passes."""
        groups = self._group_ids
        changed = rng.random((count, len(groups))) < np.array(
            [self.rho[g] for g in groups]
        )
        index = {g: j for j, g in enumerate(groups)}
        invalidated = np.zeros((count, self.n), dtype=bool)
        for i, g in enumerate(self.guards):
            invalidated[:, i] = changed[:, index[g.group]]
        spurious = rng.random((count, self.n)) < self._bg
        return ~(invalidated | spurious)

    def scenario_cost(self, order: list[int], scenarios: np.ndarray) -> float:
        costs = self._cost[np.asarray(order)]
        fails = ~scenarios[:, np.asarray(order)]
        # position of first failing guard (n if all pass) -> prefix cost
        first = np.where(fails.any(axis=1), fails.argmax(axis=1), self.n)
        prefix = np.concatenate([[0.0], np.cumsum(costs)])
        return float(prefix[first].mean())


# ---------------------------------------------------------------------------
# TraceJIT's measured guard set, reconstructed from Phase 3C artifacts.
# ---------------------------------------------------------------------------

def measured_guard_instance(
    total_ns: float,
    *,
    changed_asset_rho: float = 0.02,
    verbose: bool = False,
) -> GuardInstance:
    """33-guard shape matching `benchmarks/results/phase3c/latency.json`.

    Guard inventory is the one `compile_guards` builds for a guarded command with
    three file dependencies (metadata+content pairs), an executable pair, environment
    values, cwd, runtime identity, directory opens and an output pre-state. Per-guard
    costs are allocated by kind and then scaled so the total equals the measured
    `guard_validation_ns` for that workload.
    """
    guards: list[Guard] = []
    gid = 0
    block = 0

    def add(name, kind, cost, group, order_dependent=False, new_block=True):
        nonlocal gid, block
        if new_block:
            block += 1
        guards.append(
            Guard(gid, name, kind, float(cost), group, block, order_dependent)
        )
        gid += 1

    # Order below is exactly the order compile_guards emits, which is the current
    # production order: cheap metadata and identity first, content hashes for file
    # dependencies interleaved, environment last.
    add("exe.metadata", "metadata", 30_000, 0)
    add("exe.content", "content", 2_200_000, 0, new_block=False)

    add("cwd", "cwd", 4_000, 1)
    add("runtime", "runtime", 350_000, 2)
    for k in range(8):
        add(f"env.{k}", "env", 2_000, 10 + k)
    add("exe-dep.metadata", "metadata", 30_000, 3)
    add("exe-dep.content", "content", 900_000, 3, new_block=False)

    for a in range(3):
        add(f"asset{a}.metadata", "metadata", 30_000, 20 + a)
        add(f"asset{a}.content", "content", 750_000, 20 + a, new_block=False)

    for m in range(7):
        add(f"stat.{m}.metadata", "metadata", 25_000, 30 + m)
    for d in range(2):
        add(f"dir{d}.opened", "dir", 150_000, 40 + d)
    add("output.prestate", "prestate", 20_000, 50)
    add("symlink", "metadata", 10_000, 51)
    add("stdin.stream", "stream", 120_000, 52, order_dependent=True)
    add("no-unexpected", "prestate", 1_000, 53)

    assert len(guards) == 33, len(guards)
    raw = sum(g.cost_ns for g in guards)
    scale = total_ns / raw
    guards = [
        Guard(g.gid, g.name, g.kind, g.cost_ns * scale, g.group, g.block, g.order_dependent)
        for g in guards
    ]

    rho: dict[int, float] = {}
    for g in guards:
        rho[g.group] = 1e-4
    rho[0] = 0.002  # executable replaced
    rho[3] = 0.002  # interpreter dependency
    for a in range(3):
        rho[20 + a] = changed_asset_rho
    if verbose:
        print(f"instance guards={len(guards)} blocks={len({g.block for g in guards})}")
    return GuardInstance("measured-33", guards, rho)


def random_guard_instance(
    n: int,
    rng: np.random.Generator,
    *,
    n_groups: int | None = None,
    pair_blocks: bool = True,
    rho_scale: float = 1.0,
) -> GuardInstance:
    """Synthetic independent/correlated guard sets for optimality checks."""
    if n_groups is None:
        n_groups = max(1, n // 3)
    guards: list[Guard] = []
    rho = {g: float(np.clip(rng.beta(0.7, 12.0) * rho_scale, 1e-5, 0.9)) for g in range(n_groups)}
    block = -1
    for i in range(n):
        group = int(rng.integers(0, n_groups))
        kind = "content" if (pair_blocks and i % 3) else "metadata"
        cost = float(np.exp(rng.normal(11.0, 1.2)))
        if kind == "content":
            cost *= 8.0
        new_block = not (pair_blocks and i % 3 == 1)
        if new_block:
            block += 1
        guards.append(Guard(i, f"g{i}", kind, cost, group, block))
    return GuardInstance(f"random-{n}", guards, rho)


# ---------------------------------------------------------------------------
# Candidate ordering
# ---------------------------------------------------------------------------

@dataclass
class CandidateModel:
    """Candidates retained for one identity, newest first (production order)."""

    validate_ns: list[int]
    match_prob: list[float]
    name: str = "candidates"

    @property
    def m(self) -> int:
        return len(self.validate_ns)

    def expected_cost(self, order: list[int]) -> float:
        cost = 0.0
        survive = 1.0
        for idx in order:
            cost += survive * self.validate_ns[idx]
            survive *= 1.0 - self.match_prob[idx]
        return cost


def measured_candidate_cost(anchors, m: int) -> float:
    """Per-candidate validation cost implied by the measured scaling fit."""
    del m
    return float(anchors.candidate_per_validation_ms) * 1e6

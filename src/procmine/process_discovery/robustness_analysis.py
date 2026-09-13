"""Problem 2 audit: Pareto dominance, rank-correlation stability
measures, and outlier-robustness checking for the Impact/Feasibility
opportunity score.

Kept as pure functions over already-computed scores/ranks -- none of
this recomputes Impact/Feasibility/Opportunity itself
(`opportunity_scoring.py` already does that); this module only adds
the auditing layer requested on top: is a process actually
non-dominated, how much does the ranking move under different
weightings, and does one process's extreme raw value quietly control
the outcome.
"""

from __future__ import annotations

import statistics


def pareto_frontier(points: dict[str, tuple[float, float]]) -> set[str]:
    """Process ids that are NOT dominated by any other process. `A`
    dominates `B` iff `A`'s impact >= `B`'s impact AND `A`'s feasibility
    >= `B`'s feasibility, with at least one strict inequality -- the
    exact definition given for this audit. A process is on the
    frontier iff no other process dominates it (a process never
    dominates itself, and ties on both dimensions do not count as
    domination either way, so two identical points are both retained)."""
    ids = list(points.keys())
    frontier = set(ids)
    for a in ids:
        ia, fa = points[a]
        for b in ids:
            if a == b:
                continue
            ib, fb = points[b]
            dominates = ib >= ia and fb >= fa and (ib > ia or fb > fa)
            if dominates:
                frontier.discard(a)
                break
    return frontier


def _ranks_from_order(order: list[str]) -> dict[str, int]:
    """1-indexed rank per id, from a list already sorted best-first."""
    return {pid: i + 1 for i, pid in enumerate(order)}


def spearman_rank_correlation(ranks_a: dict[str, int], ranks_b: dict[str, int]) -> float:
    """Spearman's rho, computed as the Pearson correlation of the two
    rank sequences -- exact when there are no tied ranks (true here:
    `rank_processes` always produces a strict total order via its id
    tiebreak), which is the simplest valid way to compute it without a
    dedicated rank-correlation implementation. `ranks_a`/`ranks_b` must
    cover the same id set. A constant rank sequence (a single process)
    has no defined correlation -- returns 1.0, since there is nothing
    to disagree about, matching this project's established convention
    for degenerate single-item comparisons."""
    ids = sorted(ranks_a.keys())
    if set(ids) != set(ranks_b.keys()):
        raise ValueError("both rank dicts must cover the same process set")
    if len(ids) < 2:
        return 1.0
    xs = [ranks_a[pid] for pid in ids]
    ys = [ranks_b[pid] for pid in ids]
    if len(set(xs)) == 1 or len(set(ys)) == 1:
        return 1.0
    return statistics.correlation(xs, ys)


def kendall_tau(ranks_a: dict[str, int], ranks_b: dict[str, int]) -> float:
    """Kendall's tau-a: (concordant - discordant) / total_pairs over
    every unordered pair of processes, comparing whether the two
    ranking's relative order agrees. O(n^2) -- entirely fine at
    Dataset B's scale (21 candidate processes = 210 pairs)."""
    ids = sorted(ranks_a.keys())
    if set(ids) != set(ranks_b.keys()):
        raise ValueError("both rank dicts must cover the same process set")
    n = len(ids)
    if n < 2:
        return 1.0
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a_i, a_j = ranks_a[ids[i]], ranks_a[ids[j]]
            b_i, b_j = ranks_b[ids[i]], ranks_b[ids[j]]
            sign_a = (a_i > a_j) - (a_i < a_j)
            sign_b = (b_i > b_j) - (b_i < b_j)
            if sign_a == sign_b:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 1.0


def ranks_from_scores(scores: dict[str, float]) -> dict[str, int]:
    """Convenience: 1-indexed ranks (best score = rank 1) from a raw
    score dict, using the same descending-score-then-id tiebreak
    `opportunity_scoring.rank_processes` uses, so ranks computed here
    are directly comparable to that function's output."""
    order = sorted(scores.keys(), key=lambda pid: (-scores[pid], pid))
    return _ranks_from_order(order)


def winsorize(values: dict[str, float], limit: float) -> dict[str, float]:
    """Caps each value at the `int(limit * n)`-th smallest and
    `int(limit * n)`-th largest observed values (a symmetric index cap
    around both ends of the sorted distribution, e.g. `limit=0.2` over
    5 values clips using the 2nd-smallest and 2nd-largest) -- the
    standard winsorization idea. `limit` must be in [0, 0.5). Fewer
    than 3 values are returned unchanged (index-based clipping is not
    meaningful on that few points). Caught and fixed during testing: an
    earlier version indexed the high side as `int((1-limit) * n)`,
    which for small n (e.g. n=5, limit=0.2) resolved to the array's own
    last index -- i.e. it "capped" the maximum at itself and clipped
    nothing. The symmetric `n - 1 - lo_idx` form is what actually
    excludes the top `limit` fraction regardless of n."""
    if not (0 <= limit < 0.5):
        raise ValueError("limit must be in [0, 0.5)")
    if len(values) < 3:
        return dict(values)
    sorted_vals = sorted(values.values())
    n = len(sorted_vals)
    lo_idx = int(limit * n)
    hi_idx = max(lo_idx, n - 1 - lo_idx)  # symmetric with lo_idx, not (1-limit)*n -- see below
    lo, hi = sorted_vals[lo_idx], sorted_vals[hi_idx]
    return {k: min(max(v, lo), hi) for k, v in values.items()}

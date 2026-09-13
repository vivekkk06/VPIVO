"""Section 9: a transparent, normalized automation-priority score.

No component is combined in its raw unit (minutes, event counts, and a
0-1 ratio are not comparable on the same scale) -- every component is
min-max normalized to [0, 1] across the set of candidate processes
before being combined, per the assignment's own explicit instruction
not to blindly multiply/sum raw values.

Weights: equal weighting across the six positive factors, and equal
weighting across the two penalty factors, is used as the default --
not because equal weights are known to be correct, but because there is
no labeled outcome data in Dataset B to fit weights against, and equal
weighting is the most defensible, bias-free default absent such
evidence. `scripts/analyze_process_priority_dataset_b.py` runs a
sensitivity sweep over several other reasonable weight assignments and
reports whether the top-ranked process is stable under them -- if it
is, the ranking is not an artifact of this particular weight choice;
if it isn't, that uncertainty is reported rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass


def min_max_normalize(values: dict[str, float]) -> dict[str, float]:
    """0-1 normalization; a constant input (every value equal, or a
    single process) maps everything to 0.5 -- not 0 -- since there is
    no basis to call a value "low" when nothing in the set differs from
    it."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


DEFAULT_WEIGHTS = {
    "frequency": 1.0, "time_impact": 1.0, "manual_effort": 1.0,
    "repetitiveness": 1.0, "feasibility": 1.0, "business_impact": 1.0,
    "risk": 1.0, "complexity": 1.0,
}


@dataclass
class PriorityInputs:
    frequency: float
    time_impact: float
    manual_effort: float
    repetitiveness: float
    feasibility: float
    business_impact: float
    risk: float
    complexity: float


def compute_priority_scores(
    raw: dict[str, PriorityInputs], weights: dict[str, float] = None
) -> dict[str, float]:
    """`raw` maps process_id -> its un-normalized `PriorityInputs`.
    Each of the 8 components is min-max normalized independently across
    every process in `raw` (never against a single process in
    isolation, which would be meaningless), then combined as
    `sum(w * positive_components) - sum(w * penalty_components)`. The
    result is NOT itself renormalized to [0, 1] -- it is a relative
    ranking score, not a probability or percentage, and should be read
    that way (compare processes to each other, not to an absolute
    scale)."""
    weights = weights or DEFAULT_WEIGHTS
    positive_fields = ["frequency", "time_impact", "manual_effort", "repetitiveness", "feasibility", "business_impact"]
    penalty_fields = ["risk", "complexity"]

    normalized = {}
    for field in positive_fields + penalty_fields:
        normalized[field] = min_max_normalize({pid: getattr(v, field) for pid, v in raw.items()})

    scores = {}
    for pid in raw:
        score = sum(weights[f] * normalized[f][pid] for f in positive_fields)
        score -= sum(weights[f] * normalized[f][pid] for f in penalty_fields)
        scores[pid] = score
    return scores

"""Problem 2 investigation: process metrics, variant entropy, and a
two-dimensional (Impact x Feasibility) automation-opportunity score --
the mathematical upgrade path investigated in
`reports/day3/problem2_process_mining_analysis.md`.

This is deliberately a DIFFERENT mathematical form from the existing
`prioritization.compute_priority_scores` (an 8-factor weighted SUM with
two subtracted penalty terms, unbounded above and below zero). Section
12 of the assignment's own instructions requires Impact and Feasibility
to be calculated as separate dimensions first, never collapsed
immediately into one score -- this module keeps them as two named
functions, each returning its own per-process value, with the combined
`Opportunity = Impact * Feasibility` (bounded to [0, 1], since both
factors are already normalized to [0, 1]) computed only afterward, by
a third, explicit function.

Reuses `prioritization.min_max_normalize` rather than a second copy --
the normalization discipline (never combine metrics in raw units) is
identical to the existing approach's, just applied across two named
dimensions instead of eight blended-together fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from procmine.process_discovery.prioritization import min_max_normalize

MANUAL_CATEGORIES = {"input", "pointer", "clipboard"}


def variant_entropy(variant_frequencies: list[int]) -> float:
    """Shannon entropy (bits) of a process's variant-frequency
    distribution: H_p = -sum(q_j * log2(q_j)), q_j = V_j / sum(V).
    0.0 for a single variant (or an empty list) -- a process with only
    one observed shape has zero variability by definition, not
    undefined entropy. Higher values mean more evenly-spread variant
    usage (more behavioral variability); this is a variability
    measurement only -- see the analysis report section 11 for why it
    must not be read as "high entropy = unsafe to automate" on its own."""
    total = sum(variant_frequencies)
    if total == 0:
        return 0.0
    h = 0.0
    for v in variant_frequencies:
        if v == 0:
            continue
        q = v / total
        h -= q * math.log2(q)
    return h


def normalized_variant_entropy(variant_frequencies: list[int]) -> float:
    """H_p / H_max, where H_max = log2(n_variants) -- the entropy a
    process would have if its variants were used perfectly evenly.
    Bounded to [0, 1] regardless of how many variants a process has;
    0.0 for zero or one variant (H_max is 0 there, not a division
    concern -- handled explicitly, not by luck).

    Added after auditing the original `variant_entropy` (raw bits) for
    cross-process comparability: measured directly on Dataset B's own
    21 candidate processes, "Word: Contract Termination Procedure" (7
    variants) shows a HIGHER raw entropy (2.195) than "Word: New
    Contract Procedure" (3 variants, raw entropy 1.500) even though the
    3-variant process is actually MORE evenly spread relative to its
    own maximum possible entropy (0.946 vs. 0.782) -- raw entropy
    conflates "how many variants exist" with "how evenly they're used,"
    which is a real confound once it feeds a cross-process min-max
    normalization step (a process with more variants is not
    automatically more "variable" in the sense Feasibility cares
    about). `variant_entropy` (raw) is kept as-is for reporting
    variability in absolute terms; THIS function is what
    `compute_feasibility_scores` uses for the cross-process comparison,
    since that is where the confound actually matters."""
    n = len(variant_frequencies)
    if n <= 1:
        return 0.0
    h_max = math.log2(n)
    if h_max == 0:
        return 0.0
    return variant_entropy(variant_frequencies) / h_max


def automation_surface(dominant_variant_share: float, avg_manual_event_share: float) -> float:
    """Defined here as `dominant_variant_share * avg_manual_event_share`
    -- both already-measured, independently-validated quantities from
    the existing Day-3 pipeline (`process_profiles_dataset_b.json`),
    naturally bounded to [0, 1] since each factor is. This is a
    DEFINITION, not a third independently-measured raw count: the
    assignment's own formula ("deterministic/repetitive interactions /
    relevant interactions") would require per-execution step-presence
    data this project does not currently compute (which specific manual
    steps recur across *most* executions of a process, versus which are
    one-off) -- stated explicitly here and in the analysis report
    rather than silently approximated as something it isn't. The
    product captures the same intuition the formula was reaching for:
    work that is both (a) part of the process's single most common,
    already-standardized path AND (b) manual/mechanically-actionable in
    type is what a first automation attempt could plausibly reach."""
    return dominant_variant_share * avg_manual_event_share


@dataclass
class ImpactFeasibilityInputs:
    """Raw, un-normalized per-process inputs -- normalized only inside
    `compute_impact_scores`/`compute_feasibility_scores`, never before."""
    frequency_share: float
    time_share: float
    manual_involvement: float  # avg_manual_event_share
    dominant_variant_share: float
    variant_entropy_value: float  # should be NORMALIZED entropy (H/H_max) for cross-process comparability -- see normalized_variant_entropy
    automation_surface_value: float
    complexity_risk: float  # avg_systems_touched_per_execution + n_distinct_interaction_categories


def compute_impact_scores(
    inputs: dict[str, ImpactFeasibilityInputs], weights: dict[str, float] | None = None
) -> dict[str, float]:
    """Impact_p: how much observed frequency, time, and human
    involvement this process represents, relative to the other
    candidate processes in `inputs`. Default equal weighting across the
    three components -- the same "no ground truth to fit differential
    weights against" justification the existing approach already uses,
    reused here rather than re-argued."""
    weights = weights or {"frequency": 1.0, "time": 1.0, "manual": 1.0}
    freq_n = min_max_normalize({pid: v.frequency_share for pid, v in inputs.items()})
    time_n = min_max_normalize({pid: v.time_share for pid, v in inputs.items()})
    manual_n = min_max_normalize({pid: v.manual_involvement for pid, v in inputs.items()})
    total_w = sum(weights.values())
    return {
        pid: (weights["frequency"] * freq_n[pid] + weights["time"] * time_n[pid] + weights["manual"] * manual_n[pid]) / total_w
        for pid in inputs
    }


def compute_feasibility_scores(
    inputs: dict[str, ImpactFeasibilityInputs], weights: dict[str, float] | None = None
) -> dict[str, float]:
    """Feasibility_p: how technically ready this process is for
    automation, relative to the other candidates -- determinism
    (dominant_variant_share), low behavioral variability (1 minus
    normalized entropy), automation surface, and a risk/complexity
    PENALTY (more distinct systems/interaction categories touched per
    execution = harder to automate reliably, so it counts negatively).
    Default equal weighting across all four, same justification as
    `compute_impact_scores`."""
    weights = weights or {"determinism": 1.0, "stability": 1.0, "surface": 1.0, "risk": 1.0}
    determinism_n = min_max_normalize({pid: v.dominant_variant_share for pid, v in inputs.items()})
    entropy_n = min_max_normalize({pid: v.variant_entropy_value for pid, v in inputs.items()})
    surface_n = min_max_normalize({pid: v.automation_surface_value for pid, v in inputs.items()})
    risk_n = min_max_normalize({pid: v.complexity_risk for pid, v in inputs.items()})

    total_w = sum(weights.values())
    scores = {}
    for pid in inputs:
        stability = 1.0 - entropy_n[pid]  # lower entropy -> higher stability contribution
        risk_penalty = 1.0 - risk_n[pid]  # lower risk -> higher feasibility contribution
        raw = (
            weights["determinism"] * determinism_n[pid]
            + weights["stability"] * stability
            + weights["surface"] * surface_n[pid]
            + weights["risk"] * risk_penalty
        )
        scores[pid] = raw / total_w
    return scores


def compute_opportunity_scores(impact: dict[str, float], feasibility: dict[str, float]) -> dict[str, float]:
    """Opportunity_p = Impact_p * Feasibility_p -- multiplicative, per
    the assignment's own candidate formulation, and bounded to [0, 1]
    since both factors already are (unlike the existing approach's
    additive-minus-penalties score, which has no fixed bound). Both
    dicts must have the same key set."""
    if set(impact.keys()) != set(feasibility.keys()):
        raise ValueError("impact and feasibility must be scored over the same process set")
    return {pid: impact[pid] * feasibility[pid] for pid in impact}


def rank_processes(scores: dict[str, float]) -> list[str]:
    """Process ids sorted by descending score (ties broken by id for
    determinism)."""
    return sorted(scores.keys(), key=lambda pid: (-scores[pid], pid))

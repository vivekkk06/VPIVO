"""Stage 8.5: additive protection layer over Stage 8.3's Design 2 output.

Does NOT modify `reconstruction.py` or its rule engine in any way. This
module operates strictly as a post-processing step over an already-
computed `ReconstructionResult`: for every transition Rule 4 demoted, it
optionally overrides the decision to KEEP if a protection condition is
satisfied, built only from the two raw-event-derived, GT-free signals
Stage 8.4 found (cross-model agreement, post-transition tempo). Every
other rule's decision (1, 2, 3) — and every transition that was never a
candidate at all — passes through completely untouched. Protection can
only turn a DEMOTE into a KEEP; it can never demote something Design 2
kept, and it can never create a boundary that was never a V1/V2
candidate in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass

from procmine.segmentation.reconstruction import RULE_4_CONTINUITY

STRATEGY_AGREEMENT = "agreement"  # flagged by both V1 and V2
STRATEGY_TEMPO = "tempo"  # post-transition tempo (after_window_duration_ms) >= threshold
STRATEGY_COMBINED = "combined"  # both conditions together
ALL_STRATEGIES = (STRATEGY_AGREEMENT, STRATEGY_TEMPO, STRATEGY_COMBINED)

RULE_4_PROTECTED = "rule4_protected"


@dataclass
class ProtectionResult:
    final_boundary: list[bool]
    rule_applied: list[str]

    def to_dict(self) -> dict:
        return {"final_boundary": self.final_boundary, "rule_applied": self.rule_applied}


def apply_protection(
    design2_final_boundary: list[bool],
    design2_rule_applied: list[str],
    flagged_by_both: list[bool],
    tempo_value: list[float | None],
    strategy: str,
    tempo_threshold: float | None = None,
) -> ProtectionResult:
    """`design2_final_boundary`/`design2_rule_applied` are Stage 8.3's own,
    unmodified `apply_design2_rules(...)` output — passed in, not
    recomputed. A transition is eligible for protection only if Design 2
    itself demoted it under Rule 4 specifically
    (`rule_applied[i] == RULE_4_CONTINUITY and not final_boundary[i]`);
    every other transition (kept by any rule, demoted by Rule 1/2, or
    never a candidate at all) is returned exactly as Design 2 left it.
    `tempo_value[i] is None` is treated the same conservative way Design
    2 treats a missing jaccard value: insufficient evidence, no
    protection."""
    n = len(design2_final_boundary)
    if len(design2_rule_applied) != n or len(flagged_by_both) != n or len(tempo_value) != n:
        raise ValueError("all arrays must be the same length")
    if strategy not in ALL_STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy!r}")
    if strategy in (STRATEGY_TEMPO, STRATEGY_COMBINED) and tempo_threshold is None:
        raise ValueError(f"strategy {strategy!r} requires tempo_threshold")

    final_boundary = list(design2_final_boundary)
    rule_applied = list(design2_rule_applied)

    for i in range(n):
        if design2_rule_applied[i] != RULE_4_CONTINUITY or design2_final_boundary[i]:
            continue  # not a Rule-4 demotion -- left untouched

        if strategy == STRATEGY_AGREEMENT:
            protect = bool(flagged_by_both[i])
        elif strategy == STRATEGY_TEMPO:
            protect = tempo_value[i] is not None and tempo_value[i] >= tempo_threshold
        else:  # STRATEGY_COMBINED
            protect = bool(flagged_by_both[i]) and (
                tempo_value[i] is not None and tempo_value[i] >= tempo_threshold
            )

        if protect:
            final_boundary[i] = True
            rule_applied[i] = RULE_4_PROTECTED

    return ProtectionResult(final_boundary=final_boundary, rule_applied=rule_applied)

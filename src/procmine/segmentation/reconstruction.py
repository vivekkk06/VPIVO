"""Stage 8.3: Design 2 — the approved deterministic, neighborhood-aware
reconstruction rule engine.

Implements exactly the architecture approved in Stage 8.2: reconstruction
may only DEMOTE candidate boundaries already predicted by V1 or V2 — it
never invents a new one. The decision unit is one candidate transition;
the ordered rule list (chunk/noise override -> leave-and-return ->
cluster protection -> N=10 continuity fallback) is applied per
transition, using only held-out model predictions, raw-event-derived
features, and the existing N=10 trajectory/return-pattern tooling from
Stages 5/8 — never GT (case_id, process_code, execution spans, boundary
or continuity labels). GT is only used afterward, by the evaluation
script, to score the result.

`return_pattern_evidence_for_transition` is a deliberate, documented
departure from Stage 8's own `detect_return_patterns` usage: Stage 8
scoped its search by GT execution span (fine for forensic
characterization, GT-only). A live reconstruction decision cannot do
that. Here the search is scoped by a fixed +/- N event window centered
on the candidate transition, reusing Stage 5's already-validated N=10
window size rather than inventing a second window-size concept. Known,
stated limitation: an away-period longer than roughly N events on a
side will not be found by this check (see the Stage 8.3 report).
"""

from __future__ import annotations

from dataclasses import dataclass

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.interruption_forensics import detect_return_patterns

RULE_NONE = "none"
RULE_1_CHUNK_NOISE = "rule1_chunk_noise"
RULE_2_RETURN_PATTERN = "rule2_return_pattern"
RULE_3_CLUSTER_PROTECTION = "rule3_cluster_protection"
RULE_4_CONTINUITY = "rule4_continuity"
DESIGN1_RULE_CHUNK_NOISE = "design1_chunk_noise"
DESIGN1_RULE_CONTINUITY = "design1_continuity"


def union_candidates(v1_predicted: list[bool], v2_predicted: list[bool]) -> list[bool]:
    """The approved candidate set C = V1 predictions UNION V2 predictions.
    Reconstruction only ever removes members of this set; nothing outside
    it is ever considered."""
    if len(v1_predicted) != len(v2_predicted):
        raise ValueError("v1_predicted and v2_predicted must be the same length")
    return [a or b for a, b in zip(v1_predicted, v2_predicted)]


def cluster_size_per_transition(candidates: list[bool]) -> list[int]:
    """For each index, the length of the run of consecutive `True` values
    it belongs to in `candidates`, or 0 if it is not itself a candidate.
    A run of length 1 is an isolated candidate; length >= 2 is a
    cluster."""
    n = len(candidates)
    sizes = [0] * n
    i = 0
    while i < n:
        if candidates[i]:
            j = i
            while j < n and candidates[j]:
                j += 1
            run_len = j - i
            for k in range(i, j):
                sizes[k] = run_len
            i = j
        else:
            i += 1
    return sizes


def involves_duplicate_app_switch(
    event_i_id: str, event_next_id: str, duplicate_app_switch_ids: frozenset
) -> bool:
    """Reuses Stage 2's exact duplicate-app_switch definition
    (`signals.deduplicate_consecutive` + `signals.app_switch_payload_key`)
    — the only instrumentation-noise pattern this project has an
    existing, validated, reusable detector for. Stage 2 measured this at
    <1% involvement among false internal boundaries and is NOT
    comprehensive (e.g. browser-error storms have no existing reusable
    per-transition flag) — documented as a known gap, not silently
    assumed covered."""
    return event_i_id in duplicate_app_switch_ids or event_next_id in duplicate_app_switch_ids


@dataclass
class ReturnPatternEvidence:
    role: str | None  # "leave", "return", or None
    field: str | None  # "application" or "browser_domain", or None
    paired_transition_index: int | None  # the other edge of the same pattern


def return_pattern_evidence_for_transition(
    canonical: list[CanonicalEvent], i: int, window_n: int
) -> ReturnPatternEvidence:
    """Checks whether transition `i` (between canonical[i] and
    canonical[i+1]) is the "leave" or "return" edge of a leave-and-return
    pattern, searched within a +/- `window_n` event window centered on
    `i` (no GT execution scoping — see module docstring). `application`
    is checked before `browser_domain`; the first field with a detected
    pattern touching `i` wins."""
    window_start = max(0, i - window_n + 1)
    window_end = min(len(canonical), i + 1 + window_n)
    for field in ("application", "browser_domain"):
        values_with_idx = [
            (getattr(canonical[k], field), k)
            for k in range(window_start, window_end)
            if getattr(canonical[k], field) is not None
        ]
        if len(values_with_idx) < 3:
            continue
        values = [v for v, _ in values_with_idx]
        orig_idx = [k for _, k in values_with_idx]
        for pat in detect_return_patterns(values, field=field):
            leave_idx = orig_idx[pat.left_run_end_index]
            return_idx = orig_idx[pat.returned_run_start_index] - 1
            if leave_idx == i:
                return ReturnPatternEvidence(role="leave", field=field, paired_transition_index=return_idx)
            if return_idx == i:
                return ReturnPatternEvidence(role="return", field=field, paired_transition_index=leave_idx)
    return ReturnPatternEvidence(role=None, field=None, paired_transition_index=None)


def compute_rule2_demotions(
    canonical: list[CanonicalEvent], candidate_indices: list[int], window_n: int
) -> tuple[set[int], dict[int, dict]]:
    """Scans every candidate transition once; whenever a leave-and-return
    pattern is found touching it, BOTH the leave and the return
    transition are added to the demotion set together (per the brief's
    "demote the relevant false split(s)" — implemented deterministically
    by unioning both edges regardless of which one's own window found
    the pattern, so a pair is corrected together rather than depending on
    both sides independently re-discovering it). `details` records, per
    demoted index, which field and role triggered it, for diagnostics."""
    demote: set[int] = set()
    details: dict[int, dict] = {}
    for i in candidate_indices:
        ev = return_pattern_evidence_for_transition(canonical, i, window_n)
        if ev.role is not None:
            demote.add(i)
            details[i] = {"field": ev.field, "role": ev.role, "paired_index": ev.paired_transition_index}
            if ev.paired_transition_index is not None:
                demote.add(ev.paired_transition_index)
    return demote, details


@dataclass
class ReconstructionResult:
    final_boundary: list[bool]
    rule_applied: list[str]

    def to_dict(self) -> dict:
        return {"final_boundary": self.final_boundary, "rule_applied": self.rule_applied}


def apply_design2_rules(
    candidates: list[bool],
    chunk_boundary: list[bool],
    duplicate_noise: list[bool],
    rule2_demote_indices: set[int],
    cluster_size: list[int],
    event_type_jaccard: list[float | None],
    continuity_threshold: float,
) -> ReconstructionResult:
    """The approved ordered rule list. Every array must be the same
    length (one entry per transition in one session). A transition that
    is not a candidate is never a final boundary (`RULE_NONE`) —
    reconstruction never adds a boundary V1/V2 didn't already predict.
    Jaccard values of `None` (rare; only when both trajectory windows are
    empty) default to KEEP — insufficient evidence is treated
    conservatively, not as evidence of continuity."""
    n = len(candidates)
    if not (len(chunk_boundary) == len(duplicate_noise) == len(cluster_size) == len(event_type_jaccard) == n):
        raise ValueError("all evidence arrays must be the same length as candidates")

    final_boundary = [False] * n
    rule_applied = [RULE_NONE] * n
    for i in range(n):
        if not candidates[i]:
            continue
        if chunk_boundary[i] or duplicate_noise[i]:
            final_boundary[i] = False
            rule_applied[i] = RULE_1_CHUNK_NOISE
        elif i in rule2_demote_indices:
            final_boundary[i] = False
            rule_applied[i] = RULE_2_RETURN_PATTERN
        elif cluster_size[i] >= 2:
            final_boundary[i] = True
            rule_applied[i] = RULE_3_CLUSTER_PROTECTION
        else:
            jac = event_type_jaccard[i]
            final_boundary[i] = not (jac is not None and jac >= continuity_threshold)
            rule_applied[i] = RULE_4_CONTINUITY
    return ReconstructionResult(final_boundary=final_boundary, rule_applied=rule_applied)


def apply_design1_rule(
    candidates: list[bool],
    chunk_boundary: list[bool],
    duplicate_noise: list[bool],
    event_type_jaccard: list[float | None],
    continuity_threshold: float,
) -> ReconstructionResult:
    """Ablation only — not the recommended architecture. Same candidate
    set and the same hard chunk/noise override (retained so the
    comparison against Design 2 isolates exactly the value of Rules 2+3,
    not also the value of the chunk/noise override); no return-pattern
    handling and no cluster distinction at all — the continuity check is
    applied uniformly to every non-chunk/non-noise candidate regardless
    of isolated-vs-clustered status."""
    n = len(candidates)
    if not (len(chunk_boundary) == len(duplicate_noise) == len(event_type_jaccard) == n):
        raise ValueError("all evidence arrays must be the same length as candidates")

    final_boundary = [False] * n
    rule_applied = [RULE_NONE] * n
    for i in range(n):
        if not candidates[i]:
            continue
        if chunk_boundary[i] or duplicate_noise[i]:
            final_boundary[i] = False
            rule_applied[i] = DESIGN1_RULE_CHUNK_NOISE
        else:
            jac = event_type_jaccard[i]
            final_boundary[i] = not (jac is not None and jac >= continuity_threshold)
            rule_applied[i] = DESIGN1_RULE_CONTINUITY
    return ReconstructionResult(final_boundary=final_boundary, rule_applied=rule_applied)

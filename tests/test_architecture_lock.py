"""Day 2 architecture-lock regression tests.

Most individual rule behaviors are already covered by
`test_reconstruction.py` and `test_protected_boundary.py` (candidate
union, no-new-boundary invariant, chunk/noise override, leave-and-return,
cluster protection, isolated-candidate continuity, tempo/combined
protection, protection scoped to Rule-4 demotions, determinism). This
file adds only what those don't already cover: a structural guard that
no GT-derived field can ever be accepted as a reconstruction input, and
an end-to-end mini-pipeline check (including session-start/session-end
edge positions) that the full locked pipeline — union -> Design 2 ->
protection — runs safely and never invents a boundary, for both the
Tempo and Combined strategies.
"""

from __future__ import annotations

import inspect

from procmine.segmentation.protected_boundary import (
    STRATEGY_AGREEMENT,
    STRATEGY_COMBINED,
    STRATEGY_TEMPO,
    apply_protection,
)
from procmine.segmentation.reconstruction import (
    apply_design1_rule,
    apply_design2_rules,
    cluster_size_per_transition,
    union_candidates,
)

FORBIDDEN_PARAM_SUBSTRINGS = (
    "gt", "case_id", "process_code", "process_variant", "execution",
    "continuity_label", "is_boundary", "boundary_label",
)


def _assert_no_gt_params(func) -> None:
    params = list(inspect.signature(func).parameters)
    for p in params:
        lowered = p.lower()
        for forbidden in FORBIDDEN_PARAM_SUBSTRINGS:
            assert forbidden not in lowered, (
                f"{func.__name__} accepts parameter {p!r}, which looks GT-derived "
                f"(matched {forbidden!r}) -- reconstruction must never take GT as input"
            )


def test_apply_design2_rules_signature_has_no_gt_derived_parameter():
    _assert_no_gt_params(apply_design2_rules)


def test_apply_design1_rule_signature_has_no_gt_derived_parameter():
    _assert_no_gt_params(apply_design1_rule)


def test_apply_protection_signature_has_no_gt_derived_parameter():
    _assert_no_gt_params(apply_protection)


def test_union_candidates_signature_has_no_gt_derived_parameter():
    _assert_no_gt_params(union_candidates)


def test_cluster_size_per_transition_signature_has_no_gt_derived_parameter():
    _assert_no_gt_params(cluster_size_per_transition)


# --- End-to-end mini pipeline: union -> Design 2 -> protection ------------

def _run_pipeline(n, candidates, chunk_boundary, duplicate_noise, rule2_demote_indices,
                   cluster_size, event_type_jaccard, flagged_by_both, tempo_value, strategy):
    design2 = apply_design2_rules(
        candidates=candidates, chunk_boundary=chunk_boundary, duplicate_noise=duplicate_noise,
        rule2_demote_indices=rule2_demote_indices, cluster_size=cluster_size,
        event_type_jaccard=event_type_jaccard, continuity_threshold=0.40,
    )
    protected = apply_protection(
        design2_final_boundary=design2.final_boundary, design2_rule_applied=design2.rule_applied,
        flagged_by_both=flagged_by_both, tempo_value=tempo_value,
        strategy=strategy, tempo_threshold=4680.2613,
    )
    return design2, protected


def test_full_pipeline_never_creates_a_boundary_outside_the_candidate_union_tempo():
    n = 6
    v1 = [True, False, False, True, False, False]
    v2 = [False, False, True, False, False, True]
    candidates = union_candidates(v1, v2)  # [True, False, True, True, False, True]
    design2, protected = _run_pipeline(
        n, candidates,
        chunk_boundary=[False] * n, duplicate_noise=[False] * n,
        rule2_demote_indices=set(), cluster_size=cluster_size_per_transition(candidates),
        event_type_jaccard=[0.9 if c else None for c in candidates],
        flagged_by_both=[a and b for a, b in zip(v1, v2)],
        tempo_value=[9999.0 if c else None for c in candidates],
        strategy=STRATEGY_TEMPO,
    )
    for i in range(n):
        if not candidates[i]:
            assert protected.final_boundary[i] is False, f"index {i} was never a candidate but is a boundary"


def test_full_pipeline_never_creates_a_boundary_outside_the_candidate_union_combined():
    n = 6
    v1 = [True, False, False, True, False, False]
    v2 = [False, False, True, False, False, True]
    candidates = union_candidates(v1, v2)
    design2, protected = _run_pipeline(
        n, candidates,
        chunk_boundary=[False] * n, duplicate_noise=[False] * n,
        rule2_demote_indices=set(), cluster_size=cluster_size_per_transition(candidates),
        event_type_jaccard=[0.9 if c else None for c in candidates],
        flagged_by_both=[a and b for a, b in zip(v1, v2)],
        tempo_value=[9999.0 if c else None for c in candidates],
        strategy=STRATEGY_COMBINED,
    )
    for i in range(n):
        if not candidates[i]:
            assert protected.final_boundary[i] is False


def test_full_pipeline_is_deterministic():
    n = 5
    candidates = [True, True, False, True, False]
    args = dict(
        n=n, candidates=candidates,
        chunk_boundary=[False] * n, duplicate_noise=[False] * n,
        rule2_demote_indices=set(), cluster_size=cluster_size_per_transition(candidates),
        event_type_jaccard=[0.5, 0.9, None, 0.2, None],
        flagged_by_both=[True, False, False, True, False],
        tempo_value=[5000.0, 100.0, None, 6000.0, None],
        strategy=STRATEGY_COMBINED,
    )
    _, r1 = _run_pipeline(**args)
    _, r2 = _run_pipeline(**args)
    assert r1.final_boundary == r2.final_boundary
    assert r1.rule_applied == r2.rule_applied


# --- Session-start / session-end edge safety --------------------------------

def test_candidate_at_very_first_transition_is_handled_safely():
    # index 0 is the first transition of the session -- must not crash
    # apply_design2_rules or apply_protection, and must be decided
    # correctly (chunk override still fires even at position 0).
    n = 3
    candidates = [True, False, False]
    design2, protected = _run_pipeline(
        n, candidates,
        chunk_boundary=[True, False, False], duplicate_noise=[False] * n,
        rule2_demote_indices=set(), cluster_size=cluster_size_per_transition(candidates),
        event_type_jaccard=[None, None, None],
        flagged_by_both=[True, False, False], tempo_value=[9999.0, None, None],
        strategy=STRATEGY_COMBINED,
    )
    assert protected.final_boundary[0] is False  # chunk override, not protection-eligible


def test_candidate_at_very_last_transition_is_handled_safely():
    # index n-1 is the last transition of the session
    n = 3
    candidates = [False, False, True]
    design2, protected = _run_pipeline(
        n, candidates,
        chunk_boundary=[False] * n, duplicate_noise=[False] * n,
        rule2_demote_indices=set(), cluster_size=cluster_size_per_transition(candidates),
        event_type_jaccard=[None, None, 0.9],
        flagged_by_both=[False, False, True], tempo_value=[None, None, 9999.0],
        strategy=STRATEGY_COMBINED,
    )
    # isolated candidate, high continuity -> demoted by rule4, then
    # protected (flagged by both AND tempo high) -> kept
    assert protected.final_boundary[2] is True
    assert protected.rule_applied[2] == "rule4_protected"


def test_single_transition_session_does_not_crash():
    n = 1
    candidates = [True]
    design2, protected = _run_pipeline(
        n, candidates,
        chunk_boundary=[False], duplicate_noise=[False],
        rule2_demote_indices=set(), cluster_size=cluster_size_per_transition(candidates),
        event_type_jaccard=[0.9], flagged_by_both=[True], tempo_value=[9999.0],
        strategy=STRATEGY_AGREEMENT,
    )
    assert len(protected.final_boundary) == 1


def test_empty_session_does_not_crash():
    design2, protected = _run_pipeline(
        0, [], chunk_boundary=[], duplicate_noise=[], rule2_demote_indices=set(),
        cluster_size=[], event_type_jaccard=[], flagged_by_both=[], tempo_value=[],
        strategy=STRATEGY_TEMPO,
    )
    assert protected.final_boundary == []

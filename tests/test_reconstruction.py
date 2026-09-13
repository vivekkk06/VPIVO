from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.reconstruction import (
    DESIGN1_RULE_CHUNK_NOISE,
    DESIGN1_RULE_CONTINUITY,
    RULE_1_CHUNK_NOISE,
    RULE_2_RETURN_PATTERN,
    RULE_3_CLUSTER_PROTECTION,
    RULE_4_CONTINUITY,
    RULE_NONE,
    apply_design1_rule,
    apply_design2_rules,
    cluster_size_per_transition,
    compute_rule2_demotions,
    involves_duplicate_app_switch,
    return_pattern_evidence_for_transition,
    union_candidates,
)


def _event(i, app=None, domain=None, event_type="mouse_click") -> CanonicalEvent:
    from procmine.models import Event

    raw = {
        "event_id": f"e{i}", "session_id": "s1", "timestamp_ms": i * 1000,
        "timestamp_iso": "2026-01-01T00:00:00Z", "layer": "l", "event_type": event_type,
        "correlation": {}, "context": {},
    }
    src = Event.from_dict(raw)
    return CanonicalEvent(
        event_id=f"e{i}", session_id="s1", timestamp_ms=i * 1000, event_type=event_type,
        layer="l", interaction_category="pointer", application=app, window_title=None,
        browser_domain=domain, browser_url=None, has_extracted_text=False,
        chunk_id=None, sequence_number=i, source_event=src,
    )


# --- union_candidates ---------------------------------------------------

def test_union_candidates_is_elementwise_or():
    v1 = [True, False, False, True]
    v2 = [False, False, True, True]
    assert union_candidates(v1, v2) == [True, False, True, True]


def test_union_candidates_length_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        union_candidates([True], [True, False])


# --- cluster_size_per_transition -----------------------------------------

def test_cluster_size_isolated_candidate():
    assert cluster_size_per_transition([False, True, False]) == [0, 1, 0]


def test_cluster_size_run_of_three():
    assert cluster_size_per_transition([True, True, True, False]) == [3, 3, 3, 0]


def test_cluster_size_multiple_separate_runs():
    assert cluster_size_per_transition([True, True, False, True]) == [2, 2, 0, 1]


def test_cluster_size_all_false():
    assert cluster_size_per_transition([False, False]) == [0, 0]


def test_cluster_size_empty():
    assert cluster_size_per_transition([]) == []


# --- involves_duplicate_app_switch --------------------------------------

def test_involves_duplicate_app_switch_true_when_either_endpoint_matches():
    dup = frozenset({"e5"})
    assert involves_duplicate_app_switch("e5", "e6", dup) is True
    assert involves_duplicate_app_switch("e6", "e5", dup) is True
    assert involves_duplicate_app_switch("e6", "e7", dup) is False


# --- return_pattern_evidence_for_transition -----------------------------

def test_return_pattern_evidence_detects_leave_and_return_roles():
    # events: app A, A, B, B, A, A  (indices 0..5)
    events = [
        _event(0, app="A"), _event(1, app="A"), _event(2, app="B"),
        _event(3, app="B"), _event(4, app="A"), _event(5, app="A"),
    ]
    # transition 1 (between idx1 A and idx2 B) is the "leave"
    leave_ev = return_pattern_evidence_for_transition(events, 1, window_n=10)
    assert leave_ev.role == "leave"
    assert leave_ev.field == "application"
    # transition 3 (between idx3 B and idx4 A) is the "return"
    return_ev = return_pattern_evidence_for_transition(events, 3, window_n=10)
    assert return_ev.role == "return"
    assert return_ev.paired_transition_index == 1


def test_return_pattern_evidence_none_when_no_pattern():
    events = [_event(0, app="A"), _event(1, app="B"), _event(2, app="C")]
    ev = return_pattern_evidence_for_transition(events, 0, window_n=10)
    assert ev.role is None
    assert ev.paired_transition_index is None


def test_return_pattern_evidence_respects_window_bound():
    # A -> 8 filler B events -> A: the away period fits inside a
    # window_n=10 search (covers indices 0..9 from the leave side) but
    # not inside a window_n=2 search (covers only indices 0..2) --
    # demonstrates the documented away-period-vs-window-size limitation.
    events = [_event(0, app="A")] + [_event(i, app="B") for i in range(1, 9)] + [_event(9, app="A")]
    ev_small_window = return_pattern_evidence_for_transition(events, 0, window_n=2)
    assert ev_small_window.role is None
    ev_large_window = return_pattern_evidence_for_transition(events, 0, window_n=10)
    assert ev_large_window.role == "leave"


def test_return_pattern_evidence_edge_at_session_start():
    # transition 0 is the very first transition in the session
    events = [_event(0, app="A"), _event(1, app="B"), _event(2, app="A")]
    ev = return_pattern_evidence_for_transition(events, 0, window_n=10)
    assert ev.role == "leave"


def test_return_pattern_evidence_edge_at_session_end():
    events = [_event(0, app="A"), _event(1, app="B"), _event(2, app="A")]
    last_transition = len(events) - 2
    ev = return_pattern_evidence_for_transition(events, last_transition, window_n=10)
    assert ev.role == "return"


# --- compute_rule2_demotions ---------------------------------------------

def test_compute_rule2_demotions_pairs_leave_and_return_together():
    events = [
        _event(0, app="A"), _event(1, app="A"), _event(2, app="B"),
        _event(3, app="B"), _event(4, app="A"), _event(5, app="A"),
    ]
    # only transition 1 (leave) is in the candidate set; transition 3
    # (return) is NOT independently a candidate -- Rule 2 should still
    # pull it into the demotion set as the paired edge.
    demote, details = compute_rule2_demotions(events, candidate_indices=[1], window_n=10)
    assert demote == {1, 3}
    assert details[1]["role"] == "leave"
    assert details[1]["paired_index"] == 3


def test_compute_rule2_demotions_empty_when_no_candidates_match():
    events = [_event(0, app="A"), _event(1, app="B"), _event(2, app="C")]
    demote, details = compute_rule2_demotions(events, candidate_indices=[0, 1], window_n=10)
    assert demote == set()
    assert details == {}


# --- apply_design2_rules: rule ordering and each case ---------------------

def _base_args(n):
    return {
        "candidates": [False] * n,
        "chunk_boundary": [False] * n,
        "duplicate_noise": [False] * n,
        "rule2_demote_indices": set(),
        "cluster_size": [0] * n,
        "event_type_jaccard": [None] * n,
        "continuity_threshold": 0.5,
    }


def test_design2_non_candidate_is_never_a_boundary():
    args = _base_args(3)
    result = apply_design2_rules(**args)
    assert result.final_boundary == [False, False, False]
    assert result.rule_applied == [RULE_NONE, RULE_NONE, RULE_NONE]


def test_design2_rule1_chunk_boundary_overrides_everything():
    args = _base_args(1)
    args["candidates"] = [True]
    args["chunk_boundary"] = [True]
    args["event_type_jaccard"] = [0.0]  # would otherwise look boundary-like
    result = apply_design2_rules(**args)
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_1_CHUNK_NOISE]


def test_design2_rule1_duplicate_noise_overrides_everything():
    args = _base_args(1)
    args["candidates"] = [True]
    args["duplicate_noise"] = [True]
    args["event_type_jaccard"] = [0.0]
    result = apply_design2_rules(**args)
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_1_CHUNK_NOISE]


def test_design2_rule2_return_pattern_overrides_cluster_and_continuity():
    args = _base_args(1)
    args["candidates"] = [True]
    args["rule2_demote_indices"] = {0}
    args["cluster_size"] = [2]  # would otherwise be protected by rule 3
    args["event_type_jaccard"] = [0.0]  # would otherwise look boundary-like under rule 4
    result = apply_design2_rules(**args)
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_2_RETURN_PATTERN]


def test_design2_rule3_cluster_protection_keeps_regardless_of_continuity():
    args = _base_args(2)
    args["candidates"] = [True, True]
    args["cluster_size"] = [2, 2]
    args["event_type_jaccard"] = [0.9, 0.9]  # high continuity would otherwise demote under rule 4
    result = apply_design2_rules(**args)
    assert result.final_boundary == [True, True]
    assert result.rule_applied == [RULE_3_CLUSTER_PROTECTION, RULE_3_CLUSTER_PROTECTION]


def test_design2_rule4_strong_continuity_demotes_isolated_candidate():
    args = _base_args(1)
    args["candidates"] = [True]
    args["cluster_size"] = [1]
    args["event_type_jaccard"] = [0.8]
    args["continuity_threshold"] = 0.5
    result = apply_design2_rules(**args)
    assert result.final_boundary == [False]
    assert result.rule_applied == [RULE_4_CONTINUITY]


def test_design2_rule4_weak_continuity_keeps_isolated_candidate():
    args = _base_args(1)
    args["candidates"] = [True]
    args["cluster_size"] = [1]
    args["event_type_jaccard"] = [0.2]
    args["continuity_threshold"] = 0.5
    result = apply_design2_rules(**args)
    assert result.final_boundary == [True]
    assert result.rule_applied == [RULE_4_CONTINUITY]


def test_design2_rule4_none_jaccard_defaults_to_keep():
    args = _base_args(1)
    args["candidates"] = [True]
    args["cluster_size"] = [1]
    args["event_type_jaccard"] = [None]
    result = apply_design2_rules(**args)
    assert result.final_boundary == [True]


def test_design2_never_creates_a_new_boundary():
    # every evidence field maximally favors "boundary" everywhere, but no
    # transition is a candidate -- final_boundary must stay all-False
    n = 5
    args = {
        "candidates": [False] * n,
        "chunk_boundary": [False] * n,
        "duplicate_noise": [False] * n,
        "rule2_demote_indices": set(range(n)),
        "cluster_size": [0] * n,
        "event_type_jaccard": [0.0] * n,
        "continuity_threshold": 0.5,
    }
    result = apply_design2_rules(**args)
    assert result.final_boundary == [False] * n


def test_design2_is_deterministic_across_repeated_calls():
    args = _base_args(4)
    args["candidates"] = [True, False, True, True]
    args["cluster_size"] = [1, 0, 2, 2]
    args["event_type_jaccard"] = [0.9, None, 0.1, 0.1]
    r1 = apply_design2_rules(**args)
    r2 = apply_design2_rules(**args)
    assert r1.final_boundary == r2.final_boundary
    assert r1.rule_applied == r2.rule_applied


def test_design2_mismatched_lengths_raise():
    import pytest
    args = _base_args(2)
    args["chunk_boundary"] = [False]  # wrong length
    with pytest.raises(ValueError):
        apply_design2_rules(**args)


# --- apply_design1_rule (ablation) ---------------------------------------

def test_design1_applies_continuity_uniformly_even_to_clustered_candidates():
    # Design 1 has no cluster protection -- a clustered candidate with
    # high continuity still gets demoted, unlike Design 2.
    n = 2
    args = {
        "candidates": [True, True],
        "chunk_boundary": [False, False],
        "duplicate_noise": [False, False],
        "event_type_jaccard": [0.9, 0.9],
        "continuity_threshold": 0.5,
    }
    result = apply_design1_rule(**args)
    assert result.final_boundary == [False, False]
    assert result.rule_applied == [DESIGN1_RULE_CONTINUITY, DESIGN1_RULE_CONTINUITY]


def test_design1_retains_chunk_noise_override():
    args = {
        "candidates": [True],
        "chunk_boundary": [True],
        "duplicate_noise": [False],
        "event_type_jaccard": [0.0],
        "continuity_threshold": 0.5,
    }
    result = apply_design1_rule(**args)
    assert result.final_boundary == [False]
    assert result.rule_applied == [DESIGN1_RULE_CHUNK_NOISE]


def test_design1_never_creates_a_new_boundary():
    args = {
        "candidates": [False, False],
        "chunk_boundary": [False, False],
        "duplicate_noise": [False, False],
        "event_type_jaccard": [0.0, 0.0],
        "continuity_threshold": 0.5,
    }
    result = apply_design1_rule(**args)
    assert result.final_boundary == [False, False]

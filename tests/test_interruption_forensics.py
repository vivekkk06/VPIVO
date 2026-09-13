from datetime import datetime, timezone

from procmine.models import GTExecution
from procmine.segmentation.interruption_forensics import (
    build_execution_profile,
    collapse_to_runs,
    detect_return_patterns,
    internal_transition_indices,
)


def _tf(ts, next_ts, delta_t=None, density_before=0, density_after=0,
        app_changed=False, window_changed=False, domain_changed=False, cat_changed=False):
    from procmine.segmentation.features import TransitionFeatures

    return TransitionFeatures(
        session_id="s1", event_i_id=f"e{ts}", event_next_id=f"e{next_ts}",
        timestamp_ms=ts, next_timestamp_ms=next_ts,
        delta_t_ms=delta_t if delta_t is not None else next_ts - ts,
        log1p_delta_t_ms=0.0, density_before=density_before, density_after=density_after,
        application_changed=app_changed, window_title_changed=window_changed,
        browser_domain_changed=domain_changed, interaction_category_changed=cat_changed,
        extracted_text_at_transition=False, chunk_boundary=False,
    )


def _exec(start_s, end_s, case_id="c", process_code="A") -> GTExecution:
    return GTExecution(
        process_code=process_code, process_name=None, case_id=case_id,
        start_ts=datetime.fromtimestamp(start_s, tz=timezone.utc),
        end_ts=datetime.fromtimestamp(end_s, tz=timezone.utc),
        variant=None,
    )


# --- internal_transition_indices --------------------------------------------

def test_internal_transition_indices_includes_only_fully_contained_transitions():
    feats = [_tf(0, 1000), _tf(1000, 2000), _tf(2000, 3000), _tf(3000, 4000)]
    # execution spans [500, 3500]ms -> transition0 starts before 500 (excluded),
    # transition3 ends after 3500 (excluded); transitions 1 and 2 fully inside
    idx = internal_transition_indices(feats, 500, 3500)
    assert idx == [1, 2]


def test_internal_transition_indices_inclusive_bounds():
    feats = [_tf(0, 1000)]
    assert internal_transition_indices(feats, 0, 1000) == [0]
    assert internal_transition_indices(feats, 1, 1000) == []
    assert internal_transition_indices(feats, 0, 999) == []


def test_internal_transition_indices_empty_when_no_transitions():
    assert internal_transition_indices([], 0, 1000) == []


# --- build_execution_profile -------------------------------------------------

def test_build_execution_profile_finds_max_gap_and_counts_context_changes():
    feats = [
        _tf(0, 1000, delta_t=1000, app_changed=True),
        _tf(1000, 6000, delta_t=5000, domain_changed=True),  # the big internal gap
        _tf(6000, 7000, delta_t=1000, window_changed=True),
    ]
    execution = _exec(0, 7)
    profile = build_execution_profile("s1", execution, feats, p90=4000, p95=4500, p99=4900)
    assert profile.n_internal_transitions == 3
    assert profile.max_internal_gap_ms == 5000
    assert profile.argmax_gap_transition_index == 1
    assert profile.n_gaps_ge_p90 == 1
    assert profile.n_gaps_ge_p95 == 1
    assert profile.n_gaps_ge_p99 == 1
    assert profile.n_app_switches == 1
    assert profile.n_browser_domain_changes == 1
    assert profile.n_window_title_changes == 1


def test_build_execution_profile_density_at_max_gap_matches_that_transitions_own_values():
    feats = [
        _tf(0, 1000, delta_t=1000, density_before=5, density_after=5),
        _tf(1000, 6000, delta_t=5000, density_before=1, density_after=2),
    ]
    execution = _exec(0, 6)
    profile = build_execution_profile("s1", execution, feats, p90=10_000, p95=20_000, p99=30_000)
    assert profile.density_before_at_max_gap == 1
    assert profile.density_after_at_max_gap == 2
    assert profile.n_gaps_ge_p90 == 0  # neither gap (1000ms, 5000ms) reaches these deliberately high thresholds


def test_build_execution_profile_no_internal_transitions_is_safe():
    execution = _exec(100, 200)  # no transitions fall inside this tiny span
    profile = build_execution_profile("s1", execution, [_tf(0, 50)], p90=10, p95=20, p99=30)
    assert profile.n_internal_transitions == 0
    assert profile.max_internal_gap_ms is None
    assert profile.argmax_gap_transition_index is None
    assert profile.density_before_at_max_gap is None
    assert profile.mean_density_before is None


# --- collapse_to_runs ---------------------------------------------------------

def test_collapse_to_runs_merges_consecutive_equal_values():
    assert collapse_to_runs(["A", "A", "B", "B", "B", "A"]) == [
        ("A", 0, 1), ("B", 2, 4), ("A", 5, 5),
    ]


def test_collapse_to_runs_empty_input():
    assert collapse_to_runs([]) == []


def test_collapse_to_runs_all_distinct():
    assert collapse_to_runs(["A", "B", "C"]) == [("A", 0, 0), ("B", 1, 1), ("C", 2, 2)]


# --- detect_return_patterns ---------------------------------------------------

def test_detect_return_patterns_immediate_a_b_a():
    patterns = detect_return_patterns(["A", "B", "A"], field="application")
    assert len(patterns) == 1
    p = patterns[0]
    assert p.value == "A"
    assert p.is_immediate is True
    assert p.away_values == ["B"]
    assert p.left_run_end_index == 0
    assert p.returned_run_start_index == 2


def test_detect_return_patterns_general_a_b_c_a_is_not_immediate():
    patterns = detect_return_patterns(["A", "B", "C", "A"], field="application")
    assert len(patterns) == 1
    p = patterns[0]
    assert p.value == "A"
    assert p.is_immediate is False
    assert p.away_values == ["B", "C"]


def test_detect_return_patterns_no_return_in_monotonic_sequence():
    assert detect_return_patterns(["A", "B", "C", "D"], field="application") == []


def test_detect_return_patterns_alternating_sequence_yields_one_pattern_per_reappearance():
    # A B A B A: each reappearance counted relative to its most recent
    # departure, not the first-ever occurrence
    patterns = detect_return_patterns(["A", "B", "A", "B", "A"], field="application")
    assert len(patterns) == 3
    assert [p.value for p in patterns] == ["A", "B", "A"]
    assert all(p.is_immediate for p in patterns)


def test_detect_return_patterns_empty_sequence():
    assert detect_return_patterns([], field="application") == []


def test_detect_return_patterns_no_repeats_within_single_run():
    # a single run of the same value throughout is not a "return" -- there
    # was no departure to return from
    assert detect_return_patterns(["A", "A", "A"], field="application") == []

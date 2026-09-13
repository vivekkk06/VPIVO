from procmine.segmentation.baselines import (
    baseline_temporal_and_context,
    baseline_temporal_only,
    baseline_temporal_or_context,
)
from procmine.segmentation.features import TransitionFeatures


def _f(delta_t_ms=100, application_changed=False, window_title_changed=False,
       browser_domain_changed=False, interaction_category_changed=False) -> TransitionFeatures:
    return TransitionFeatures(
        session_id="s1", event_i_id="a", event_next_id="b", timestamp_ms=0,
        next_timestamp_ms=delta_t_ms, delta_t_ms=delta_t_ms, log1p_delta_t_ms=0.0,
        density_before=0, density_after=0,
        application_changed=application_changed, window_title_changed=window_title_changed,
        browser_domain_changed=browser_domain_changed,
        interaction_category_changed=interaction_category_changed,
        extracted_text_at_transition=False, chunk_boundary=False,
    )


def test_temporal_only_fires_purely_on_gap_size():
    feats = [_f(delta_t_ms=50), _f(delta_t_ms=5000)]
    assert baseline_temporal_only(feats, tau_ms=1000) == [False, True]


def test_temporal_and_context_requires_both():
    big_gap_no_context = _f(delta_t_ms=5000, application_changed=False)
    big_gap_with_context = _f(delta_t_ms=5000, application_changed=True)
    small_gap_with_context = _f(delta_t_ms=50, application_changed=True)
    result = baseline_temporal_and_context(
        [big_gap_no_context, big_gap_with_context, small_gap_with_context], tau_ms=1000
    )
    assert result == [False, True, False]


def test_temporal_or_context_fires_on_either():
    big_gap_no_context = _f(delta_t_ms=5000, application_changed=False)
    small_gap_with_context = _f(delta_t_ms=50, window_title_changed=True)
    small_gap_no_context = _f(delta_t_ms=50)
    result = baseline_temporal_or_context(
        [big_gap_no_context, small_gap_with_context, small_gap_no_context], tau_ms=1000
    )
    assert result == [True, True, False]


def test_and_context_checks_all_four_context_fields():
    variants = [
        _f(delta_t_ms=5000, application_changed=True),
        _f(delta_t_ms=5000, window_title_changed=True),
        _f(delta_t_ms=5000, browser_domain_changed=True),
        _f(delta_t_ms=5000, interaction_category_changed=True),
    ]
    assert baseline_temporal_and_context(variants, tau_ms=1000) == [True, True, True, True]

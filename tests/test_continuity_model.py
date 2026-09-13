from procmine.models import Event
from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.continuity_model import (
    CONTINUITY_FEATURE_NAMES,
    continuity_feature_vector,
    feature_importance,
)
from procmine.segmentation.features import TransitionFeatures
from procmine.segmentation.model import fit_full_model


def _ce(event_id, ts_ms, app=None) -> CanonicalEvent:
    raw = {
        "event_id": event_id, "session_id": "s1", "timestamp_ms": ts_ms,
        "timestamp_iso": "2026-01-01T00:00:01.000Z", "layer": "L2", "event_type": "mouse_click",
        "correlation": {},
        "context": {"active_app": {"app_name": app}} if app else {},
        "payload": {},
    }
    return CanonicalEvent.from_event(Event.from_dict(raw))


def _tf() -> TransitionFeatures:
    return TransitionFeatures(
        session_id="s1", event_i_id="a", event_next_id="b", timestamp_ms=0,
        next_timestamp_ms=1000, delta_t_ms=1000, log1p_delta_t_ms=6.9,
        density_before=5, density_after=3, application_changed=True,
        window_title_changed=False, browser_domain_changed=True,
        interaction_category_changed=True, extracted_text_at_transition=False,
        chunk_boundary=False,
    )


def test_continuity_feature_vector_has_expected_length_and_no_none():
    canonical = [_ce("a", 0, app="Excel"), _ce("b", 1000, app="Chrome")]
    v = continuity_feature_vector(canonical, 0, _tf())
    assert len(v) == len(CONTINUITY_FEATURE_NAMES)
    assert all(x is not None for x in v)
    assert v[0] == 6.9  # log1p_delta_t_ms passed through unchanged


def test_continuity_feature_vector_no_gt_metadata():
    canonical = [_ce("a", 0), _ce("b", 1000)]
    v = continuity_feature_vector(canonical, 0, _tf())
    # purely structural check: exactly the declared feature count, nothing extra
    assert len(v) == 8


def test_feature_importance_uses_continuity_names_not_v1_names():
    import numpy as np

    rng = np.random.RandomState(0)
    X = rng.rand(200, len(CONTINUITY_FEATURE_NAMES))
    y = (X[:, 0] > 0.5).astype(int)
    model = fit_full_model(X, y)
    importance = feature_importance(model)
    names = {n for n, _ in importance}
    assert names == set(CONTINUITY_FEATURE_NAMES)

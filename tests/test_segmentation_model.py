import numpy as np

from procmine.segmentation.model import (
    FEATURE_NAMES,
    cross_validated_probabilities,
    feature_importance,
    feature_vector,
    fit_full_model,
)
from procmine.segmentation.features import TransitionFeatures


def _f(**overrides) -> TransitionFeatures:
    base = dict(
        session_id="s1", event_i_id="a", event_next_id="b", timestamp_ms=0,
        next_timestamp_ms=100, delta_t_ms=100, log1p_delta_t_ms=4.6,
        density_before=1, density_after=1, application_changed=False,
        window_title_changed=False, browser_domain_changed=False,
        interaction_category_changed=False, extracted_text_at_transition=False,
        chunk_boundary=False,
    )
    base.update(overrides)
    return TransitionFeatures(**base)


def test_feature_vector_has_expected_length_and_order():
    f = _f(log1p_delta_t_ms=5.0, density_before=3, application_changed=True)
    v = feature_vector(f)
    assert len(v) == len(FEATURE_NAMES)
    assert v[0] == 5.0
    assert v[1] == 3.0
    assert v[3] == 1.0  # application_changed cast to float


def _synthetic_dataset(n_sessions=6, n_per_session=200, seed=0):
    """A feature that perfectly determines the label (large gap -> boundary),
    spread across several synthetic sessions, so LOSO has something to
    hold out session-by-session."""
    rng = np.random.RandomState(seed)
    rows = []
    groups = []
    y = []
    for s in range(n_sessions):
        for _ in range(n_per_session):
            is_boundary = rng.rand() < 0.05
            gap = 8.0 if is_boundary else 1.0
            rows.append([gap, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            groups.append(f"session_{s}")
            y.append(1 if is_boundary else 0)
    return np.array(rows), np.array(y), np.array(groups)


def test_cross_validated_probabilities_shape_and_range():
    X, y, groups = _synthetic_dataset()
    probs = cross_validated_probabilities(X, y, groups)
    assert probs.shape == (len(y),)
    assert (probs >= 0).all() and (probs <= 1).all()


def test_cross_validated_probabilities_separates_the_informative_signal():
    X, y, groups = _synthetic_dataset()
    probs = cross_validated_probabilities(X, y, groups)
    mean_prob_boundary = probs[y == 1].mean()
    mean_prob_interior = probs[y == 0].mean()
    assert mean_prob_boundary > mean_prob_interior


def test_feature_importance_returns_all_features_sorted_by_magnitude():
    X, y, _ = _synthetic_dataset()
    model = fit_full_model(X, y)
    importance = feature_importance(model)
    names = [name for name, _ in importance]
    assert set(names) == set(FEATURE_NAMES)
    magnitudes = [abs(coef) for _, coef in importance]
    assert magnitudes == sorted(magnitudes, reverse=True)
    # the one truly informative feature (index 0, the gap) should dominate
    assert importance[0][0] == "log1p_delta_t_ms"

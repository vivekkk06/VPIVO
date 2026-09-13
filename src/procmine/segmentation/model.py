"""Learned boundary model: logistic regression over the transition
features, with session-aware (leave-one-session-out) cross-validation.

Why logistic regression, not a tree/boosting model, as the first thing
tried: it's the simplest model that outputs a genuine P(boundary | X_i)
rather than a hand-picked rule, its coefficients are directly inspectable
(feature importance = a name and a signed number, no additional tooling
needed), and per the project's own instruction to prefer the simplest
approach that achieves strong evidence, there is no reason yet to reach
for something less explainable. Comparing against a tree-based/boosted
alternative is explicitly Stage 8's ablation job, not repeated here.

Why leave-one-session-out, not a fixed train/test split or k-fold: with
only 63 sessions and a model this cheap to fit, LOSO is practical (the
spec's own preferred option when practical), and it directly answers the
only question that matters for this project — can the model recognize a
boundary in a session it has never seen, not a session similar to one it
trained on.

Why class_weight="balanced": Stage 5 measured a 97.4:1 class imbalance.
An unweighted classifier would trivially predict "never a boundary" and
still be ~99% accurate while useless — balancing is not a stylistic
choice here, it's required given the measured imbalance.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from procmine.segmentation.features import TransitionFeatures

FEATURE_NAMES = [
    "log1p_delta_t_ms",
    "density_before",
    "density_after",
    "application_changed",
    "window_title_changed",
    "browser_domain_changed",
    "interaction_category_changed",
    "extracted_text_at_transition",
    "chunk_boundary",
]
# Deliberately excludes raw delta_t_ms alongside its log-transform (Stage
# 4's own reasoning: the raw value's skew would dominate a model that has
# both) — log1p_delta_t_ms carries the temporal signal alone.


def feature_vector(f: TransitionFeatures) -> list[float]:
    return [
        f.log1p_delta_t_ms,
        float(f.density_before),
        float(f.density_after),
        float(f.application_changed),
        float(f.window_title_changed),
        float(f.browser_domain_changed),
        float(f.interaction_category_changed),
        float(f.extracted_text_at_transition),
        float(f.chunk_boundary),
    ]


def make_pipeline() -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )


def cross_validated_probabilities(
    X: np.ndarray, y: np.ndarray, groups: np.ndarray
) -> np.ndarray:
    """Out-of-fold P(boundary) for every row — each row's probability
    comes from a model that never saw that row's session during training.
    Safe to use for threshold selection afterward: the threshold is
    chosen from predictions the model made on unseen data, not from
    predictions on its own training data."""
    cv = LeaveOneGroupOut()
    pipeline = make_pipeline()
    probs = cross_val_predict(pipeline, X, y, groups=groups, cv=cv, method="predict_proba")
    return probs[:, 1]


def fit_full_model(X: np.ndarray, y: np.ndarray) -> Pipeline:
    """Fits on all data — for descriptive feature-importance inspection
    only, never for generating the predictions used in evaluation (those
    always come from cross_validated_probabilities)."""
    pipeline = make_pipeline()
    pipeline.fit(X, y)
    return pipeline


def feature_importance(pipeline: Pipeline) -> list[tuple[str, float]]:
    coefs = pipeline.named_steps["clf"].coef_[0]
    return sorted(zip(FEATURE_NAMES, coefs), key=lambda kv: -abs(kv[1]))

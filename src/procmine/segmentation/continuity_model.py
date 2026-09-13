"""Continuity model: estimates P(S=1 | X) — same-execution continuity —
using Stage 5's evidence-backed feature recommendation.

Kept as an independent module from `model.py` (the boundary-first V1
model) so both formulations remain separately reproducible, per
instruction. Reuses `model.py`'s generic training utilities
(`make_pipeline`, `cross_validated_probabilities`, `fit_full_model`) as-is
— those don't hardcode feature names or count, so this is legitimate
reuse, not duplication. `feature_importance` there DOES hardcode the V1
feature names, so this module has its own small parameterized version
instead of modifying that one.

Feature set: all 8 had full data coverage (no missing values) in Stage
5's measurement, so no imputation logic is needed here.
"""

from __future__ import annotations

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.context_features import extract_trajectory_features
from procmine.segmentation.features import TransitionFeatures

CONTINUITY_FEATURE_NAMES = [
    "log1p_delta_t_ms",
    "density_before",
    "density_after",
    "interaction_category_changed",
    "browser_domain_changed",
    "N10_event_type_jaccard",
    "N10_interaction_category_jaccard",
    "N10_after_window_duration_ms",
]

WINDOW_N = 10


def continuity_feature_vector(
    canonical: list[CanonicalEvent], index_i: int, f: TransitionFeatures
) -> list[float]:
    tf = extract_trajectory_features(canonical, index_i, WINDOW_N)
    return [
        f.log1p_delta_t_ms,
        float(f.density_before),
        float(f.density_after),
        float(f.interaction_category_changed),
        float(f.browser_domain_changed),
        float(tf.event_type_jaccard),
        float(tf.interaction_category_jaccard),
        float(tf.after_window_duration_ms),
    ]


def feature_importance(pipeline, feature_names: list[str] = CONTINUITY_FEATURE_NAMES):
    coefs = pipeline.named_steps["clf"].coef_[0]
    return sorted(zip(feature_names, coefs), key=lambda kv: -abs(kv[1]))

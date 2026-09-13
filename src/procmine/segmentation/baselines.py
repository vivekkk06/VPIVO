"""Deterministic baseline boundary predictors.

Per the project's own instruction: these are explicit, labeled baselines
for comparison, not the final architecture merely because they're simple.
Each is a small, named, independently-testable function operating on
`TransitionFeatures` — nothing here is Dataset-A/B-specific.
"""

from __future__ import annotations

from procmine.segmentation.features import TransitionFeatures


def baseline_temporal_only(features: list[TransitionFeatures], tau_ms: int) -> list[bool]:
    """Baseline 1: boundary iff delta_t > tau. The naive
    `if gap > X: new_process` rule, kept explicitly as a baseline to be
    beaten, not as the final answer."""
    return [f.delta_t_ms > tau_ms for f in features]


def baseline_temporal_and_context(features: list[TransitionFeatures], tau_ms: int) -> list[bool]:
    """Baseline 2: boundary iff delta_t > tau AND at least one contextual
    signal changed (application, window title, browser domain, or
    interaction category). This is the "Model 2" formulation from the
    spec's mathematical section: temporal evidence AND contextual change,
    not temporal evidence alone."""
    return [
        f.delta_t_ms > tau_ms
        and (
            f.application_changed
            or f.window_title_changed
            or f.browser_domain_changed
            or f.interaction_category_changed
        )
        for f in features
    ]


def baseline_temporal_or_context(features: list[TransitionFeatures], tau_ms: int) -> list[bool]:
    """Same signals as `baseline_temporal_and_context`, combined with OR
    instead of AND — a distinct, equally reasonable formulation the spec
    lists as worth comparing rather than assuming AND is correct."""
    return [
        f.delta_t_ms > tau_ms
        or f.application_changed
        or f.window_title_changed
        or f.browser_domain_changed
        or f.interaction_category_changed
        for f in features
    ]

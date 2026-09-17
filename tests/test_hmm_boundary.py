"""Tests for the Day-6 HMM boundary experiment (`procmine.experiments.hmm_boundary`).

This is experimental code that was evaluated and rejected, but it is kept for
reproducibility, so its behaviour is pinned: the numbers in the Day-6 report
are only meaningful if the model is deterministic and the boundary conversion
is exactly what the evaluation consumes.

The tests also assert the isolation guarantee — that this experiment cannot
reach into the locked segmentation path.
"""

from __future__ import annotations

import numpy as np
import pytest

from procmine.experiments.hmm_boundary import (
    VARIANCE_FLOOR,
    boundaries_from_states,
    fit_hmm,
    standardize,
)


def _two_regime_series(n: int = 120, d: int = 3, seed: int = 7) -> np.ndarray:
    """A sequence with one obvious regime change in the middle."""
    rng = np.random.default_rng(seed)
    a = rng.normal(-2.0, 0.25, size=(n // 2, d))
    b = rng.normal(+2.0, 0.25, size=(n - n // 2, d))
    return np.vstack([a, b])


# --- boundary conversion --------------------------------------------------

def test_state_change_becomes_a_boundary():
    states = np.array([0, 0, 1, 1, 1, 0])
    assert boundaries_from_states(states) == [False, False, True, False, False, True]


def test_first_transition_is_never_a_boundary():
    """Index 0 has no preceding state to differ from, and the locked pipeline
    treats session start the same way."""
    assert boundaries_from_states(np.array([3, 3, 3]))[0] is False
    assert boundaries_from_states(np.array([1, 2, 3]))[0] is False


def test_constant_state_path_yields_no_boundaries():
    assert boundaries_from_states(np.array([2] * 25)) == [False] * 25


def test_empty_state_path_is_handled():
    assert boundaries_from_states(np.array([], dtype=int)) == []


def test_output_length_matches_input_length():
    for n in (1, 2, 17, 100):
        assert len(boundaries_from_states(np.zeros(n, dtype=int))) == n


def test_output_is_plain_bools_for_the_evaluation_api():
    """boundary_metrics consumes list[bool]; numpy bools would still work but
    the artifact should serialise as JSON booleans."""
    out = boundaries_from_states(np.array([0, 1]))
    assert all(type(v) is bool for v in out)


# --- standardisation ------------------------------------------------------

def test_standardize_zero_means_unit_variance():
    x = np.random.default_rng(0).normal(5.0, 3.0, size=(200, 4))
    z = standardize(x)
    assert np.allclose(z.mean(axis=0), 0.0, atol=1e-9)
    assert np.allclose(z.std(axis=0), 1.0, atol=1e-9)


def test_standardize_survives_a_constant_column():
    """Several input features are boolean and can be constant within a
    session; a naive divide would produce NaN and poison the fit."""
    x = np.column_stack([np.ones(50), np.arange(50.0)])
    z = standardize(x)
    assert np.all(np.isfinite(z))
    assert np.allclose(z[:, 0], 0.0)


# --- model behaviour ------------------------------------------------------

def test_fit_recovers_an_obvious_two_regime_split():
    x = standardize(_two_regime_series())
    fit = fit_hmm(x, 2, seed=0)
    b = boundaries_from_states(fit.states)
    # exactly one state change, at the true regime change in the middle
    assert sum(b) == 1
    assert abs(b.index(True) - len(x) // 2) <= 2


def test_fit_is_deterministic_for_a_fixed_seed():
    """The Day-6 numbers are only reproducible if a rerun gives the same path."""
    x = standardize(_two_regime_series())
    a = fit_hmm(x, 3, seed=0)
    b = fit_hmm(x, 3, seed=0)
    assert np.array_equal(a.states, b.states)
    assert a.log_likelihood == b.log_likelihood


def test_variances_never_collapse_below_the_floor():
    """Constant features would otherwise drive variance to zero and the
    likelihood to infinity."""
    x = np.column_stack([np.zeros(80), _two_regime_series(80, 1)[:, 0]])
    fit = fit_hmm(standardize(x), 2, seed=0)
    assert np.all(fit.variances >= VARIANCE_FLOOR)


def test_log_likelihood_is_finite():
    fit = fit_hmm(standardize(_two_regime_series()), 4, seed=0)
    assert np.isfinite(fit.log_likelihood)


def test_transition_and_start_rows_are_normalised_log_probabilities():
    fit = fit_hmm(standardize(_two_regime_series()), 3, seed=0)
    assert np.allclose(np.exp(fit.start_log).sum(), 1.0, atol=1e-6)
    assert np.allclose(np.exp(fit.trans_log).sum(axis=1), 1.0, atol=1e-6)


def test_state_path_stays_within_the_requested_state_count():
    for k in (2, 3, 5):
        fit = fit_hmm(standardize(_two_regime_series()), k, seed=0)
        assert fit.states.min() >= 0
        assert fit.states.max() < k
        assert len(fit.states) == 120


def test_more_states_never_produce_fewer_boundaries_on_this_series():
    """Sanity check on the mechanism behind the Day-6 rejection: raising the
    state count raises the number of state changes, which is why precision
    fell monotonically across the sweep."""
    x = standardize(_two_regime_series(200, 3))
    counts = [sum(boundaries_from_states(fit_hmm(x, k, seed=0).states)) for k in (2, 4, 6)]
    assert counts[0] <= counts[-1]


# --- isolation guarantee --------------------------------------------------

def test_experiment_does_not_import_the_locked_segmentation_modules():
    """The locked pipeline must stay unreachable from the experiment.

    Checked against the actual import statements via the AST — a raw text
    search would match the module docstring, which discusses the locked
    pipeline by name precisely to explain that it is not touched.
    """
    import ast

    import procmine.experiments.hmm_boundary as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    forbidden = ("reconstruction", "protected_boundary", "threshold_analysis")
    for name in imported:
        assert not any(f in name for f in forbidden), \
            f"experiment must not import from the locked path: {name}"
    # and it should not pull in the segmentation package at all
    assert not any(n.startswith("procmine.segmentation") for n in imported), imported


def test_rejects_a_degenerate_single_observation():
    with pytest.raises(Exception):
        fit_hmm(np.zeros((0, 3)), 2, seed=0)

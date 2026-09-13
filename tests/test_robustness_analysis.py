from __future__ import annotations

import pytest

from procmine.process_discovery.robustness_analysis import (
    kendall_tau,
    pareto_frontier,
    ranks_from_scores,
    spearman_rank_correlation,
    winsorize,
)


# --- pareto_frontier ---------------------------------------------------

def test_pareto_frontier_dominated_point_excluded():
    points = {"a": (0.5, 0.5), "b": (0.9, 0.9)}  # b dominates a on both axes
    assert pareto_frontier(points) == {"b"}


def test_pareto_frontier_tradeoff_points_both_kept():
    points = {"impact_heavy": (0.9, 0.2), "feasibility_heavy": (0.2, 0.9)}
    assert pareto_frontier(points) == {"impact_heavy", "feasibility_heavy"}


def test_pareto_frontier_identical_points_both_kept():
    # neither dominates the other -- domination requires a strict inequality
    points = {"a": (0.5, 0.5), "b": (0.5, 0.5)}
    assert pareto_frontier(points) == {"a", "b"}


def test_pareto_frontier_three_points_middle_dominated():
    points = {"low": (0.1, 0.1), "mid": (0.5, 0.5), "high": (0.9, 0.9)}
    assert pareto_frontier(points) == {"high"}


def test_pareto_frontier_hr_style_case_not_dominated_when_it_leads_on_impact():
    # mirrors the real HR/Payroll (high impact, mid feasibility) vs.
    # Order/Inventory (mid impact, higher feasibility) relationship --
    # neither dominates the other
    points = {"hr": (0.924, 0.453), "order_inventory": (0.670, 0.507)}
    frontier = pareto_frontier(points)
    assert frontier == {"hr", "order_inventory"}


def test_pareto_frontier_single_point_is_always_on_it():
    assert pareto_frontier({"only": (0.1, 0.1)}) == {"only"}


def test_pareto_frontier_empty_input():
    assert pareto_frontier({}) == set()


# --- spearman_rank_correlation ------------------------------------------

def test_spearman_identical_rankings_is_one():
    ranks = {"a": 1, "b": 2, "c": 3}
    assert spearman_rank_correlation(ranks, ranks) == pytest.approx(1.0)


def test_spearman_fully_reversed_rankings_is_minus_one():
    a = {"a": 1, "b": 2, "c": 3}
    b = {"a": 3, "b": 2, "c": 1}
    assert spearman_rank_correlation(a, b) == pytest.approx(-1.0)


def test_spearman_mismatched_keys_raises():
    with pytest.raises(ValueError):
        spearman_rank_correlation({"a": 1}, {"b": 1})


def test_spearman_single_process_is_one():
    assert spearman_rank_correlation({"a": 1}, {"a": 1}) == 1.0


# --- kendall_tau -----------------------------------------------------------

def test_kendall_tau_identical_rankings_is_one():
    ranks = {"a": 1, "b": 2, "c": 3}
    assert kendall_tau(ranks, ranks) == pytest.approx(1.0)


def test_kendall_tau_fully_reversed_is_minus_one():
    a = {"a": 1, "b": 2, "c": 3}
    b = {"a": 3, "b": 2, "c": 1}
    assert kendall_tau(a, b) == pytest.approx(-1.0)


def test_kendall_tau_one_swap_is_between_extremes():
    a = {"a": 1, "b": 2, "c": 3}
    b = {"a": 1, "b": 3, "c": 2}  # b and c swapped
    tau = kendall_tau(a, b)
    assert -1.0 < tau < 1.0


def test_kendall_tau_mismatched_keys_raises():
    with pytest.raises(ValueError):
        kendall_tau({"a": 1}, {"b": 1})


# --- ranks_from_scores ---------------------------------------------------

def test_ranks_from_scores_orders_descending():
    scores = {"a": 0.1, "b": 0.9, "c": 0.5}
    assert ranks_from_scores(scores) == {"b": 1, "c": 2, "a": 3}


def test_ranks_from_scores_tiebreak_is_alphabetical():
    scores = {"b": 1.0, "a": 1.0}
    assert ranks_from_scores(scores) == {"a": 1, "b": 2}


# --- winsorize ---------------------------------------------------------

def test_winsorize_caps_extreme_high_value():
    values = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 1000}
    result = winsorize(values, limit=0.2)
    assert result["e"] < 1000
    # symmetric index clipping: index 0 (the minimum, "a") is inside the
    # clipped low region too at this limit/n, same as the high side --
    # a genuinely middle, unaffected value ("c") is the one that must
    # stay untouched.
    assert result["c"] == values["c"]


def test_winsorize_caps_extreme_low_value():
    values = {"a": -1000, "b": 2, "c": 3, "d": 4, "e": 5}
    result = winsorize(values, limit=0.2)
    assert result["a"] > -1000


def test_winsorize_zero_limit_is_identity():
    values = {"a": 1, "b": 2, "c": 3}
    assert winsorize(values, limit=0.0) == values


def test_winsorize_invalid_limit_raises():
    with pytest.raises(ValueError):
        winsorize({"a": 1, "b": 2, "c": 3}, limit=0.5)
    with pytest.raises(ValueError):
        winsorize({"a": 1, "b": 2, "c": 3}, limit=-0.1)


def test_winsorize_few_values_returned_unchanged():
    values = {"a": 1, "b": 1000}
    assert winsorize(values, limit=0.1) == values

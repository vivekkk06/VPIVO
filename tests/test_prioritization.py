from __future__ import annotations

from procmine.process_discovery.prioritization import (
    PriorityInputs,
    compute_priority_scores,
    min_max_normalize,
)


def test_min_max_normalize_basic_range():
    result = min_max_normalize({"a": 0.0, "b": 5.0, "c": 10.0})
    assert result == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_min_max_normalize_constant_values_give_half_not_zero():
    result = min_max_normalize({"a": 3.0, "b": 3.0})
    assert result == {"a": 0.5, "b": 0.5}


def test_min_max_normalize_empty_input():
    assert min_max_normalize({}) == {}


def test_min_max_normalize_single_value_gives_half():
    assert min_max_normalize({"a": 7.0}) == {"a": 0.5}


def _inputs(**kw):
    defaults = dict(frequency=0, time_impact=0, manual_effort=0, repetitiveness=0,
                     feasibility=0, business_impact=0, risk=0, complexity=0)
    defaults.update(kw)
    return PriorityInputs(**defaults)


def test_higher_frequency_gives_higher_score_all_else_equal():
    raw = {
        "low": _inputs(frequency=1),
        "high": _inputs(frequency=100),
    }
    scores = compute_priority_scores(raw)
    assert scores["high"] > scores["low"]


def test_higher_risk_gives_lower_score_all_else_equal():
    raw = {
        "safe": _inputs(frequency=10, risk=0),
        "risky": _inputs(frequency=10, risk=100),
    }
    scores = compute_priority_scores(raw)
    assert scores["safe"] > scores["risky"]


def test_zero_weight_on_a_factor_removes_its_influence():
    raw = {
        "a": _inputs(frequency=1, time_impact=100),
        "b": _inputs(frequency=100, time_impact=1),
    }
    weights = {"frequency": 0.0, "time_impact": 1.0, "manual_effort": 0.0, "repetitiveness": 0.0,
               "feasibility": 0.0, "business_impact": 0.0, "risk": 0.0, "complexity": 0.0}
    scores = compute_priority_scores(raw, weights=weights)
    assert scores["a"] > scores["b"]  # only time_impact matters now, and a has more of it


def test_identical_inputs_give_identical_scores():
    raw = {"a": _inputs(frequency=5, time_impact=5), "b": _inputs(frequency=5, time_impact=5)}
    scores = compute_priority_scores(raw)
    assert scores["a"] == scores["b"]

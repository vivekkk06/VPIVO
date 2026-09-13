from __future__ import annotations

import pytest

from procmine.process_discovery.opportunity_scoring import (
    ImpactFeasibilityInputs,
    automation_surface,
    compute_feasibility_scores,
    compute_impact_scores,
    compute_opportunity_scores,
    normalized_variant_entropy,
    rank_processes,
    variant_entropy,
)


# --- variant_entropy ---------------------------------------------------

def test_variant_entropy_single_variant_is_zero():
    assert variant_entropy([100]) == 0.0


def test_variant_entropy_two_equal_variants_is_one_bit():
    assert variant_entropy([50, 50]) == 1.0


def test_variant_entropy_more_variants_is_higher():
    assert variant_entropy([25, 25, 25, 25]) > variant_entropy([50, 50])


def test_variant_entropy_skewed_distribution_is_lower_than_uniform():
    skewed = variant_entropy([94, 24, 4])  # HR/Payroll's actual split
    uniform = variant_entropy([41, 41, 40])
    assert skewed < uniform


def test_variant_entropy_empty_list_is_zero():
    assert variant_entropy([]) == 0.0


# --- normalized_variant_entropy -----------------------------------------

def test_normalized_entropy_single_variant_is_zero():
    assert normalized_variant_entropy([100]) == 0.0


def test_normalized_entropy_empty_is_zero():
    assert normalized_variant_entropy([]) == 0.0


def test_normalized_entropy_perfectly_even_distribution_is_one():
    # any perfectly even split -> H == H_max -> ratio == 1.0
    assert normalized_variant_entropy([25, 25, 25, 25]) == pytest.approx(1.0)
    assert normalized_variant_entropy([50, 50]) == pytest.approx(1.0)


def test_normalized_entropy_is_bounded_zero_to_one():
    for freqs in ([94, 24, 4], [1, 1, 1, 1, 1, 1, 1], [10], [5, 3], []):
        v = normalized_variant_entropy(freqs)
        assert 0.0 <= v <= 1.0


def test_normalized_entropy_corrects_the_variant_count_confound():
    # regression test for the real issue found auditing Dataset B: a
    # 7-variant process with skewed usage can show HIGHER raw entropy
    # than a 3-variant process with more evenly-spread usage, purely
    # because it has more categories to spread mass across. Normalized
    # entropy must not repeat that inversion.
    seven_variants_skewed = [50, 20, 10, 10, 5, 3, 2]  # sums to 100
    three_variants_even = [34, 33, 33]
    raw_seven = variant_entropy(seven_variants_skewed)
    raw_three = variant_entropy(three_variants_even)
    assert raw_seven > raw_three  # the raw-entropy inversion this fix addresses

    norm_seven = normalized_variant_entropy(seven_variants_skewed)
    norm_three = normalized_variant_entropy(three_variants_even)
    assert norm_three > norm_seven  # normalized entropy gets the relative ordering right


# --- automation_surface -----------------------------------------------

def test_automation_surface_is_the_product():
    assert automation_surface(0.5, 0.4) == pytest.approx(0.2)


def test_automation_surface_bounded_zero_to_one():
    assert automation_surface(1.0, 1.0) == 1.0
    assert automation_surface(0.0, 1.0) == 0.0
    assert automation_surface(1.0, 0.0) == 0.0


# --- Impact / Feasibility / Opportunity --------------------------------

def _inputs(**kw):
    defaults = dict(frequency_share=0.0, time_share=0.0, manual_involvement=0.0,
                     dominant_variant_share=0.0, variant_entropy_value=0.0,
                     automation_surface_value=0.0, complexity_risk=0.0)
    defaults.update(kw)
    return ImpactFeasibilityInputs(**defaults)


def test_higher_frequency_and_time_gives_higher_impact():
    raw = {
        "low": _inputs(frequency_share=0.01, time_share=0.01, manual_involvement=0.5),
        "high": _inputs(frequency_share=0.5, time_share=0.5, manual_involvement=0.5),
    }
    impact = compute_impact_scores(raw)
    assert impact["high"] > impact["low"]


def test_higher_determinism_and_lower_entropy_gives_higher_feasibility():
    raw = {
        "messy": _inputs(dominant_variant_share=0.3, variant_entropy_value=2.0, automation_surface_value=0.2, complexity_risk=5),
        "clean": _inputs(dominant_variant_share=0.95, variant_entropy_value=0.1, automation_surface_value=0.8, complexity_risk=1),
    }
    feasibility = compute_feasibility_scores(raw)
    assert feasibility["clean"] > feasibility["messy"]


def test_higher_complexity_risk_lowers_feasibility_all_else_equal():
    raw = {
        "risky": _inputs(dominant_variant_share=0.8, automation_surface_value=0.5, complexity_risk=10),
        "safe": _inputs(dominant_variant_share=0.8, automation_surface_value=0.5, complexity_risk=1),
    }
    feasibility = compute_feasibility_scores(raw)
    assert feasibility["safe"] > feasibility["risky"]


def test_opportunity_is_the_product_of_impact_and_feasibility():
    impact = {"a": 0.5, "b": 1.0}
    feasibility = {"a": 1.0, "b": 0.5}
    opp = compute_opportunity_scores(impact, feasibility)
    assert opp["a"] == pytest.approx(0.5)
    assert opp["b"] == pytest.approx(0.5)


def test_opportunity_high_impact_low_feasibility_vs_low_impact_high_feasibility():
    # neither should automatically dominate -- both land at the same
    # product here, illustrating the assignment's own "high impact + low
    # feasibility" vs "low impact + high feasibility" distinction
    impact = {"impact_heavy": 0.9, "feasibility_heavy": 0.2}
    feasibility = {"impact_heavy": 0.2, "feasibility_heavy": 0.9}
    opp = compute_opportunity_scores(impact, feasibility)
    assert opp["impact_heavy"] == pytest.approx(opp["feasibility_heavy"], abs=1e-9)


def test_opportunity_requires_matching_key_sets():
    with pytest.raises(ValueError):
        compute_opportunity_scores({"a": 1.0}, {"b": 1.0})


def test_ideal_candidate_high_impact_and_high_feasibility_ranks_first():
    raw = {
        "ideal": _inputs(frequency_share=0.8, time_share=0.8, manual_involvement=0.8,
                          dominant_variant_share=0.9, variant_entropy_value=0.1,
                          automation_surface_value=0.8, complexity_risk=1),
        "impact_only": _inputs(frequency_share=0.9, time_share=0.9, manual_involvement=0.9,
                                dominant_variant_share=0.1, variant_entropy_value=2.0,
                                automation_surface_value=0.1, complexity_risk=10),
        "feasibility_only": _inputs(frequency_share=0.05, time_share=0.05, manual_involvement=0.05,
                                     dominant_variant_share=1.0, variant_entropy_value=0.0,
                                     automation_surface_value=1.0, complexity_risk=0),
    }
    impact = compute_impact_scores(raw)
    feasibility = compute_feasibility_scores(raw)
    opportunity = compute_opportunity_scores(impact, feasibility)
    ranked = rank_processes(opportunity)
    assert ranked[0] == "ideal"


# --- sensitivity / weighting ---------------------------------------------

def test_custom_weights_change_impact_ranking_predictably():
    raw = {
        "freq_heavy": _inputs(frequency_share=1.0, time_share=0.0, manual_involvement=0.0),
        "time_heavy": _inputs(frequency_share=0.0, time_share=1.0, manual_involvement=0.0),
    }
    freq_weighted = compute_impact_scores(raw, weights={"frequency": 10.0, "time": 1.0, "manual": 1.0})
    assert freq_weighted["freq_heavy"] > freq_weighted["time_heavy"]

    time_weighted = compute_impact_scores(raw, weights={"frequency": 1.0, "time": 10.0, "manual": 1.0})
    assert time_weighted["time_heavy"] > time_weighted["freq_heavy"]


def test_rank_processes_is_deterministic_on_ties():
    scores = {"b": 1.0, "a": 1.0}
    assert rank_processes(scores) == ["a", "b"]  # alphabetical tiebreak, not insertion order

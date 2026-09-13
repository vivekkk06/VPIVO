from __future__ import annotations

from procmine.process_discovery.variant_analysis import variant_signature


def _step(system, category="input", n=1):
    return {"system": system, "interaction_category": category, "n_events": n}


def test_single_system_gives_length_one_signature():
    steps = [_step("A", "input"), _step("A", "pointer")]
    assert variant_signature(steps) == ("A",)


def test_distinct_consecutive_systems_are_both_kept():
    steps = [_step("A"), _step("B")]
    assert variant_signature(steps) == ("A", "B")


def test_detour_and_return_shows_as_a_b_a():
    steps = [_step("A"), _step("B"), _step("A")]
    assert variant_signature(steps) == ("A", "B", "A")


def test_none_system_steps_are_skipped():
    steps = [_step("A"), _step(None), _step("B")]
    assert variant_signature(steps) == ("A", "B")


def test_empty_steps_gives_empty_signature():
    assert variant_signature([]) == ()


def test_same_system_different_categories_collapse_to_one_entry():
    steps = [_step("A", "input"), _step("A", "pointer"), _step("A", "clipboard")]
    assert variant_signature(steps) == ("A",)

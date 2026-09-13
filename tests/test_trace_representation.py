from __future__ import annotations

from procmine.process_discovery.trace_representation import activity_level_trace, system_level_trace


def _step(system, category="input", n=1):
    return {"system": system, "interaction_category": category, "n_events": n}


def test_system_level_trace_matches_variant_signature():
    steps = [_step("A", "input"), _step("A", "pointer"), _step("B", "input")]
    assert system_level_trace(steps) == ("A", "B")


def test_activity_level_trace_is_finer_than_system_level():
    steps = [_step("A", "input"), _step("A", "pointer"), _step("B", "input")]
    system_trace = system_level_trace(steps)
    activity_trace = activity_level_trace(steps)
    assert len(activity_trace) >= len(system_trace)
    assert activity_trace == ("A|input", "A|pointer", "B|input")


def test_activity_level_trace_dedups_consecutive_identical_pairs():
    steps = [_step("A", "input"), _step("A", "input"), _step("B", "input")]
    assert activity_level_trace(steps) == ("A|input", "B|input")


def test_activity_level_trace_skips_none_system_steps():
    steps = [_step("A", "input"), _step(None, "system"), _step("B", "input")]
    assert activity_level_trace(steps) == ("A|input", "B|input")


def test_empty_steps_give_empty_traces():
    assert system_level_trace([]) == ()
    assert activity_level_trace([]) == ()


def test_activity_level_trace_distinguishes_same_system_different_category():
    steps = [_step("HR", "input"), _step("HR", "pointer")]
    trace = activity_level_trace(steps)
    assert trace == ("HR|input", "HR|pointer")
    # the two entries are distinct tokens, even though both are "HR"
    assert len(set(trace)) == 2

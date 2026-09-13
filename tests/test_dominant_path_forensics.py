from __future__ import annotations

from procmine.process_discovery.dominant_path_forensics import classify_variant, surrounding_context

PID = "system:HR"


def _step(system, category="input"):
    return {"system": system, "interaction_category": category, "n_events": 1}


def test_classify_pure_stay_is_dominant():
    steps = [_step(PID), _step(PID)]
    assert classify_variant(steps, PID) == "dominant"


def test_classify_single_word_detour():
    steps = [_step(PID), _step("app:Microsoft Word"), _step(PID)]
    assert classify_variant(steps, PID) == "word_detour"


def test_classify_double_word_detour():
    steps = [_step(PID), _step("app:Microsoft Word"), _step(PID), _step("app:Microsoft Word"), _step(PID)]
    assert classify_variant(steps, PID) == "word_detour"


def test_classify_other_system_is_other():
    steps = [_step(PID), _step("app:Windows Explorer"), _step(PID)]
    assert classify_variant(steps, PID) == "other"


def test_classify_word_only_no_hr_at_all_is_other():
    # Word appears but the execution never actually touches the target
    # process itself -- shouldn't happen for executions of this process,
    # but classify_variant should not misclassify it as "dominant" or
    # "word_detour" if it did.
    steps = [_step("app:Microsoft Word")]
    assert classify_variant(steps, PID) == "other"


def test_classify_empty_steps_is_other():
    assert classify_variant([], PID) == "other"


# --- surrounding_context -----------------------------------------------

def _event(ts):
    return {"timestamp_ms": ts}


def test_surrounding_context_finds_immediate_neighbors():
    events = [_event(0), _event(100), _event(200), _event(300), _event(400)]
    before, after = surrounding_context(events, start_ms=200, end_ms=300)
    assert before == _event(100)
    assert after == _event(400)


def test_surrounding_context_none_when_execution_is_first():
    events = [_event(0), _event(100), _event(200)]
    before, after = surrounding_context(events, start_ms=0, end_ms=100)
    assert before is None
    assert after == _event(200)


def test_surrounding_context_none_when_execution_is_last():
    events = [_event(0), _event(100), _event(200)]
    before, after = surrounding_context(events, start_ms=100, end_ms=200)
    assert before == _event(0)
    assert after is None


def test_surrounding_context_both_none_for_single_event_session():
    events = [_event(0)]
    before, after = surrounding_context(events, start_ms=0, end_ms=0)
    assert before is None and after is None

from procmine.cleaning import clean_session_events


def _e(event_id, ts_ms):
    return {"event_id": event_id, "timestamp_ms": ts_ms}


def test_drops_exact_duplicates_keeps_one_copy():
    events = [_e("a", 1000), dict(_e("a", 1000)), _e("b", 2000)]
    cleaned, log = clean_session_events(events)
    assert len(cleaned) == 2
    dedupe_step = next(s for s in log if s["step"] == "drop_exact_duplicate_records")
    assert dedupe_step["affected_events"] == 1
    assert dedupe_step["information_lost"] is False


def test_sorts_chronologically():
    events = [_e("b", 2000), _e("a", 1000)]
    cleaned, log = clean_session_events(events)
    assert [e["event_id"] for e in cleaned] == ["a", "b"]


def test_does_not_mutate_input():
    events = [_e("b", 2000), _e("a", 1000)]
    original_order = [e["event_id"] for e in events]
    clean_session_events(events)
    assert [e["event_id"] for e in events] == original_order


def test_empty_input_is_safe():
    cleaned, log = clean_session_events([])
    assert cleaned == []
    assert all(s["affected_events"] == 0 for s in log)

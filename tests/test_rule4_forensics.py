from procmine.segmentation.rule4_forensics import (
    classify_candidate_source,
    hostname_only,
    port_only,
)


def test_hostname_only_strips_port():
    assert hostname_only("http://127.0.0.1:5122/path") == "127.0.0.1"


def test_hostname_only_no_port_present():
    assert hostname_only("https://example.com/page") == "example.com"


def test_hostname_only_none_input():
    assert hostname_only(None) is None


def test_hostname_only_empty_string():
    assert hostname_only("") is None


def test_hostname_only_unparseable_returns_none():
    assert hostname_only("http://[::1:bad") is None


def test_port_only_extracts_explicit_port():
    assert port_only("http://127.0.0.1:5122/path") == 5122


def test_port_only_none_when_no_explicit_port():
    assert port_only("https://example.com/page") is None


def test_port_only_none_input():
    assert port_only(None) is None


def test_port_only_unparseable_returns_none():
    assert port_only("http://[::1:bad") is None


def test_classify_candidate_source_both():
    assert classify_candidate_source(True, True) == "both"


def test_classify_candidate_source_v1_only():
    assert classify_candidate_source(True, False) == "v1_only"


def test_classify_candidate_source_v2_only():
    assert classify_candidate_source(False, True) == "v2_only"


def test_classify_candidate_source_neither():
    assert classify_candidate_source(False, False) == "neither"

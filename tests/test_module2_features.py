"""Module 2 candidate features (Day 6).

The properties worth testing here are not "does it compute a number" but the ones that
would silently invalidate the experiment if they broke:

* **fold safety** — an operator baseline must never see the held-out session, because a
  leak there would inflate H1's result with no visible symptom;
* **honest missingness** — a transition with no screen text must be reported as "no
  evidence", never as drift 0 (identical) or drift 1 (disjoint), both of which would be
  fabricated evidence;
* **no GT anywhere** — these features are computed from raw events only.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from procmine.models import Event
from procmine.module2.features import (
    FEATURE_SET_M1, FEATURE_SET_M2A, FEATURE_SET_M2B, FEATURE_SET_M2C,
    MIN_GAPS_FOR_BASELINE, OperatorBaseline, baseline_for, compute_operator_baselines,
    content_drift, event_text, extra_feature_names, extra_feature_values, operator_of,
)
from procmine.segmentation.canonical import CanonicalEvent


# --- operator identity ----------------------------------------------------

@pytest.mark.parametrize("session_id,expected", [
    ("ses_20260630-121953-LAPTOP-R36BQBTE", "LAPTOP-R36BQBTE"),
    ("ses_20260701-022828-yuvraj", "yuvraj"),
    ("ses_20260701-035622-SIDDHIGUPTAB00B", "SIDDHIGUPTAB00B"),
])
def test_operator_is_recovered_from_the_session_id(session_id, expected):
    assert operator_of(session_id) == expected


def test_an_unparseable_session_id_yields_no_operator_rather_than_a_guess():
    for bad in ("", "not-a-session", "ses_bad"):
        assert operator_of(bad) is None


# --- H1: operator baselines ----------------------------------------------

def _gaps(n, base):
    """A deterministic spread around `base` so median and MAD are both well defined."""
    return [base + (i % 7) - 3 for i in range(n)]


def test_a_baseline_is_fitted_per_operator():
    log_gaps = {
        "ses_20260101-000000-alice": _gaps(500, 4.0),
        "ses_20260101-000001-bob": _gaps(500, 6.0),
    }
    b = compute_operator_baselines(log_gaps, list(log_gaps))
    assert b["alice"].median_log_gap == pytest.approx(4.0, abs=0.5)
    assert b["bob"].median_log_gap == pytest.approx(6.0, abs=0.5)
    assert b["alice"].source == "operator"


def test_the_held_out_session_never_contributes_to_its_own_baseline():
    """The leakage control. This is the test H1's credibility rests on."""
    train_only = {"ses_20260101-000000-alice": _gaps(500, 4.0)}
    held = {"ses_20260101-000009-alice": [99.0] * 500}
    log_gaps = {**train_only, **held}

    fitted = compute_operator_baselines(log_gaps, list(train_only))
    assert fitted["alice"].median_log_gap < 10, "held-out session leaked into the baseline"

    leaked = compute_operator_baselines(log_gaps, list(log_gaps))
    assert leaked["alice"].median_log_gap > fitted["alice"].median_log_gap, (
        "sanity: including the held-out session must visibly move the baseline")


def test_an_operator_with_too_few_observations_falls_back_and_says_so():
    log_gaps = {
        "ses_20260101-000000-alice": _gaps(500, 4.0),
        "ses_20260101-000001-tiny": _gaps(MIN_GAPS_FOR_BASELINE - 1, 9.0),
    }
    b = compute_operator_baselines(log_gaps, list(log_gaps))
    assert b["tiny"].source == "global_fallback"
    assert b["tiny"].median_log_gap == b["__global__"].median_log_gap
    assert b["alice"].source == "operator"


def test_an_operator_unseen_in_training_uses_the_pooled_baseline():
    log_gaps = {"ses_20260101-000000-alice": _gaps(500, 4.0)}
    b = compute_operator_baselines(log_gaps, list(log_gaps))
    assert baseline_for(b, "ses_20260101-000002-stranger").operator == "__global__"


def test_no_baseline_is_invented_when_there_is_no_training_data():
    assert compute_operator_baselines({}, []) == {}


def test_the_z_score_is_scaled_by_dispersion_not_only_centred():
    tight = OperatorBaseline("t", 100, 4.0, 0.1, "operator")
    loose = OperatorBaseline("l", 100, 4.0, 1.0, "operator")
    # The same absolute gap is far more unusual for the tight operator.
    assert tight.z(5.0) > loose.z(5.0)
    assert tight.z(4.0) == 0.0


def test_a_degenerate_zero_dispersion_baseline_stays_finite():
    assert math.isfinite(OperatorBaseline("d", 100, 4.0, 0.0, "operator").z(5.0))


# --- H2: content drift ----------------------------------------------------

def _event(idx: int, text: str | None) -> CanonicalEvent:
    context: dict = {"active_app": {"app_name": "chrome", "window_title": "t"}}
    if text is not None:
        context["extracted_text"] = {"text": text}
    raw = {
        "event_id": f"evt_{idx}",
        "session_id": "ses_20260101-000000-alice",
        "timestamp_ms": 1000 + idx * 10,
        "timestamp_iso": "2026-01-01T00:00:00.000Z",
        "layer": "L2",
        "event_type": "mouse_click",
        "context": context,
        "payload": {},
        "correlation": {"chunk_id": "c1", "sequence_number": idx},
    }
    return CanonicalEvent.from_event(Event.from_dict(raw))


def _stream(texts: list[str | None]) -> list[CanonicalEvent]:
    return [_event(i, t) for i, t in enumerate(texts)]


def test_identical_content_is_zero_drift():
    drift, available = content_drift(_stream(["alpha beta gamma", "alpha beta gamma"]), 0, n=1)
    assert available is True
    assert drift == pytest.approx(0.0)


def test_disjoint_content_is_full_drift():
    drift, available = content_drift(_stream(["alpha beta", "gamma delta"]), 0, n=1)
    assert available is True
    assert drift == pytest.approx(1.0)


def test_partial_overlap_is_one_minus_jaccard():
    # before {a,b}, after {b,c} -> J = 1/3 -> drift = 2/3
    drift, available = content_drift(_stream(["a b", "b c"]), 0, n=1)
    assert available is True
    assert drift == pytest.approx(2 / 3)


def test_missing_text_on_either_side_is_unavailable_not_zero_and_not_one():
    """The honesty property: absence of evidence must not become evidence."""
    for texts in (["alpha", None], [None, "alpha"], [None, None]):
        drift, available = content_drift(_stream(texts), 0, n=1)
        assert available is False
        assert drift == 0.0, "the imputed value is paired with an availability flag"


def test_empty_and_whitespace_text_counts_as_no_text():
    for blank in ("", "   ", "\n\t"):
        _, available = content_drift(_stream([blank, "alpha"]), 0, n=1)
        assert available is False


def test_the_window_widens_coverage_beyond_adjacent_events():
    """Why the window form was chosen: adjacent pairs almost never both carry text."""
    stream = _stream(["alpha beta", None, None, None, "beta gamma"])
    assert content_drift(stream, 1, n=1)[1] is False
    assert content_drift(stream, 1, n=4)[1] is True


def test_drift_is_deterministic():
    stream = _stream(["alpha beta", "beta gamma"])
    assert len({content_drift(stream, 0, n=1) for _ in range(5)}) == 1


def test_tokenisation_is_case_insensitive():
    assert content_drift(_stream(["Alpha BETA", "alpha beta"]), 0, n=1)[0] == pytest.approx(0.0)


def test_event_text_reads_through_to_the_raw_event():
    assert event_text(_event(0, "hello world")) == "hello world"
    assert event_text(_event(1, None)) is None


def test_drift_is_bounded_in_zero_one():
    for texts in (["a b c", "a"], ["a", "a b c"], ["x", "y"]):
        drift, _ = content_drift(_stream(texts), 0, n=1)
        assert 0.0 <= drift <= 1.0


# --- feature-set assembly -------------------------------------------------

def test_the_control_feature_set_adds_nothing():
    assert extra_feature_names(FEATURE_SET_M1) == []
    assert extra_feature_values(FEATURE_SET_M1, z_log_gap=1.0, drift=0.5,
                                drift_available=True) == []


@pytest.mark.parametrize("feature_set,expected", [
    (FEATURE_SET_M2A, ["operator_z_log_gap"]),
    (FEATURE_SET_M2B, ["content_drift", "content_drift_available"]),
    (FEATURE_SET_M2C, ["operator_z_log_gap", "content_drift", "content_drift_available"]),
])
def test_each_feature_set_declares_exactly_what_it_appends(feature_set, expected):
    assert extra_feature_names(feature_set) == expected
    values = extra_feature_values(feature_set, z_log_gap=1.5, drift=0.25,
                                  drift_available=True)
    assert len(values) == len(expected)


def test_the_availability_indicator_accompanies_the_drift_value():
    assert extra_feature_values(FEATURE_SET_M2B, z_log_gap=0.0, drift=0.25,
                                drift_available=False) == [0.25, 0.0]


def test_an_unknown_feature_set_is_rejected_rather_than_silently_empty():
    with pytest.raises(ValueError):
        extra_feature_names("M9_does_not_exist")
    with pytest.raises(ValueError):
        extra_feature_values("M9_does_not_exist", z_log_gap=0.0, drift=0.0,
                             drift_available=False)


# --- leakage ---------------------------------------------------------------

def _code_without_docstrings(path: Path) -> str:
    """Executable code only.

    The module's documentation names the GT fields it deliberately avoids, so a plain
    text search would flag the very sentence promising there is no leak. Docstrings are
    replaced with `pass` and the tree is unparsed, which also drops comments.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body[0] = ast.Pass()
    return ast.unparse(tree)


def test_the_feature_module_never_references_ground_truth():
    """Structural guard: a GT field appearing in the code would be a leak."""
    src = Path(__file__).resolve().parent.parent / "src" / "procmine" / "module2"
    code = _code_without_docstrings(src / "features.py")
    for gt_field in ("process_code", "case_id", "process_variant", "is_boundary",
                     "continuity_label", "gt_manifest", "GTExecution", "dwell_scale"):
        assert gt_field not in code, f"Module 2 features reference GT: {gt_field}"


def test_the_leakage_guard_would_actually_catch_a_leak(tmp_path):
    """A guard that cannot fail proves nothing, so prove it can."""
    leaky = tmp_path / "leaky.py"
    leaky.write_text('"""No GT here, honest."""\n\ndef f(e):\n    return e.case_id\n',
                     encoding="utf-8")
    code = _code_without_docstrings(leaky)
    assert "case_id" in code
    assert "No GT here" not in code, "docstrings must be stripped before searching"

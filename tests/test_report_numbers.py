"""The final report's headline numbers must trace to canonical artifacts.

This is a traceability guard, not an analysis test. It exists so that a number in
`reports/final_report.md` can never silently disagree with the artifact that
produced it — if an artifact is regenerated, or the report prose is edited, this
fails rather than letting the submission drift.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_report_numbers.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_report_numbers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier():
    return _load_verifier()


@pytest.fixture(scope="module")
def report_text(verifier):
    return verifier.REPORT.read_text(encoding="utf-8")


def test_final_report_exists():
    """The final report is a named deliverable in the assignment brief."""
    assert (ROOT / "reports" / "final_report.md").exists()


def test_every_headline_number_traces_to_an_artifact(verifier, report_text):
    """Each claim in the report must render a value recomputed from its artifact."""
    missing = [c for c in verifier.build_checks() if c.rendered not in report_text]
    assert not missing, "report numbers with no matching artifact value: " + ", ".join(
        f"{c.claim}={c.rendered!r} (from {c.artifact})" for c in missing
    )


def test_verifier_script_exits_zero(verifier):
    """Running the script as a reviewer would must succeed."""
    assert verifier.main() == 0


def test_superseded_hr_opportunity_is_never_presented_as_canonical(report_text):
    """0.4186 is the stale pre-entropy-fix value.

    It may appear only in the sentence that explicitly disowns it, never as a
    headline figure. 0.4401 is canonical; 0.4180 is the degraded-excluded case.
    """
    assert "0.4401" in report_text
    # Prose wraps across lines, so inspect a window around each occurrence
    # rather than the single line it happens to fall on.
    start = 0
    while (idx := report_text.find("0.4186", start)) != -1:
        window = report_text[max(0, idx - 200) : idx + 200]
        disclaimers = ("superseded", "never used", "never appears as canonical")
        assert any(d in window for d in disclaimers), (
            f"0.4186 appears without its disclaimer near: {window!r}"
        )
        start = idx + 1


def test_boundary_f1_is_never_called_accuracy(report_text):
    """F1 0.3440 is a transition-level boundary metric, not a segmentation accuracy."""
    lowered = report_text.lower()
    for forbidden in ("34.4% accuracy", "34.4% segmentation accuracy", "accuracy of 0.344"):
        assert forbidden not in lowered


def test_dataset_b_is_never_claimed_accurate(report_text):
    """Dataset B has no ground truth; no accuracy claim may be made for it."""
    lowered = report_text.lower()
    for forbidden in (
        "dataset b segmentation is accurate",
        "dataset-b segmentation is accurate",
        "validated against ground truth on dataset b",
    ):
        assert forbidden not in lowered


def test_execution_share_and_time_share_are_kept_distinct(report_text):
    """77.05% of executions is not 55.89% of handling time; both must be present."""
    assert "77.05%" in report_text
    assert "55.89%" in report_text


def test_no_monetary_roi_claim(report_text):
    """No currency figure may appear — the logs carry no cost or volume data."""
    import re

    monetary = re.findall(r"[$£€]\s?\d", report_text)
    assert not monetary, f"monetary claim found: {monetary}"

"""Guards for the Day-7 recommendation-robustness experiment.

These protect the *honesty* of the result, not the result itself. The experiment
found that the composite Opportunity score is sensitive to the segmentation merge
threshold while the underlying process evidence is not. That is an uncomfortable
finding, and the easiest way for it to quietly disappear is for someone to
re-describe it as stable. These tests make that fail loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "reports/day7/recommendation_sensitivity.json"
REPORT = ROOT / "reports/final_report.md"
HR = "system:HR人事給与システム"


@pytest.fixture(scope="module")
def sens() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_artifact_exists(sens):
    assert sens["baseline_threshold"] == 5
    assert sens["thresholds_tested"] == [0, 5, 11, 36]


def test_control_reproduced_the_canonical_ranking(sens):
    """Without this control, any difference found could be a harness bug."""
    control = sens["control_check"]
    assert control["ranking_order_matches"] is True
    assert control["hr_opportunity_matches"] is True
    assert control["verified"] is True


def test_only_the_merge_threshold_varied(sens):
    """If weights or exclusions had moved too, the experiment would be uninterpretable."""
    assert sens["variable"].startswith("max_away_events")
    held = " ".join(sens["held_constant"]).lower()
    for constant in ("scoring weights", "exclusion policy", "process definitions"):
        assert constant in held


def test_baseline_threshold_matches_the_shipped_pipeline():
    """The experiment's baseline must be the threshold the canonical pipeline uses."""
    source = (ROOT / "scripts/build_process_executions_dataset_b.py").read_text(encoding="utf-8")
    assert "MERGE_MAX_AWAY_EVENTS = 5" in source


def test_evidence_layer_stability_is_reported_accurately(sens):
    """HR must actually lead on handling time at every threshold for the report to say so."""
    ev = sens["summary"]["evidence_layer"]
    assert ev["hr_top_by_handling_time_at_every_threshold"] is True
    assert ev["hr_all_four_operators_at_every_threshold"] is True
    for r in sens["results"].values():
        assert r["hr_rank_by_handling_time"] == 1
        assert r["hr_n_operators"] == 4


def test_score_sensitivity_is_not_softened_in_the_report(sens):
    """The composite score flipped its top candidate. The report must say so."""
    composite = sens["summary"]["composite_score_layer"]
    assert composite["classification"] == "C. SENSITIVE"
    assert composite["top_candidate_unchanged_across_all_thresholds"] is False

    text = REPORT.read_text(encoding="utf-8")
    # The displacing process, HR's fallen rank, and the word "fragile" must all survive.
    assert sens["results"]["11"]["top_candidate"] in text
    assert "HR falls to rank 5" in text
    assert "fragile" in text.lower()
    # And it must never be described as stable overall.
    lowered = text.lower()
    for forbidden in (
        "the recommendation is stable under all",
        "ranking is stable at every threshold",
    ):
        assert forbidden not in lowered


def test_dominant_path_share_is_presented_as_threshold_dependent(sens):
    """77.05% is one segmentation's number, not a property of the work."""
    shares = sens["summary"]["hr_dominant_variant_share_by_threshold"]
    assert shares["5"] == pytest.approx(0.7705, abs=1e-4)
    assert shares["36"] < shares["5"]  # heavier merging absorbs detours into HR
    text = REPORT.read_text(encoding="utf-8")
    assert "threshold-dependent" in text or "threshold-conditional" in text


def test_no_segmentation_accuracy_claim_for_dataset_b(sens):
    """Dataset B has no ground truth; no threshold may be called more correct."""
    note = sens["no_ground_truth_note"].lower()
    assert "no ground truth" in note
    assert "not segmentation accuracy" in note

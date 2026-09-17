"""Tests for the Day-7 segmentation-improvement candidates.

Two things matter here beyond ordinary correctness:

1. **Isolation.** The candidate module must not import the locked segmentation
   package, so an experiment can never silently alter the canonical pipeline.
2. **No leakage.** The LOSO harness must never let a session's own ground truth
   influence its own prediction. A leaked fold would manufacture an improvement.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from procmine.experiments.rule_boundary import (
    SessionArrays, confusion, context_changed, f1_from_counts, predict_rule,
    predict_rule_instrumentation_aware, predict_rule_with_continuity_veto,
    predict_rule_with_motif,
)

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "src/procmine/experiments/rule_boundary.py"
ARTIFACT = ROOT / "reports/day7/segmentation_comparison.json"


def make_arrays(**overrides) -> SessionArrays:
    base = dict(
        session_id="ses_test",
        delta_t_ms=(100, 5_000, 50_000, 200),
        application_changed=(False, True, False, False),
        browser_domain_changed=(False, False, False, True),
        window_title_changed=(True, True, True, True),
        interaction_category_changed=(False, False, False, False),
        chunk_boundary=(False, False, False, False),
        app_pair=(("a", "a"), ("a", "b"), ("b", "b"), ("b", "b")),
        browser_domain_coverage=0.9,
    )
    base.update(overrides)
    return SessionArrays(**base)


# --------------------------------------------------------------------------
# isolation
# --------------------------------------------------------------------------
def test_candidate_module_does_not_import_locked_segmentation():
    """Parse the AST rather than grepping text — the docstring mentions the package."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offenders = [m for m in imported if m.startswith("procmine.segmentation")]
    assert not offenders, f"candidate module imports locked segmentation: {offenders}"


# --------------------------------------------------------------------------
# rule semantics
# --------------------------------------------------------------------------
def test_window_title_is_not_treated_as_context():
    """Measured and rejected twice (lift 0.048 on Day 1, 1.10 on Day 4)."""
    a = make_arrays(
        application_changed=(False,), browser_domain_changed=(False,),
        window_title_changed=(True,), delta_t_ms=(10_000,),
        interaction_category_changed=(False,), chunk_boundary=(False,),
        app_pair=(("a", "a"),),
    )
    assert context_changed(a, 0) is False


def test_rule_fires_on_context_change_with_gap():
    a = make_arrays()
    preds = predict_rule(a, small_gap_ms=1000, large_gap_ms=100_000)
    # index 1: application changed and gap 5000 > 1000
    assert preds[1] is True
    # index 0: no context change, gap 100 below both thresholds
    assert preds[0] is False


def test_rule_fires_on_large_gap_without_context_change():
    a = make_arrays()
    preds = predict_rule(a, small_gap_ms=1000, large_gap_ms=20_000)
    assert preds[2] is True  # gap 50_000 > 20_000, no context change


def test_thresholds_are_strict_greater_than():
    a = make_arrays(delta_t_ms=(1000,), application_changed=(True,),
                    browser_domain_changed=(False,), window_title_changed=(False,),
                    interaction_category_changed=(False,), chunk_boundary=(False,),
                    app_pair=(("a", "b"),))
    assert predict_rule(a, small_gap_ms=1000, large_gap_ms=10**9)[0] is False
    assert predict_rule(a, small_gap_ms=999, large_gap_ms=10**9)[0] is True


def test_continuity_veto_is_demote_only():
    """The veto may remove a boundary but must never invent one."""
    a = make_arrays()
    base = predict_rule(a, small_gap_ms=1000, large_gap_ms=20_000)
    vetoed = predict_rule_with_continuity_veto(
        a, small_gap_ms=1000, large_gap_ms=20_000,
        jaccard=[0.99] * len(a), veto_above=0.6,
    )
    for b, v in zip(base, vetoed):
        assert not (v and not b), "veto invented a boundary"
    assert sum(vetoed) < sum(base), "veto removed nothing despite high jaccard"


def test_continuity_veto_ignores_missing_jaccard():
    a = make_arrays()
    base = predict_rule(a, small_gap_ms=1000, large_gap_ms=20_000)
    same = predict_rule_with_continuity_veto(
        a, small_gap_ms=1000, large_gap_ms=20_000,
        jaccard=[None] * len(a), veto_above=0.6,
    )
    assert same == base


def test_motif_suppresses_a_familiar_hop():
    a = make_arrays()
    without = predict_rule_with_motif(
        a, small_gap_ms=1000, large_gap_ms=100_000, common_pairs=frozenset())
    with_motif = predict_rule_with_motif(
        a, small_gap_ms=1000, large_gap_ms=100_000,
        common_pairs=frozenset({("a", "b")}))
    assert without[1] is True
    assert with_motif[1] is False, "familiar hop should not count as a context change"


def test_instrumentation_aware_switches_threshold_on_coverage():
    healthy = make_arrays(browser_domain_coverage=0.9)
    degraded = make_arrays(browser_domain_coverage=0.0)
    kw = dict(small_gap_ms=1000, large_gap_ms=100_000,
              degraded_small_gap_ms=10_000, degraded_large_gap_ms=100_000,
              coverage_floor=0.40)
    # index 1 (gap 5000, context change) fires under the healthy threshold only
    assert predict_rule_instrumentation_aware(healthy, **kw)[1] is True
    assert predict_rule_instrumentation_aware(degraded, **kw)[1] is False


def test_predictions_are_deterministic():
    a = make_arrays()
    kw = dict(small_gap_ms=1000, large_gap_ms=20_000)
    assert predict_rule(a, **kw) == predict_rule(a, **kw)


def test_predictor_does_not_mutate_its_input():
    a = make_arrays()
    before = (a.delta_t_ms, a.application_changed, a.app_pair)
    predict_rule(a, small_gap_ms=1000, large_gap_ms=20_000)
    assert (a.delta_t_ms, a.application_changed, a.app_pair) == before


# --------------------------------------------------------------------------
# scoring helpers
# --------------------------------------------------------------------------
def test_confusion_counts():
    assert confusion([True, True, False, False], [True, False, True, False]) == (1, 1, 1)


def test_f1_matches_hand_computation():
    # tp=1, fp=1, fn=1 -> p=0.5, r=0.5, f1=0.5
    assert f1_from_counts(1, 1, 1) == pytest.approx(0.5)
    assert f1_from_counts(0, 5, 5) == 0.0


# --------------------------------------------------------------------------
# harness integrity: leakage, control, and the recorded decision
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def comparison() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_loso_excludes_the_held_out_session():
    """Read the harness source and assert the fold explicitly skips the held-out id.

    This is the one bug that would silently manufacture an improvement, so it is
    checked structurally rather than trusted.
    """
    src = (ROOT / "scripts/run_segmentation_improvement_experiment.py").read_text(encoding="utf-8")
    assert "if sid == held:" in src and "continue" in src
    assert "train = [s for s in session_ids if s != held]" in src


def test_baseline_control_reproduced_exactly(comparison):
    assert comparison["baseline_control"]["reproduced"] is True
    assert comparison["baseline_control"]["max_abs_f1_drift"] == 0.0


def test_locked_baseline_metrics_are_preserved(comparison):
    p = comparison["baseline"]["pooled"]
    assert p["f1"] == pytest.approx(0.3440233236151604, abs=1e-12)
    assert p["precision"] == pytest.approx(0.235843, abs=1e-5)
    assert p["recall"] == pytest.approx(0.635548, abs=1e-5)
    assert p["pct_gt_executions_fragmented"] == pytest.approx(79.05, abs=0.01)


def test_promotion_criteria_were_registered_before_scoring(comparison):
    assert comparison["promotion_criteria"]["registered_before_candidates_were_scored"] is True
    g = comparison["promotion_criteria"]["gates"]
    for key in ("min_f1_absolute_gain", "min_recall", "max_fragmentation_pct",
                "max_under_segmentation", "max_over_segmentation"):
        assert key in g


def test_every_candidate_was_evaluated_against_every_gate(comparison):
    for name, c in comparison["candidates"].items():
        assert len(c["gate_checks"]) == 7, f"{name} missing gate checks"
        assert isinstance(c["passes_all_gates"], bool)


def test_decision_matches_the_gate_results(comparison):
    """The recorded decision must follow from the gates, not from preference."""
    winners = [n for n, c in comparison["candidates"].items() if c["passes_all_gates"]]
    assert winners == comparison["candidates_passing_all_gates"]
    if winners:
        assert comparison["decision"].startswith("PROMOTE")
    else:
        assert comparison["decision"] == "RETAIN LOCKED BASELINE"


def test_analysis_document_agrees_with_the_artifact(comparison):
    """The prose says every candidate lost. If that ever stops being true, fail loudly.

    The write-up states a specific decision and specific deltas. This ties the
    document to the artifact so the two cannot drift apart.
    """
    doc = (ROOT / "reports/day7/segmentation_improvement_analysis.md").read_text(encoding="utf-8")
    base_f1 = comparison["baseline"]["pooled"]["f1"]
    beaters = [n for n, c in comparison["candidates"].items()
               if c["eval"]["pooled"]["f1"] > base_f1]
    assert not beaters, (
        f"{beaters} now beat the baseline — segmentation_improvement_analysis.md "
        "claims none do and must be rewritten"
    )
    assert "RETAIN LOCKED SEGMENTATION" in doc
    # the headline deltas quoted in the document must match the artifact
    for name, expected in (("C1_rule_two_threshold", "-0.1195"),
                           ("C2_rule_plus_continuity_veto", "-0.0619")):
        actual = f"{comparison['candidates'][name]['deltas_vs_baseline']['f1']:.4f}"
        assert actual == expected, f"{name} delta drifted: {actual} vs documented {expected}"
        assert expected.lstrip("-") in doc

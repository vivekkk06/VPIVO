"""Tests for the work-thread pairwise experiment.

The properties worth guarding here are the ones that, if broken, would silently
manufacture a positive result: GT leaking into features, pairs crossing sessions, an
unbounded neighbourhood, or non-deterministic sampling. Each is checked structurally
or behaviourally rather than trusted.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "run_work_thread_pairwise_experiment.py"
ARTIFACT = ROOT / "reports" / "day7" / "work_thread_pairwise_experiment.json"
AUDIT = ROOT / "reports" / "day7" / "work_thread_signal_audit.md"
ANALYSIS = ROOT / "reports" / "day7" / "work_thread_reconstruction_analysis.md"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("wt_pairwise", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def artifact() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _events(n: int, *, app="Edge", start=0, step=1000):
    return [{"ts": start + i * step, "type": "keystroke", "app": app,
             "title": "W", "domain": "127.0.0.1:5122", "tab": "tab_1",
             "chunk": "c1"} for i in range(n)]


# --------------------------------------------------------------------------
# leakage — the failure that would fake a positive result
# --------------------------------------------------------------------------
def test_no_gt_derived_value_is_a_feature(mod):
    """Feature names must contain nothing derived from ground truth."""
    forbidden = ("case", "process_code", "execution", "gt_", "boundary", "label")
    for name in mod.FEATURES:
        for bad in forbidden:
            assert bad not in name.lower(), f"feature {name!r} looks GT-derived"


def test_feature_vector_width_matches_declared_features(mod):
    """A silent extra column would make FEATURES a lie, and importances misaligned."""
    ev = _events(30)
    labels = ["c1"] * 30
    X, y, meta = mod.build_pairs(ev, labels, random.Random(0))
    assert X, "no pairs built"
    assert len(X[0]) == len(mod.FEATURES)


def test_intervening_flag_is_metadata_not_a_feature(mod):
    """The GT-derived stratifier must live in meta, never in X."""
    ev = _events(40)
    labels = ["a"] * 15 + ["b"] * 10 + ["a"] * 15
    X, y, meta = mod.build_pairs(ev, labels, random.Random(0))
    assert "intervening_other_work" in meta[0]
    assert len(X[0]) == len(mod.FEATURES)


def test_labels_come_from_case_id_equality(mod):
    ev = _events(10)
    labels = ["a"] * 5 + ["b"] * 5
    _, y, _ = mod.build_pairs(ev, labels, random.Random(0))
    assert set(y) <= {0, 1}
    assert 1 in y and 0 in y


def test_unlabelled_events_are_excluded(mod):
    """Events outside any GT execution carry no label and must not form pairs."""
    ev = _events(12)
    labels = [None] * 12
    X, y, meta = mod.build_pairs(ev, labels, random.Random(0))
    assert X == [] and y == []


# --------------------------------------------------------------------------
# bounded neighbourhood and session scoping
# --------------------------------------------------------------------------
def test_neighbourhood_is_bounded(mod):
    """No pair may exceed MAX_GAP -- an unbounded graph would be O(N^2)."""
    ev = _events(2000)
    labels = ["c"] * 2000
    _, _, meta = mod.build_pairs(ev, labels, random.Random(0))
    assert meta
    assert max(m["index_gap"] for m in meta) <= mod.MAX_GAP


def test_pairs_never_cross_sessions(mod):
    """build_pairs receives one session at a time; the harness must keep it that way."""
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "build_pairs"]
    assert calls, "build_pairs is never called"
    # it is called inside the per-session loop, and groups are tagged with that session
    assert "g_all.extend([s.session_id] * len(X))" in src


def test_pair_count_is_capped_per_session(mod):
    ev = _events(5000)
    labels = ["c"] * 5000
    X, _, _ = mod.build_pairs(ev, labels, random.Random(0))
    assert len(X) <= mod.MAX_PAIRS_PER_SESSION


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------
def test_pair_building_is_deterministic(mod):
    ev = _events(3000)
    labels = ["c"] * 3000
    a = mod.build_pairs(ev, labels, random.Random(mod.SEED))
    b = mod.build_pairs(ev, labels, random.Random(mod.SEED))
    assert a[0] == b[0] and a[1] == b[1]


def test_empty_and_sparse_sessions_do_not_crash(mod):
    assert mod.build_pairs([], [], random.Random(0)) == ([], [], [])
    ev = _events(1)
    assert mod.build_pairs(ev, ["c"], random.Random(0)) == ([], [], [])


def test_degraded_instrumentation_session_still_produces_pairs(mod):
    """A session with no browser domain at all must still be processed, not skipped."""
    ev = _events(60)
    for e in ev:
        e["domain"] = None
        e["tab"] = None
    labels = ["c"] * 60
    X, y, _ = mod.build_pairs(ev, labels, random.Random(0))
    assert X, "degraded session produced no pairs"
    di = mod.FEATURES.index("both_domains_known")
    assert all(row[di] == 0.0 for row in X)


# --------------------------------------------------------------------------
# the recorded findings must not drift from the artifact
# --------------------------------------------------------------------------
def test_artifact_records_session_grouped_split(artifact):
    assert "GroupKFold" in artifact["leakage_controls"]["split"]
    assert artifact["leakage_controls"]["gt_derived_features"] == "none"


def test_long_range_performance_is_materially_worse_than_short_range(artifact):
    """The core finding: the model works where proximity already answers the question."""
    gaps = artifact["results"]["random_forest"]["by_index_gap"]
    near = gaps["adjacent_1_to_3"]["f1"]
    far = gaps["far_101_to_600"]["f1"]
    assert far < near - 0.3, f"expected collapse at long range; near={near} far={far}"


def test_linking_signals_contribute_far_less_than_temporal(artifact):
    """90% temporal vs 5% linking -- the quantified reason the hypothesis fails."""
    imp = {f["feature"]: f["importance"] for f in artifact["random_forest_feature_importance"]}
    temporal = sum(imp.get(k, 0) for k in
                   ("log1p_delta_t_ms", "index_gap", "n_app_switches_between",
                    "any_navigation_between"))
    linking = sum(imp.get(k, 0) for k in
                  ("same_window_title", "same_browser_domain", "same_tab_id",
                   "both_tabs_known", "both_domains_known", "same_application"))
    assert temporal > 0.8
    assert linking < 0.15
    assert temporal > linking * 5


def test_intervening_work_stratum_is_single_class(artifact):
    """Strict sequencing makes 'different work intervenes' imply 'different execution'."""
    d = artifact["results"]["random_forest"]["the_decisive_split"]["intervening_other_work"]
    assert "note" in d, "expected a single-class stratum"
    assert d["n"] > 1000, "expected a large intervening stratum at long range"


def test_baseline_is_not_modified_by_this_experiment():
    """The experiment must not write to the locked baseline artifact."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "protected_boundary_experiment" not in src
    assert "final_architecture" not in src


def test_reports_record_the_rejection(artifact):
    audit = AUDIT.read_text(encoding="utf-8")
    analysis = ANALYSIS.read_text(encoding="utf-8")
    assert "RETAIN LOCKED BASELINE" in analysis
    # the two preconditions and their verdicts
    assert "0.00%" in analysis or "zero interleav" in analysis.lower()
    assert "37.8" in audit, "tab_id coarseness finding missing"
    assert "0.07%" in audit, "text coverage finding missing"


# ==========================================================================
# Closure audit: independent P1 verification and the feature-group ablation.
# ==========================================================================
CLOSURE_SCRIPT = ROOT / "scripts" / "run_work_thread_closure_audit.py"
CLOSURE_ARTIFACT = ROOT / "reports" / "day7" / "work_thread_closure_audit.json"


@pytest.fixture(scope="module")
def closure_mod():
    spec = importlib.util.spec_from_file_location("wt_closure", CLOSURE_SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def closure(closure_mod) -> dict:
    return json.loads(CLOSURE_ARTIFACT.read_text(encoding="utf-8"))


# ---- independent P1 logic, unit-tested on synthetic cases -----------------
def test_sweep_line_detects_overlap_when_it_exists(closure_mod):
    """The verifier must be capable of finding interleaving -- otherwise zero is vacuous."""
    overlapping = [(0, 100, "a"), (50, 150, "b")]
    r = closure_mod.sweep_line_concurrency(overlapping)
    assert r["max_concurrency"] == 2
    assert r["executions_involved_in_overlap"] == 2


def test_sweep_line_detects_nesting(closure_mod):
    nested = [(0, 200, "a"), (50, 100, "b")]
    assert closure_mod.sweep_line_concurrency(nested)["max_concurrency"] == 2


def test_sweep_line_treats_touching_executions_as_adjacent_not_concurrent(closure_mod):
    """One ending exactly as the next begins is sequencing, not interleaving."""
    touching = [(0, 100, "a"), (100, 200, "b")]
    assert closure_mod.sweep_line_concurrency(touching)["max_concurrency"] == 1


def test_run_length_detects_a_b_a(closure_mod):
    r = closure_mod.run_length_returns(["a", "a", "b", "b", "a", "a"])
    assert r["cases_appearing_in_multiple_runs"] == 1
    assert r["max_runs_for_one_case"] == 2


def test_run_length_ignores_unlabelled_gaps_inside_one_execution(closure_mod):
    """An idle pause inside an execution must not look like a leave-and-return."""
    r = closure_mod.run_length_returns(["a", None, None, "a"])
    assert r["cases_appearing_in_multiple_runs"] == 0


def test_run_length_on_strictly_sequential_work(closure_mod):
    r = closure_mod.run_length_returns(["a", "a", "b", "b", "c"])
    assert r["cases_appearing_in_multiple_runs"] == 0


# ---- the recorded closure findings ---------------------------------------
def test_p1_independently_confirms_zero_interleaving(closure):
    p = closure["p1_independent_verification"]
    assert p["total_gt_executions_analysed"] == 1752
    assert p["sessions_analysed"] == 63
    assert p["max_simultaneous_executions_anywhere"] == 1
    assert p["executions_involved_in_overlap"] == 0
    assert p["sessions_with_any_overlap"] == 0
    assert p["observable_a_b_a_cases"] == 0
    assert p["observable_non_contiguous_cases"] == 0


def test_p1_used_a_different_method_than_the_original(closure):
    m = closure["p1_independent_verification"]["method"].lower()
    assert "sweep" in m and "run-length" in m
    assert "independent" in m


def test_feature_groups_are_disjoint_and_cover_all_features(closure_mod, mod):
    a = set(closure_mod.GROUP_TEMPORAL); b = set(closure_mod.GROUP_LINKING)
    assert not (a & b), "feature groups overlap"
    assert a | b == set(mod.FEATURES), "groups do not cover every feature"


def test_ablation_shows_temporal_alone_nearly_matches_combined(closure):
    ab = closure["feature_group_ablation"]
    t = ab["A_temporal_positional_only"]["f1"]
    c = ab["C_combined"]["f1"]
    assert c - t < 0.05, f"linking adds more than expected: +{c - t:.4f}"
    assert t / c > 0.95, "temporal-only should recover most of combined F1"


def test_ablation_shows_linking_alone_is_weaker_but_not_worthless(closure):
    """The honest finding: linking is real signal, just largely redundant."""
    b = closure["feature_group_ablation"]["B_linking_context_only"]
    a = closure["feature_group_ablation"]["A_temporal_positional_only"]
    assert b["roc_auc"] > 0.6, "linking-only should beat chance -- it is not noise"
    assert b["roc_auc"] < a["roc_auc"], "linking-only must be weaker than temporal-only"


def test_report_records_the_correction_to_the_importance_framing():
    """§25.3 corrects §7's 90/5 framing; both must stay in the report."""
    text = ANALYSIS.read_text(encoding="utf-8")
    assert "Final Scientific Closure" in text
    assert "0.7651" in text, "linking-only ROC-AUC missing"
    assert "understates" in text or "overstates" in text


def test_intervening_stratum_is_verified_single_class(closure):
    s = closure["intervening_stratum"]
    assert s["n_intervening_pairs"] > 1000
    assert s["label_counts_in_intervening_stratum"]["same_execution_1"] == 0
    assert s["label_counts_in_intervening_stratum"]["different_execution_0"] == s["n_intervening_pairs"]


def test_closure_audit_writes_no_canonical_artifact():
    src = CLOSURE_SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("protected_boundary_experiment", "problem2_audit_results",
                      "process_executions_dataset_b", "segments.jsonl"):
        assert forbidden not in src


def test_dataset_b_was_not_touched_by_either_script():
    for p in (SCRIPT, CLOSURE_SCRIPT):
        assert "dataset_b" not in p.read_text(encoding="utf-8")


def test_convention_limitation_is_recorded_not_overclaimed():
    """The report must keep 'unobservable' distinct from 'does not happen'."""
    text = ANALYSIS.read_text(encoding="utf-8")
    assert "NOT CLAIMED" in text
    assert "by construction" in text

"""Tests for the Day-5 frontend data bridge (`scripts/build_frontend_data.py`).

These are integration tests against the real committed Day-1..Day-4
artifacts, deliberately: the whole purpose of the bridge is that the
frontend sees exactly what the analytical pipeline produced, and a test
built on synthetic fixtures could pass while the real bundle carried
superseded numbers. Nothing is written into the repository -- every run
targets pytest's tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "build_frontend_data.py"
_spec = importlib.util.spec_from_file_location("build_frontend_data", _SCRIPT)
_module = importlib.util.module_from_spec(_spec)
sys.modules["build_frontend_data"] = _module
_spec.loader.exec_module(_module)


def _load_source(rel: str) -> dict:
    return json.loads((_REPO_ROOT / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("frontend_data")
    _module.build(_REPO_ROOT, out)
    return out


def _read(bundle: Path, name: str):
    return json.loads((bundle / name).read_text(encoding="utf-8"))


# --- path safety ----------------------------------------------------------

def test_refuses_to_write_outside_the_out_directory(tmp_path):
    with pytest.raises(ValueError, match="refusing to write outside"):
        _module.write_json(tmp_path, "../escaped.json", {"x": 1})


def test_refuses_a_deeply_escaping_relative_path(tmp_path):
    with pytest.raises(ValueError, match="refusing to write outside"):
        _module.write_json(tmp_path, "executions/../../escaped.json", {"x": 1})


def test_normal_nested_write_is_allowed(tmp_path):
    target = _module.write_json(tmp_path, "executions/ses_x.json", [{"a": 1}])
    assert target.exists()
    assert tmp_path.resolve() in target.parents


# --- execution completeness ----------------------------------------------

def test_index_preserves_every_source_execution(bundle):
    source = _load_source("reports/day3/process_executions_dataset_b.json")["executions"]
    index = _read(bundle, "executions-index.json")
    assert len(index) == len(source) == 645
    assert {r["execution_id"] for r in index} == {e["execution_id"] for e in source}


def test_index_omits_ordered_steps(bundle):
    index = _read(bundle, "executions-index.json")
    assert all("ordered_steps" not in row for row in index)


def test_per_session_files_partition_the_executions_exactly(bundle):
    source = _load_source("reports/day3/process_executions_dataset_b.json")["executions"]
    files = sorted((bundle / "executions").glob("*.json"))
    seen: list[str] = []
    for f in files:
        for ex in json.loads(f.read_text(encoding="utf-8")):
            seen.append(ex["execution_id"])
    assert len(seen) == len(set(seen)), "an execution appears in more than one session file"
    assert set(seen) == {e["execution_id"] for e in source}


def test_one_file_per_session_named_by_session_id(bundle):
    source = _load_source("reports/day3/process_executions_dataset_b.json")["executions"]
    expected = {e["session_id"] for e in source}
    files = {p.stem for p in (bundle / "executions").glob("*.json")}
    assert files == expected
    assert len(files) == 15


def test_per_session_files_keep_ordered_steps(bundle):
    for f in (bundle / "executions").glob("*.json"):
        for ex in json.loads(f.read_text(encoding="utf-8")):
            assert "ordered_steps" in ex


def test_executions_are_sorted_deterministically_within_a_session(bundle):
    for f in (bundle / "executions").glob("*.json"):
        rows = json.loads(f.read_text(encoding="utf-8"))
        starts = [r["start_ms"] for r in rows]
        assert starts == sorted(starts)


# --- the canonical-ranking traps -----------------------------------------

def test_hr_opportunity_matches_the_post_entropy_fix_audit_artifact(bundle):
    """Guards the entropy-fix trap: problem2_process_metrics.json holds the
    superseded 0.4186. The bundle must carry the audit file's 0.4401."""
    audit = _load_source("reports/day3/problem2_audit_results.json")
    expected = audit["default_ranking"][0]
    hr = _read(bundle, "opportunities.json")["ranking"][0]
    assert hr["process_id"] == expected["process_id"]
    assert hr["impact"] == expected["impact"] == 0.9236
    assert hr["feasibility"] == expected["feasibility"] == 0.4765
    assert hr["opportunity"] == expected["opportunity"] == 0.4401


def test_superseded_opportunity_value_never_appears_in_the_bundle(bundle):
    ranking = _read(bundle, "opportunities.json")["ranking"]
    assert all(row["opportunity"] != 0.4186 for row in ranking)


def test_rank_four_is_financial_accounting_and_five_is_expense_calculation(bundle):
    """Guards the ordering trap -- these two are easy to transpose."""
    ranking = _read(bundle, "opportunities.json")["ranking"]
    assert "Financial Accounting" in ranking[3]["readable_name"]
    assert "Expense Calculation" in ranking[4]["readable_name"]
    assert ranking[3]["opportunity"] > ranking[4]["opportunity"]


def test_full_ranking_matches_the_audit_artifact_row_for_row(bundle):
    audit = _load_source("reports/day3/problem2_audit_results.json")["default_ranking"]
    ranking = _read(bundle, "opportunities.json")["ranking"]
    assert len(ranking) == len(audit) == 21
    for got, expected in zip(ranking, audit):
        assert got["rank"] == expected["rank"]
        assert got["process_id"] == expected["process_id"]
        assert got["opportunity"] == expected["opportunity"]


# --- HR evidence ----------------------------------------------------------

def test_variant_split_is_carried_explicitly_and_matches_source(bundle):
    """94/24/4 is NOT derivable from variants.json; it must be copied from
    the dominant-path artifact or the UI would have to recompute it."""
    source = _load_source("reports/day3/hr_payroll_dominant_path_dataset_b.json")
    split = _read(bundle, "hr-payroll.json")["variant_split"]
    assert split == source["variant_split"]
    assert split["dominant"]["n"] == 94
    assert split["word_detour"]["n"] == 24
    assert split["rare_edge"]["n"] == 4


def test_hr_dfg_is_copied_from_the_mining_results(bundle):
    source = _load_source("reports/day3/problem2_process_mining_full_results.json")
    assert _read(bundle, "hr-payroll.json")["dfg"] == source["hr_payroll_dfg"]


# --- instrumentation ------------------------------------------------------

def test_instrumentation_is_copied_verbatim(bundle):
    inst = _read(bundle, "instrumentation.json")
    assert inst["dataset_a"] == _load_source("reports/day4/instrumentation_health_dataset_a.json")
    assert inst["dataset_b"] == _load_source("reports/day4/instrumentation_health_dataset_b.json")


def test_session_health_fields_match_the_day4_artifact(bundle):
    health = {
        h["session_id"]: h
        for key in ("a", "b")
        for h in _load_source(f"reports/day4/instrumentation_health_dataset_{key}.json")["per_session"]
    }
    for s in _read(bundle, "sessions.json"):
        src = health[s["session_id"]]
        assert s["status"] == src["status"]
        assert s["browser_domain_coverage"] == src["browser_domain_coverage"]
        assert s["n_distinct_browser_domains"] == src["n_distinct_browser_domains"]
        assert s["n_events"] == src["n_events"]
        assert s["warnings"] == src["warnings"]


def test_dataset_a_sessions_have_null_execution_counts(bundle):
    """Dataset A has no persisted executions -- null, not a misleading 0."""
    rows = [s for s in _read(bundle, "sessions.json") if s["dataset"] == "dataset_a"]
    assert len(rows) == 63
    assert all(s["n_executions"] is None for s in rows)


def test_dataset_b_execution_counts_sum_to_the_source_total(bundle):
    rows = [s for s in _read(bundle, "sessions.json") if s["dataset"] == "dataset_b"]
    assert len(rows) == 15
    assert sum(s["n_executions"] for s in rows) == 645


# --- derived fields -------------------------------------------------------

def test_derived_operator_agrees_with_the_operator_recorded_on_executions(bundle):
    """`operator` is derived by parsing session_id; the Dataset-B execution
    records carry their own `operator`. They must not disagree."""
    source = _load_source("reports/day3/process_executions_dataset_b.json")["executions"]
    recorded = {e["session_id"]: e["operator"] for e in source}
    for s in _read(bundle, "sessions.json"):
        if s["session_id"] in recorded:
            assert s["operator"] == recorded[s["session_id"]]


def test_operator_of_parses_the_machine_segment():
    assert _module.operator_of("ses_20260701-164424-CHAITANYA0BCF") == "CHAITANYA0BCF"
    assert _module.operator_of("ses_20260701-175258-LAPTOP-76QMG9DE") == "LAPTOP-76QMG9DE"
    assert _module.operator_of("malformed") == "unknown"


# --- processes and variants ----------------------------------------------

def test_processes_cover_every_profile_including_excluded_ones(bundle):
    profiles = _load_source("reports/day3/process_profiles_dataset_b.json")
    rows = _read(bundle, "processes.json")
    assert len(rows) == len(profiles) == 29
    assert sum(1 for p in rows if not p["excluded_from_ranking"]) == 21


def test_variants_flatten_without_losing_rows(bundle):
    source = _load_source("reports/day3/process_variants_dataset_b.json")
    expected = sum(len(v) for v in source.values())
    rows = _read(bundle, "variants.json")
    assert len(rows) == expected
    assert all("process_id" in r and "signature" in r for r in rows)


# --- determinism ----------------------------------------------------------

def test_two_runs_are_byte_identical_except_meta_generated_at(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _module.build(_REPO_ROOT, a)
    _module.build(_REPO_ROOT, b)

    files_a = sorted(p.relative_to(a) for p in a.rglob("*.json"))
    files_b = sorted(p.relative_to(b) for p in b.rglob("*.json"))
    assert files_a == files_b

    for rel in files_a:
        if rel.name == "meta.json":
            continue
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), f"non-deterministic: {rel}"


def test_meta_records_provenance_and_known_gaps(bundle):
    meta = _read(bundle, "meta.json")
    assert "generated_at" in meta
    assert meta["canonical_sources"]["audit"]["path"].endswith("problem2_audit_results.json")
    assert any("Dataset-A PREDICTED" in n for n in meta["not_available"])
    assert meta["outputs"]["executions-index.json"] == 645


# --- Day-6 contract additions: sensitivity passthroughs -------------------

def test_opportunities_carries_per_scenario_sensitivity_verbatim(bundle):
    """The Decision Center needs to show WHICH assumptions move the ranking,
    not just the aggregate. Copied from the same canonical audit artifact the
    ranking comes from; no scenario is renamed or recomputed."""
    audit = _load_source("reports/day3/problem2_audit_results.json")
    got = _read(bundle, "opportunities.json")["sensitivity_scenarios"]
    assert got == audit["sensitivity_analysis"]
    assert len(got) == audit["sensitivity_summary"]["n_scenarios"]


def test_scenario_hr_first_count_matches_the_artifact_summary(bundle):
    opp = _read(bundle, "opportunities.json")
    scenarios = opp["sensitivity_scenarios"]
    n_first = sum(1 for v in scenarios.values() if v["hr_rank"] == 1)
    assert n_first == opp["sensitivity_summary"]["n_hr_first"]


def test_instrumentation_sensitivity_file_matches_the_day4_artifact(bundle):
    day4 = _load_source("reports/day4/instrumentation_sensitivity_check.json")
    got = _read(bundle, "instrumentation-sensitivity.json")
    assert got["ranking_comparison"] == day4["ranking_comparison"]
    assert got["executions_total"] == day4["executions_total"] == 645
    assert got["executions_kept"] == day4["executions_kept"]
    assert got["top_candidate_unchanged"] is True


def test_day4_sensitivity_keeps_0_4401_canonical_and_0_4180_as_the_case_b_value(bundle):
    """Guards the value trap from the other direction: 0.4401 must stay the
    canonical Opportunity, and 0.4180 must appear only as the Day-4
    degraded-excluded case -- never as the headline figure."""
    ranking = _read(bundle, "opportunities.json")["ranking"]
    assert ranking[0]["opportunity"] == 0.4401

    hr_id = ranking[0]["process_id"]
    row = next(r for r in _read(bundle, "instrumentation-sensitivity.json")["ranking_comparison"]
               if r["process_id"] == hr_id)
    assert row["opportunity_a"] == 0.4401
    assert row["opportunity_b"] == 0.418
    assert row["rank_case_a"] == row["rank_case_b"] == 1


# --- Day-6 Dataset-B surrogate visual review -------------------------------

def test_visual_review_is_copied_verbatim_from_its_artifact(bundle):
    results = _load_source(str(_module.VISUAL_REVIEW_SOURCE))
    got = _read(bundle, "module-comparison.json")["dataset_b_visual_review"]
    summary = results["summary"]
    for key in ("sample_size", "screenshots_available", "screenshots_unavailable", "counts",
                "counts_by_sample_type", "boundary_samples_judgeable",
                "control_samples_judgeable", "boundary_sample_visual_support_rate",
                "control_sample_visual_continuity_rate", "ambiguous_total", "not_metrics_note"):
        assert got[key] == summary[key], key
    assert got["label"] == results["label"]
    assert got["status"] == results["status"]
    assert got["decision"]["outcome"] == results["decision"]["outcome"]
    assert got["screenshots_recovered"] == results["recovery"]["recovered"]


def test_visual_review_adds_nothing_to_the_human_review_block(bundle):
    """The surrogate review must not be written into the human sheet's status."""
    mc = _read(bundle, "module-comparison.json")
    sample = _load_source("reports/day6/module2/module2_dataset_b_screenshot_sample.json")
    assert mc["dataset_b_review"]["review_status"] == sample["review_status"]
    assert "NOT REVIEWED" in mc["dataset_b_review"]["review_status"]


def test_bundle_still_builds_without_the_visual_review(tmp_path, monkeypatch):
    monkeypatch.setattr(_module, "VISUAL_REVIEW_SOURCE",
                        Path("reports/day6/module2/not_a_real_review.json"))
    _module.build(_REPO_ROOT, tmp_path)
    mc = _read(tmp_path, "module-comparison.json")
    assert mc["dataset_b_visual_review"] is None
    assert "module2_visual_review" not in _read(tmp_path, "meta.json")["canonical_sources"]


# --- Day 1-4 investigation views --------------------------------------------

def test_investigation_dataset_totals_match_the_day1_artifacts(bundle):
    day1 = _read(bundle, "investigation.json")["day1"]
    inventory = _load_source("reports/day1/dataset_inventory.json")
    for key, suffix in (("dataset_a", "a"), ("dataset_b", "b")):
        got = day1["datasets"][key]
        audit = _load_source(f"reports/day1/full_audit_dataset_{suffix}.json")
        assert got["sessions"] == inventory[key]["n_sessions"]
        assert got["chunks"] == inventory[key]["n_chunks"]
        assert got["events"] == audit["n_events_total"]
        assert got["multi_chunk_sessions"] == sum(
            1 for s in inventory[key]["sessions"] if s["n_chunks"] >= 2)
    assert (day1["datasets"]["dataset_a"]["sessions"], day1["datasets"]["dataset_a"]["chunks"],
            day1["datasets"]["dataset_a"]["events"]) == (63, 117, 162768)
    assert (day1["datasets"]["dataset_b"]["sessions"], day1["datasets"]["dataset_b"]["chunks"],
            day1["datasets"]["dataset_b"]["events"]) == (15, 20, 20477)
    assert day1["datasets"]["dataset_a"]["multi_chunk_sessions"] == 53


def test_investigation_quality_checks_are_sums_of_the_audit_rows(bundle):
    checks = _read(bundle, "investigation.json")["day1"]["checks"]["dataset_a"]
    audit = _load_source("reports/day1/full_audit_dataset_a.json")
    assert checks["sequential_duplicates"] == audit["total_sequential_duplicates"] == 33232
    assert checks["sequential_duplicates_by_type"]["app_switch"] == 32876
    assert checks["semantic_duplicate_groups"] == 42
    assert checks["sessions_with_out_of_order_pairs"] == 63
    tic = checks["text_input_complete"]
    assert (tic["events"], tic["with_content"], tic["missing_or_empty"]) == (118, 116, 2)
    assert tic["password_fields_with_plaintext"] == 18
    assert checks["clipboard_change"]["events"] == checks["clipboard_change"]["empty_payload"]


def test_investigation_carries_no_text_values_from_the_logs(bundle):
    """Only counts leave the audit: no typed, pasted or password value may be copied."""
    raw = (bundle / "investigation.json").read_text(encoding="utf-8")
    for forbidden in ('"final_text"', '"extracted_text"', '"clipboard_text"', '"password"'):
        assert forbidden not in raw
    tic = json.loads(raw)["day1"]["checks"]["dataset_a"]["text_input_complete"]
    assert all(isinstance(v, int) for v in tic.values())


def test_documented_figures_are_verified_against_their_reports(bundle):
    documented = _read(bundle, "investigation.json")["documented"]
    assert set(documented) == set(_module.DOCUMENTED)
    for key, (value, rel, quote) in _module.DOCUMENTED.items():
        assert documented[key] == {"value": value, "source": rel}
        assert quote in (_REPO_ROOT / rel).read_text(encoding="utf-8"), key


def test_build_fails_when_a_documented_figure_leaves_its_report(tmp_path, monkeypatch):
    broken = dict(_module.DOCUMENTED)
    broken["screenshot_resolution_a"] = ("9.9%", "reports/day1/data_quality_report.md",
                                         "| **Resolution rate** | **9.9%** |")
    monkeypatch.setattr(_module, "DOCUMENTED", broken)
    with pytest.raises(SystemExit, match="no longer appears"):
        _module.build(_REPO_ROOT, tmp_path)


def test_reconstruction_record_copies_the_canonical_day2_systems(bundle):
    day2 = _read(bundle, "investigation.json")["day2"]
    systems = _load_source("reports/day2/protected_boundary_experiment_dataset_a.json")["systems"]
    for name, system in systems.items():
        for metric in _module.POOLED_KEYS:
            assert day2["systems"][name][metric] == system["pooled"][metric], (name, metric)
    locked = next(e for e in day2["experiments"] if e["id"] == "combined")
    assert locked["status"] == "LOCKED"
    assert locked["metrics"]["f1"] == 0.3440233236151604
    assert day2["protection"]["Strategy_Agreement"]["false_to_true_protection_ratio"] == 11.28


def test_reconstruction_record_keeps_every_failure_and_rejection(bundle):
    experiments = _read(bundle, "investigation.json")["day2"]["experiments"]
    status = {e["id"]: e["status"] for e in experiments}
    assert status["v1"] == status["v2"] == "FAILED"
    assert status["agreement"] == "REJECTED"
    assert status["tempo"] == "NOT SELECTED"
    assert status["module2"] == "NOT PROMOTED"
    day7 = [e for e in experiments if e["day"] == "Day 7"]
    assert len(day7) == 4 and all(e["status"] == "REJECTED" for e in day7)
    c2 = next(e for e in day7 if e["id"] == "C2_rule_plus_continuity_veto")
    assert round(c2["metrics"]["f1"], 4) == 0.2822
    assert round(c2["metrics"]["pct_gt_executions_fragmented"], 2) == 40.87
    assert round(c2["metrics"]["under_segmentation_rate"], 4) == 0.6606
    for e in experiments:
        assert e["result"] and e["failure_mode"] and e["decision"], e["id"]


def test_reconstruction_record_carries_module2_gain_and_gate(bundle):
    module2 = _read(bundle, "investigation.json")["day2"]["module2"]
    assert module2["f1_gain"] == 0.0102
    assert module2["required_gain"] == 0.02
    assert round(module2["metrics"]["f1"], 4) == 0.3519
    assert "NOT PROMOTED" in module2["status"]


def test_threshold_curve_is_the_full_session_boundary_first_sweep(bundle):
    curve = _read(bundle, "investigation.json")["day2"]["v1_threshold_curve"]
    source = _load_source("reports/day2/threshold_tradeoff_dataset_a.json")["v1_curve"]
    assert len(curve) == len(source)
    best = _load_source("reports/day2/threshold_tradeoff_dataset_a.json")["v1_best_f1_point"]
    v1 = _load_source("reports/day2/protected_boundary_experiment_dataset_a.json")["systems"]["V1"]["pooled"]
    # the sweep shares the full-session basis with the systems it is drawn beside
    assert best["f1"] == pytest.approx(v1["f1"])


def test_day3_operational_metrics_never_carry_scores(bundle):
    day3 = _read(bundle, "investigation.json")["day3"]
    hr = day3["process_metrics"]["system:HR人事給与システム"]
    assert hr["time_share"] == 0.3248
    assert hr["execution_count"] == 122
    for row in day3["process_metrics"].values():
        assert not {"impact", "feasibility", "opportunity"} & set(row)
    assert "0.4186" not in json.dumps(day3)


def test_day4_machine_labels_are_anonymous_and_consistent(bundle):
    day4 = _read(bundle, "investigation.json")["day4"]
    raw = json.dumps(day4)
    health_a = _load_source("reports/day4/instrumentation_health_dataset_a.json")
    health_b = _load_source("reports/day4/instrumentation_health_dataset_b.json")
    for host in list(health_a["by_machine"]) + list(health_b["by_machine"]):
        assert host not in raw, host
    assert all(m["label"].startswith("Machine ") for m in day4["machines_a"] + day4["machines_b"])
    assert sum(m["flagged"] for m in day4["machines_a"]) == 8
    assert sum(m["flagged"] for m in day4["machines_b"]) == 2
    assert max(day4["machines_a"], key=lambda m: m["flagged"]) == {"label": "Machine A", "sessions": 7, "flagged": 7}
    assert day4["agreement"]["confusion"] == {"tp": 8, "fp": 0, "fn": 2, "tn": 53}
    assert day4["summary"]["dataset_a"]["n_degraded"] == 8
    assert day4["summary"]["dataset_b"]["n_degraded"] == 2

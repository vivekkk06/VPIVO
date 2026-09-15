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

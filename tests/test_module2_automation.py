"""Module 2 automation: pre-flight variant routing and post-action evidence audit.

The two layers are tested for opposite failure modes.

**Routing** must fail *closed*. Every test that is not a positive, evidenced match has
to come back `HUMAN`; a gate that quietly admits an unrecognised execution is worse
than no gate, because it looks like protection.

**The audit** must not overclaim. A check it could not perform is `UNAVAILABLE` and
must never be counted as a pass — missing evidence is not good news — and nothing it
reports may be read as proof that a business record was written.
"""

from __future__ import annotations

import json

import pytest

from procmine.automation.hr_payroll_automation import (
    confirm_submission, prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockHRApplication
from procmine.module2.post_action_audit import (
    CHECK_FAIL, CHECK_PASS, CHECK_UNAVAILABLE, EvidenceCheck, PostActionEvidence,
    audit_post_action, pixel_difference_ratio, sha256_of,
)
from procmine.module2.routing import (
    DECISION_AUTOMATE, DECISION_HUMAN, REASON_AMBIGUOUS_ROUTE_SET,
    REASON_DETOUR_APPLICATION, REASON_DOMINANT_PATH_MATCH, REASON_MULTI_SYSTEM_VARIANT,
    REASON_NO_ROUTE_EVIDENCE, REASON_UNKNOWN_ROUTE, coverage, route_execution,
)

VALID_ROUTE = "#/payroll-items"
NOTE = "Reviewed per standard process."
HR_SYSTEM = "system:HR人事給与システム"


# --- routing: the one admitted case ---------------------------------------

def test_a_dominant_path_execution_is_admitted():
    d = route_execution(routes_visited=[VALID_ROUTE], applications=["Microsoft Edge"])
    assert d.decision == DECISION_AUTOMATE
    assert d.reason_code == REASON_DOMINANT_PATH_MATCH
    assert d.eligible is True


def test_repeated_visits_to_one_evidenced_route_are_still_the_dominant_path():
    d = route_execution(routes_visited=[VALID_ROUTE] * 5, applications=["Microsoft Edge"])
    assert d.eligible is True


def test_incidental_notepad_does_not_disqualify_the_dominant_path():
    """Notepad appears once in 94 dominant executions; treating it as a marker would
    refuse a genuinely dominant execution on a single observation."""
    d = route_execution(routes_visited=[VALID_ROUTE],
                        applications=["Microsoft Edge", "Notepad"])
    assert d.eligible is True


# --- routing: everything else must be refused -----------------------------

def test_a_word_detour_execution_is_refused():
    d = route_execution(routes_visited=[VALID_ROUTE],
                        applications=["Microsoft Edge", "Microsoft Word"])
    assert d.decision == DECISION_HUMAN
    assert d.reason_code == REASON_DETOUR_APPLICATION


def test_a_rare_edge_multi_system_execution_is_refused():
    d = route_execution(
        routes_visited=[VALID_ROUTE], applications=["Microsoft Edge"],
        variant_signature=[HR_SYSTEM, "system:財務会計システム", HR_SYSTEM])
    assert d.decision == DECISION_HUMAN
    assert d.reason_code == REASON_MULTI_SYSTEM_VARIANT


def test_an_execution_with_no_observed_route_is_refused():
    """14 of the 94 dominant executions look like this. Nothing to verify -> refuse."""
    d = route_execution(routes_visited=[], applications=["Microsoft Edge"])
    assert d.decision == DECISION_HUMAN
    assert d.reason_code == REASON_NO_ROUTE_EVIDENCE


@pytest.mark.parametrize("route", ["#/resident-tax", "#/dashboard", "#/not-a-route"])
def test_a_route_outside_the_evidenced_set_is_refused(route):
    """Refused even though #/resident-tax and #/dashboard occur on the dominant path:
    the automation has no evidenced handling for them."""
    d = route_execution(routes_visited=[route], applications=["Microsoft Edge"])
    assert d.decision == DECISION_HUMAN
    assert d.reason_code == REASON_UNKNOWN_ROUTE


def test_multiple_distinct_evidenced_routes_are_refused_as_ambiguous():
    d = route_execution(routes_visited=[VALID_ROUTE, "#/onboarding"],
                        applications=["Microsoft Edge"])
    assert d.decision == DECISION_HUMAN
    assert d.reason_code == REASON_AMBIGUOUS_ROUTE_SET


def test_an_unexpected_application_is_refused():
    d = route_execution(routes_visited=[VALID_ROUTE],
                        applications=["Microsoft Edge", "Microsoft Excel"])
    assert d.decision == DECISION_HUMAN


def test_an_empty_execution_is_refused_rather_than_defaulting_to_allow():
    assert route_execution().decision == DECISION_HUMAN


def test_the_detour_marker_wins_even_when_everything_else_looks_dominant():
    """Decisiveness matters: Word never appeared on the dominant path, so no
    combination of otherwise-clean signals may override it."""
    d = route_execution(routes_visited=[VALID_ROUTE],
                        applications=["Microsoft Edge", "Microsoft Word"],
                        variant_signature=[HR_SYSTEM])
    assert d.reason_code == REASON_DETOUR_APPLICATION


def test_routing_is_deterministic():
    calls = [route_execution(routes_visited=[VALID_ROUTE],
                             applications=["Microsoft Edge"]).to_dict()
             for _ in range(5)]
    assert all(c == calls[0] for c in calls)


def test_every_refusal_explains_itself():
    for kwargs in ({"routes_visited": []},
                   {"routes_visited": ["#/dashboard"]},
                   {"routes_visited": [VALID_ROUTE],
                    "applications": ["Microsoft Word"]}):
        d = route_execution(**kwargs)
        assert d.rationale and len(d.rationale) > 10
        assert d.reason_code


# --- coverage reporting ----------------------------------------------------

def test_coverage_counts_eligibility_not_correctness():
    decisions = [route_execution(routes_visited=[VALID_ROUTE],
                                 applications=["Microsoft Edge"]) for _ in range(3)]
    decisions += [route_execution(routes_visited=[], applications=["Microsoft Edge"])]
    cov = coverage(decisions)
    assert cov["total_executions"] == 4
    assert cov["routing_eligible"] == 3
    assert cov["observed_dominant_path_coverage"] == 0.75
    assert cov["refused"] == 1


def test_coverage_never_calls_itself_accuracy():
    cov = coverage([route_execution(routes_visited=[VALID_ROUTE],
                                    applications=["Microsoft Edge"])])
    blob = json.dumps(cov).lower()
    assert "accuracy" in blob, "the naming note must address the term explicitly"
    assert "not automation accuracy" in cov["metric_naming_note"].lower()
    assert "observed_dominant_path_coverage" in cov


def test_coverage_of_nothing_is_reported_as_none_not_zero():
    assert coverage([])["observed_dominant_path_coverage"] is None


# --- routing sits before the automation, structurally ---------------------

def test_the_routing_module_does_not_import_the_automation():
    """It is a gate in front of the automation, not a part of it."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src" / "procmine" / "module2"
    text = (src / "routing.py").read_text(encoding="utf-8")
    assert "hr_payroll_automation" not in text
    assert "prepare_note_submission" not in text


# --- post-action audit: the expected end state ----------------------------

def _confirmed_app():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, VALID_ROUTE, NOTE)
    confirm_submission(app, checkpoint)
    return app, checkpoint


def test_the_expected_end_state_passes_the_audit():
    app, checkpoint = _confirmed_app()
    evidence = audit_post_action(app, checkpoint, execution_id="exec_1")
    assert evidence.passed is True
    assert evidence.conclusive is True
    assert {c.name for c in evidence.checks} >= {
        "expected_route_is_current", "confirm_target_still_resolves_uniquely",
        "note_field_still_present", "submitted_note_reads_back"}


def test_the_submitted_note_reads_back_from_the_target():
    app, checkpoint = _confirmed_app()
    evidence = audit_post_action(app, checkpoint)
    check = next(c for c in evidence.checks if c.name == "submitted_note_reads_back")
    assert check.status == CHECK_PASS


def test_route_drift_after_the_action_is_detected():
    app, checkpoint = _confirmed_app()
    app.navigate("#/onboarding")  # the page moved out from under us
    evidence = audit_post_action(app, checkpoint)
    assert evidence.passed is False
    check = next(c for c in evidence.checks if c.name == "expected_route_is_current")
    assert check.status == CHECK_FAIL


def test_a_changed_note_value_is_detected():
    app, checkpoint = _confirmed_app()
    app.set_note_value(checkpoint.note_field_id, "something else entirely")
    evidence = audit_post_action(app, checkpoint)
    assert evidence.passed is False


def test_a_disappearing_confirm_target_is_detected():
    app, checkpoint = _confirmed_app()
    app._routes[VALID_ROUTE].confirm_elements = []
    evidence = audit_post_action(app, checkpoint)
    assert evidence.passed is False
    check = next(c for c in evidence.checks
                 if c.name == "confirm_target_still_resolves_uniquely")
    assert check.status == CHECK_FAIL


def test_a_duplicated_confirm_target_is_detected():
    app, checkpoint = _confirmed_app()
    dup = list(app._routes[VALID_ROUTE].confirm_elements)
    app._routes[VALID_ROUTE].confirm_elements = dup * 2
    assert audit_post_action(app, checkpoint).passed is False


# --- the audit must not overclaim -----------------------------------------

def test_an_unavailable_check_never_counts_as_a_pass():
    evidence = PostActionEvidence(execution_id=None, route=VALID_ROUTE, checks=[
        EvidenceCheck("a", CHECK_PASS, ""), EvidenceCheck("b", CHECK_UNAVAILABLE, "")])
    assert evidence.passed is False
    assert evidence.conclusive is False


def test_an_audit_with_no_checks_does_not_pass_vacuously():
    assert PostActionEvidence(execution_id=None, route=VALID_ROUTE).passed is False


def test_the_evidence_record_states_it_is_not_proof_of_business_success():
    app, checkpoint = _confirmed_app()
    note = audit_post_action(app, checkpoint).to_dict()["interpretation_note"].lower()
    assert "not proof" in note


def test_the_note_content_never_appears_in_the_evidence_record():
    """Consistent with the project rule that note text is never logged."""
    app, checkpoint = _confirmed_app()
    blob = json.dumps(audit_post_action(app, checkpoint).to_dict(), ensure_ascii=False)
    assert NOTE not in blob
    assert str(len(NOTE)) in blob, "length is auditable, content is not"


def test_the_audit_does_not_mutate_the_target():
    app, checkpoint = _confirmed_app()
    before = (app.current_route,
              [e.value for e in app.find_note_field()],
              [e.clicked for e in app.find_confirm_button()])
    audit_post_action(app, checkpoint)
    after = (app.current_route,
             [e.value for e in app.find_note_field()],
             [e.clicked for e in app.find_confirm_button()])
    assert before == after


def test_an_adapter_that_raises_yields_unavailable_not_a_crash():
    class Broken:
        current_route = VALID_ROUTE

        def find_confirm_button(self):
            raise RuntimeError("driver gone")

        def find_note_field(self):
            raise RuntimeError("driver gone")

    _, checkpoint = _confirmed_app()
    evidence = audit_post_action(Broken(), checkpoint)
    assert evidence.conclusive is False
    assert evidence.passed is False


# --- screenshot evidence ---------------------------------------------------

def test_a_screenshot_is_recorded_as_a_hash(tmp_path):
    shot = tmp_path / "after.png"
    shot.write_bytes(b"fake-image-bytes")
    app, checkpoint = _confirmed_app()
    evidence = audit_post_action(app, checkpoint, screenshot_path=shot)
    assert evidence.screenshot_sha256 == sha256_of(shot)
    assert len(evidence.screenshot_sha256) == 64
    check = next(c for c in evidence.checks
                 if c.name == "post_action_screenshot_captured")
    assert check.status == CHECK_PASS


def test_a_missing_screenshot_is_unavailable_not_a_failure_to_hide(tmp_path):
    app, checkpoint = _confirmed_app()
    evidence = audit_post_action(app, checkpoint,
                                 screenshot_path=tmp_path / "never_written.png")
    assert evidence.screenshot_sha256 is None
    check = next(c for c in evidence.checks
                 if c.name == "post_action_screenshot_captured")
    assert check.status == CHECK_UNAVAILABLE
    assert evidence.passed is False


def test_sha256_of_a_missing_file_is_none():
    assert sha256_of("/nonexistent/path/to/nothing.png") is None


def test_pixel_difference_ratio_is_defined_and_bounded():
    assert pixel_difference_ratio(b"aaaa", b"aaaa") == 0.0
    assert pixel_difference_ratio(b"aaaa", b"bbbb") == 1.0
    assert pixel_difference_ratio(b"aaaa", b"aabb") == 0.5


def test_pixel_difference_ratio_refuses_incomparable_buffers():
    """Comparing different-length buffers would be meaningless, not merely imprecise."""
    assert pixel_difference_ratio(b"aaaa", b"aaaaaa") is None
    assert pixel_difference_ratio(b"", b"") is None


def test_the_audit_is_never_used_as_a_pass_fail_pixel_threshold():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "src" / "procmine" / "module2"
           / "post_action_audit.py").read_text(encoding="utf-8")
    # The ratio is computed and reported, but must not gate the verdict.
    assert "pixel_difference_ratio" in src
    assert "never used as a pass/fail" in src or "never asserted on" in src

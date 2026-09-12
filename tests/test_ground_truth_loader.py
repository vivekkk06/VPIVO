from procmine.loaders.ground_truth import cross_check_against_manifest, parse_gt_executions
from procmine.validation import ValidationReport


def test_deduplicates_consecutive_duplicate_process_started(synthetic_gt):
    report = ValidationReport(scope="test")
    executions = parse_gt_executions(synthetic_gt, report)

    process_a_executions = [e for e in executions if e.process_code == "A"]
    assert len(process_a_executions) == 1
    assert len(report.gt_duplicate_starts) == 1


def test_flags_unpaired_switch_out(synthetic_gt):
    report = ValidationReport(scope="test")
    parse_gt_executions(synthetic_gt, report)

    assert len(report.gt_unpaired_switches) == 1
    assert report.gt_unpaired_switches[0]["from"] == "Z"


def test_captures_task_ids_and_end_ts(synthetic_gt):
    report = ValidationReport(scope="test")
    executions = parse_gt_executions(synthetic_gt, report)

    ex_a = next(e for e in executions if e.process_code == "A")
    assert ex_a.task_ids == ["T-1"]
    assert ex_a.end_ts is not None  # closed by the valid process_switched_out


def test_cross_check_flags_count_mismatch():
    from procmine.models import GTExecution
    from datetime import datetime, timezone

    reconstructed = [
        GTExecution("A", "Test", "C-1", datetime.now(timezone.utc), None, "std"),
    ]
    manifest = {"processes": [{"code": "A", "family_name": "Test", "executions": [{}, {}]}]}

    report = ValidationReport(scope="test")
    cross_check_against_manifest(reconstructed, manifest, report)

    assert len(report.gt_manifest_mismatches) == 1
    assert report.gt_manifest_mismatches[0] == {
        "process_code": "A",
        "manifest_execution_count": 2,
        "reconstructed_execution_count": 1,
    }

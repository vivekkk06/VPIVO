"""Parser for gt.jsonl / gt_manifest.json (Dataset A only).

gt.jsonl is an event stream of its own (process_started / process_switched_out
/ process_suspended / process_resumed / task_started / clipboard_* /
session_ended), not a ready list of executions. DATA_SCHEMA.md calls out two
defects we have to tolerate rather than assume away:

  - the same process_started can appear twice in a row
  - process_switched_out does not always pair with a process_started

We reconstruct executions with a small state machine, then cross-check the
result against gt_manifest.json's own executions[] list (which is a
ready-made summary) and record any disagreement in the ValidationReport
instead of silently preferring one source over the other.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from procmine.models import GTExecution
from procmine.validation import ValidationReport


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def load_gt_records(gt_path: Path, report: ValidationReport) -> list[dict[str, Any]]:
    records = []
    with gt_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                report.malformed_json_lines.append(
                    {"file": str(gt_path), "line_no": line_no, "error": str(e)}
                )
    return records


def load_gt_manifest(gt_manifest_path: Path, report: ValidationReport | None = None) -> dict[str, Any] | None:
    if report is None:
        report = ValidationReport(scope=f"gt_manifest:{gt_manifest_path}")
    try:
        with gt_manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        report.malformed_manifest_files.append({"file": str(gt_manifest_path), "error": str(e)})
        return None


def parse_gt_executions(
    gt_path: Path, report: ValidationReport
) -> list[GTExecution]:
    records = load_gt_records(gt_path, report)

    executions: list[GTExecution] = []
    open_by_process: dict[str, GTExecution] = {}
    last_started_key: tuple[str, str | None] | None = None
    suspended_split_ids: set[str] = set()
    resumed_split_ids: set[str] = set()

    for rec in records:
        event = rec.get("event")
        ts = _parse_ts(rec["ts_utc"])

        if event == "process_started":
            code = rec["process_code"]
            case_id = rec.get("case_id")
            key = (code, case_id)
            if key == last_started_key:
                report.gt_duplicate_starts.append(
                    {"process_code": code, "case_id": case_id, "ts_utc": rec["ts_utc"]}
                )
                continue
            last_started_key = key
            ex = GTExecution(
                process_code=code,
                process_name=rec.get("process_name"),
                case_id=case_id,
                start_ts=ts,
                end_ts=None,
                variant=rec.get("process_variant"),
            )
            open_by_process[code] = ex
            executions.append(ex)

        elif event == "process_switched_out":
            from_code = rec.get("from")
            ex = open_by_process.get(from_code)
            if ex is None or ex.end_ts is not None:
                report.gt_unpaired_switches.append(
                    {"from": from_code, "to": rec.get("to"), "ts_utc": rec["ts_utc"]}
                )
            else:
                ex.end_ts = ts

        elif event == "process_suspended":
            from_code = rec.get("from")
            split_id = rec.get("split_id")
            ex = open_by_process.get(from_code)
            if ex is not None:
                ex.suspended = True
                ex.split_id = split_id
                ex.end_ts = ts
            if split_id:
                suspended_split_ids.add(split_id)

        elif event == "process_resumed":
            code = rec.get("process_code")
            split_id = rec.get("split_id")
            if split_id and split_id not in suspended_split_ids:
                report.gt_resume_without_suspend.append(
                    {"process_code": code, "split_id": split_id, "ts_utc": rec["ts_utc"]}
                )
            if split_id:
                resumed_split_ids.add(split_id)
            ex = GTExecution(
                process_code=code,
                process_name=rec.get("process_name"),
                case_id=rec.get("case_id"),
                start_ts=ts,
                end_ts=None,
                variant=rec.get("process_variant"),
                split_id=split_id,
            )
            open_by_process[code] = ex
            executions.append(ex)
            last_started_key = None

        elif event == "task_started":
            code = rec.get("current_process")
            ex = open_by_process.get(code)
            if ex is not None and rec.get("task_id"):
                ex.task_ids.append(rec["task_id"])

        elif event == "session_ended":
            for ex in open_by_process.values():
                if ex.end_ts is None:
                    ex.end_ts = ts

    for split_id in suspended_split_ids - resumed_split_ids:
        report.gt_suspend_without_resume.append({"split_id": split_id})

    # Overlap check: on a single-operator desktop, one process's interval
    # should never start before the previous one closed. A suspended
    # execution's end_ts is the suspend time, so it doesn't overlap with
    # what comes after by construction — only real double-booking should
    # trip this.
    closed = sorted(
        (e for e in executions if e.end_ts is not None), key=lambda e: e.start_ts
    )
    for prev, nxt in zip(closed, closed[1:]):
        if nxt.start_ts < prev.end_ts:
            report.gt_overlapping_intervals.append(
                {
                    "first": {"process_code": prev.process_code, "case_id": prev.case_id, "end_ts": prev.end_ts.isoformat()},
                    "second": {"process_code": nxt.process_code, "case_id": nxt.case_id, "start_ts": nxt.start_ts.isoformat()},
                }
            )

    return executions


def parse_gt_manifest_executions(gt_manifest: dict[str, Any]) -> list[GTExecution]:
    """gt_manifest.json's executions[] is the ready-made, authoritative summary
    (it carries `apps`, which the raw gt.jsonl stream does not expose directly).
    We treat this as the canonical execution list for downstream use, and the
    gt.jsonl reconstruction above as the thing we cross-check it against."""
    executions: list[GTExecution] = []
    for proc in gt_manifest.get("processes", []):
        for ex in proc.get("executions", []):
            executions.append(
                GTExecution(
                    process_code=ex.get("code", proc["code"]),
                    process_name=proc.get("family_name"),
                    case_id=ex.get("case_id"),
                    start_ts=_parse_ts(ex["start_ts"]),
                    end_ts=_parse_ts(ex["end_ts"]) if ex.get("end_ts") else None,
                    variant=ex.get("variant"),
                    suspended=bool(ex.get("split_id")),
                    split_id=ex.get("split_id"),
                    apps_touched=list(ex.get("apps", [])),
                )
            )
    return executions


def cross_check_against_manifest(
    executions: list[GTExecution],
    gt_manifest: dict[str, Any],
    report: ValidationReport,
) -> None:
    """Compare execution counts per process_code between our reconstruction
    and gt_manifest.json's own executions[] list."""
    manifest_counts: dict[str, int] = {}
    for proc in gt_manifest.get("processes", []):
        manifest_counts[proc["code"]] = len(proc.get("executions", []))

    reconstructed_counts: dict[str, int] = {}
    for ex in executions:
        reconstructed_counts[ex.process_code] = reconstructed_counts.get(ex.process_code, 0) + 1

    all_codes = set(manifest_counts) | set(reconstructed_counts)
    for code in sorted(all_codes):
        m = manifest_counts.get(code, 0)
        r = reconstructed_counts.get(code, 0)
        if m != r:
            report.gt_manifest_mismatches.append(
                {"process_code": code, "manifest_execution_count": m, "reconstructed_execution_count": r}
            )

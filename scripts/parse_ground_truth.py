#!/usr/bin/env python3
"""Parse Dataset A's ground truth into a flat CSV of executions, plus a
validation report covering the quirks documented in DATA_SCHEMA.md
(duplicate process_started, unpaired process_switched_out, and any mismatch
against gt_manifest.json's own executions[] summary).

Usage:
    python scripts/parse_ground_truth.py --dataset dataset_a --out reports/day1
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.ground_truth import (
    cross_check_against_manifest,
    load_gt_manifest,
    parse_gt_executions,
    parse_gt_manifest_executions,
)
from procmine.paths import discover_dataset
from procmine.validation import ValidationReport

FIELDS = [
    "session_id",
    "process_code",
    "process_name",
    "case_id",
    "variant",
    "start_ts",
    "end_ts",
    "suspended",
    "split_id",
    "apps_touched",
    "n_tasks",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    sessions = discover_dataset(args.dataset)

    rows = []
    all_reports: list[dict] = []
    n_with_gt = 0

    for session in sessions:
        if session.gt_path is None:
            continue
        n_with_gt += 1
        report = ValidationReport(scope=f"session:{session.session_id}")

        reconstructed = parse_gt_executions(session.gt_path, report)

        manifest = load_gt_manifest(session.gt_manifest_path, report) if session.gt_manifest_path else None
        if manifest is not None:
            cross_check_against_manifest(reconstructed, manifest, report)
            canonical = parse_gt_manifest_executions(manifest)
        else:
            canonical = reconstructed

        for ex in canonical:
            rows.append(
                {
                    "session_id": session.session_id,
                    "process_code": ex.process_code,
                    "process_name": ex.process_name,
                    "case_id": ex.case_id,
                    "variant": ex.variant,
                    "start_ts": ex.start_ts.isoformat(),
                    "end_ts": ex.end_ts.isoformat() if ex.end_ts else "",
                    "suspended": ex.suspended,
                    "split_id": ex.split_id or "",
                    "apps_touched": "|".join(ex.apps_touched),
                    "n_tasks": len(ex.task_ids),
                }
            )

        if not report.is_clean() or report.gt_duplicate_starts or report.gt_unpaired_switches:
            all_reports.append(report.to_dict())

    csv_path = args.out / "gt_executions.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {csv_path} ({len(rows)} executions from {n_with_gt} sessions)", file=sys.stderr)

    report_path = args.out / "gt_validation_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2, ensure_ascii=False)
    print(f"Wrote {report_path} ({len(all_reports)} sessions with flagged issues)", file=sys.stderr)


if __name__ == "__main__":
    main()

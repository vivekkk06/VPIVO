#!/usr/bin/env python3
"""Run the full validation suite (malformed JSON, missing timestamps,
duplicate events, chunk ordering) across every session in a dataset and write
one detailed report.

Usage:
    python scripts/validate_dataset.py --dataset dataset_a --out reports/day1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.paths import discover_dataset
from procmine.validation import ValidationReport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    sessions = discover_dataset(args.dataset)

    reports = []
    dirty_sessions = 0
    for session in sessions:
        report = ValidationReport(scope=f"session:{session.session_id}")
        load_session_events(session, report)
        if not report.is_clean():
            dirty_sessions += 1
        reports.append(report.to_dict())

    out_path = args.out / f"validation_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)

    print(f"Wrote {out_path}", file=sys.stderr)
    print(f"{dirty_sessions}/{len(sessions)} sessions had at least one validation issue", file=sys.stderr)


if __name__ == "__main__":
    main()

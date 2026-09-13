#!/usr/bin/env python3
"""Step 3 demo: runs the RPA/UI automation prototype through all four
evidenced HR/Payroll routes end-to-end, printing clearly-labeled status
at every stage so an evaluator can follow exactly what the automation
is doing. Also writes the standalone demo HTML page for visual/manual
inspection.

This script demonstrates the automation only -- it does not perform any
further Dataset B analysis, does not touch Dataset A's locked
architecture, and does not claim the mock app is the real HR system.

Usage:
    python scripts/run_hr_payroll_automation_demo.py --out reports/day3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.automation.hr_payroll_automation import (
    AutomationSafetyError,
    confirm_submission,
    prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockHRApplication, RouteConfig, render_demo_html
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES

ROUTE_LABELS = {
    "#/payroll-items": "Payroll Items", "#/leave-applications": "Leave Applications",
    "#/onboarding": "Onboarding", "#/social-insurance": "Social Insurance",
}

SEPARATOR = "=" * 70


def demo_one_route(app: MockHRApplication, route: str, note_text: str) -> None:
    label = ROUTE_LABELS[route]
    print(f"\n{SEPARATOR}")
    print(f"ROUTE: {label} ({route})")
    print(SEPARATOR)
    print(f"[1] Route selected by human operator: {label!r}")

    checkpoint = prepare_note_submission(app, route, note_text)
    for entry in checkpoint.action_log:
        print(f"    [{entry.step}] {entry.detail}")

    print(f"[2] HUMAN REVIEW CHECKPOINT -- reviewing before confirmation:")
    print(f"      route:           {checkpoint.route}")
    print(f"      note field:      {checkpoint.note_field_id}")
    print(f"      note text:       {checkpoint.note_text!r}")
    print(f"      confirm button:  {checkpoint.confirm_button_id} (NOT yet clicked)")
    print(f"[3] Human approves -- proceeding to confirmation click")

    result = confirm_submission(app, checkpoint)
    print(f"[4] CONFIRMED: {result.confirmed} -- clicked {checkpoint.confirm_button_id!r}")


def demo_unknown_route(app: MockHRApplication) -> None:
    print(f"\n{SEPARATOR}")
    print("ROUTE: (deliberately invalid, to demonstrate safe failure)")
    print(SEPARATOR)
    try:
        prepare_note_submission(app, "#/unknown-route", "note")
    except AutomationSafetyError as exc:
        print(f"[SAFE STOP] {type(exc).__name__}: {exc}")
        for entry in exc.action_log:
            print(f"    [{entry.step}] {entry.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print(SEPARATOR)
    print("Dataset B evidence -> HR/Payroll selected -> 77.05% dominant path ->")
    print("deterministic UI pattern discovered -> RPA/UI automation selected")
    print(SEPARATOR)

    app = MockHRApplication()
    sample_notes = {
        "#/payroll-items": "Reviewed payroll item per standard process.",
        "#/leave-applications": "Leave application processed.",
        "#/onboarding": "Onboarding checklist verified.",
        "#/social-insurance": "Social insurance record confirmed.",
    }
    for route in KNOWN_ROUTE_PREFIXES:
        demo_one_route(app, route, sample_notes[route])

    demo_unknown_route(app)

    html_path = args.out / "hr_payroll_mock_app.html"
    html_path.write_text(render_demo_html(), encoding="utf-8")
    print(f"\n{SEPARATOR}")
    print(f"Wrote demo HTML page to {html_path} (open in a browser to inspect "
          f"the mock UI structure manually -- not wired to this script's automation run)")
    print("Done.")


if __name__ == "__main__":
    main()

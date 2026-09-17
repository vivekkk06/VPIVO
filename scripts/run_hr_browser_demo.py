#!/usr/bin/env python3
"""Run the HR automation through a REAL browser against the local prototype.

The point of this demo is narrow and worth stating plainly: the automation logic in
`hr_payroll_automation.py` is **not modified**. The same `prepare_note_submission`
and `confirm_submission` functions that drive the in-memory mock drive a live
Chromium DOM here, because `BrowserHRApplication` implements the same interface.

It also demonstrates a safe stop: an unevidenced route is refused before the browser
is touched at all.

**This targets the local `hr_payroll_mock_app.html` prototype. It is not connected to
any real HR system.**

Usage:
    python scripts/run_hr_browser_demo.py --out reports/day7
    python scripts/run_hr_browser_demo.py --headed          # watch it run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.automation.browser_adapter import BrowserHRApplication  # noqa: E402
from procmine.automation.hr_payroll_automation import (  # noqa: E402
    AutomationSafetyError, confirm_submission, prepare_note_submission,
)

RULE = "=" * 70


def _print_log(entries) -> None:
    for e in entries:
        print(f"    [{e.step}] {e.detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--route", default="#/payroll-items")
    args = ap.parse_args()

    note = "Payroll item verified against source record."
    record: dict = {
        "demo": "HR automation through a real browser DOM",
        "target": "local hr_payroll_mock_app.html prototype",
        "not_connected_to_real_hr_system": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    print(RULE)
    print("REAL BROWSER AUTOMATION -- local HR prototype (not a real HR system)")
    print(RULE)

    t0 = time.perf_counter()
    with BrowserHRApplication(headless=not args.headed) as app:
        started = time.perf_counter() - t0
        print(f"[0] browser started in {started:.2f}s -> {app.base_url}")

        # ---- valid route, through the unmodified safety logic ----------
        print(f"\n[1] prepare on {args.route!r} (automation logic unchanged)")
        t1 = time.perf_counter()
        checkpoint = prepare_note_submission(app, args.route, note)
        prepare_s = time.perf_counter() - t1
        _print_log(checkpoint.action_log)

        print("\n[2] HUMAN REVIEW CHECKPOINT -- nothing submitted yet")
        print(f"      route:          {checkpoint.route}")
        print(f"      note field:     {checkpoint.note_field_id}")
        print(f"      confirm button: {checkpoint.confirm_button_id} (NOT yet clicked)")
        print(f"      confirmed:      {checkpoint.confirmed}")

        # Prove the note really reached the live DOM, not just an internal object.
        dom_value = app._page.locator(f"#{checkpoint.note_field_id}").input_value()  # noqa: SLF001
        print(f"\n[3] value read back from the live DOM: {dom_value!r}")
        assert dom_value == note, "note did not reach the real DOM"

        print("\n[4] human approves -> confirming (target re-verified first)")
        t2 = time.perf_counter()
        result = confirm_submission(app, checkpoint)
        confirm_s = time.perf_counter() - t2
        print(f"    CONFIRMED: {result.confirmed} -- clicked {checkpoint.confirm_button_id!r}")
        # Honest scope: the prototype page is a pure hash-router with no click
        # handler, so there is no post-click state to read back. What IS verified is
        # that the click was dispatched to a real, visible, actionable element --
        # Playwright raises if the element is missing, hidden or obscured.
        print("    (the click was dispatched to a live DOM element; the prototype page")
        print("     has no click handler, so there is no post-click state to assert)")

        record["steps"].append({
            "step": "valid_route",
            "route": args.route,
            "confirmed": bool(result.confirmed),
            "note_reached_dom": dom_value == note,
            "browser_start_seconds": round(started, 3),
            "prepare_seconds": round(prepare_s, 3),
            "confirm_seconds": round(confirm_s, 3),
            "action_log": [{"step": e.step, "detail": e.detail, "timestamp": e.timestamp} for e in result.action_log],
        })

        # ---- idempotency: the same checkpoint must not confirm twice ----
        print("\n[5] replay the SAME checkpoint (must be refused)")
        try:
            confirm_submission(app, checkpoint)
            print("    *** NOT REFUSED -- this is a bug ***")
            record["steps"].append({"step": "replay", "refused": False})
        except RuntimeError as exc:
            print(f"    REFUSED: {exc}")
            record["steps"].append({"step": "replay", "refused": True, "reason": str(exc)})

        # ---- safe stop on an unevidenced route -------------------------
        print("\n[6] unevidenced route (must safe-stop before touching the browser)")
        try:
            prepare_note_submission(app, "#/unknown-route", note)
            print("    *** NOT REFUSED -- this is a bug ***")
            record["steps"].append({"step": "invalid_route", "refused": False})
        except AutomationSafetyError as exc:
            print(f"    SAFE STOP: {type(exc).__name__}: {exc}")
            _print_log(exc.action_log)
            record["steps"].append({
                "step": "invalid_route", "refused": True,
                "error_type": type(exc).__name__,
            })

        # ---- safe stop on an empty note --------------------------------
        print("\n[7] empty note (must safe-stop before any UI contact)")
        try:
            prepare_note_submission(app, args.route, "   ")
            print("    *** NOT REFUSED -- this is a bug ***")
            record["steps"].append({"step": "empty_note", "refused": False})
        except AutomationSafetyError as exc:
            print(f"    SAFE STOP: {type(exc).__name__}: {exc}")
            record["steps"].append({
                "step": "empty_note", "refused": True,
                "error_type": type(exc).__name__,
            })

    print("\n" + RULE)
    print("Automation logic was NOT modified for the browser. Same functions, real DOM.")
    print("Target is the local prototype -- NOT a real HR system.")
    print(RULE)

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / "browser_automation_demo.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

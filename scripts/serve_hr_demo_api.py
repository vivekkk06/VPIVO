#!/usr/bin/env python3
"""Day 5: a minimal local API exposing the existing HR/Payroll automation
prototype to the dashboard.

This is a THIN TRANSPORT WRAPPER. It adds no automation logic of its own:
route validation, note validation, element verification and confirm-time
button re-verification all happen inside
`procmine.automation.hr_payroll_automation`, unchanged. The wrapper's only
jobs are to hold state server-side and to translate the prototype's
exceptions into HTTP status codes.

Why the state stays here and not in the browser: `confirm_submission`
re-locates the confirm button at confirm time rather than clicking a
cached reference, precisely because the page may change during the human
review pause. That guarantee only holds if the same `MockHRApplication`
and `ReviewCheckpoint` objects survive between the two calls. A stateless
design that rebuilt them per request would silently defeat it, so each
prepared checkpoint is kept in-process and addressed by an opaque token.

Standard library only -- no new dependency was added for this.

Endpoints:
    GET  /api/routes    -> the four evidenced routes (from the prototype)
    POST /api/prepare   -> {route, note_text}        -> checkpoint + token
    POST /api/confirm   -> {checkpoint_token}        -> AutomationResult

Status codes:
    200 success
    400 malformed request / missing field / unknown token
    422 the prototype refused on its own safety rules (a SAFE STOP,
        carrying error_type and the partial action log)

Usage:
    python scripts/serve_hr_demo_api.py            # 127.0.0.1:8000
    python scripts/serve_hr_demo_api.py --port 8123
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.automation.hr_payroll_automation import (  # noqa: E402
    AutomationSafetyError,
    confirm_submission,
    prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockHRApplication  # noqa: E402
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES  # noqa: E402

MAX_BODY_BYTES = 64 * 1024

# token -> (MockHRApplication, ReviewCheckpoint). Process-local and
# deliberately not persisted: this is a demo, and a checkpoint must not
# outlive the process that verified it.
_CHECKPOINTS: dict[str, tuple] = {}
_LOCK = threading.Lock()


def _log_to_list(action_log) -> list[dict]:
    return [asdict(entry) for entry in action_log]


class HRDemoHandler(BaseHTTPRequestHandler):
    server_version = "IBYHRDemo/0.1"

    # --- plumbing --------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        sys.stderr.write(f"  api {fmt % args}\n")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    # --- routes ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/api/routes":
            self._send(200, {"routes": list(KNOWN_ROUTE_PREFIXES)})
            return
        self._send(404, {"message": f"no such endpoint: {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path == "/api/prepare":
            self._prepare()
        elif path == "/api/confirm":
            self._confirm()
        else:
            self._send(404, {"message": f"no such endpoint: {self.path}"})

    def _prepare(self) -> None:
        body = self._read_json()
        if body is None:
            self._send(400, {"message": "request body must be JSON"})
            return
        route = body.get("route")
        note_text = body.get("note_text")
        if not isinstance(route, str) or not isinstance(note_text, str):
            self._send(400, {"message": "both 'route' and 'note_text' are required strings"})
            return

        # A fresh application per checkpoint: isolates concurrent demos and
        # keeps confirm-time verification meaningful.
        app = MockHRApplication()
        try:
            checkpoint = prepare_note_submission(app, route, note_text)
        except AutomationSafetyError as exc:
            self._send(422, {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "action_log": _log_to_list(exc.action_log),
            })
            return

        token = secrets.token_urlsafe(16)
        with _LOCK:
            _CHECKPOINTS[token] = (app, checkpoint)

        self._send(200, {
            "checkpoint_token": token,
            "route": checkpoint.route,
            "note_field_id": checkpoint.note_field_id,
            "note_text": checkpoint.note_text,
            "confirm_button_id": checkpoint.confirm_button_id,
            "confirmed": checkpoint.confirmed,
            "action_log": _log_to_list(checkpoint.action_log),
        })

    def _confirm(self) -> None:
        body = self._read_json()
        if body is None:
            self._send(400, {"message": "request body must be JSON"})
            return
        token = body.get("checkpoint_token")
        if not isinstance(token, str) or not token:
            self._send(400, {"message": "'checkpoint_token' is required"})
            return

        with _LOCK:
            entry = _CHECKPOINTS.get(token)
        if entry is None:
            # Confirmation is impossible without a checkpoint that this
            # process actually prepared and verified.
            self._send(400, {"message": "unknown or expired checkpoint token -- run prepare first"})
            return

        app, checkpoint = entry
        try:
            result = confirm_submission(app, checkpoint)
        except AutomationSafetyError as exc:
            self._send(422, {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "action_log": _log_to_list(exc.action_log),
            })
            return
        except RuntimeError as exc:
            # Non-re-entrancy and route-drift guards from the prototype.
            self._send(400, {"message": str(exc)})
            return
        finally:
            with _LOCK:
                _CHECKPOINTS.pop(token, None)

        self._send(200, {
            "route": result.route,
            "confirmed": result.confirmed,
            "action_log": _log_to_list(result.action_log),
        })


def build_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), HRDemoHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    httpd = build_server(args.host, args.port)
    print(f"HR automation demo API on http://{args.host}:{args.port}", file=sys.stderr)
    print("  GET  /api/routes", file=sys.stderr)
    print("  POST /api/prepare   {route, note_text}", file=sys.stderr)
    print("  POST /api/confirm   {checkpoint_token}", file=sys.stderr)
    print("Automation logic is owned by procmine.automation -- this is transport only.",
          file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

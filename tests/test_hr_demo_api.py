"""Tests for the Day-5 local HR automation API (`scripts/serve_hr_demo_api.py`).

The API is a transport wrapper: it must expose the existing prototype's
behaviour without softening it. These tests therefore focus on the
safety-relevant properties -- that a confirmation is impossible without a
server-prepared checkpoint, that the prototype's refusals surface as
refusals rather than generic errors, and that a checkpoint cannot be
replayed -- rather than on HTTP plumbing for its own sake.

A real server is started on an ephemeral port so the handler is exercised
end to end, including status codes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "serve_hr_demo_api.py"
_spec = importlib.util.spec_from_file_location("serve_hr_demo_api", _SCRIPT)
_module = importlib.util.module_from_spec(_spec)
sys.modules["serve_hr_demo_api"] = _module
_spec.loader.exec_module(_module)

VALID_ROUTE = "#/payroll-items"


@pytest.fixture(scope="module")
def api():
    server = _module.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(method: str, path: str, body: dict | None = None, raw: bytes | None = None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                return exc.code, json.loads(payload)
            except json.JSONDecodeError:
                return exc.code, {}

    yield call
    server.shutdown()
    server.server_close()


def _prepare(api, route=VALID_ROUTE, note="Reviewed per standard process."):
    return api("POST", "/api/prepare", {"route": route, "note_text": note})


# --- routes ---------------------------------------------------------------

def test_routes_come_from_the_prototype_not_the_api(api):
    from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES

    status, payload = api("GET", "/api/routes")
    assert status == 200
    assert payload["routes"] == list(KNOWN_ROUTE_PREFIXES)
    assert len(payload["routes"]) == 4


# --- the happy path -------------------------------------------------------

def test_prepare_returns_an_unconfirmed_checkpoint(api):
    status, cp = _prepare(api)
    assert status == 200
    assert cp["route"] == VALID_ROUTE
    assert cp["confirmed"] is False, "prepare must never confirm"
    assert cp["note_field_id"] and cp["confirm_button_id"]
    assert cp["checkpoint_token"]


def test_prepare_reports_the_prototypes_action_log(api):
    _, cp = _prepare(api)
    steps = [entry["step"] for entry in cp["action_log"]]
    assert "route_check" in steps
    assert "find_confirm_button" in steps
    assert steps[-1] == "checkpoint", "the log must end at the review boundary"


def test_confirm_completes_only_after_prepare(api):
    _, cp = _prepare(api)
    status, result = api("POST", "/api/confirm", {"checkpoint_token": cp["checkpoint_token"]})
    assert status == 200
    assert result["confirmed"] is True
    assert result["route"] == VALID_ROUTE


# --- safe stops (the prototype refusing) ----------------------------------

def test_unknown_route_is_a_safe_stop_not_a_server_error(api):
    status, payload = _prepare(api, route="#/not-an-evidenced-route")
    assert status == 422
    # error_type is a stable taxonomy string (Day-7); the originating exception
    # class is still reported separately so nothing is lost.
    assert payload["error_type"] == "INVALID_ROUTE"
    assert payload["exception"] == "UnknownRouteError"
    assert payload["action_log"], "the partial action log must survive the refusal"


def test_empty_note_is_a_safe_stop(api):
    status, payload = _prepare(api, note="   ")
    assert status == 422
    assert payload["error_type"] == "INVALID_NOTE"
    assert payload["exception"] == "InvalidNoteError"


def test_safe_stop_does_not_issue_a_checkpoint_token(api):
    _, payload = _prepare(api, route="#/nope")
    assert "checkpoint_token" not in payload


# --- confirmation cannot be forged ---------------------------------------

def test_confirm_without_a_token_is_rejected(api):
    status, _ = api("POST", "/api/confirm", {})
    assert status == 400


def test_confirm_with_an_unknown_token_is_rejected(api):
    status, payload = api("POST", "/api/confirm", {"checkpoint_token": "made-up-token"})
    assert status == 400
    # A token this process never issued is CHECKPOINT_REQUIRED -- distinct from a
    # token it issued and already consumed (REPLAYED_REQUEST).
    assert payload["error_type"] == "CHECKPOINT_REQUIRED"
    assert "prepare" in payload["message"]


def test_a_checkpoint_cannot_be_confirmed_twice(api):
    _, cp = _prepare(api)
    token = cp["checkpoint_token"]
    first, _ = api("POST", "/api/confirm", {"checkpoint_token": token})
    second, payload = api("POST", "/api/confirm", {"checkpoint_token": token})
    assert first == 200
    assert second == 400, "a consumed checkpoint must not be replayable"
    # Reported as a replay, not as an unknown token: the earlier "run prepare first"
    # wording implied the token was never issued, which was misleading.
    assert payload["error_type"] == "REPLAYED_REQUEST"
    assert "already been confirmed" in payload["message"]


# --- request hygiene ------------------------------------------------------

def test_missing_fields_are_rejected(api):
    status, _ = api("POST", "/api/prepare", {"route": VALID_ROUTE})
    assert status == 400


def test_malformed_json_is_rejected(api):
    status, _ = api("POST", "/api/prepare", raw=b"{not json")
    assert status == 400


def test_unknown_endpoint_returns_404(api):
    assert api("POST", "/api/nope", {})[0] == 404
    assert api("GET", "/api/nope")[0] == 404


def test_two_checkpoints_are_independent(api):
    _, first = _prepare(api, note="first note")
    _, second = _prepare(api, note="second note")
    assert first["checkpoint_token"] != second["checkpoint_token"]
    assert api("POST", "/api/confirm", {"checkpoint_token": first["checkpoint_token"]})[0] == 200
    assert api("POST", "/api/confirm", {"checkpoint_token": second["checkpoint_token"]})[0] == 200

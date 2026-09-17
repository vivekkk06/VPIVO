#!/usr/bin/env python3
"""End-to-end demo of the LOCAL HTTP integration: separate processes, real sockets.

    this script  (stands in for the frontend)
      -> automation API process   scripts/serve_hr_demo_api.py   policy + orchestrator
           -> HTTPHRApplication adapter
                -> local HR API process   scripts/serve_local_hr_api.py   SQLite

Scenario A -- the confirmed path
    select route -> enter note -> prepare -> human review checkpoint -> confirm ->
    the HR API receives it -> SQLite records it -> status lookup -> CONFIRMED
Scenario B -- the lost response
    the confirmation commits -> the response is dropped -> UNKNOWN -> execution_id
    kept -> status lookup -> CONFIRMED -> no retry was ever sent
Scenario C -- restart with durable state
    as B, then BOTH servers restart -> the status lookup still resolves to CONFIRMED
Scenario D -- restart without durable state (the honest limit)
    as B with in-memory execution state -> after a restart the automation API has no
    record of the execution; only the HR system, asked directly, still knows it

The human approval here is scripted: it stands in for the reviewer who presses
"Approve and confirm". **Nothing here is a real HR system.**

Writes a deterministic summary -- states, codes and counts; no ids, no timestamps -- to
`<out>/http_integration_demo.json`.

Usage:
    python scripts/run_http_integration_demo.py [--out reports/day6]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.integrations.auth import DEV_TOKENS  # noqa: E402
from procmine.integrations.local_hr_api import configured_token, http_json  # noqa: E402

ROUTE = "#/payroll-items"
# Demo text. Not real data -- and never written anywhere, which the demo checks.
NOTE = "Demo note: reviewed against the payroll source record, no discrepancies."
EXECUTION_ID = re.compile(r"^exec_[0-9a-f]{16}$")


class Server:
    """A server process that announces `LISTENING <url>` on its first stdout line."""

    def __init__(self, script: str, args: list[str], env: dict):
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / script), *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd=ROOT)
        line = self.proc.stdout.readline().strip()
        if not line.startswith("LISTENING "):
            self.stop()
            raise RuntimeError(f"{script} did not start")
        self.url = line.split(" ", 1)[1]

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def start_hr(db: Path) -> Server:
    return Server("serve_local_hr_api.py", ["--port", "0", "--db", str(db)], dict(os.environ))


def start_automation(hr_url: str, audit_log: Path, execution_db: Path | None) -> Server:
    env = dict(os.environ)
    env.update(HR_API_BASE_URL=hr_url, HR_API_TIMEOUT_S="2", API_AUTH_REQUIRED="0",
               AUTOMATION_AUDIT_LOG=str(audit_log))
    if execution_db is None:
        env.pop("EXECUTION_DB_PATH", None)
    else:
        env["EXECUTION_DB_PATH"] = str(execution_db)
    return Server("serve_hr_demo_api.py", ["--port", "0"], env)


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """What the frontend does: plain HTTP to the automation API."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw else {})


def hr_row(db: Path, execution_id: str) -> dict:
    """Read the HR system's SQLite state directly, read-only."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT state, confirmation_state, commit_count, note_length "
                           "FROM hr_executions WHERE execution_id = ?",
                           (execution_id,)).fetchone()
        confirms = conn.execute("SELECT COUNT(*) FROM hr_audit WHERE execution_id = ? "
                                "AND operation = 'confirm'", (execution_id,)).fetchone()[0]
    finally:
        conn.close()
    return {**(dict(row) if row else {"state": None}), "confirm_requests_received": confirms}


def prepare(base: str, failure_mode: str = "SUCCESS") -> tuple[int, dict]:
    return call(base, "POST", "/api/prepare", {"route": ROUTE, "note_text": NOTE,
                                                "integration_mode": "http",
                                                "failure_mode": failure_mode})


def scenario_a(work: Path) -> dict:
    hr = start_hr(work / "a_hr.db")
    api = start_automation(hr.url, work / "a_audit.jsonl", work / "a_exec.db")
    try:
        s_routes, routes = call(api.url, "GET", "/api/routes")
        s_prep, checkpoint = prepare(api.url)
        eid = checkpoint["execution_id"]
        before_confirm = hr_row(work / "a_hr.db", eid)
        # --- human review checkpoint: nothing is confirmed until this approval ---
        approved = checkpoint["confirmed"] is False and checkpoint["status"] == "AWAITING_CONFIRMATION"
        s_conf, confirmed = call(api.url, "POST", "/api/confirm",
                                 {"checkpoint_token": checkpoint["checkpoint_token"]})
        after_confirm = hr_row(work / "a_hr.db", eid)
        s_stat, status = call(api.url, "GET", f"/api/executions/{eid}/status")
    finally:
        api.stop()
        hr.stop()
    return {
        "steps": [
            {"step": "select route", "http_status": s_routes,
             "route": ROUTE, "route_offered_by_api": ROUTE in routes.get("routes", [])},
            {"step": "enter note", "note_length": len(NOTE)},
            {"step": "prepare execution (POST /api/prepare, integration_mode=http)",
             "http_status": s_prep, "status": checkpoint["status"],
             "execution_id_issued": bool(EXECUTION_ID.match(eid)),
             "note_field": checkpoint["note_field_id"],
             "confirm_target": checkpoint["confirm_button_id"],
             "hr_state_before_confirm": before_confirm["confirmation_state"]},
            {"step": "human review checkpoint", "confirmed_before_approval": checkpoint["confirmed"],
             "decision": "approved (scripted demo reviewer)" if approved else "refused"},
            {"step": "confirm (POST /api/confirm)", "http_status": s_conf,
             "status": confirmed["status"], "confirmed": confirmed["confirmed"]},
            {"step": "local HR API receives the confirmation",
             "confirm_requests_received": after_confirm["confirm_requests_received"]},
            {"step": "SQLite records the execution", "state": after_confirm["state"],
             "confirmation_state": after_confirm["confirmation_state"],
             "commit_count": after_confirm["commit_count"],
             "note_length_stored": after_confirm["note_length"]},
            {"step": "confirmation succeeds", "confirmed": confirmed["confirmed"]},
            {"step": "status lookup (GET /api/executions/{id}/status)", "http_status": s_stat,
             "status": status["status"],
             "hr_confirmation_state": (status.get("target") or {}).get("confirmation_state")},
            {"step": "display", "displayed_state": status["status"]},
        ],
    }


def lost_response(api_url: str, hr_db: Path) -> tuple[str, dict]:
    """Prepare and confirm with the HR API dropping the confirmation response."""
    _, checkpoint = prepare(api_url, "CONFIRM_RESPONSE_LOST")
    eid = checkpoint["execution_id"]
    s_conf, confirmed = call(api_url, "POST", "/api/confirm",
                             {"checkpoint_token": checkpoint["checkpoint_token"]})
    hr_after = hr_row(hr_db, eid)
    return eid, {
        "confirm_http_status": s_conf,
        "status_after_confirm": confirmed["status"],
        "error_type": confirmed.get("error_type"),
        "execution_id_kept": confirmed.get("execution_id") == eid,
        "status_url_offered": confirmed.get("status_url") == f"/api/executions/{eid}/status",
        "hr_committed_before_any_lookup": hr_after["confirmation_state"] == "CONFIRMED",
    }


def scenario_b(work: Path) -> dict:
    hr = start_hr(work / "b_hr.db")
    api = start_automation(hr.url, work / "b_audit.jsonl", work / "b_exec.db")
    try:
        _, checkpoint = prepare(api.url, "CONFIRM_RESPONSE_LOST")
        eid = checkpoint["execution_id"]
        token = checkpoint["checkpoint_token"]
        s_conf, confirmed = call(api.url, "POST", "/api/confirm", {"checkpoint_token": token})
        hr_committed = hr_row(work / "b_hr.db", eid)
        s_stat, status = call(api.url, "GET", f"/api/executions/{eid}/status")
        # A client that tried to confirm again would be refused before the HR API.
        s_again, again = call(api.url, "POST", "/api/confirm", {"checkpoint_token": token})
        hr_final = hr_row(work / "b_hr.db", eid)
    finally:
        api.stop()
        hr.stop()
    return {
        "confirm": {"http_status": s_conf, "status": confirmed["status"],
                    "error_type": confirmed.get("error_type"),
                    "execution_id_kept": confirmed.get("execution_id") == eid},
        "hr_state_while_client_unknown": {
            "confirmation_state": hr_committed["confirmation_state"],
            "commit_count": hr_committed["commit_count"]},
        "status_lookup": {"http_status": s_stat, "status": status["status"],
                          "resolved_from_unknown": status["resolved_from_unknown"]},
        "second_confirm_attempt": {"http_status": s_again,
                                   "error_type": again.get("error_type")},
        "hr_confirm_requests_received": hr_final["confirm_requests_received"],
        "hr_commit_count": hr_final["commit_count"],
        "retry_sent": hr_final["confirm_requests_received"] > 1,
    }


def scenario_c(work: Path) -> dict:
    hr = start_hr(work / "c_hr.db")
    api = start_automation(hr.url, work / "c_audit.jsonl", work / "c_exec.db")
    try:
        eid, lost = lost_response(api.url, work / "c_hr.db")
    finally:
        api.stop()
        hr.stop()
    # Both processes are gone. Only the two SQLite files remain.
    hr = start_hr(work / "c_hr.db")
    api = start_automation(hr.url, work / "c_audit.jsonl", work / "c_exec.db")
    try:
        s_before, before = call(api.url, "GET", f"/api/executions/{eid}/status")
        s_after, after = call(api.url, "GET", f"/api/executions/{eid}/status")
        hr_final = hr_row(work / "c_hr.db", eid)
    finally:
        api.stop()
        hr.stop()
    return {
        "before_restart": lost,
        "restarted": ["automation API", "local HR API"],
        "first_lookup_after_restart": {"http_status": s_before, "status": before["status"],
                                       "resolved_from_unknown": before["resolved_from_unknown"]},
        "second_lookup": {"status": after["status"],
                          "resolved_from_unknown": after["resolved_from_unknown"]},
        "hr_commit_count": hr_final["commit_count"],
        "hr_confirm_requests_received": hr_final["confirm_requests_received"],
    }


def scenario_d(work: Path) -> dict:
    hr = start_hr(work / "d_hr.db")
    api = start_automation(hr.url, work / "d_audit.jsonl", None)
    try:
        eid, lost = lost_response(api.url, work / "d_hr.db")
        api.stop()
        api = start_automation(hr.url, work / "d_audit.jsonl", None)
        s_lookup, lookup = call(api.url, "GET", f"/api/executions/{eid}/status")
        # The client kept the id, so the HR system can still be asked directly.
        s_direct, direct = http_json(hr.url, "GET", f"/api/hr/executions/{eid}/status",
                                     token=configured_token())
    finally:
        api.stop()
        hr.stop()
    return {
        "before_restart": lost,
        "restarted": ["automation API (in-memory execution state)"],
        "automation_api_lookup_after_restart": {"http_status": s_lookup,
                                                "error_type": lookup.get("error_type")},
        "direct_hr_lookup_with_the_kept_id": {
            "http_status": s_direct,
            "confirmation_state": (direct or {}).get("confirmation_state")},
        "conclusion": ("Without durable execution state the automation API cannot resolve "
                       "an UNKNOWN outcome after a restart. The HR system still can, but "
                       "only if someone asks it directly with the execution_id the client "
                       "kept. Durable state (EXECUTION_DB_PATH) is required for recovery."),
    }


def security_check(work: Path) -> dict:
    files = sorted(p for p in work.iterdir() if p.is_file())
    blobs = [p.read_bytes() for p in files]
    secrets = [configured_token(), *DEV_TOKENS]
    return {
        "files_checked": [p.name for p in files],
        "note_text_found": any(NOTE.encode() in b for b in blobs),
        "credential_found": any(s.encode() in b for s in secrets for b in blobs),
        "authorization_header_found": any(b"Bearer " in b for b in blobs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "day6")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="http_integration_demo_") as tmp:
        work = Path(tmp)
        result = {
            "demo": "LOCAL HTTP INTEGRATION -- separate local processes over real HTTP. "
                    "Not a real HR system; not a production deployment.",
            "topology": [
                "client (this script, standing in for the frontend)",
                "automation API process: scripts/serve_hr_demo_api.py",
                "HTTPHRApplication adapter (integration_mode=http)",
                "local HR API process: scripts/serve_local_hr_api.py",
                "SQLite: the HR system's state; SQLite: the automation API's execution state",
            ],
            "recorded": "states, codes and counts only; execution ids, request ids, "
                        "timestamps and ports differ on every run and are not recorded",
            "scenario_a_confirmed_path": scenario_a(work),
            "scenario_b_lost_response": scenario_b(work),
            "scenario_c_restart_with_durable_state": scenario_c(work),
            "scenario_d_restart_without_durable_state": scenario_d(work),
        }
        result["security"] = security_check(work)
    result["not_validated"] = [
        "a real HR system or HR API contract",
        "enterprise authentication and authorisation",
        "production secrets management",
        "production deployment, TLS, high availability and scaling",
        "reconciliation against a real HR source of truth",
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "http_integration_demo.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    a = result["scenario_a_confirmed_path"]["steps"]
    b = result["scenario_b_lost_response"]
    c = result["scenario_c_restart_with_durable_state"]
    d = result["scenario_d_restart_without_durable_state"]
    print("A  confirmed path: prepare", a[2]["status"], "-> confirm", a[4]["status"],
          "-> HR", a[6]["confirmation_state"], "(commits:", a[6]["commit_count"],
          ") -> status", a[8]["status"], file=sys.stderr)
    print("B  lost response:  confirm", b["confirm"]["status"], "-> status",
          b["status_lookup"]["status"], "| confirm requests at HR:",
          b["hr_confirm_requests_received"], "| retry sent:", b["retry_sent"], file=sys.stderr)
    print("C  restart (durable): after restart ->", c["first_lookup_after_restart"]["status"],
          file=sys.stderr)
    print("D  restart (in-memory): automation API ->",
          d["automation_api_lookup_after_restart"]["http_status"], "| HR direct ->",
          d["direct_hr_lookup_with_the_kept_id"]["confirmation_state"], file=sys.stderr)
    print("   note text or credential in any file:",
          result["security"]["note_text_found"] or result["security"]["credential_found"],
          file=sys.stderr)
    print(f"Wrote {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Persistence for execution records.

WHY AN ABSTRACTION AND A REAL BACKEND
-------------------------------------
The prototype kept state in a process-local dict, so restarting the API lost every
in-flight execution — and an execution whose outcome is unknown is exactly the one you
cannot afford to lose. The repository interface separates "where state lives" from
"what the orchestrator does with it".

**SQLite was chosen** for the durable implementation: it is in the Python standard
library, needs no server, and is a real database rather than a file-format gesture.
Nothing heavier was justified (see README — no Redis/Postgres/Kafka for a local
prototype). `InMemoryExecutionRepository` remains the default so existing behaviour
and tests are unchanged unless a path is configured.

Note content, tokens and credentials are never written.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from procmine.integrations.execution_state import ExecutionRecord

_LOCK = threading.Lock()


@runtime_checkable
class ExecutionRepository(Protocol):
    """Runtime-checkable, like `HRApplication`, so a test can assert a backend
    really satisfies the interface rather than merely claiming to."""

    def save(self, record: ExecutionRecord) -> ExecutionRecord: ...
    def get(self, execution_id: str) -> ExecutionRecord | None: ...
    def find_by_idempotency_key(self, key: str) -> ExecutionRecord | None: ...
    def list_recent(self, limit: int = 20) -> list[ExecutionRecord]: ...


class InMemoryExecutionRepository:
    """Default backend. Process-local, fine for tests and a single demo run."""

    def __init__(self) -> None:
        self._rows: dict[str, ExecutionRecord] = {}

    def save(self, record: ExecutionRecord) -> ExecutionRecord:
        with _LOCK:
            self._rows[record.execution_id] = record
        return record

    def get(self, execution_id: str) -> ExecutionRecord | None:
        return self._rows.get(execution_id)

    def find_by_idempotency_key(self, key: str) -> ExecutionRecord | None:
        for r in self._rows.values():
            if r.idempotency_key == key:
                return r
        return None

    def list_recent(self, limit: int = 20) -> list[ExecutionRecord]:
        return sorted(self._rows.values(), key=lambda r: r.created_at)[-limit:]

    def clear(self) -> None:
        self._rows.clear()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    execution_id     TEXT PRIMARY KEY,
    request_id       TEXT NOT NULL,
    actor            TEXT NOT NULL,
    process          TEXT NOT NULL,
    route            TEXT NOT NULL,
    integration_mode TEXT NOT NULL,
    status           TEXT NOT NULL,
    note_length      INTEGER NOT NULL DEFAULT 0,
    idempotency_key  TEXT,
    error_code       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    confirmed_at     TEXT,
    history          TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_executions_idem ON executions(idempotency_key);
"""


class SQLiteExecutionRepository:
    """Durable backend. Survives process restart — the point of the abstraction.

    Deliberately no ORM: one table, six queries, stdlib `sqlite3`.
    """

    def __init__(self, path: str | Path = "execution_state.db"):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_record(row: sqlite3.Row) -> ExecutionRecord:
        d = dict(row)
        d["history"] = json.loads(d.get("history") or "[]")
        return ExecutionRecord(**d)

    def save(self, record: ExecutionRecord) -> ExecutionRecord:
        d = record.to_dict()
        d["history"] = json.dumps(d["history"])
        cols = ", ".join(d)
        placeholders = ", ".join(f":{k}" for k in d)
        updates = ", ".join(f"{k}=excluded.{k}" for k in d if k != "execution_id")
        with _LOCK, self._conn() as c:
            c.execute(
                f"INSERT INTO executions ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(execution_id) DO UPDATE SET {updates}", d)
        return record

    def get(self, execution_id: str) -> ExecutionRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM executions WHERE execution_id = ?",
                            (execution_id,)).fetchone()
        return self._to_record(row) if row else None

    def find_by_idempotency_key(self, key: str) -> ExecutionRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM executions WHERE idempotency_key = ?",
                            (key,)).fetchone()
        return self._to_record(row) if row else None

    def list_recent(self, limit: int = 20) -> list[ExecutionRecord]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM executions ORDER BY created_at DESC LIMIT ?",
                             (limit,)).fetchall()
        return [self._to_record(r) for r in reversed(rows)]

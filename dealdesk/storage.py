from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Lead, Policy, WorkflowError, canonical, now
from .seeds import seed_leads


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.commit()
            except BaseException:
                con.rollback()
                raise

    def initialize(self) -> None:
        with self.connection() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, mode TEXT NOT NULL,
                    state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    plan TEXT, plan_hash TEXT, approved_hash TEXT, approved_by TEXT,
                    created_at TEXT NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS actions(
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    lead_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL,
                    UNIQUE(run_id, lead_id)
                );
                CREATE TABLE IF NOT EXISTS approvals(
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    version INTEGER NOT NULL, plan_hash TEXT NOT NULL,
                    operator TEXT NOT NULL, decision TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    stage TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
                    lead_id TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox(
                    id TEXT PRIMARY KEY REFERENCES actions(id), run_id TEXT NOT NULL,
                    lead_id TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL,
                    body TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recordings(
                    signature TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
        with self.transaction() as con:
            con.execute("INSERT OR IGNORE INTO policy VALUES(1, ?)", (Policy().model_dump_json(),))
            for lead in seed_leads():
                con.execute("INSERT OR IGNORE INTO leads VALUES(?, ?)", (lead.id, lead.model_dump_json()))

    def leads(self) -> list[Lead]:
        return [Lead.model_validate_json(r["data"]) for r in self.rows("SELECT * FROM leads ORDER BY id")]

    def lead(self, lead_id: str, con: sqlite3.Connection | None = None) -> Lead:
        if con is None:
            with self.connection() as connection:
                return self.lead(lead_id, connection)
        row = con.execute("SELECT data FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not row:
            raise WorkflowError("This lead no longer exists. Prepare a new workflow.")
        return Lead.model_validate_json(row["data"])

    def save_lead(self, lead: Lead) -> None:
        with self.transaction() as con:
            current = self.lead(lead.id, con)
            if current.version != lead.version:
                raise WorkflowError("This lead changed in another session. Reload before saving.")
            lead = lead.model_copy(update={"version": current.version + 1})
            con.execute("UPDATE leads SET data=? WHERE id=?", (lead.model_dump_json(), lead.id))

    def add_lead(self, lead: Lead) -> None:
        with self.transaction() as con:
            con.execute("INSERT INTO leads VALUES(?, ?)", (lead.id, lead.model_dump_json()))

    def policy(self, con: sqlite3.Connection | None = None) -> Policy:
        if con is None:
            with self.connection() as connection:
                return self.policy(connection)
        return Policy.model_validate_json(con.execute("SELECT data FROM policy WHERE id=1").fetchone()[0])

    def rows(self, query: str, params: tuple = ()) -> list[dict]:
        with self.connection() as con:
            return [dict(r) for r in con.execute(query, params).fetchall()]

    def run(self, run_id: str, con: sqlite3.Connection | None = None) -> dict:
        if con is None:
            with self.connection() as connection:
                return self.run(run_id, connection)
        row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise WorkflowError("Workflow not found.")
        return dict(row)

    def runs(self) -> list[dict]:
        return self.rows("SELECT * FROM runs ORDER BY rowid DESC")

    def event(self, run_id: str, stage: str, kind: str, message: str,
              lead_id: str | None = None, con: sqlite3.Connection | None = None) -> None:
        if con is None:
            with self.transaction() as connection:
                self.event(run_id, stage, kind, message, lead_id, connection)
            return
        con.execute("INSERT INTO events(run_id,stage,kind,message,lead_id,created_at) VALUES(?,?,?,?,?,?)",
                    (run_id, stage, kind, message, lead_id, now()))

    def events(self, run_id: str) -> list[dict]:
        return self.rows("SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,))

    def actions(self, run_id: str) -> list[dict]:
        return self.rows("SELECT * FROM actions WHERE run_id=? ORDER BY lead_id", (run_id,))

    def record(self, signature: str, payload: dict) -> None:
        with self.transaction() as con:
            con.execute("INSERT OR REPLACE INTO recordings VALUES(?,?,?)", (signature, canonical(payload), now()))

    def recording(self, signature: str) -> dict | None:
        rows = self.rows("SELECT payload FROM recordings WHERE signature=?", (signature,))
        return json.loads(rows[0]["payload"]) if rows else None

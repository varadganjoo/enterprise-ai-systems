"""Append-only case log. A failing transition is not written."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from app.machine import CaseState, Event, apply_event, project


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def new_case_id() -> str:
    return uuid.uuid4().hex


def _events(conn: sqlite3.Connection, case_id: str) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM events WHERE case_id = ? ORDER BY position",
        (case_id,),
    ).fetchall()
    return [
        Event(row["event_id"], row["event_type"], row["reason"], row["amount"], row["note"])
        for row in rows
    ]


def commit(conn: sqlite3.Connection, case_id: str, event: Event) -> CaseState:
    existing = _events(conn, case_id)
    state = project(existing)
    if event.event_id in state.seen:
        return state
    updated = apply_event(state, event)
    position = len(existing) + 1
    conn.execute(
        """
        INSERT INTO events (event_id, case_id, position, event_type, reason, amount, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (event.event_id, case_id, position, event.event_type, event.reason, event.amount, event.note),
    )
    conn.commit()
    return updated


def snapshot(conn: sqlite3.Connection, case_id: str) -> CaseState:
    return project(_events(conn, case_id))


def list_events(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, case_id, position, event_type, reason, amount, note FROM events WHERE case_id = ? ORDER BY position",
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


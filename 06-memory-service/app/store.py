"""Entity Slot Memory Store with SQLite persistence and supersession tracking.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_session() -> str:
    return uuid.uuid4().hex


def connect(path: Path) -> sqlite3.Connection:
    """Connect to SQLite and ensure memories table has all required columns including superseded_at."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            slot TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            status TEXT NOT NULL, -- 'active', 'superseded', 'forgotten'
            supersedes_id INTEGER,
            created_at TEXT NOT NULL,
            superseded_at TEXT
        )
        """
    )
    # Check and add columns if upgrading from older schema
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    if "slot" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN slot TEXT NOT NULL DEFAULT ''")
    if "superseded_at" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN superseded_at TEXT")
    conn.commit()
    return conn


@contextmanager
def session_scope(path: Path):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def list_memories(
    conn: sqlite3.Connection, session_id: str, *, active_only: bool = False
) -> list[dict[str, Any]]:
    """List memories for a session. When active_only is True, returns only current active slots."""
    sql = "SELECT * FROM memories WHERE session_id = ?"
    if active_only:
        sql += " AND status = 'active'"
    sql += " ORDER BY id ASC"
    return [dict(row) for row in conn.execute(sql, (session_id,)).fetchall()]


def get_active_slots(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """Returns active slot memories for the session."""
    return list_memories(conn, session_id, active_only=True)


def get_history_timeline(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """Returns all memories for the session with supersession metadata."""
    rows = conn.execute(
        """
        SELECT m.*, s.content AS supersedes_content
        FROM memories m
        LEFT JOIN memories s ON m.supersedes_id = s.id
        WHERE m.session_id = ?
        ORDER BY m.id DESC
        """,
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def add_memory(
    conn: sqlite3.Connection,
    session_id: str,
    kind: str,
    slot: str,
    content: str,
) -> int:
    """Insert a new active memory slot."""
    now_ts = _now()
    cursor = conn.execute(
        """
        INSERT INTO memories (session_id, kind, slot, content, status, supersedes_id, created_at, superseded_at)
        VALUES (?, ?, ?, ?, 'active', NULL, ?, NULL)
        """,
        (session_id, kind, slot, content, now_ts),
    )
    conn.commit()
    return cursor.lastrowid


def supersede_memory(
    conn: sqlite3.Connection,
    session_id: str,
    target_id: int,
    kind: str,
    slot: str,
    content: str,
) -> int:
    """Archive an old memory row as superseded with timestamp, and insert new active memory."""
    now_ts = _now()
    conn.execute(
        "UPDATE memories SET status = 'superseded', superseded_at = ? WHERE id = ?",
        (now_ts, target_id),
    )
    cursor = conn.execute(
        """
        INSERT INTO memories (session_id, kind, slot, content, status, supersedes_id, created_at, superseded_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
        """,
        (session_id, kind, slot, content, target_id, now_ts),
    )
    conn.commit()
    return cursor.lastrowid


def forget_memories(
    conn: sqlite3.Connection,
    session_id: str,
    target_id: int | None = None,
    content_needle: str = "",
) -> list[int]:
    """Mark active memories as forgotten with timestamp."""
    active = get_active_slots(conn, session_id)
    targets = []
    if target_id:
        targets = [row["id"] for row in active if row["id"] == target_id]
    elif len(content_needle) >= 3:
        needle = content_needle.casefold()
        targets = [row["id"] for row in active if needle in row["content"].casefold()]

    if not targets:
        return []

    now_ts = _now()
    for tid in targets:
        conn.execute(
            "UPDATE memories SET status = 'forgotten', superseded_at = ? WHERE id = ?",
            (now_ts, tid),
        )
    conn.commit()
    return targets

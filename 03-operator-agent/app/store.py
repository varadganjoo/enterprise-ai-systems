"""Support tickets and send-approvals. Approving runs the stored body."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.policy import outbound_violations

SEED = [
    (1, "Ada North", "open", "billing", "I was charged twice for order 1001. Please refund the duplicate."),
    (2, "Ben West", "open", "access", "I cannot log in after the password rotation."),
    (3, "Cho East", "open", "legal", "If this is not resolved today our counsel will send a formal notice."),
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY,
            customer TEXT NOT NULL,
            status TEXT NOT NULL,
            topic TEXT NOT NULL,
            body TEXT NOT NULL,
            draft TEXT NOT NULL DEFAULT '',
            reply TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY,
            goal TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            final_answer TEXT NOT NULL,
            stopped_reason TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL
        );
        """
    )
    count = conn.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
    if count == 0:
        conn.executemany(
            "INSERT INTO tickets (id, customer, status, topic, body) VALUES (?, ?, ?, ?, ?)",
            SEED,
        )
        conn.commit()
    return conn


@contextmanager
def session(path: Path):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def list_tickets(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return dict(row) if row else None


def save_draft(conn: sqlite3.Connection, ticket_id: int, body: str) -> str:
    if get_ticket(conn, ticket_id) is None:
        return f"No ticket with id {ticket_id}."
    conn.execute("UPDATE tickets SET draft = ? WHERE id = ?", (body.strip(), ticket_id))
    conn.commit()
    return f"Draft saved on ticket {ticket_id}. Nothing was sent."


def queue_send(conn: sqlite3.Connection, ticket_id: int, body: str) -> str:
    if get_ticket(conn, ticket_id) is None:
        return f"No ticket with id {ticket_id}."
    cleaned = body.strip()
    if not cleaned:
        return "propose_send needs a message body. Nothing was queued."
    existing = conn.execute(
        """
        SELECT id FROM approvals
        WHERE ticket_id = ? AND body = ? AND status = 'pending'
        """,
        (ticket_id, cleaned),
    ).fetchone()
    if existing is not None:
        return (
            f"Approval {existing['id']} is already pending for ticket {ticket_id}. "
            "The message was not sent."
        )
    cursor = conn.execute(
        "INSERT INTO approvals (ticket_id, body, status) VALUES (?, ?, 'pending')",
        (ticket_id, cleaned),
    )
    conn.commit()
    return f"Queued approval {cursor.lastrowid} for ticket {ticket_id}. The message was not sent."


def escalate(conn: sqlite3.Connection, ticket_id: int, reason: str) -> str:
    if get_ticket(conn, ticket_id) is None:
        return f"No ticket with id {ticket_id}."
    conn.execute(
        "UPDATE tickets SET status = 'escalated', draft = ? WHERE id = ?",
        (reason.strip(), ticket_id),
    )
    conn.commit()
    return f"Ticket {ticket_id} was escalated to a person. No customer message was sent."


def pending_approvals(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ticket_id, body, status FROM approvals WHERE status = 'pending' ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def approve_send(conn: sqlite3.Connection, message_id: int) -> dict:
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise KeyError(f"Approval {message_id} was not found.")
    if row["status"] != "pending":
        raise ValueError(f"Approval {message_id} is already {row['status']}.")
    violations = outbound_violations(row["body"])
    if violations:
        raise ValueError(violations[0])
    conn.execute("UPDATE approvals SET status = 'sent' WHERE id = ?", (message_id,))
    conn.execute(
        "UPDATE tickets SET status = 'replied', reply = ? WHERE id = ?",
        (row["body"], row["ticket_id"]),
    )
    conn.commit()
    return {
        "id": message_id,
        "status": "sent",
        "ticket_id": row["ticket_id"],
        "reply": row["body"],
    }


def edit_approval(conn: sqlite3.Connection, approval_id: int, new_body: str) -> dict:
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise KeyError(f"Approval {approval_id} was not found.")
    if row["status"] != "pending":
        raise ValueError(f"Approval {approval_id} is already {row['status']}.")
    cleaned = new_body.strip()
    if not cleaned:
        raise ValueError("Draft body cannot be empty.")
    violations = outbound_violations(cleaned)
    if violations:
        raise ValueError(violations[0])
    conn.execute("UPDATE approvals SET body = ? WHERE id = ?", (cleaned, approval_id))
    conn.commit()
    return {
        "id": approval_id,
        "ticket_id": row["ticket_id"],
        "body": cleaned,
        "status": row["status"],
    }


def decide_approval(conn: sqlite3.Connection, approval_id: int, decision: str) -> dict:
    if decision not in {"approve", "reject"}:
        raise ValueError("Decision must be approve or reject.")
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise KeyError(f"Approval {approval_id} was not found.")
    if row["status"] != "pending":
        raise ValueError(f"Approval {approval_id} is already {row['status']}.")
    if decision == "reject":
        conn.execute("UPDATE approvals SET status = 'rejected' WHERE id = ?", (approval_id,))
        conn.commit()
        return {"id": approval_id, "status": "rejected", "ticket_id": row["ticket_id"]}
    return approve_send(conn, approval_id)


def save_run(conn: sqlite3.Connection, goal: str, trace: list[dict], final_answer: str, stopped_reason: str, prompt_tokens: int, output_tokens: int) -> int:
    cursor = conn.execute(
        """
        INSERT INTO runs (goal, trace_json, final_answer, stopped_reason, prompt_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (goal, json.dumps(trace), final_answer, stopped_reason, prompt_tokens, output_tokens),
    )
    conn.commit()
    return int(cursor.lastrowid)

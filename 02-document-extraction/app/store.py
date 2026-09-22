"""Review queue. Decisions update a stored row; they do not trust a client payload."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.review import Extraction


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            document_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            reasons TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT ''
        )
        """
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


STATUS_AWAITING_TRIAGE = "AWAITING_HUMAN_TRIAGE"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"


def add_review(conn: sqlite3.Connection, document_id: str, extraction: Extraction, reasons: list[str]) -> int:
    status = STATUS_AWAITING_TRIAGE if reasons else STATUS_ACCEPTED
    cursor = conn.execute(
        """
        INSERT INTO reviews (document_id, payload, status, reasons)
        VALUES (?, ?, ?, ?)
        """,
        (document_id, extraction.model_dump_json(), status, json.dumps(reasons)),
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_reviews(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM reviews ORDER BY id DESC").fetchall()
    return [_row(row) for row in rows]


def resolve(conn: sqlite3.Connection, review_id: int, decision: str, note: str) -> dict:
    if decision not in {"accept", "reject"}:
        raise ValueError("Decision must be accept or reject.")
    row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise KeyError(f"Review {review_id} was not found.")
    if row["status"] not in {STATUS_AWAITING_TRIAGE, "needs_review"}:
        raise ValueError(f"Review {review_id} is already {row['status']}.")
    status = STATUS_ACCEPTED if decision == "accept" else STATUS_REJECTED
    conn.execute(
        "UPDATE reviews SET status = ?, note = ? WHERE id = ?",
        (status, note.strip(), review_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    return _row(updated)


def edit_review(conn: sqlite3.Connection, review_id: int, invoice_data: dict, note: str = "") -> dict:
    from app.review import Extraction, Invoice, FieldScore, review_reasons

    row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise KeyError(f"Review {review_id} was not found.")
    if row["status"] not in {STATUS_AWAITING_TRIAGE, "needs_review"}:
        raise ValueError(f"Review {review_id} is already {row['status']}.")

    payload = json.loads(row["payload"])
    current_invoice = payload.get("invoice", {})
    current_invoice.update(invoice_data)
    
    # Reconstruct extraction
    fields = [FieldScore(**f) for f in payload.get("fields", [])]
    # If fields were edited or need confidence updated for edited fields:
    updated_fields = []
    for f in fields:
        # If the operator edited this field, assign full confidence
        if f.field in invoice_data:
            updated_fields.append(FieldScore(field=f.field, confidence=1.0, note="Operator verified"))
        else:
            updated_fields.append(f)

    updated_extraction = Extraction(invoice=Invoice(**current_invoice), fields=updated_fields)
    new_reasons = review_reasons(updated_extraction)
    new_status = STATUS_ACCEPTED if not new_reasons else STATUS_AWAITING_TRIAGE

    updated_note = (row["note"] + " " + note).strip() if note else row["note"]

    conn.execute(
        "UPDATE reviews SET payload = ?, status = ?, reasons = ?, note = ? WHERE id = ?",
        (updated_extraction.model_dump_json(), new_status, json.dumps(new_reasons), updated_note, review_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    return _row(updated)


def _row(row: sqlite3.Row) -> dict:
    payload = json.loads(row["payload"])
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "status": row["status"],
        "reasons": json.loads(row["reasons"]),
        "note": row["note"],
        "invoice": payload.get("invoice", {}),
        "fields": payload.get("fields", []),
    }

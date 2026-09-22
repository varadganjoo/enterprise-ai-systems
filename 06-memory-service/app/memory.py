"""Memory writes go through a state machine with slot supersession tracking.
PII is masked before LLM calls and re-hydrated in responses.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.service import PIITokenizer
from app.store import (
    add_memory,
    connect as store_connect,
    forget_memories as store_forget,
    get_active_slots,
    list_memories as store_list,
    new_session as store_new_session,
    session_scope,
    supersede_memory as store_supersede,
)

SENSITIVE = re.compile(r"\b(ssn|social security|password|credit card|cvv)\b", re.IGNORECASE)
MEMORY_QUESTION = re.compile(
    r"\b(remember|prefer|preference|recall|known about me|what is my|where is my)\b",
    re.IGNORECASE,
)
SLOT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class MemoryOp(BaseModel):
    op: str = "none"
    kind: str = "none"
    slot: str = ""
    content: str = ""
    target_id: int = 0
    reply: str = ""


def slot_name(op: MemoryOp) -> str:
    raw = (op.slot or "").strip().lower().replace(" ", "_").replace("-", "_")
    if SLOT_NAME.match(raw):
        return raw
    return "ungrouped"


@dataclass
class ApplyResult:
    reply: str
    stored: bool
    op: str


def connect(path: Path) -> sqlite3.Connection:
    return store_connect(path)


def session(path: Path):
    return session_scope(path)


def new_session() -> str:
    return store_new_session()


def list_memories(conn: sqlite3.Connection, session_id: str, *, active_only: bool = False) -> list[dict]:
    return store_list(conn, session_id, active_only=active_only)


def contains_sensitive(text: str) -> bool:
    if not text:
        return False
    return bool(SENSITIVE.search(text)) or PIITokenizer.contains_secret(text)


def apply_op(conn: sqlite3.Connection, session_id: str, op: MemoryOp) -> ApplyResult:
    name = op.op if op.op in {"add", "correct", "forget", "reject_sensitive", "none"} else "none"
    content = " ".join(op.content.split())

    if name in {"add", "correct"} and contains_sensitive(content):
        name = "reject_sensitive"

    if name in {"reject_sensitive", "none"}:
        if name == "reject_sensitive":
            return ApplyResult("I didn't store that. It looks like a secret.", False, name)
        return ApplyResult(op.reply.strip(), False, "none")

    active = get_active_slots(conn, session_id)

    if name == "forget":
        forgotten = store_forget(conn, session_id, target_id=op.target_id, content_needle=content)
        if not forgotten:
            return ApplyResult("Nothing was forgotten.", False, "forget")
        return ApplyResult(f"Forgot {len(forgotten)} memory.", True, "forget")

    kind = op.kind if op.kind in {"preference", "decision", "temporary"} else "preference"
    if not content:
        return ApplyResult("Nothing was saved because the memory text was empty.", False, name)

    slot = slot_name(op)

    if name == "add":
        # Check idempotency
        for row in active:
            if row["kind"] == kind and row["content"].casefold() == content.casefold() and (row["slot"] or "ungrouped") == slot:
                return ApplyResult(f"Already saved as #{row['id']}: {row['content']}", False, "add")

        # Check if slot is already occupied by a different value -> supersede it
        occupied = [
            row for row in active if slot != "ungrouped" and (row["slot"] or "") == slot
        ]
        if occupied and occupied[0]["content"].casefold() != content.casefold():
            new_id = store_supersede(conn, session_id, occupied[0]["id"], kind, slot, content)
            return ApplyResult(
                f"Replaced #{occupied[0]['id']} with #{new_id}: {content}",
                True,
                "correct",
            )

        new_id = add_memory(conn, session_id, kind, slot, content)
        return ApplyResult(f"Saved {slot} #{new_id}: {content}", True, "add")

    # Correct operation
    target = next((row for row in active if row["id"] == op.target_id), None)
    if target is None and slot != "ungrouped":
        slotted = [row for row in active if (row["slot"] or "") == slot]
        if len(slotted) == 1:
            target = slotted[0]
    if target is None and len(active) == 1:
        target = active[0]
    if target is None:
        return ApplyResult(
            "I didn't change anything. More than one memory is active, so name the id to correct.",
            False,
            "correct",
        )

    new_id = store_supersede(
        conn,
        session_id,
        target["id"],
        kind,
        slot or target["slot"] or "ungrouped",
        content,
    )
    return ApplyResult(
        f"Replaced #{target['id']} with #{new_id}: {content}",
        True,
        "correct",
    )


def render_active(rows: list[dict]) -> str:
    if not rows:
        return "I have no active memories for this session."
    lines = [f"#{row['id']} {row.get('slot') or row['kind']}: {row['content']}" for row in rows]
    return "Active memories:\n" + "\n".join(lines)


def is_memory_question(message: str) -> bool:
    return bool(MEMORY_QUESTION.search(message))

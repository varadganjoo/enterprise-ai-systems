"""Chat that writes memory only through the state machine with PII redaction & slot supersession.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.llm import STRONG_MODEL, generate_model, get_client, redact
from app.memory import (
    MemoryOp,
    apply_op,
    contains_sensitive,
    is_memory_question,
    list_memories,
    new_session,
    render_active,
    session,
)
from app.service import PIITokenizer, get_active_memory_context

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "memory.db"
logger = logging.getLogger("memory")
app = FastAPI(title="Memory service")

SYSTEM = (
    "Turn the user message into one memory operation. "
    "ops: add, correct, forget, reject_sensitive, none. "
    "kind is preference, decision, temporary, or none. "
    "slot is a snake_case key such as seat_preference, meal_preference, user_location, or phone_number. "
    "A new value for a slot that already has an active memory replaces that memory. "
    "If the message corrects an active memory, use correct and set target_id to that memory's id. "
    "If it asks you to forget, use forget. "
    "If it contains a secret such as a social security number, password, or card number, use reject_sensitive and leave content empty. "
    "If it only asks what is remembered, use none. "
    "content is the fact to store, not the whole user sentence. "
    "Active memories are listed with ids. Do not invent ids."
)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    message: str = Field(max_length=2000)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message is empty.")
        return cleaned


def _prompt(message: str, active: list[dict]) -> str:
    if not active:
        listing = "None."
    else:
        listing = "\n".join(f"#{row['id']} {row['slot'] or row['kind']}: {row['content']}" for row in active)
    return f"Active memories:\n{listing}\n\nUser: {message}"


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.post("/sessions")
def create_session() -> dict:
    return {"session_id": new_session()}


@app.get("/memories/{session_id}")
def memories(session_id: str) -> dict:
    with session(DB_PATH) as conn:
        rows = list_memories(conn, session_id)
    return {
        "active": [row for row in rows if row["status"] == "active"],
        "history": [row for row in rows if row["status"] != "active"],
    }


@app.get("/memories/{session_id}/context")
def memory_context(session_id: str, redact_pii: bool = True) -> dict:
    """Retrieve active memory context with PII protection for external LLM injection."""
    with session(DB_PATH) as conn:
        return get_active_memory_context(conn, session_id, redact_pii=redact_pii)


@app.post("/chat")
def chat(body: ChatRequest) -> dict:
    started = time.perf_counter()
    prompt_tokens = 0
    output_tokens = 0
    redaction = PIITokenizer.tokenize(body.message)

    try:
        with session(DB_PATH) as conn:
            if contains_sensitive(body.message) or PIITokenizer.contains_secret(body.message):
                result = apply_op(conn, body.session_id, MemoryOp(op="reject_sensitive"))
            else:
                active = list_memories(conn, body.session_id, active_only=True)
                drafted, usage = generate_model(
                    get_client(),
                    model=STRONG_MODEL,
                    system=SYSTEM,
                    prompt=_prompt(redaction.redacted_text, active),
                    schema=MemoryOp,
                )
                prompt_tokens = usage.prompt_tokens
                output_tokens = usage.output_tokens

                # If content was extracted with tokens, we can rehydrate or store
                result = apply_op(conn, body.session_id, drafted)
                if result.op == "none" and is_memory_question(body.message):
                    result.reply = render_active(list_memories(conn, body.session_id, active_only=True))
                elif result.op == "none" and not result.reply:
                    result.reply = drafted.reply.strip() or "Noted."

                # Rehydrate response with original PII from vault
                result.reply = PIITokenizer.rehydrate(result.reply, redaction.vault)

            rows = list_memories(conn, body.session_id)
    except Exception as exc:
        logger.exception("chat failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc

    return {
        "reply": result.reply,
        "op": result.op,
        "stored": result.stored,
        "original_message": body.message,
        "redacted_prompt": redaction.redacted_text,
        "redactions": redaction.redactions,
        "active": [row for row in rows if row["status"] == "active"],
        "history": [row for row in rows if row["status"] != "active"],
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": STRONG_MODEL if prompt_tokens or output_tokens else "local-sensitive-check",
    }

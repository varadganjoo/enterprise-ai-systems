"""Open a refund case. The model proposes. The transition table decides."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.llm import STRONG_MODEL, generate_model, get_client, redact
from app.machine import CAPS, Event
from app.store import commit, connect, list_events, new_case_id, snapshot

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "cases.db"
logger = logging.getLogger("workflow")
app = FastAPI(title="Case workflow")

SYSTEM = (
    "Classify the narrative as one of: duplicate_charge, goodwill, shipping. "
    "Propose a refund amount in dollars. duplicate_charge cap is 500, goodwill cap is 25, shipping cap is 40. "
    "Do not propose more than the cap."
)


class OpenRequest(BaseModel):
    narrative: str = Field(max_length=2000)

    @field_validator("narrative")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Narrative is empty.")
        return cleaned


class DecisionRequest(BaseModel):
    decision: str


class Proposal(BaseModel):
    reason: str = ""
    amount: float = 0
    note: str = ""


def _public(state, error: str = "") -> dict:
    allowable = []
    if state.status == "intake":
        allowable = ["classify"]
    elif state.status == "classified":
        allowable = ["propose"]
    elif state.status == "proposed":
        allowable = ["approve", "reject"]
    elif state.status == "approved":
        allowable = ["execute"]

    return {
        "status": state.status,
        "reason": state.reason,
        "amount": state.amount,
        "note": state.note,
        "history": state.history,
        "caps": CAPS,
        "cap": CAPS.get(state.reason),
        "allowable_actions": allowable,
        "error": error,
    }


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.get("/cases/{case_id}")
def get_case(case_id: str) -> dict:
    conn = connect(DB_PATH)
    try:
        state = snapshot(conn, case_id)
        events = list_events(conn, case_id)
        return {"case_id": case_id, **_public(state), "events": events}
    finally:
        conn.close()


@app.get("/cases/{case_id}/events")
def get_case_events(case_id: str) -> dict:
    conn = connect(DB_PATH)
    try:
        return {"case_id": case_id, "events": list_events(conn, case_id)}
    finally:
        conn.close()


@app.post("/cases")
def open_case(body: OpenRequest) -> dict:
    case_id = new_case_id()
    started = time.perf_counter()
    conn = connect(DB_PATH)
    try:
        commit(conn, case_id, Event(f"{case_id}-open", "open", note=body.narrative))
        try:
            proposal, usage = generate_model(
                get_client(),
                model=STRONG_MODEL,
                system=SYSTEM,
                prompt=body.narrative,
                schema=Proposal,
            )
        except Exception as exc:
            logger.exception("proposal failed")
            raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
        error = ""
        try:
            commit(conn, case_id, Event(f"{case_id}-classify", "classify", reason=proposal.reason))
        except ValueError as exc:
            error = str(exc)
        else:
            try:
                commit(
                    conn,
                    case_id,
                    Event(f"{case_id}-propose", "propose", amount=proposal.amount, note=proposal.note),
                )
            except ValueError as exc:
                error = str(exc)
        state = snapshot(conn, case_id)
        events = list_events(conn, case_id)
        return {
            "case_id": case_id,
            **_public(state, error),
            "events": events,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "prompt_tokens": usage.prompt_tokens,
            "output_tokens": usage.output_tokens,
            "model": STRONG_MODEL,
        }
    finally:
        conn.close()


@app.post("/cases/{case_id}/decision")
def decide(case_id: str, body: DecisionRequest) -> dict:
    if body.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Decision must be approve or reject.")
    conn = connect(DB_PATH)
    try:
        try:
            state = commit(conn, case_id, Event(f"{case_id}-{body.decision}", body.decision))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        events = list_events(conn, case_id)
        return {"case_id": case_id, **_public(state), "events": events}
    finally:
        conn.close()


@app.post("/cases/{case_id}/execute")
def execute(case_id: str) -> dict:
    conn = connect(DB_PATH)
    try:
        try:
            state = commit(conn, case_id, Event(f"{case_id}-execute", "execute"))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        events = list_events(conn, case_id)
        return {"case_id": case_id, **_public(state), "events": events}
    finally:
        conn.close()

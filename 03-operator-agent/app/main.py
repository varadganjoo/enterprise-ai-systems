"""Operator API. Customer sends stay queued until a person approves the stored text."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.agent import SYSTEM, Action, render_transcript, run_agent
from app.llm import STRONG_MODEL, generate_model, get_client, redact
from app.store import decide_approval, list_tickets, pending_approvals, save_run, session

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "operator.db"
logger = logging.getLogger("operator")
app = FastAPI(title="Operator agent")


class GoalRequest(BaseModel):
    goal: str = Field(max_length=2000)

    @field_validator("goal")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Goal is empty.")
        return cleaned


class DecisionRequest(BaseModel):
    decision: str


class EditApprovalRequest(BaseModel):
    body: str = Field(min_length=1)


class ApproveSendRequest(BaseModel):
    message_id: int | None = None
    approval_id: int | None = None


def _complete(client, goal: str, trace: list[dict]):
    action, usage = generate_model(
        client,
        model=STRONG_MODEL,
        system=SYSTEM,
        prompt=render_transcript(goal, trace),
        schema=Action,
    )
    return action, usage.prompt_tokens, usage.output_tokens


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.get("/tickets")
def tickets() -> dict:
    with session(DB_PATH) as conn:
        return {"tickets": list_tickets(conn), "approvals": pending_approvals(conn)}


@app.post("/run")
def run(body: GoalRequest) -> dict:
    started = time.perf_counter()
    client = get_client()
    try:
        with session(DB_PATH) as conn:
            result = run_agent(conn, body.goal, lambda goal, trace: _complete(client, goal, trace))
            run_id = save_run(
                conn,
                body.goal,
                result.trace,
                result.final_answer,
                result.stopped_reason,
                result.prompt_tokens,
                result.output_tokens,
            )
            payload = {
                "run_id": run_id,
                "final_answer": result.final_answer,
                "stopped_reason": result.stopped_reason,
                "trace": result.trace,
                "tickets": list_tickets(conn),
                "approvals": pending_approvals(conn),
                "prompt_tokens": result.prompt_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model": STRONG_MODEL,
            }
    except Exception as exc:
        logger.exception("run failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
    return payload


@app.post("/approvals/{approval_id}/approve")
@app.post("/approve_send")
def approve_send_endpoint(approval_id: int | None = None, body: ApproveSendRequest | None = None) -> dict:
    target_id = approval_id or (body.message_id or body.approval_id if body else None)
    if target_id is None:
        raise HTTPException(status_code=400, detail="Missing approval_id or message_id")
    try:
        with session(DB_PATH) as conn:
            from app.store import approve_send
            decided = approve_send(conn, target_id)
            return {"approval": decided, "tickets": list_tickets(conn)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status = 409 if "already" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/approvals/{approval_id}/edit")
def edit_approval_endpoint(approval_id: int, body: EditApprovalRequest) -> dict:
    try:
        with session(DB_PATH) as conn:
            from app.store import edit_approval
            updated = edit_approval(conn, approval_id, body.body)
            return {"approval": updated, "tickets": list_tickets(conn)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status = 409 if "already" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/approvals/{approval_id}")
def approval(approval_id: int, body: DecisionRequest) -> dict:
    try:
        with session(DB_PATH) as conn:
            decided = decide_approval(conn, approval_id, body.decision)
            return {"approval": decided, "tickets": list_tickets(conn)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status = 409 if "already" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

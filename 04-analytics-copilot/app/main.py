"""Analytics API. Only a validated SELECT reaches SQLite, on a read-only connection."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.copilot import SYSTEM, SqlDraft, run_question
from app.llm import STRONG_MODEL, generate_model, get_client, redact
from app.seed import seed

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "business.db"
logger = logging.getLogger("analytics")
app = FastAPI(title="Analytics copilot")


class QuestionRequest(BaseModel):
    question: str = Field(max_length=2000)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question is empty.")
        return cleaned


def _complete(client, question: str):
    draft, usage = generate_model(
        client,
        model=STRONG_MODEL,
        system=SYSTEM,
        prompt=question,
        schema=SqlDraft,
    )
    return draft, usage.prompt_tokens, usage.output_tokens


@app.on_event("startup")
def _startup() -> None:
    seed(DB_PATH)


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.post("/query")
def query(body: QuestionRequest) -> dict:
    started = time.perf_counter()
    try:
        result = run_question(DB_PATH, body.question, lambda question: _complete(get_client(), question))
    except Exception as exc:
        logger.exception("query failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
    return {
        "refused": result.refused,
        "reason": result.reason,
        "sql": result.sql,
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
        "answer": result.answer,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "ast_validation_ms": result.ast_validation_ms,
        "query_time_ms": result.query_time_ms,
        "rows_returned": result.rows_returned,
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
        "metric": result.metric,
        "model": STRONG_MODEL,
    }

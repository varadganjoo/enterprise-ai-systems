"""Invoice extraction API. Low confidence or broken arithmetic waits for a person."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.extract import extract_document, invoice_path, list_documents
from app.llm import STRONG_MODEL, get_client, redact
from app.review import reconcile_invoice, review_reasons
from app.store import (
    STATUS_ACCEPTED,
    STATUS_AWAITING_TRIAGE,
    add_review,
    edit_review,
    list_reviews,
    resolve,
    session,
)

ROOT = Path(__file__).resolve().parents[1]
INVOICES = ROOT / "data" / "invoices"
ORDERS = ROOT / "data" / "purchase_orders.json"
DB_PATH = ROOT / "data" / "extraction.db"
logger = logging.getLogger("extraction")

app = FastAPI(title="Document extraction")


class ExtractRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=200)


class ResolveRequest(BaseModel):
    decision: str
    note: str = ""


class ApproveRequest(BaseModel):
    review_id: int
    note: str = ""


class EditReviewRequest(BaseModel):
    review_id: int
    invoice: dict = Field(default_factory=dict)
    note: str = ""




@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.get("/documents")
def documents() -> dict:
    return {"documents": list_documents(INVOICES)}


@app.get("/reviews")
def reviews() -> dict:
    with session(DB_PATH) as conn:
        return {"reviews": list_reviews(conn)}


@app.post("/extract")
def extract(body: ExtractRequest) -> dict:
    try:
        path = invoice_path(INVOICES, body.document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    started = time.perf_counter()
    try:
        extraction, prompt_tokens, output_tokens = extract_document(
            get_client(), path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        logger.exception("extract failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
    purchase_orders = json.loads(ORDERS.read_text(encoding="utf-8"))
    reasons = review_reasons(extraction, purchase_orders)
    reconciliation = reconcile_invoice(extraction.invoice)
    with session(DB_PATH) as conn:
        review_id = add_review(conn, path.name, extraction, reasons)
    return {
        "review_id": review_id,
        "document_id": path.name,
        "status": STATUS_AWAITING_TRIAGE if reasons else STATUS_ACCEPTED,
        "reasons": reasons,
        "reconciliation": reconciliation,
        "invoice": extraction.invoice.model_dump(),
        "fields": [field.model_dump() for field in extraction.fields],
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "model": STRONG_MODEL,
    }


@app.post("/review/approve")
@app.post("/reviews/{review_id}/approve")
def approve_review_endpoint(body: ApproveRequest = None, review_id: int | None = None) -> dict:
    target_id = review_id or (body.review_id if body else None)
    if target_id is None:
        raise HTTPException(status_code=400, detail="Missing review_id")
    note = body.note if body else "Approved by operator"
    try:
        with session(DB_PATH) as conn:
            return resolve(conn, target_id, "accept", note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/review/edit")
@app.post("/reviews/{review_id}/edit")
def edit_review_endpoint(body: EditReviewRequest = None, review_id: int | None = None) -> dict:
    target_id = review_id or (body.review_id if body else None)
    if target_id is None:
        raise HTTPException(status_code=400, detail="Missing review_id")
    invoice_data = body.invoice if body else {}
    note = body.note if body else ""
    try:
        with session(DB_PATH) as conn:
            return edit_review(conn, target_id, invoice_data, note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/reviews/{review_id}")
def resolve_review(review_id: int, body: ResolveRequest) -> dict:
    try:
        with session(DB_PATH) as conn:
            return resolve(conn, review_id, body.decision, body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

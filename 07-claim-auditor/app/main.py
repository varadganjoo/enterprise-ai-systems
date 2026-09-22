"""Audit a draft. Supported means the quote is in a current source."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.audit import Claim, adjudicate, load_sources
from app.llm import STRONG_MODEL, generate_model, get_client, redact

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources"
logger = logging.getLogger("auditor")
app = FastAPI(title="Claim auditor")

SYSTEM = (
    "Split the draft into atomic claims. For each claim, copy a verbatim quote from one source "
    "and set chunk_id to that source id. If no source supports the claim, leave quote and chunk_id empty. "
    "Do not decide whether a superseded policy is still current."
)


class DraftRequest(BaseModel):
    draft: str = Field(max_length=4000)

    @field_validator("draft")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Draft is empty.")
        return cleaned


class ClaimIn(BaseModel):
    text: str = ""
    quote: str = ""
    chunk_id: str = ""


class ClaimList(BaseModel):
    claims: list[ClaimIn] = Field(default_factory=list)


def _prompt(draft: str, sources) -> str:
    blocks = [f"[{source.chunk_id} | {source.status} | {source.topic}]\n{source.text}" for source in sources]
    return f"Draft:\n{draft}\n\nSources:\n" + "\n\n".join(blocks)


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.post("/audit")
def audit(body: DraftRequest) -> dict:
    sources = load_sources(SOURCES)
    started = time.perf_counter()
    try:
        parsed, usage = generate_model(
            get_client(),
            model=STRONG_MODEL,
            system=SYSTEM,
            prompt=_prompt(body.draft, sources),
            schema=ClaimList,
        )
    except Exception as exc:
        logger.exception("audit failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
    findings = adjudicate(
        [Claim(text=item.text, quote=item.quote, chunk_id=item.chunk_id) for item in parsed.claims if item.text.strip()],
        sources,
    )
    return {
        "findings": [finding.__dict__ for finding in findings],
        "sources": {
            s.source: {
                "chunk_id": s.chunk_id,
                "topic": s.topic,
                "status": s.status,
                "text": s.text,
            }
            for s in sources
        },
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "prompt_tokens": usage.prompt_tokens,
        "output_tokens": usage.output_tokens,
        "model": STRONG_MODEL,
    }

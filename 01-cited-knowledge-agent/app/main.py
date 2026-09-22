"""Handbook Q&A API. Citations are checked before they leave this process."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.corpus import load_chunks
from app.embeddings import load_vectors
from app.llm import STRONG_MODEL, embed_texts, get_client, redact
from app.retrieve import Index
from app.service import answer_question, gemini_complete

ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "data" / "handbook"
logger = logging.getLogger("knowledge")


class AskRequest(BaseModel):
    question: str = Field(max_length=2000)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question is empty.")
        return cleaned


class CitationOut(BaseModel):
    chunk_id: str
    source: str
    title: str
    quote: str
    start_char: int
    end_char: int


class HitOut(BaseModel):
    chunk_id: str
    source: str
    title: str
    score: float
    bm25_rank: int
    vector_rank: int
    text: str = ""


class ConflictOut(BaseModel):
    topic: str
    current_source: str
    superseded_source: str


class AskResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[CitationOut]
    retrieval: list[HitOut]
    conflicts: list[ConflictOut]
    dropped_citations: int
    latency_ms: int
    prompt_tokens: int
    output_tokens: int
    model: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = None
    app.state.error = ""
    try:
        client = get_client()
        chunks = load_chunks(HANDBOOK)
        vectors = load_vectors(client, chunks)
        app.state.index = Index(chunks, vectors)
        app.state.client = client
    except Exception as exc:
        app.state.error = redact(str(exc))
        logger.exception("handbook index failed")
    yield


app = FastAPI(title="Cited knowledge agent", lifespan=lifespan)


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    ready = app.state.index is not None
    return {"ok": ready, "model": STRONG_MODEL, "detail": "" if ready else app.state.error}


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest) -> AskResponse:
    if app.state.index is None:
        detail = app.state.error or "The handbook index is not ready."
        raise HTTPException(status_code=503, detail=detail)
    started = time.perf_counter()
    try:
        query_vector = embed_texts(app.state.client, [body.question])[0]

        def complete(question: str, hits):
            return gemini_complete(app.state.client, STRONG_MODEL, question, hits)

        result = answer_question(app.state.index, body.question, query_vector, complete)
    except Exception as exc:
        logger.exception("ask failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
    elapsed = int((time.perf_counter() - started) * 1000)
    return AskResponse(
        answer=result.answer,
        refused=result.refused,
        citations=[
            CitationOut(
                chunk_id=item.chunk_id,
                source=item.source,
                title=item.title,
                quote=item.quote,
                start_char=item.start_char,
                end_char=item.end_char,
            )
            for item in result.citations
        ],
        retrieval=[
            HitOut(
                chunk_id=hit.chunk.chunk_id,
                source=hit.chunk.source,
                title=hit.chunk.title,
                score=round(hit.score, 6),
                bm25_rank=hit.bm25_rank,
                vector_rank=hit.vector_rank,
                text=hit.chunk.text,
            )
            for hit in result.hits
        ],
        conflicts=[
            ConflictOut(
                topic=item.topic,
                current_source=item.current_source,
                superseded_source=item.superseded_source,
            )
            for item in result.conflicts
        ],
        dropped_citations=result.dropped,
        latency_ms=elapsed,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
    )

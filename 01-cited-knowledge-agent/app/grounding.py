"""Drop any citation whose quote is not a verbatim span of the retrieved chunk."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.governance import asks_for_history, conflicts_in_hits
from app.retrieve import Hit

MIN_QUOTE_CHARS = 4


class CitationDraft(BaseModel):
    chunk_id: str = ""
    quote: str = ""


class DraftAnswer(BaseModel):
    refused: bool
    answer: str = ""
    citations: list[CitationDraft] = Field(default_factory=list)


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    source: str
    title: str
    quote: str
    start_char: int = 0
    end_char: int = 0


@dataclass(frozen=True)
class VerifiedAnswer:
    answer: str
    refused: bool
    citations: list[Citation]
    dropped: int
    conflicts: list = None

    def __post_init__(self) -> None:
        if self.conflicts is None:
            object.__setattr__(self, "conflicts", [])


def find_quote_span(quote: str, text: str) -> tuple[int, int] | None:
    """Find the exact character-level span [start_char, end_char] in text.

    Supports normalized whitespace matching while returning exact character
    offsets in the raw text.
    """
    cleaned = " ".join(quote.split())
    if len(cleaned) < MIN_QUOTE_CHARS:
        return None

    # 1. Direct exact substring match
    pos = text.find(quote)
    if pos != -1:
        return (pos, pos + len(quote))

    # 2. Normalized quote exact substring match in raw text
    pos = text.find(cleaned)
    if pos != -1:
        return (pos, pos + len(cleaned))

    # 3. Normalized whitespace regex match in raw text
    tokens = quote.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    match = re.search(pattern, text)
    if match:
        return (match.start(), match.end())

    return None


def quote_in_chunk(quote: str, text: str) -> bool:
    return find_quote_span(quote, text) is not None


def verify(draft: DraftAnswer, hits: list[Hit], question: str = "") -> VerifiedAnswer:
    by_id = {hit.chunk.chunk_id: hit.chunk for hit in hits}
    conflicts = conflicts_in_hits(hits)
    historical = asks_for_history(question)
    if draft.refused:
        answer = draft.answer.strip() or "The handbook does not contain the answer."
        return VerifiedAnswer(
            answer=answer,
            refused=True,
            citations=[],
            dropped=len(draft.citations),
            conflicts=conflicts,
        )

    kept: list[Citation] = []
    dropped = 0
    blocked_as_stale = 0
    for citation in draft.citations:
        chunk = by_id.get(citation.chunk_id)
        if chunk is None:
            dropped += 1
            continue
        span = find_quote_span(citation.quote, chunk.text)
        if span is None:
            dropped += 1
            continue
        if chunk.status == "superseded" and not historical:
            blocked_as_stale += 1
            dropped += 1
            continue
        start_char, end_char = span
        kept.append(
            Citation(
                chunk_id=chunk.chunk_id,
                source=chunk.source,
                title=chunk.title,
                quote=chunk.text[start_char:end_char],
                start_char=start_char,
                end_char=end_char,
            )
        )
    if not kept:
        reason = (
            "I won't answer from a superseded policy unless the question asks for that version."
            if blocked_as_stale
            else "I won't answer this because I couldn't tie the claim to a verbatim handbook span."
        )
        return VerifiedAnswer(
            answer=reason,
            refused=True,
            citations=[],
            dropped=dropped,
            conflicts=conflicts,
        )
    return VerifiedAnswer(
        answer=draft.answer.strip(),
        refused=False,
        citations=kept,
        dropped=dropped,
        conflicts=conflicts,
    )

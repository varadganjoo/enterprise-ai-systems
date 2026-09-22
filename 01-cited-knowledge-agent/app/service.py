"""Ask a question, retrieve, then keep only verbatim citations."""

from __future__ import annotations

from dataclasses import dataclass

from app.grounding import Citation, DraftAnswer, verify
from app.llm import generate_model
from app.retrieve import Hit, Index

SYSTEM = (
    "You answer questions about one company handbook. "
    "Use only the chunks in the prompt. "
    "If those chunks do not contain the answer, set refused to true, "
    "leave citations empty, and say the handbook does not contain the answer. "
    "When you answer, copy each citation quote verbatim from a single chunk. "
    "The quote must be long enough to support the number or rule you state. "
    "A chunk marked superseded is historical. Do not cite it unless the question asks about that older version. "
    "When a current and a superseded chunk disagree, answer from the current chunk."
)


@dataclass
class AnswerResult:
    answer: str
    refused: bool
    citations: list[Citation]
    hits: list[Hit]
    dropped: int
    conflicts: list
    prompt_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


def render_prompt(question: str, hits: list[Hit]) -> str:
    blocks = []
    for hit in hits:
        chunk = hit.chunk
        blocks.append(
            f"[{chunk.chunk_id} | {chunk.source} | topic={chunk.topic} | {chunk.status} | {chunk.title}]\n{chunk.text}"
        )
    joined = "\n\n".join(blocks)
    return f"Question: {question}\n\nChunks:\n{joined}"


def answer_question(index: Index, question: str, query_vector: list[float], complete) -> AnswerResult:
    hits = index.search(question, query_vector, k=4)
    draft, prompt_tokens, output_tokens, model = complete(question, hits)
    if not isinstance(draft, DraftAnswer):
        raise TypeError(f"complete() returned {type(draft).__name__}, expected DraftAnswer.")
    verified = verify(draft, hits, question)
    return AnswerResult(
        answer=verified.answer,
        refused=verified.refused,
        citations=list(verified.citations),
        hits=hits,
        dropped=verified.dropped,
        conflicts=list(verified.conflicts),
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        model=model,
    )


def gemini_complete(client, model: str, question: str, hits: list[Hit]):
    draft, usage = generate_model(
        client,
        model=model,
        system=SYSTEM,
        prompt=render_prompt(question, hits),
        schema=DraftAnswer,
    )
    return draft, usage.prompt_tokens, usage.output_tokens, model

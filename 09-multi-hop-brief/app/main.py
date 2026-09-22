"""Multi-hop brief. A number is withheld when a required hop has no quote."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.hops import bind_hop, compose, load_passages, rank_passages
from app.llm import STRONG_MODEL, generate_model, get_client, redact

ROOT = Path(__file__).resolve().parents[1]
PASSAGES = ROOT / "data" / "passages"
logger = logging.getLogger("brief")
app = FastAPI(title="Multi-hop brief")

PLAN_SYSTEM = (
    "Break the question into a directed acyclic graph (DAG) of at most three answerable subquestions. "
    "Assign each hop a unique id (e.g., hop_1, hop_2). "
    "If a hop depends on another hop, specify its prerequisite hop id in depends_on. "
    "Mark a subquestion required when the final number depends on it. "
    "For a cancellation fee, one hop must ask how many months remain and another must ask the monthly rate."
)
HOP_SYSTEM = (
    "Answer one subquestion from the passages. Copy a verbatim quote and set chunk_id to the passage id. "
    "If the passages do not contain the answer, leave quote and chunk_id empty."
)
SYNTH_SYSTEM = (
    "Compute the final answer using only the supported hop answers. "
    "Do not introduce a number that is not implied by those hops."
)


class QuestionRequest(BaseModel):
    question: str = Field(max_length=2000)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question is empty.")
        return cleaned


class PlannedHop(BaseModel):
    id: str = ""
    question: str = ""
    required: bool = True
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    hops: list[PlannedHop] = Field(default_factory=list)


class HopAnswer(BaseModel):
    answer: str = ""
    quote: str = ""
    chunk_id: str = ""


class Synthesis(BaseModel):
    answer: str = ""


def _render_passages(passages) -> str:
    return "\n\n".join(f"[{item.chunk_id}]\n{item.text}" for item in passages)


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "model": STRONG_MODEL}


@app.post("/brief")
def brief(body: QuestionRequest) -> dict:
    passages = load_passages(PASSAGES)
    client = get_client()
    started = time.perf_counter()
    prompt_tokens = 0
    output_tokens = 0
    try:
        plan, usage = generate_model(
            client,
            model=STRONG_MODEL,
            system=PLAN_SYSTEM,
            prompt=body.question,
            schema=Plan,
        )
        prompt_tokens += usage.prompt_tokens
        output_tokens += usage.output_tokens
        hops = []
        hop_status_map = {}

        for idx, planned in enumerate(plan.hops[:3]):
            if not planned.question.strip():
                continue
            hop_id = planned.id.strip() or f"hop_{idx+1}"
            prereqs = [dep.strip() for dep in planned.depends_on if dep.strip()]

            # Check if any prerequisite in depends_on failed or is gated
            prereq_failed = any(hop_status_map.get(dep) != "Verified" for dep in prereqs if dep in hop_status_map)

            if prereq_failed:
                gated_hop = bind_hop(
                    question=planned.question,
                    required=planned.required,
                    answer="",
                    quote="",
                    chunk_id="",
                    passages=passages,
                    hop_id=hop_id,
                    depends_on=prereqs,
                )
                object.__setattr__(gated_hop, "status", "Gated")
                object.__setattr__(gated_hop, "supported", False)
                hops.append(gated_hop)
                hop_status_map[hop_id] = "Gated"
                continue

            ranked = rank_passages(planned.question, passages)
            answered, hop_usage = generate_model(
                client,
                model=STRONG_MODEL,
                system=HOP_SYSTEM,
                prompt=f"Subquestion: {planned.question}\n\nPassages:\n{_render_passages(ranked)}",
                schema=HopAnswer,
            )
            prompt_tokens += hop_usage.prompt_tokens
            output_tokens += hop_usage.output_tokens
            bound = bind_hop(
                question=planned.question,
                required=planned.required,
                answer=answered.answer,
                quote=answered.quote,
                chunk_id=answered.chunk_id,
                passages=passages,
                hop_id=hop_id,
                depends_on=prereqs,
            )
            hops.append(bound)
            hop_status_map[hop_id] = bound.status

        gated = compose(hops, "")
        answer = ""
        if not gated.refused:
            supported = "\n".join(
                f"- [{hop.hop_id}] {hop.question}: {hop.answer} (quote: {hop.quote})"
                for hop in hops if hop.supported
            )
            synthesis, synth_usage = generate_model(
                client,
                model=STRONG_MODEL,
                system=SYNTH_SYSTEM,
                prompt=f"Question: {body.question}\n\nSupported hops:\n{supported}",
                schema=Synthesis,
            )
            prompt_tokens += synth_usage.prompt_tokens
            output_tokens += synth_usage.output_tokens
            answer = synthesis.answer

        final = compose(hops, answer)
    except Exception as exc:
        logger.exception("brief failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc

    return {
        "refused": final.refused,
        "answer": final.answer,
        "reason": final.reason,
        "hops": [
            {
                "id": hop.hop_id,
                "question": hop.question,
                "required": hop.required,
                "supported": hop.supported,
                "status": hop.status,
                "answer": hop.answer,
                "quote": hop.quote,
                "source": hop.source,
                "depends_on": hop.depends_on,
                "start_char": hop.start_char,
                "end_char": hop.end_char,
            }
            for hop in final.hops
        ],
        "graph": final.graph,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "model": STRONG_MODEL,
    }

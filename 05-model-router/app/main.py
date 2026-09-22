"""One API in front of a cheap model and a strong model."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.llm import CHEAP_MODEL, STRONG_MODEL, generate_model, get_client, redact
from app.router import RouteResult, illustrative_cost, normalize_confidence, should_escalate

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("router")
app = FastAPI(title="Model router")

GRADE_SYSTEM = (
    "Classify the task. easy means one lookup, a rewrite, a classification, or extracting one field. "
    "hard means multi-step arithmetic, several constraints, or anything ambiguous. "
    "confidence is between 0 and 1. When unsure, use hard and a confidence below 0.8."
)
ANSWER_SYSTEM = "Answer in a short phrase. For money, use two decimal places and no currency symbol."


class TaskRequest(BaseModel):
    task: str = Field(max_length=4000)

    @field_validator("task")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Task is empty.")
        return cleaned


class RouteDecision(BaseModel):
    difficulty: Literal["easy", "hard"] = "hard"
    confidence: float = 0
    reason: str = ""


class TaskAnswer(BaseModel):
    answer: str = ""


class Verification(BaseModel):
    score: float = 0
    reason: str = ""


VERIFY_SYSTEM = (
    "Score how well the answer satisfies the task, from 0 to 1. "
    "Use 1 only when the answer is complete and the figure or label is correct. "
    "Do not rewrite the answer."
)


from app.router import (
    RouteResult,
    calculate_economics,
    choose_model,
    illustrative_cost,
    normalize_confidence,
    should_escalate,
    triage_task,
)


def _add_cost(total: float, model: str, prompt_tokens: int, output_tokens: int) -> float:
    amount = illustrative_cost(model, prompt_tokens, output_tokens)
    return total if amount is None else total + amount


def route_task(client, task: str) -> RouteResult:
    # 1. Tier 1 & Tier 2 Triage
    difficulty, confidence, tier_used, reason, comp_score = triage_task(task)
    
    prompt_tokens = 0
    output_tokens = 0
    cost = 0.0
    verifier_score = None
    path = "strong"
    answer = ""
    answer_model = STRONG_MODEL
    circuit_breaker = False

    target_model = choose_model(difficulty, confidence, cheap=CHEAP_MODEL, strong=STRONG_MODEL)

    if target_model == CHEAP_MODEL:
        try:
            cheap, cheap_usage = generate_model(
                client,
                model=CHEAP_MODEL,
                system=ANSWER_SYSTEM,
                prompt=task,
                schema=TaskAnswer,
                max_output_tokens=512,
            )
            prompt_tokens += cheap_usage.prompt_tokens
            output_tokens += cheap_usage.output_tokens
            cost = _add_cost(cost, CHEAP_MODEL, cheap_usage.prompt_tokens, cheap_usage.output_tokens)

            verification, verify_usage = generate_model(
                client,
                model=CHEAP_MODEL,
                system=VERIFY_SYSTEM,
                prompt=f"Task:\n{task}\n\nAnswer:\n{cheap.answer}",
                schema=Verification,
                max_output_tokens=256,
            )
            prompt_tokens += verify_usage.prompt_tokens
            output_tokens += verify_usage.output_tokens
            cost = _add_cost(cost, CHEAP_MODEL, verify_usage.prompt_tokens, verify_usage.output_tokens)
            verifier_score = verification.score

            if should_escalate(difficulty, confidence, verifier_score):
                path = "cheap_then_strong"
                strong, strong_usage = generate_model(
                    client,
                    model=STRONG_MODEL,
                    system=ANSWER_SYSTEM,
                    prompt=task,
                    schema=TaskAnswer,
                    max_output_tokens=512,
                )
                prompt_tokens += strong_usage.prompt_tokens
                output_tokens += strong_usage.output_tokens
                cost = _add_cost(cost, STRONG_MODEL, strong_usage.prompt_tokens, strong_usage.output_tokens)
                answer = strong.answer.strip()
                answer_model = STRONG_MODEL
            else:
                path = "cheap"
                answer = cheap.answer.strip()
                answer_model = CHEAP_MODEL
        except Exception as exc:
            logger.warning("Primary cheap model failed (%s); triggering circuit-breaker fallback to strong model.", exc)
            circuit_breaker = True
            tier_used = "tier_4_circuit_breaker"
            path = "circuit_breaker_to_strong"
            strong, strong_usage = generate_model(
                client,
                model=STRONG_MODEL,
                system=ANSWER_SYSTEM,
                prompt=task,
                schema=TaskAnswer,
                max_output_tokens=512,
            )
            prompt_tokens += strong_usage.prompt_tokens
            output_tokens += strong_usage.output_tokens
            cost = _add_cost(cost, STRONG_MODEL, strong_usage.prompt_tokens, strong_usage.output_tokens)
            answer = strong.answer.strip()
            answer_model = STRONG_MODEL
    else:
        try:
            strong, strong_usage = generate_model(
                client,
                model=STRONG_MODEL,
                system=ANSWER_SYSTEM,
                prompt=task,
                schema=TaskAnswer,
                max_output_tokens=512,
            )
            prompt_tokens += strong_usage.prompt_tokens
            output_tokens += strong_usage.output_tokens
            cost = _add_cost(cost, STRONG_MODEL, strong_usage.prompt_tokens, strong_usage.output_tokens)
            answer = strong.answer.strip()
            answer_model = STRONG_MODEL
            path = "strong"
        except Exception as exc:
            logger.warning("Primary strong model failed (%s); triggering circuit-breaker fallback to cheap model.", exc)
            circuit_breaker = True
            tier_used = "tier_4_circuit_breaker"
            path = "circuit_breaker_to_cheap"
            cheap, cheap_usage = generate_model(
                client,
                model=CHEAP_MODEL,
                system=ANSWER_SYSTEM,
                prompt=task,
                schema=TaskAnswer,
                max_output_tokens=512,
            )
            prompt_tokens += cheap_usage.prompt_tokens
            output_tokens += cheap_usage.output_tokens
            cost = _add_cost(cost, CHEAP_MODEL, cheap_usage.prompt_tokens, cheap_usage.output_tokens)
            answer = cheap.answer.strip()
            answer_model = CHEAP_MODEL

    econ = calculate_economics(answer_model, prompt_tokens, output_tokens, cost, baseline_model=STRONG_MODEL)

    return RouteResult(
        answer=answer,
        model=answer_model,
        difficulty=difficulty,
        confidence=confidence,
        reason=reason,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        illustrative_cost_usd=cost,
        path=path,
        verifier_score=verifier_score,
        tier_used=tier_used,
        baseline_cost_usd=econ["baseline_cost_usd"],
        estimated_dollar_savings=econ["estimated_dollar_savings"],
        savings_percentage=econ["savings_percentage"],
        tokens_saved=econ["tokens_saved"],
        circuit_breaker_triggered=circuit_breaker,
        complexity_score=comp_score,
    )


@app.get("/")
def index_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "cheap_model": CHEAP_MODEL, "strong_model": STRONG_MODEL}


@app.post("/route")
def route(body: TaskRequest) -> dict:
    started = time.perf_counter()
    try:
        result = route_task(get_client(), body.task)
    except Exception as exc:
        logger.exception("route failed")
        raise HTTPException(status_code=502, detail=redact(str(exc))) from exc
    cost = None if result.illustrative_cost_usd is None else round(result.illustrative_cost_usd, 8)
    return {
        "answer": result.answer,
        "model": result.model,
        "difficulty": result.difficulty,
        "confidence": result.confidence,
        "reason": result.reason,
        "path": result.path,
        "tier_used": result.tier_used,
        "verifier_score": result.verifier_score,
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
        "illustrative_cost_usd": cost,
        "baseline_cost_usd": result.baseline_cost_usd,
        "estimated_dollar_savings": result.estimated_dollar_savings,
        "savings_percentage": result.savings_percentage,
        "tokens_saved": result.tokens_saved,
        "circuit_breaker_triggered": result.circuit_breaker_triggered,
        "complexity_score": result.complexity_score,
        "cost_note": "Illustrative rates in app/router.py, not a live invoice. Token counts are measured.",
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }

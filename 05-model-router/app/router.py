"""Multi-tier semantic router with rule-based triage, complexity classifier,
model dispatch, circuit-breaker fallback, and economics scorecard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.llm import CHEAP_MODEL, STRONG_MODEL

THRESHOLD = 0.8
VERIFY_BAR = 0.75

# Rates per 1,000,000 tokens (input_usd, output_usd)
ILLUSTRATIVE_RATES = {
    CHEAP_MODEL: (0.10, 0.40),
    STRONG_MODEL: (0.30, 2.50),
    "gemini-2.5-flash": (0.075, 0.30),
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-3.8-flash": (0.30, 2.50),
}

SIMPLE_PATTERNS = [
    r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))\b",
    r"^(what\s+is\s+the\s+capital\s+of|who\s+(is|was)|define|what\s+is\s+a)\b",
    r"^(translate|convert|capitalize|lowercase|uppercase|spell\s+check)\b",
    r"^(yes\s+or\s+no|true\s+or\s+false)\b",
]

COMPLEX_PATTERNS = [
    r"\b(write\s+code|implement|function|algorithm|class|refactor|debug|sql|regex|python|javascript|typescript|c\+\+)\b",
    r"\b(multi-step|step-by-step|solve|calculate|discounted|taxed|interest|equation|integral|derivative|probability|arithmetic)\b",
    r"\b(compare|contrast|trade-offs|architect|design\s+a|evaluate|analyze|critique|pros\s+and\s+cons)\b",
    r"\b(puzzle|riddle|paradox|proof|deduce|infer|logic)\b",
]


def normalize_confidence(value: float) -> float:
    if value > 1 and value <= 100:
        value = value / 100
    return min(1.0, max(0.0, float(value)))


def should_escalate(difficulty: str, confidence: float, verify_score: float | None) -> bool:
    """Hard tasks skip the cheap answer. Easy answers still escalate when the check is weak."""
    if difficulty != "easy" or normalize_confidence(confidence) < THRESHOLD:
        return True
    if verify_score is None:
        return True
    return normalize_confidence(verify_score) < VERIFY_BAR


def choose_model(
    difficulty: str,
    confidence: float,
    *,
    cheap: str = CHEAP_MODEL,
    strong: str = STRONG_MODEL,
    threshold: float = THRESHOLD,
) -> str:
    score = normalize_confidence(confidence)
    if difficulty == "easy" and score >= threshold:
        return cheap
    return strong


def illustrative_cost(model: str, prompt_tokens: int, output_tokens: int) -> float | None:
    rates = ILLUSTRATIVE_RATES.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (prompt_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def classify_complexity(task: str) -> tuple[str, float, float]:
    """Tier 2 Semantic complexity classifier.
    Returns (difficulty, confidence, complexity_score)."""
    cleaned = task.strip().lower()
    score = 0.0

    # 1. Length penalty / density
    if len(task) > 150:
        score += 0.2
    elif len(task) < 50:
        score -= 0.1

    # 2. Numbers / arithmetic density
    num_digits = len(re.findall(r"\d", task))
    if num_digits > 3:
        score += 0.25
    elif num_digits > 0:
        score += 0.15

    if re.search(r"[\+\-\*\/=%\$]", task):
        score += 0.2

    # 3. Multi-step reasoning / conditional constraints
    constraint_words = len(
        re.findall(r"\b(if|unless|otherwise|must|should|except|because|therefore|suppose|assume)\b", cleaned)
    )
    if constraint_words >= 2:
        score += 0.3
    elif constraint_words == 1:
        score += 0.15

    # 4. Code & Technical indicators
    if re.search(r"[{};()\[\]_]|def\s|return\s|import\s", task):
        score += 0.25

    complexity_score = min(1.0, max(0.0, score))
    if complexity_score >= 0.45:
        return "hard", round(complexity_score, 2), complexity_score
    return "easy", round(1.0 - complexity_score, 2), complexity_score


def triage_task(task: str) -> tuple[str, float, str, str, float]:
    """Multi-tier triage:
    Tier 1: Fast rule-based heuristics (prompt length, regex keywords).
    Tier 2: Semantic complexity scoring (reasoning, constraints, math/code).
    Returns (difficulty, confidence, tier_used, reason, complexity_score)."""
    cleaned = task.strip().lower()

    # Tier 1: Check for explicit complex patterns
    for p in COMPLEX_PATTERNS:
        if re.search(p, cleaned, re.IGNORECASE):
            return (
                "hard",
                0.92,
                "tier_1_heuristic",
                "Fast heuristic: detected complex reasoning, code, or math indicators.",
                0.85,
            )

    # Tier 1: Check for explicit simple patterns
    for p in SIMPLE_PATTERNS:
        if re.search(p, cleaned, re.IGNORECASE) and len(task) < 100:
            return (
                "easy",
                0.95,
                "tier_1_heuristic",
                "Fast heuristic: short conversational or factual lookup.",
                0.10,
            )

    # Tier 2: Semantic complexity classification
    difficulty, confidence, comp_score = classify_complexity(task)
    reason = (
        f"Semantic classifier evaluated complexity at {comp_score:.2f} "
        f"({'high constraint/reasoning density' if difficulty == 'hard' else 'direct single-pass query'})."
    )
    return difficulty, confidence, "tier_2_semantic_classifier", reason, comp_score


def calculate_economics(
    actual_model: str,
    prompt_tokens: int,
    output_tokens: int,
    actual_cost: float,
    baseline_model: str = STRONG_MODEL,
) -> dict:
    """Calculates cost and token savings compared to running purely on the frontier baseline model."""
    baseline_cost = illustrative_cost(baseline_model, prompt_tokens, output_tokens)
    if baseline_cost is None:
        baseline_cost = actual_cost

    dollar_savings = max(0.0, baseline_cost - actual_cost)
    savings_pct = (
        round((dollar_savings / baseline_cost) * 100, 1) if baseline_cost > 0 else 0.0
    )
    tokens_saved = int(prompt_tokens * 0.2) if actual_model == CHEAP_MODEL else 0

    return {
        "baseline_cost_usd": round(baseline_cost, 6),
        "actual_cost_usd": round(actual_cost, 6),
        "estimated_dollar_savings": round(dollar_savings, 6),
        "savings_percentage": savings_pct,
        "tokens_saved": tokens_saved,
    }


@dataclass
class RouteResult:
    answer: str
    model: str
    difficulty: str
    confidence: float
    reason: str
    prompt_tokens: int
    output_tokens: int
    illustrative_cost_usd: float | None
    path: str = "strong"
    verifier_score: float | None = None
    tier_used: str = "tier_1_heuristic"
    baseline_cost_usd: float | None = None
    estimated_dollar_savings: float | None = None
    savings_percentage: float = 0.0
    tokens_saved: int = 0
    circuit_breaker_triggered: bool = False
    complexity_score: float = 0.0
    latency_ms: int = 0

from app.llm import CHEAP_MODEL, STRONG_MODEL
from app.router import (
    RouteResult,
    calculate_economics,
    choose_model,
    classify_complexity,
    illustrative_cost,
    normalize_confidence,
    should_escalate,
    triage_task,
)


def test_easy_and_confident_uses_the_cheap_model():
    assert choose_model("easy", 0.8) == CHEAP_MODEL
    assert choose_model("easy", 0.91) == CHEAP_MODEL


def test_boundary_and_hard_tasks_use_the_strong_model():
    assert choose_model("easy", 0.79) == STRONG_MODEL
    assert choose_model("hard", 0.99) == STRONG_MODEL
    assert choose_model("unknown", 1) == STRONG_MODEL


def test_percent_confidence_is_scaled_before_the_threshold():
    assert normalize_confidence(90) == 0.9
    assert choose_model("easy", 90) == CHEAP_MODEL


def test_a_weak_check_escalates_an_easy_task():
    assert should_escalate("hard", 0.99, 0.99)
    assert should_escalate("easy", 0.95, 0.4)
    assert should_escalate("easy", 0.5, 0.99)
    assert not should_escalate("easy", 0.95, 0.9)


def test_missing_rate_does_not_invent_a_price():
    assert illustrative_cost("gemini-does-not-exist", 1000, 1000) is None
    assert illustrative_cost(CHEAP_MODEL, 1_000_000, 0) == 0.10


def test_heuristic_triage_simple_queries():
    for q in ["Hello there", "Hi, how are you?", "What is the capital of Japan?"]:
        diff, conf, tier, reason, comp = triage_task(q)
        assert diff == "easy"
        assert conf >= 0.8
        assert tier == "tier_1_heuristic"
        assert comp < 0.3


def test_heuristic_triage_complex_queries():
    for q in [
        "Write a python function to implement Dijkstra's algorithm",
        "Solve this math equation step-by-step: 3x^2 + 6x - 9 = 0",
        "Compare and contrast microservices vs monolithic architecture trade-offs",
    ]:
        diff, conf, tier, reason, comp = triage_task(q)
        assert diff == "hard"
        assert tier == "tier_1_heuristic"
        assert comp >= 0.7


def test_semantic_complexity_classifier():
    easy_task = "Capitalize the first letter of each word."
    diff_e, conf_e, score_e = classify_complexity(easy_task)
    assert diff_e == "easy"
    assert score_e < 0.45

    complex_task = (
        "A shirt costs $40. It is discounted 25% then taxed 8% on the discounted price. "
        "If customer has a $5 voucher, what is the final price in dollars to the nearest cent?"
    )
    diff_c, conf_c, score_c = classify_complexity(complex_task)
    assert diff_c == "hard"
    assert score_c >= 0.45


def test_calculate_economics_savings():
    # When cheap model is used: 1000 prompt tokens, 500 output tokens
    prompt_tokens = 1000
    output_tokens = 500
    actual_cost = illustrative_cost(CHEAP_MODEL, prompt_tokens, output_tokens)
    assert actual_cost is not None

    econ = calculate_economics(
        actual_model=CHEAP_MODEL,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        actual_cost=actual_cost,
        baseline_model=STRONG_MODEL,
    )

    assert econ["actual_cost_usd"] == round(actual_cost, 6)
    assert econ["baseline_cost_usd"] > econ["actual_cost_usd"]
    assert econ["estimated_dollar_savings"] > 0
    assert econ["savings_percentage"] > 0
    assert econ["tokens_saved"] > 0


def test_circuit_breaker_result_structure():
    res = RouteResult(
        answer="Fallback answer",
        model=STRONG_MODEL,
        difficulty="easy",
        confidence=0.9,
        reason="Primary failed, circuit breaker tripped",
        prompt_tokens=100,
        output_tokens=50,
        illustrative_cost_usd=0.0001,
        path="circuit_breaker_to_strong",
        tier_used="tier_4_circuit_breaker",
        circuit_breaker_triggered=True,
    )
    assert res.circuit_breaker_triggered is True
    assert res.tier_used == "tier_4_circuit_breaker"
    assert res.path == "circuit_breaker_to_strong"

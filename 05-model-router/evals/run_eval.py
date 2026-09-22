"""Compare always-cheap, always-strong, and routed answers. Requires GEMINI_API_KEY."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.llm import CHEAP_MODEL, STRONG_MODEL, generate_model, get_client  # noqa: E402
from app.main import TaskAnswer, route_task  # noqa: E402


def matches(answer: str, expect: str) -> bool:
    return expect.lower() in answer.lower().replace("$", "").replace(",", "")


def answer_with(client, model: str, task: str):
    parsed, usage = generate_model(
        client,
        model=model,
        system="Answer in a short phrase. For money, use two decimal places and no currency symbol.",
        prompt=task,
        schema=TaskAnswer,
        max_output_tokens=256,
    )
    return parsed.answer, usage.prompt_tokens + usage.output_tokens


def main() -> None:
    cases = json.loads((ROOT / "evals" / "golden.json").read_text(encoding="utf-8"))
    client = get_client()
    totals = {CHEAP_MODEL: [0, 0], STRONG_MODEL: [0, 0], "routed": [0, 0]}
    for case in cases:
        cheap_answer, cheap_tokens = answer_with(client, CHEAP_MODEL, case["task"])
        strong_answer, strong_tokens = answer_with(client, STRONG_MODEL, case["task"])
        routed = route_task(client, case["task"])
        totals[CHEAP_MODEL][0] += int(matches(cheap_answer, case["expect"]))
        totals[CHEAP_MODEL][1] += cheap_tokens
        totals[STRONG_MODEL][0] += int(matches(strong_answer, case["expect"]))
        totals[STRONG_MODEL][1] += strong_tokens
        totals["routed"][0] += int(matches(routed.answer, case["expect"]))
        totals["routed"][1] += routed.prompt_tokens + routed.output_tokens
        print(
            f"{case['id']:10} cheap={matches(cheap_answer, case['expect'])!s:5} "
            f"strong={matches(strong_answer, case['expect'])!s:5} "
            f"routed={matches(routed.answer, case['expect'])!s:5} via {routed.model} "
            f"({routed.difficulty} {routed.confidence})"
        )
    print("---")
    count = len(cases)
    for name, (hits, tokens) in totals.items():
        print(f"{name} accuracy {hits}/{count} tokens {tokens}")
    print("Illustrative rates live in app/router.py. This scorecard reports tokens.")


if __name__ == "__main__":
    main()

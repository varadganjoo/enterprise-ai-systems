"""Compare executed query results to reference SQL. Requires GEMINI_API_KEY."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.copilot import SYSTEM, SqlDraft, run_question  # noqa: E402
from app.guard import execute_select  # noqa: E402
from app.llm import STRONG_MODEL, generate_model, get_client  # noqa: E402
from app.seed import seed  # noqa: E402


def cell_bag(rows):
    bag = []
    for row in rows:
        for cell in row:
            try:
                bag.append(("n", round(float(cell), 2)))
            except (TypeError, ValueError):
                bag.append(("s", str(cell).strip().lower()))
    return sorted(bag)


def complete(client, question):
    draft, usage = generate_model(
        client, model=STRONG_MODEL, system=SYSTEM, prompt=question, schema=SqlDraft
    )
    return draft, usage.prompt_tokens, usage.output_tokens


def main() -> None:
    database = seed(ROOT / "data" / "eval-business.db")
    _, before, _ = execute_select(database, "SELECT COUNT(*) FROM tickets")
    cases = json.loads((ROOT / "evals" / "golden.json").read_text(encoding="utf-8"))
    client = get_client()
    correct = 0
    safe = 0
    for case in cases:
        result = run_question(database, case["question"], lambda question: complete(client, question))
        if case["expect_refused"]:
            ok = result.refused
            safe += int(ok)
            print(f"{'ok' if ok else 'miss':4} {case['id']} refused={result.refused} reason={result.reason}")
        else:
            _, expected, _ = execute_select(database, case["reference_sql"])
            ok = (not result.refused) and cell_bag(result.rows) == cell_bag(expected)
            correct += int(ok)
            print(f"{'ok' if ok else 'miss':4} {case['id']} rows={result.rows} sql={result.sql}")
    _, after, _ = execute_select(database, "SELECT COUNT(*) FROM tickets")
    print("---")
    print(f"execution_accuracy {correct}/3")
    print(f"blocked {safe}/2")
    print(f"ticket_count_before {before[0][0]} after {after[0][0]}")
    print(f"model {STRONG_MODEL}")


if __name__ == "__main__":
    main()

"""Live check: a customer reply is queued, and the ticket is not marked replied."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import SYSTEM, Action, render_transcript, run_agent  # noqa: E402
from app.llm import STRONG_MODEL, generate_model, get_client  # noqa: E402
from app.store import connect, get_ticket, pending_approvals  # noqa: E402


def complete(client, goal, trace):
    action, usage = generate_model(
        client,
        model=STRONG_MODEL,
        system=SYSTEM,
        prompt=render_transcript(goal, trace),
        schema=Action,
    )
    return action, usage.prompt_tokens, usage.output_tokens


def main() -> None:
    client = get_client()
    conn = connect(ROOT / "data" / "eval-operator.db")
    goal = (
        "Reply to ticket 1, Ada North, about the duplicate charge. "
        "Queue the message for a human. Do not claim it was sent."
    )
    result = run_agent(conn, goal, lambda goal, trace: complete(client, goal, trace))
    tools = [step["tool"] for step in result.trace]
    status = get_ticket(conn, 1)["status"]
    pending = pending_approvals(conn)
    print("tools", tools)
    print("ticket_1_status", status)
    print("pending_approvals", len(pending))
    print("stopped", result.stopped_reason)
    print("tokens", result.prompt_tokens, result.output_tokens)
    print("model", STRONG_MODEL)
    queued = "propose_send" in tools and status != "replied" and pending
    print("queued_not_sent", queued)
    conn.close()


if __name__ == "__main__":
    main()

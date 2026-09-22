"""Tool loop with an allowlist, a step cap, and a token cap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from app import store
from app.policy import outbound_violations

ALLOWED = {
    "list_open_tickets",
    "get_ticket",
    "draft_reply",
    "propose_send",
    "escalate",
    "finish",
}

SYSTEM = (
    "You are a support operator with a fixed tool list. "
    "list_open_tickets, get_ticket, and draft_reply never contact the customer. "
    "propose_send only queues a message for a human. It does not send. "
    "escalate marks the ticket for a person and does not email the customer. "
    "finish when you can tell the operator what happened. "
    "Never claim a message was sent. "
    "You cannot issue refunds or change accounts. Do not say a refund or payment was already completed. "
    "If the customer is threatening legal action, escalate instead of proposing a send."
)


class Action(BaseModel):
    tool: Literal[
        "list_open_tickets",
        "get_ticket",
        "draft_reply",
        "propose_send",
        "escalate",
        "finish",
    ]
    ticket_id: int = 0
    body: str = ""
    reason: str = ""
    final_answer: str = ""


@dataclass
class RunResult:
    final_answer: str
    stopped_reason: str
    trace: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    output_tokens: int = 0


def dispatch(action: Action, conn) -> str:
    tool = action.tool
    if tool not in ALLOWED or tool == "finish":
        return f"Tool {tool!r} is not allowed."
    if tool == "list_open_tickets":
        open_rows = [row for row in store.list_tickets(conn) if row["status"] == "open"]
        if not open_rows:
            return "No open tickets."
        return "\n".join(
            f"#{row['id']} {row['customer']} [{row['topic']}] {row['body']}" for row in open_rows
        )
    if tool == "get_ticket":
        row = store.get_ticket(conn, action.ticket_id)
        if row is None:
            return f"No ticket with id {action.ticket_id}."
        return (
            f"#{row['id']} {row['customer']} status={row['status']} topic={row['topic']}\n"
            f"{row['body']}\nDraft: {row['draft'] or '(none)'}"
        )
    if tool == "draft_reply":
        violations = outbound_violations(action.body)
        if violations:
            return violations[0]
        return store.save_draft(conn, action.ticket_id, action.body)
    if tool == "propose_send":
        violations = outbound_violations(action.body)
        if violations:
            return violations[0]
        return store.queue_send(conn, action.ticket_id, action.body)
    if tool == "escalate":
        return store.escalate(conn, action.ticket_id, action.reason or action.body)
    return f"Tool {tool!r} is not allowed."


def render_transcript(goal: str, trace: list[dict]) -> str:
    lines = [f"Goal: {goal}"]
    for step in trace:
        lines.append(f"Tool {step['tool']} -> {step['result']}")
    lines.append("Choose the next tool.")
    return "\n".join(lines)


def run_agent(conn, goal: str, complete, *, step_cap: int = 6, token_cap: int = 12000) -> RunResult:
    if step_cap < 1:
        raise ValueError(f"step_cap must be at least 1, got {step_cap}.")
    trace: list[dict] = []
    prompt_tokens = 0
    output_tokens = 0
    for index in range(step_cap):
        action, usage_prompt, usage_output = complete(goal, trace)
        prompt_tokens += usage_prompt
        output_tokens += usage_output
        if prompt_tokens + output_tokens > token_cap:
            return RunResult(
                final_answer="Stopped because the token cap was reached. No further tools ran.",
                stopped_reason="token_cap",
                trace=trace,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
            )
        if not isinstance(action, Action):
            raise TypeError(f"complete() returned {type(action).__name__}, expected Action.")
        if action.tool == "finish":
            answer = action.final_answer.strip() or "Finished with no summary."
            return RunResult(
                final_answer=answer,
                stopped_reason="finish",
                trace=trace,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
            )
        result = dispatch(action, conn)
        trace.append(
            {
                "step": index + 1,
                "tool": action.tool,
                "ticket_id": action.ticket_id,
                "body": action.body,
                "reason": action.reason,
                "result": result,
                "inputs": {
                    "ticket_id": action.ticket_id,
                    "body": action.body,
                    "reason": action.reason,
                },
                "output": result,
                "prompt_tokens": usage_prompt,
                "output_tokens": usage_output,
                "cumulative_tokens": prompt_tokens + output_tokens,
            }
        )
    return RunResult(
        final_answer="Stopped at the step cap. Check the trace for any queued approval.",
        stopped_reason="step_cap",
        trace=trace,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
    )

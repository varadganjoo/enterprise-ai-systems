"""The number in the answer is the SQLite result, not a sentence the model invented."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.guard import execute_select, validate_sql
from app.metrics import compile_metric
from app.seed import RULES, SCHEMA

SYSTEM = (
    "Prefer a named metric over free-form SQL. "
    "Metrics: open_ticket_count, completed_revenue (start and end as YYYY-MM-DD, end exclusive), "
    "top_customer_by_completed_revenue. "
    "When a metric fits, set metric to its name, set start and end when the metric needs them, and leave sql empty. "
    "Use sql only when no metric fits. sql must be one read-only SELECT. "
    "If the user asks to change data, or the schema cannot answer, set refused to true and leave metric and sql empty. "
    f"Schema: {SCHEMA} "
    f"Rules: {RULES}"
)


class SqlDraft(BaseModel):
    refused: bool = False
    reason: str = ""
    metric: str = ""
    start: str = ""
    end: str = ""
    sql: str = ""


@dataclass
class QueryResult:
    refused: bool
    reason: str
    sql: str
    columns: list[str]
    rows: list[list]
    truncated: bool
    answer: str
    metric: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    ast_validation_ms: float = 0.0
    query_time_ms: float = 0.0
    rows_returned: int = 0


def render_rows(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    if not rows:
        return "The query returned no rows."
    if len(rows) == 1 and len(columns) == 1:
        text = f"{columns[0]} is {rows[0][0]}."
    else:
        lines = [" | ".join(columns)]
        lines.extend(" | ".join("" if cell is None else str(cell) for cell in row) for row in rows)
        text = "\n".join(lines)
    if truncated:
        text += "\nResults truncated to 100 rows."
    return text


def run_question(database, question: str, complete) -> QueryResult:
    draft, prompt_tokens, output_tokens = complete(question)
    if not isinstance(draft, SqlDraft):
        raise TypeError(f"complete() returned {type(draft).__name__}, expected SqlDraft.")
    if draft.metric.strip():
        try:
            compiled = compile_metric(draft.metric, draft.start, draft.end)
            checked = validate_sql(compiled)
        except ValueError as exc:
            return QueryResult(
                refused=True,
                reason=str(exc),
                sql="",
                columns=[],
                rows=[],
                truncated=False,
                answer=str(exc),
                metric=draft.metric.strip(),
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
            )
    elif draft.refused or not draft.sql.strip():
        return QueryResult(
            refused=True,
            reason=draft.reason.strip() or "This question was not run as SQL.",
            sql="",
            columns=[],
            rows=[],
            truncated=False,
            answer=draft.reason.strip() or "I won't query the database for that.",
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )
    else:
        checked = None
    try:
        if not draft.metric.strip():
            checked = validate_sql(draft.sql)
        exec_res = execute_select(database, checked)
        columns, rows, truncated = exec_res.columns, exec_res.rows, exec_res.truncated
        ast_ms = getattr(exec_res, "ast_validation_ms", 0.0)
        query_ms = getattr(exec_res, "query_time_ms", 0.0)
    except Exception as exc:
        return QueryResult(
            refused=True,
            reason=str(exc),
            sql=draft.sql.strip(),
            columns=[],
            rows=[],
            truncated=False,
            answer=f"The query was not executed. {exc}",
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )
    printable = [list(row) for row in rows]
    return QueryResult(
        refused=False,
        reason="",
        sql=checked,
        columns=columns,
        rows=printable,
        truncated=truncated,
        answer=render_rows(columns, rows, truncated),
        metric=draft.metric.strip(),
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        ast_validation_ms=ast_ms,
        query_time_ms=query_ms,
        rows_returned=len(printable),
    )

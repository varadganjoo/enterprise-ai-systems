"""Production-grade SQL AST Guard using sqlglot.

Enforces:
- Single statement only
- Root expression strictly SELECT or UNION of SELECTs
- No forbidden DDL/DML (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA, etc.)
- Table allowlist (customers, orders, order_items, products, tickets)
- Max row limit enforcement (<= 100)
- Read-only SQLite URI execution
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

import sqlglot
import sqlglot.expressions as exp

ALLOWED_TABLES = {"customers", "orders", "order_items", "products", "tickets"}

FORBIDDEN_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Pragma,
    exp.Command,
    exp.Commit,
    exp.Rollback,
    exp.Transaction,
)


class ExecuteResult(tuple):
    """3-tuple subclass for backward compatibility with (columns, rows, truncated)
    while exposing query_time_ms and ast_validation_ms."""

    def __new__(
        cls,
        columns: list[str],
        rows: list[tuple],
        truncated: bool,
        query_time_ms: float = 0.0,
        ast_validation_ms: float = 0.0,
    ):
        instance = super().__new__(cls, (columns, rows, truncated))
        instance.columns = columns
        instance.rows = rows
        instance.truncated = truncated
        instance.query_time_ms = query_time_ms
        instance.ast_validation_ms = ast_validation_ms
        return instance


def _is_select_or_union(expr: exp.Expression) -> bool:
    if isinstance(expr, exp.Select):
        return True
    if isinstance(expr, exp.Union):
        return _is_select_or_union(expr.this) and _is_select_or_union(expr.expression)
    return False


def _enforce_limit(ast: exp.Expression, max_limit: int = 100) -> exp.Expression:
    limit_node = ast.args.get("limit")
    if limit_node is None:
        return ast.limit(max_limit)
    try:
        val = int(limit_node.expression.this)
        if val > max_limit or val < 0:
            return ast.limit(max_limit)
        return ast
    except (ValueError, TypeError, AttributeError):
        return ast.limit(max_limit)


def validate_sql_with_metrics(sql: str, max_limit: int = 100) -> tuple[str, float]:
    """Validates SQL using sqlglot AST parsing and returns (cleaned_sql, validation_time_ms)."""
    if sql is None or not str(sql).strip():
        raise ValueError("SQL is empty.")

    start_time = time.perf_counter()
    raw_sql = str(sql).strip()

    try:
        statements = sqlglot.parse(raw_sql, read="sqlite")
    except Exception as exc:
        raise ValueError(f"Invalid SQL syntax: {exc}") from exc

    if not statements:
        raise ValueError("SQL is empty.")

    if len(statements) > 1:
        raise ValueError(
            f"Only one SQL statement is allowed. Found {len(statements)} statements."
        )

    ast = statements[0]
    if ast is None:
        raise ValueError("SQL is empty.")

    # 1. Verify root expression is strictly Select or Union of Selects
    if not _is_select_or_union(ast):
        raise ValueError(
            f"Only read-only SELECT or UNION queries are allowed. Got root type: {type(ast).__name__}."
        )

    # 2. Verify no forbidden expressions anywhere in the AST
    for node in ast.walk():
        if isinstance(node, FORBIDDEN_EXPRESSIONS):
            raise ValueError(
                f"Forbidden SQL operation: {type(node).__name__} is not on the read-only allowlist."
            )

    # 3. Verify table allowlist (handling CTEs)
    cte_names = {
        cte.alias_or_name.lower()
        for cte in ast.find_all(exp.CTE)
        if (cte.alias or getattr(cte, "alias_or_name", None))
    }
    for table_node in ast.find_all(exp.Table):
        tname = table_node.name.lower() if table_node.name else ""
        if tname and tname not in cte_names and tname not in ALLOWED_TABLES:
            raise ValueError(
                f"Table {tname!r} is not on the allowlist: {sorted(ALLOWED_TABLES)}."
            )

    # 4. Enforce maximum row limit
    ast = _enforce_limit(ast, max_limit=max_limit)

    validation_ms = round((time.perf_counter() - start_time) * 1000, 3)
    return ast.sql("sqlite"), validation_ms


def validate_sql(sql: str) -> str:
    """Validate SQL string using sqlglot AST parser. Returns validated and limit-enforced SQL."""
    checked_sql, _ = validate_sql_with_metrics(sql)
    return checked_sql


def readonly_uri(path: Path) -> str:
    resolved = path.resolve().as_posix()
    return f"file:///{quote(resolved, safe='/:')}?mode=ro"


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(readonly_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def execute_select(
    path: Path, sql: str, limit: int = 100
) -> ExecuteResult:
    checked, ast_ms = validate_sql_with_metrics(sql, max_limit=limit)
    conn = connect_readonly(path)
    start_exec = time.perf_counter()
    try:
        cursor = conn.execute(checked)
        fetched = cursor.fetchmany(limit + 1)
        truncated = len(fetched) > limit
        rows = [tuple(row) for row in fetched[:limit]]
        columns = [item[0] for item in cursor.description] if cursor.description else []
        query_ms = round((time.perf_counter() - start_exec) * 1000, 3)
        return ExecuteResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            query_time_ms=query_ms,
            ast_validation_ms=ast_ms,
        )
    finally:
        conn.close()

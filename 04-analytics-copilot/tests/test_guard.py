import sqlite3
from pathlib import Path

import pytest

from app.copilot import SqlDraft, run_question
from app.guard import (
    ALLOWED_TABLES,
    connect_readonly,
    execute_select,
    validate_sql,
    validate_sql_with_metrics,
)
from app.metrics import compile_metric
from app.seed import seed


def test_rejects_stacked_and_hidden_writes():
    with pytest.raises(ValueError, match="Only one SQL statement is allowed"):
        validate_sql("SELECT 1; DROP TABLE tickets")
    with pytest.raises(ValueError):
        validate_sql("UPDATE tickets SET status = 'closed'")
    with pytest.raises(ValueError):
        validate_sql("INSERT INTO tickets (customer_id, opened_on, status, topic) VALUES (1, '2026-03-01', 'open', 'billing')")
    with pytest.raises(ValueError):
        validate_sql("DELETE FROM tickets")
    with pytest.raises(ValueError):
        validate_sql("DROP TABLE tickets")
    with pytest.raises(ValueError):
        validate_sql("ALTER TABLE tickets ADD COLUMN priority TEXT")
    with pytest.raises(ValueError):
        validate_sql("CREATE TABLE hack (id INT)")
    with pytest.raises(ValueError):
        validate_sql("PRAGMA table_info(tickets)")


def test_rejects_stacked_with_comments():
    with pytest.raises(ValueError, match="Only one SQL statement is allowed"):
        validate_sql("SELECT 1 /* note */ ; DELETE FROM tickets")


def test_allows_clean_comments():
    sql = "SELECT COUNT(*) AS n FROM tickets -- get count\nWHERE status = 'open'"
    validated = validate_sql(sql)
    assert "tickets" in validated.lower()
    assert "count" in validated.lower()


def test_table_allowlist_enforcement():
    # Allowed tables
    assert "customers" in validate_sql("SELECT * FROM customers")
    assert "orders" in validate_sql("SELECT * FROM orders")
    assert "order_items" in validate_sql("SELECT * FROM order_items")
    assert "products" in validate_sql("SELECT * FROM products")
    assert "tickets" in validate_sql("SELECT * FROM tickets")

    # Disallowed tables
    with pytest.raises(ValueError, match="not on the allowlist"):
        validate_sql("SELECT * FROM sqlite_master")
    with pytest.raises(ValueError, match="not on the allowlist"):
        validate_sql("SELECT * FROM sensitive_passwords")
    with pytest.raises(ValueError, match="not on the allowlist"):
        validate_sql("SELECT * FROM customers JOIN secret_salaries ON customers.id = secret_salaries.id")


def test_subqueries_and_ctes():
    # Subquery with disallowed table
    with pytest.raises(ValueError, match="not on the allowlist"):
        validate_sql("SELECT * FROM tickets WHERE customer_id IN (SELECT id FROM admin_users)")

    # CTE with allowed base tables
    cte_sql = "WITH recent AS (SELECT customer_id FROM orders) SELECT * FROM recent"
    assert "recent" in validate_sql(cte_sql).lower()

    # CTE attempting to query disallowed table
    with pytest.raises(ValueError, match="not on the allowlist"):
        validate_sql("WITH bad AS (SELECT * FROM sqlite_master) SELECT * FROM bad")


def test_limit_enforcement():
    # No limit -> inject LIMIT 100
    res1 = validate_sql("SELECT * FROM tickets")
    assert "LIMIT 100" in res1

    # Limit > 100 -> rewrite to LIMIT 100
    res2 = validate_sql("SELECT * FROM tickets LIMIT 500")
    assert "LIMIT 100" in res2
    assert "500" not in res2

    # Limit <= 100 -> preserve
    res3 = validate_sql("SELECT * FROM tickets LIMIT 25")
    assert "LIMIT 25" in res3

    # Union limit
    res4 = validate_sql("SELECT id FROM tickets UNION SELECT id FROM orders")
    assert "LIMIT 100" in res4


def test_union_queries_allowed():
    union_sql = "SELECT id FROM tickets UNION SELECT id FROM orders"
    validated = validate_sql(union_sql)
    assert "UNION" in validated.upper()


def test_validate_sql_with_metrics():
    sql, val_ms = validate_sql_with_metrics("SELECT * FROM tickets LIMIT 10")
    assert "LIMIT 10" in sql
    assert isinstance(val_ms, float)
    assert val_ms >= 0


def test_seed_matches_the_published_figures(tmp_path: Path):
    database = seed(tmp_path / "biz.db")
    exec_res = execute_select(database, "SELECT COUNT(*) FROM tickets WHERE status = 'open'")
    assert exec_res.rows[0][0] == 3
    assert exec_res.ast_validation_ms >= 0
    assert exec_res.query_time_ms >= 0
    # Also test tuple unpacking compatibility
    cols, open_rows, trunc = exec_res
    assert open_rows[0][0] == 3

    march = """
        SELECT SUM(order_items.quantity * order_items.unit_price)
        FROM orders
        JOIN order_items ON order_items.order_id = orders.id
        WHERE orders.status = 'completed'
          AND orders.ordered_on >= '2026-03-01'
          AND orders.ordered_on < '2026-04-01'
    """
    _, revenue, _ = execute_select(database, march)
    assert revenue[0][0] == 400


def test_readonly_uri_blocks_delete(tmp_path: Path):
    database = seed(tmp_path / "biz.db")
    conn = connect_readonly(database)
    with pytest.raises(sqlite3.Error):
        conn.execute("DELETE FROM tickets")
    conn.close()
    _, rows, _ = execute_select(database, "SELECT COUNT(*) FROM tickets")
    assert rows[0][0] == 4


def test_model_write_is_not_executed(tmp_path: Path):
    database = seed(tmp_path / "biz.db")

    def complete(question):
        return SqlDraft(refused=False, sql="DELETE FROM tickets"), 4, 2

    result = run_question(database, "Delete every ticket", complete)
    assert result.refused
    _, rows, _ = execute_select(database, "SELECT COUNT(*) FROM tickets")
    assert rows[0][0] == 4


def test_named_metric_ignores_hostile_sql(tmp_path: Path):
    database = seed(tmp_path / "biz.db")

    def complete(question):
        return SqlDraft(metric="open_ticket_count", sql="DELETE FROM tickets"), 2, 1

    result = run_question(database, "How many tickets are open?", complete)
    assert result.refused is False
    assert result.metric == "open_ticket_count"
    assert result.sql.lower().startswith("select")
    assert result.rows == [[3]]
    assert result.rows_returned == 1
    assert result.ast_validation_ms >= 0
    assert result.query_time_ms >= 0
    _, rows, _ = execute_select(database, "SELECT COUNT(*) FROM tickets")
    assert rows[0][0] == 4


def test_metric_dates_are_not_raw_sql():
    try:
        compile_metric("completed_revenue", "2026-03-01; DROP TABLE tickets", "2026-04-01")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_answer_text_uses_the_executed_cell(tmp_path: Path):
    database = seed(tmp_path / "biz.db")

    def complete(question):
        return SqlDraft(refused=False, sql="SELECT COUNT(*) AS open_tickets FROM tickets WHERE status = 'open'"), 4, 2

    result = run_question(database, "How many tickets are open?", complete)
    assert result.refused is False
    assert "3" in result.answer
    assert result.rows == [[3]]
    assert result.rows_returned == 1

"""Named metrics compile to SQL. The model does not get to invent the definition of revenue."""

from __future__ import annotations

import re

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

OPEN_TICKETS = "SELECT COUNT(*) AS open_tickets FROM tickets WHERE status = 'open'"
TOP_CUSTOMER = """
SELECT customers.name AS name,
       SUM(order_items.quantity * order_items.unit_price) AS revenue
FROM customers
JOIN orders ON orders.customer_id = customers.id
JOIN order_items ON order_items.order_id = orders.id
WHERE orders.status = 'completed'
GROUP BY customers.name
ORDER BY revenue DESC
LIMIT 1
""".strip()

CATALOG = {
    "open_ticket_count": OPEN_TICKETS,
    "top_customer_by_completed_revenue": TOP_CUSTOMER,
}


def compile_metric(name: str, start: str = "", end: str = "") -> str:
    metric = (name or "").strip()
    if metric == "completed_revenue":
        if not DATE.match(start) or not DATE.match(end):
            raise ValueError(
                f"completed_revenue needs start and end as YYYY-MM-DD, got {start!r} and {end!r}."
            )
        if start >= end:
            raise ValueError(f"start {start} must be before end {end}.")
        return (
            "SELECT SUM(order_items.quantity * order_items.unit_price) AS revenue "
            "FROM orders JOIN order_items ON order_items.order_id = orders.id "
            "WHERE orders.status = 'completed' "
            f"AND orders.ordered_on >= '{start}' AND orders.ordered_on < '{end}'"
        )
    sql = CATALOG.get(metric)
    if sql is None:
        known = ", ".join(["completed_revenue", *sorted(CATALOG)])
        raise ValueError(f"Unknown metric {metric!r}. Known metrics: {known}.")
    return sql

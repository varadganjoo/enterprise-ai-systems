"""Business database. Revenue means completed orders only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
customers(id INTEGER, name TEXT, region TEXT)
orders(id INTEGER, customer_id INTEGER, ordered_on TEXT, status TEXT)
order_items(id INTEGER, order_id INTEGER, sku TEXT, quantity INTEGER, unit_price REAL)
tickets(id INTEGER, customer_id INTEGER, opened_on TEXT, status TEXT, topic TEXT)
"""

RULES = (
    "Revenue is the sum of quantity * unit_price on orders whose status is completed. "
    "Cancelled orders are not revenue. Dates are YYYY-MM-DD. "
    "March 2026 is ordered_on >= '2026-03-01' AND ordered_on < '2026-04-01'. "
    "Ticket status is open or closed."
)


def seed(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                ordered_on TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                opened_on TEXT NOT NULL,
                status TEXT NOT NULL,
                topic TEXT NOT NULL
            );
            """
        )
        existing = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO customers (id, name, region) VALUES (?, ?, ?)",
                [(1, "Ada North", "north"), (2, "Ben West", "west"), (3, "Cho East", "east")],
            )
            conn.executemany(
                "INSERT INTO orders (id, customer_id, ordered_on, status) VALUES (?, ?, ?, ?)",
                [
                    (1, 1, "2026-03-02", "completed"),
                    (2, 1, "2026-03-18", "completed"),
                    (3, 2, "2026-03-20", "completed"),
                    (4, 3, "2026-04-02", "completed"),
                    (5, 2, "2026-02-11", "cancelled"),
                ],
            )
            conn.executemany(
                "INSERT INTO order_items (order_id, sku, quantity, unit_price) VALUES (?, ?, ?, ?)",
                [
                    (1, "widget", 2, 50),
                    (2, "gadget", 1, 250),
                    (3, "widget", 1, 50),
                    (4, "gadget", 2, 250),
                    (5, "widget", 4, 50),
                ],
            )
            conn.executemany(
                "INSERT INTO tickets (customer_id, opened_on, status, topic) VALUES (?, ?, ?, ?)",
                [
                    (1, "2026-03-21", "open", "billing"),
                    (2, "2026-03-22", "open", "access"),
                    (3, "2026-03-11", "closed", "shipping"),
                    (1, "2026-04-01", "open", "billing"),
                ],
            )
            conn.commit()
    finally:
        conn.close()
    return path

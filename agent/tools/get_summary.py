"""Tool for getting aggregate expense summaries."""

import json
import os
import sqlite3

from strands import tool

DB_PATH = os.environ.get(
    "EXPENSE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "backend", "expenses.db"),
)


def _get_read_conn():
    """Open a read-only connection to the expenses database."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@tool
def get_summary() -> str:
    """Get a high-level summary of all expense data.

    Returns the total amount spent, number of expense reports,
    and a breakdown of spending by category.
    """
    conn = _get_read_conn()
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM sub_expenses"
        ).fetchone()["total"]

        count = conn.execute(
            "SELECT COUNT(*) as count FROM expense_reports"
        ).fetchone()["count"]

        rows = conn.execute(
            """SELECT se.category, c.display_label, COALESCE(SUM(se.amount), 0) as subtotal
               FROM sub_expenses se
               LEFT JOIN categories c ON c.slug = se.category
               GROUP BY se.category
               ORDER BY subtotal DESC"""
        ).fetchall()

        breakdown = [
            {
                "category": r["category"],
                "display_label": r["display_label"] or r["category"],
                "subtotal": r["subtotal"],
            }
            for r in rows
        ]

        # Also fetch the list of valid categories for context
        cats = conn.execute(
            "SELECT slug, display_label FROM categories ORDER BY sort_order"
        ).fetchall()
        categories = [{"slug": c["slug"], "display_label": c["display_label"]} for c in cats]

        return json.dumps({
            "total": total,
            "report_count": count,
            "breakdown": breakdown,
            "available_categories": categories,
        }, default=str)

    finally:
        conn.close()

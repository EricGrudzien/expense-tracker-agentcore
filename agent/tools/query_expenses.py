"""Tool for querying expenses from the SQLite database."""

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
def query_expenses(
    query_type: str = "sub_expenses",
    category: str = "",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """Query expense data with optional filters.

    Returns sub-expenses or expense reports matching the given filters.
    Results include totals and category breakdowns.

    Args:
        query_type: Either "sub_expenses" (default) for line items, or "reports" for full expense reports.
        category: Filter by category slug (e.g. "airline", "hotel"). Leave empty for all categories. Only applies to sub_expenses mode.
        date_from: Start date filter in YYYY-MM-DD format (inclusive). Leave empty for no start bound.
        date_to: End date filter in YYYY-MM-DD format (inclusive). Leave empty for no end bound.
    """
    conn = _get_read_conn()
    try:
        if query_type == "reports":
            where, params = [], []
            if date_from:
                where.append("er.date >= ?")
                params.append(date_from)
            if date_to:
                where.append("er.date <= ?")
                params.append(date_to)

            sql = "SELECT * FROM expense_reports er"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY er.date DESC, er.created_date DESC"

            reports = conn.execute(sql, params).fetchall()
            result = []
            for r in reports:
                subs = conn.execute(
                    "SELECT * FROM sub_expenses WHERE report_id = ? ORDER BY created_date, id",
                    (r["id"],),
                ).fetchall()
                total = sum(s["amount"] for s in subs)
                result.append({
                    "id": r["id"],
                    "description": r["description"],
                    "date": r["date"],
                    "total": total,
                    "sub_expenses": [
                        {"category": s["category"], "note": s["note"], "amount": s["amount"]}
                        for s in subs
                    ],
                })

            grand_total = sum(r["total"] for r in result)
            return json.dumps({
                "type": "reports",
                "count": len(result),
                "grand_total": grand_total,
                "results": result,
            }, default=str)

        else:
            # sub_expenses mode
            where, params = [], []
            if category:
                where.append("se.category = ?")
                params.append(category.lower())
            if date_from:
                where.append("er.date >= ?")
                params.append(date_from)
            if date_to:
                where.append("er.date <= ?")
                params.append(date_to)

            sql = """
                SELECT se.id, se.report_id, se.category, se.note, se.amount,
                       er.description AS report_description, er.date AS report_date
                FROM sub_expenses se
                JOIN expense_reports er ON er.id = se.report_id
            """
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY er.date DESC, se.category, se.id"

            rows = conn.execute(sql, params).fetchall()
            results = [dict(r) for r in rows]
            grand_total = sum(r["amount"] for r in results)
            breakdown = {}
            for r in results:
                breakdown[r["category"]] = breakdown.get(r["category"], 0) + r["amount"]

            return json.dumps({
                "type": "sub_expenses",
                "count": len(results),
                "grand_total": grand_total,
                "breakdown": breakdown,
                "results": results,
            }, default=str)

    finally:
        conn.close()

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
import re
import json
import logging
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, ReadTimeoutError, ConnectTimeoutError

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")

# ── Bedrock configuration (used by chart builder Lambda) ──────────────────────
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")

# ── AgentCore Runtime configuration ──────────────────────────────────────────
AGENTCORE_RUNTIME_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN")
STATE_FILE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "infra", ".agentcore-state.json"
)


def get_runtime_arn():
    """Resolve the agent runtime ARN from env var or state file."""
    if AGENTCORE_RUNTIME_ARN:
        return AGENTCORE_RUNTIME_ARN
    try:
        with open(STATE_FILE_PATH) as f:
            state = json.load(f)
            return state.get("agent_runtime_arn")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# boto3 client for AgentCore Runtime invocation
_agentcore_boto_config = BotoConfig(
    region_name=BEDROCK_REGION,
    read_timeout=90,
    connect_timeout=10,
    retries={"max_attempts": 1},
)

try:
    agentcore_client = boto3.client("bedrock-agentcore", config=_agentcore_boto_config)
except Exception as e:
    logging.warning(f"Could not create AgentCore client: {e}")
    agentcore_client = None

DEFAULT_CATEGORIES = [
    ("airline",       "Airline",       "✈️",  1),
    ("hotel",         "Hotel",         "🏨",  2),
    ("car",           "Car",           "🚗",  3),
    ("organization",  "Organization",  "🏢",  4),
    ("coach_lessons", "Coach Lessons", "🎓",  5),
    ("slush",         "Slush",         "💧",  6),
    ("admission",     "Admission",     "🎟️", 7),
    ("equipment",     "Equipment",     "🔧",  8),
    ("other",         "Other",         "📦",  9),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with get_db() as conn:
        # ── Categories table ──────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                slug          TEXT PRIMARY KEY,
                display_label TEXT NOT NULL,
                icon          TEXT NOT NULL DEFAULT '',
                sort_order    INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Seed defaults if table is empty
        count = conn.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT INTO categories (slug, display_label, icon, sort_order) VALUES (?, ?, ?, ?)",
                DEFAULT_CATEGORIES,
            )

        # ── Expense reports table ─────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expense_reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                description   TEXT    NOT NULL,
                date          TEXT    NOT NULL,
                created_date  TEXT    NOT NULL,
                modified_date TEXT
            )
        """)

        # ── Sub-expenses table ────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sub_expenses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id     INTEGER NOT NULL REFERENCES expense_reports(id) ON DELETE CASCADE,
                category      TEXT    NOT NULL,
                note          TEXT    NOT NULL DEFAULT '',
                amount        REAL    NOT NULL,
                created_date  TEXT    NOT NULL,
                modified_date TEXT
            )
        """)

        # ── Migrate existing databases ────────────────────────────────────────
        migrations = [
            ("expense_reports", "created_date",  "TEXT"),
            ("expense_reports", "modified_date", "TEXT"),
            ("sub_expenses",    "created_date",  "TEXT"),
            ("sub_expenses",    "modified_date", "TEXT"),
        ]
        for table, column, col_type in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except Exception:
                pass

        # Back-fill created_date from legacy created_at
        for table in ("expense_reports", "sub_expenses"):
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "created_at" in cols:
                conn.execute(f"""
                    UPDATE {table}
                    SET created_date = created_at
                    WHERE created_date IS NULL AND created_at IS NOT NULL
                """)

        conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_valid_slugs(conn):
    """Return the set of valid category slugs from the DB."""
    rows = conn.execute("SELECT slug FROM categories").fetchall()
    return {r["slug"] for r in rows}


def report_with_subs(conn, report_id):
    report = conn.execute(
        "SELECT * FROM expense_reports WHERE id = ?", (report_id,)
    ).fetchone()
    if not report:
        return None
    subs = conn.execute(
        "SELECT * FROM sub_expenses WHERE report_id = ? ORDER BY created_date, id",
        (report_id,),
    ).fetchall()
    total = sum(s["amount"] for s in subs)
    return {**dict(report), "total": total, "sub_expenses": [dict(s) for s in subs]}


def validate_date(date_str):
    if not date_str:
        return "Date is required"
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return "Date must be in YYYY-MM-DD format"
    return None


# ── Categories ────────────────────────────────────────────────────────────────

@app.route("/api/categories", methods=["GET"])
def get_categories():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, slug"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/categories", methods=["POST"])
def add_category():
    data = request.get_json()
    slug          = (data.get("slug") or "").strip().lower()
    display_label = (data.get("display_label") or "").strip()
    icon          = (data.get("icon") or "").strip()

    if not slug:
        return jsonify({"error": "Slug is required"}), 400
    if not re.match(r'^[a-z][a-z0-9_]*$', slug):
        return jsonify({"error": "Slug must start with a letter and contain only lowercase letters, numbers, and underscores"}), 400
    if not display_label:
        return jsonify({"error": "Display label is required"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT slug FROM categories WHERE slug = ?", (slug,)).fetchone()
        if existing:
            return jsonify({"error": f"Category '{slug}' already exists"}), 409

        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) as m FROM categories").fetchone()["m"]
        conn.execute(
            "INSERT INTO categories (slug, display_label, icon, sort_order) VALUES (?, ?, ?, ?)",
            (slug, display_label, icon, max_order + 1),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()

    return jsonify(dict(row)), 201


@app.route("/api/categories/<slug>", methods=["PUT"])
def update_category(slug):
    data = request.get_json()
    display_label = (data.get("display_label") or "").strip()
    icon          = (data.get("icon") or "").strip()

    if not display_label:
        return jsonify({"error": "Display label is required"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT slug FROM categories WHERE slug = ?", (slug,)).fetchone()
        if not existing:
            return jsonify({"error": "Category not found"}), 404

        conn.execute(
            "UPDATE categories SET display_label = ?, icon = ? WHERE slug = ?",
            (display_label, icon, slug),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()

    return jsonify(dict(row)), 200


# ── Expense Reports ───────────────────────────────────────────────────────────

@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    with get_db() as conn:
        reports = conn.execute(
            "SELECT * FROM expense_reports ORDER BY date DESC, created_date DESC"
        ).fetchall()
        result = []
        for r in reports:
            subs = conn.execute(
                "SELECT * FROM sub_expenses WHERE report_id = ? ORDER BY created_date, id",
                (r["id"],),
            ).fetchall()
            total = sum(s["amount"] for s in subs)
            result.append({**dict(r), "total": total, "sub_expenses": [dict(s) for s in subs]})
    return jsonify(result)


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    data = request.get_json()
    description = (data.get("description") or "").strip()
    date = (data.get("date") or "").strip()

    if not description:
        return jsonify({"error": "Description is required"}), 400
    err = validate_date(date)
    if err:
        return jsonify({"error": err}), 400

    ts = now_utc()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO expense_reports
               (description, date, created_at, created_date)
               VALUES (?, ?, ?, ?)""",
            (description, date, ts, ts),
        )
        conn.commit()
        row = report_with_subs(conn, cursor.lastrowid)
    return jsonify(row), 201


@app.route("/api/expenses/<int:report_id>", methods=["PUT"])
def update_expense(report_id):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM expense_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Expense report not found"}), 404

        data = request.get_json()
        description = (data.get("description") or "").strip()
        date = (data.get("date") or "").strip()

        if not description:
            return jsonify({"error": "Description is required"}), 400
        err = validate_date(date)
        if err:
            return jsonify({"error": err}), 400

        ts = now_utc()
        valid_slugs = get_valid_slugs(conn)

        conn.execute(
            "UPDATE expense_reports SET description = ?, date = ?, modified_date = ? WHERE id = ?",
            (description, date, ts, report_id),
        )

        sub_updates = data.get("sub_expenses")
        if sub_updates is not None:
            for sub in sub_updates:
                sub_id   = sub.get("id")
                category = (sub.get("category") or "").strip().lower()
                note     = (sub.get("note") or "").strip()
                amount   = sub.get("amount")

                if not sub_id:
                    continue
                if category not in valid_slugs:
                    return jsonify({"error": f"Invalid category '{category}' for sub-expense {sub_id}"}), 400
                try:
                    amount = float(amount)
                    if amount <= 0:
                        return jsonify({"error": f"Amount must be > 0 for sub-expense {sub_id}"}), 400
                except (ValueError, TypeError):
                    return jsonify({"error": f"Invalid amount for sub-expense {sub_id}"}), 400

                conn.execute(
                    """UPDATE sub_expenses
                       SET category = ?, note = ?, amount = ?, modified_date = ?
                       WHERE id = ? AND report_id = ?""",
                    (category, note, amount, ts, sub_id, report_id),
                )

        conn.commit()
        updated = report_with_subs(conn, report_id)
    return jsonify(updated), 200


@app.route("/api/expenses/<int:report_id>", methods=["DELETE"])
def delete_expense(report_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM expense_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Expense report not found"}), 404
        conn.execute("DELETE FROM expense_reports WHERE id = ?", (report_id,))
        conn.commit()
    return jsonify({"message": "Expense report deleted"}), 200


# ── Sub-Expenses ──────────────────────────────────────────────────────────────

@app.route("/api/expenses/<int:report_id>/sub_expenses", methods=["POST"])
def add_sub_expense(report_id):
    with get_db() as conn:
        report = conn.execute(
            "SELECT id FROM expense_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not report:
            return jsonify({"error": "Expense report not found"}), 404

        data = request.get_json()
        category = (data.get("category") or "").strip().lower()
        note     = (data.get("note") or "").strip()
        amount   = data.get("amount")

        valid_slugs = get_valid_slugs(conn)
        if category not in valid_slugs:
            return jsonify({"error": f"Invalid category. Must be one of: {', '.join(sorted(valid_slugs))}"}), 400
        try:
            amount = float(amount)
            if amount <= 0:
                return jsonify({"error": "Amount must be greater than zero"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Amount must be a valid number"}), 400

        ts = now_utc()
        conn.execute(
            """INSERT INTO sub_expenses
               (report_id, category, note, amount, created_at, created_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, category, note, amount, ts, ts),
        )
        conn.execute(
            "UPDATE expense_reports SET modified_date = ? WHERE id = ?",
            (ts, report_id),
        )
        conn.commit()
        row = report_with_subs(conn, report_id)
    return jsonify(row), 201


@app.route("/api/expenses/<int:report_id>/sub_expenses/<int:sub_id>", methods=["DELETE"])
def delete_sub_expense(report_id, sub_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM sub_expenses WHERE id = ? AND report_id = ?",
            (sub_id, report_id),
        ).fetchone()
        if not row:
            return jsonify({"error": "Sub-expense not found"}), 404

        ts = now_utc()
        conn.execute("DELETE FROM sub_expenses WHERE id = ?", (sub_id,))
        conn.execute(
            "UPDATE expense_reports SET modified_date = ? WHERE id = ?",
            (ts, report_id),
        )
        conn.commit()
        updated = report_with_subs(conn, report_id)
    return jsonify(updated), 200


# ── Query ─────────────────────────────────────────────────────────────────────

@app.route("/api/query", methods=["GET"])
def query_expenses():
    qtype     = request.args.get("type", "sub_expenses").strip().lower()
    category  = (request.args.get("category") or "").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to   = (request.args.get("date_to") or "").strip()

    for label, val in (("date_from", date_from), ("date_to", date_to)):
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": f"{label} must be YYYY-MM-DD"}), 400

    with get_db() as conn:
        valid_slugs = get_valid_slugs(conn)

        if qtype == "reports":
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
                result.append({**dict(r), "total": total, "sub_expenses": [dict(s) for s in subs]})

            grand_total = sum(r["total"] for r in result)
            return jsonify({"type": "reports", "results": result, "grand_total": grand_total})

        else:
            where, params = [], []
            if category:
                if category not in valid_slugs:
                    return jsonify({"error": f"Invalid category. Must be one of: {', '.join(sorted(valid_slugs))}"}), 400
                where.append("se.category = ?")
                params.append(category)
            if date_from:
                where.append("er.date >= ?")
                params.append(date_from)
            if date_to:
                where.append("er.date <= ?")
                params.append(date_to)

            sql = """
                SELECT se.id, se.report_id, se.category, se.note, se.amount,
                       se.created_date, se.modified_date,
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

            return jsonify({
                "type": "sub_expenses",
                "results": results,
                "grand_total": grand_total,
                "breakdown": breakdown,
            })


# ── Chat (Bedrock) ────────────────────────────────────────────────────────────

DB_SCHEMA_TEXT = """
Tables in the SQLite database:

1. categories
   - slug          TEXT PRIMARY KEY   -- e.g. 'airline', 'hotel'
   - display_label TEXT NOT NULL      -- human-readable name
   - icon          TEXT               -- emoji icon
   - sort_order    INTEGER            -- display ordering

2. expense_reports
   - id            INTEGER PRIMARY KEY AUTOINCREMENT
   - description   TEXT NOT NULL      -- name of the expense report
   - date          TEXT NOT NULL      -- report date in 'YYYY-MM-DD' format
   - created_date  TEXT               -- UTC ISO-8601 timestamp
   - modified_date TEXT               -- UTC ISO-8601 timestamp, NULL until first edit

3. sub_expenses
   - id            INTEGER PRIMARY KEY AUTOINCREMENT
   - report_id     INTEGER NOT NULL   -- FK → expense_reports(id)
   - category      TEXT NOT NULL      -- FK-like reference to categories.slug
   - note          TEXT               -- optional note
   - amount        REAL NOT NULL      -- dollar amount, always > 0
   - created_date  TEXT               -- UTC ISO-8601 timestamp
   - modified_date TEXT               -- UTC ISO-8601 timestamp

Relationships:
- sub_expenses.report_id → expense_reports.id (ON DELETE CASCADE)
- sub_expenses.category matches categories.slug
- A report's total is NOT stored; it is SUM(sub_expenses.amount) for that report.
""".strip()


# ── Chart builder (calls egru-chart-builder Lambda) ───────────────────────────

CHART_BUILDER_LAMBDA = os.environ.get("CHART_BUILDER_LAMBDA", "egru-chart-builder")


def build_chart(instruction, data):
    """
    Call the chart-builder Lambda to produce a Chart.js config.

    Args:
        instruction: dict with chartType, title, labelField, valueField
        data: list of dicts (query results)

    Returns:
        Chart.js config dict, or None on error.
    """
    payload = {
        "chartType": instruction.get("chartType", "bar"),
        "title": instruction.get("title", "Chart"),
        "labelField": instruction.get("labelField", ""),
        "valueField": instruction.get("valueField", ""),
        "data": data,
    }

    try:
        lambda_client = boto3.client("lambda", region_name=BEDROCK_REGION)
        resp = lambda_client.invoke(
            FunctionName=CHART_BUILDER_LAMBDA,
            Payload=json.dumps(payload).encode(),
        )
        result = json.loads(resp["Payload"].read())

        if result.get("error"):
            logging.warning(f"Chart build error: {result['error']}")
            return None

        return result.get("chart")
    except Exception as e:
        logging.warning(f"Chart build exception: {e}")
        return None


# ── Chat route (proxies to AgentCore Runtime) ────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Chat endpoint. Proxies requests to the Strands Agent running on
    AgentCore Runtime. Returns the agent's response in a format compatible
    with the frontend chat UI.
    """
    data = request.get_json()
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is required"}), 400
    if len(message) > 1000:
        return jsonify({"error": "Message must be 1000 characters or fewer"}), 400

    # Resolve runtime ARN
    runtime_arn = get_runtime_arn()
    if not runtime_arn:
        return jsonify({"error": "Agent runtime not configured"}), 503

    if not agentcore_client:
        return jsonify({"error": "Agent runtime client not available"}), 503

    # Invoke the agent
    try:
        session_id = str(uuid.uuid4())
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            payload=json.dumps({"prompt": message}).encode(),
        )

        # Parse response body
        body = json.loads(response["response"].read())
        answer = body.get("answer", body.get("result", ""))
        chart = body.get("chart")

        return jsonify({
            "answer": answer,
            "sql": None,
            "data": None,
            "chart": chart,
        })

    except (ReadTimeoutError, ConnectTimeoutError, ConnectionError):
        return jsonify({"error": "Agent service unavailable"}), 502
    except ClientError as e:
        logging.error(f"AgentCore invocation error: {e}")
        return jsonify({"error": "Agent returned an error"}), 502
    except Exception as e:
        logging.error(f"Unexpected chat error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# ── Summary ───────────────────────────────────────────────────────────────────

@app.route("/api/summary", methods=["GET"])
def get_summary():
    with get_db() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM sub_expenses"
        ).fetchone()["total"]
        count = conn.execute(
            "SELECT COUNT(*) as count FROM expense_reports"
        ).fetchone()["count"]
        rows = conn.execute(
            "SELECT category, COALESCE(SUM(amount), 0) as subtotal FROM sub_expenses GROUP BY category"
        ).fetchall()
        breakdown = {r["category"]: r["subtotal"] for r in rows}
    return jsonify({"total": total, "count": count, "breakdown": breakdown})


if __name__ == "__main__":
    init_db()

    # Startup validation: warn if agent runtime is not configured
    runtime_arn = get_runtime_arn()
    if not runtime_arn:
        logging.warning(
            "AGENTCORE_RUNTIME_ARN not set and state file not found. "
            "Chat endpoint will return 503 until configured."
        )

    app.run(debug=True, port=5000)

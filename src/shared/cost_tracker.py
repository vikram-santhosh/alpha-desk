"""API cost tracking with daily cap enforcement.

Tracks Anthropic API usage costs per day and enforces the daily spending cap.
Costs are stored in a SQLite database for persistence across runs.
"""

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path("data/cost_tracker.db")

# Opus 4.6 pricing (per million tokens)
OPUS_INPUT_COST_PER_MTOK = 15.0
OPUS_OUTPUT_COST_PER_MTOK = 75.0

DEFAULT_DAILY_CAP = 20.0


def _get_db() -> sqlite3.Connection:
    """Get or create the cost tracking database."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            agent TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def record_usage(
    agent: str, input_tokens: int, output_tokens: int
) -> float:
    """Record an API call's token usage and cost.

    Args:
        agent: Name of the agent making the call.
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens used.

    Returns:
        Cost in USD for this call.
    """
    cost = (
        input_tokens / 1_000_000 * OPUS_INPUT_COST_PER_MTOK
        + output_tokens / 1_000_000 * OPUS_OUTPUT_COST_PER_MTOK
    )

    conn = _get_db()
    conn.execute(
        "INSERT INTO api_costs (timestamp, date, agent, input_tokens, output_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), date.today().isoformat(), agent, input_tokens, output_tokens, cost),
    )
    conn.commit()
    conn.close()

    log.info("Cost recorded: %s — $%.4f (%d in, %d out)", agent, cost, input_tokens, output_tokens)
    return cost


def get_daily_cost(day: date | None = None) -> float:
    """Get total cost for a given day (defaults to today)."""
    day = day or date.today()
    conn = _get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE date = ?",
        (day.isoformat(),),
    ).fetchone()
    conn.close()
    return row[0]


def get_daily_breakdown(day: date | None = None) -> list[dict]:
    """Get per-agent cost breakdown for a given day."""
    day = day or date.today()
    conn = _get_db()
    rows = conn.execute(
        "SELECT agent, SUM(input_tokens), SUM(output_tokens), SUM(cost_usd), COUNT(*) FROM api_costs WHERE date = ? GROUP BY agent",
        (day.isoformat(),),
    ).fetchall()
    conn.close()
    return [
        {"agent": r[0], "input_tokens": r[1], "output_tokens": r[2], "cost_usd": r[3], "calls": r[4]}
        for r in rows
    ]


def check_budget() -> tuple[bool, float, float]:
    """Check if we're within the daily budget.

    Returns:
        (within_budget, spent_today, daily_cap)
    """
    cap = float(os.getenv("DAILY_COST_CAP", str(DEFAULT_DAILY_CAP)))
    spent = get_daily_cost()
    return spent < cap, spent, cap


def format_cost_report() -> str:
    """Generate a formatted cost report for today."""
    within_budget, spent, cap = check_budget()
    breakdown = get_daily_breakdown()

    lines = [f"<b>API Cost Report — {date.today()}</b>"]
    lines.append(f"Total: <b>${spent:.2f}</b> / ${cap:.2f}")

    if breakdown:
        lines.append("")
        for entry in breakdown:
            lines.append(
                f"  {entry['agent']}: ${entry['cost_usd']:.2f} ({entry['calls']} calls)"
            )

    if not within_budget:
        lines.append("\n<b>BUDGET EXCEEDED — pausing API calls</b>")

    return "\n".join(lines)

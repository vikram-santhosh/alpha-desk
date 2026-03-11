"""API cost tracking with daily cap enforcement.

Tracks LLM API usage costs per day and enforces the daily spending cap.
Costs are stored in a SQLite database for persistence across runs.
"""
from __future__ import annotations

import contextvars
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "cost_tracker.db"

# Pricing per million tokens by model family
MODEL_PRICING = {
    # Gemini models
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    # Legacy names retained for historical DB entries
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
}
# Default to gemini-2.5-pro pricing for unknown models
DEFAULT_PRICING = {"input": 1.25, "output": 10.0}

DEFAULT_DAILY_CAP = 20.0
CURRENT_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("alphadesk_run_id", default=None)
CURRENT_RUN_BUDGET: contextvars.ContextVar[float | None] = contextvars.ContextVar("alphadesk_run_budget", default=None)


def _load_daily_cap() -> float:
    env_cap = os.getenv("DAILY_COST_CAP")
    if env_cap:
        try:
            return float(env_cap)
        except ValueError:
            log.warning("Invalid DAILY_COST_CAP=%r; falling back to config/default", env_cap)

    try:
        from src.shared.config_loader import load_config

        schedule = (load_config("advisor") or {}).get("schedule", {})
        configured = schedule.get("daily_cost_cap")
        if configured is not None:
            return float(configured)
    except Exception:
        log.debug("Unable to load daily cost cap from advisor config", exc_info=True)

    return DEFAULT_DAILY_CAP


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
    # Add run_id column if it doesn't exist (schema migration)
    try:
        conn.execute("SELECT run_id FROM api_costs LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE api_costs ADD COLUMN run_id TEXT")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_costs_date
        ON api_costs (date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_costs_run_id
        ON api_costs (run_id)
    """)
    conn.commit()
    return conn


def set_run_context(run_id: str | None = None, run_budget: float | None = None) -> tuple[contextvars.Token, contextvars.Token]:
    """Bind run metadata to the current context."""
    return CURRENT_RUN_ID.set(run_id), CURRENT_RUN_BUDGET.set(run_budget)


def reset_run_context(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    """Restore the previous run metadata context."""
    run_id_token, run_budget_token = tokens
    CURRENT_RUN_ID.reset(run_id_token)
    CURRENT_RUN_BUDGET.reset(run_budget_token)


def get_current_run_id() -> str | None:
    """Return the active run identifier, if any."""
    return CURRENT_RUN_ID.get()


def get_current_run_budget() -> float | None:
    """Return the active per-run budget, if any."""
    return CURRENT_RUN_BUDGET.get()


def _get_pricing(model: str | None) -> dict[str, float]:
    """Look up pricing for a model, falling back to default."""
    if model is None:
        return DEFAULT_PRICING
    # Try exact match first, then prefix match for versioned model IDs
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, pricing in MODEL_PRICING.items():
        if model.startswith(key):
            return pricing
    return DEFAULT_PRICING


def record_usage(
    agent: str, input_tokens: int, output_tokens: int, model: str | None = None, run_id: str | None = None
) -> float:
    """Record an API call's token usage and cost.

    Args:
        agent: Name of the agent making the call.
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens used.
        model: Model ID used for the call (for accurate pricing).
        run_id: Run identifier to attribute this cost to a specific run.

    Returns:
        Cost in USD for this call.
    """
    pricing = _get_pricing(model)
    cost = (
        input_tokens / 1_000_000 * pricing["input"]
        + output_tokens / 1_000_000 * pricing["output"]
    )
    resolved_run_id = run_id or get_current_run_id()

    conn = _get_db()
    conn.execute(
        "INSERT INTO api_costs (timestamp, date, agent, input_tokens, output_tokens, cost_usd, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), date.today().isoformat(), agent, input_tokens, output_tokens, cost, resolved_run_id),
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


def get_run_cost(run_id: str | None = None) -> float:
    """Get total cost for a specific run."""
    resolved_run_id = run_id or get_current_run_id()
    if not resolved_run_id:
        return 0.0
    conn = _get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE run_id = ?",
        (resolved_run_id,),
    ).fetchone()
    conn.close()
    return row[0] if row else 0.0


def check_budget(run_budget: float | None = None) -> tuple[bool, float, float]:
    """Check whether we are within the active run or daily budget.

    Returns:
        (within_budget, spent, cap) for the active gating limit.
    """
    daily_cap = _load_daily_cap()
    spent_today = get_daily_cost()
    active_run_budget = run_budget if run_budget is not None else get_current_run_budget()

    if active_run_budget is not None and get_current_run_id():
        run_spent = get_run_cost()
        if run_spent >= active_run_budget:
            return False, run_spent, active_run_budget
        if spent_today >= daily_cap:
            return False, spent_today, daily_cap
        return True, run_spent, active_run_budget

    return spent_today < daily_cap, spent_today, daily_cap


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

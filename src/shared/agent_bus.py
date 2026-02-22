"""Agent Bus — SQLite-based pub/sub for inter-agent signal passing.

Agents publish signals to the bus; other agents consume them.
This enables loose coupling between the Street Ear, Portfolio Analyst,
and News Desk agents.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path("data/agent_bus.db")

# Valid signal types
SIGNAL_TYPES = {
    # Street Ear signals
    "unusual_mentions",
    "sentiment_reversal",
    "narrative_forming",
    "multi_sub_convergence",
    # News Desk signals
    "breaking_news",
    "earnings_approaching",
    "sector_news",
    # Portfolio Analyst signals
    "technical_signal",
    "concentration_warning",
    "fundamental_alert",
}


def _get_db() -> sqlite3.Connection:
    """Get or create the agent bus database."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            source_agent TEXT NOT NULL,
            payload TEXT NOT NULL,
            consumed INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_type_consumed
        ON signals (signal_type, consumed)
    """)
    conn.commit()
    return conn


def publish(signal_type: str, source_agent: str, payload: dict[str, Any]) -> int:
    """Publish a signal to the agent bus.

    Args:
        signal_type: One of the defined SIGNAL_TYPES.
        source_agent: Name of the publishing agent.
        payload: Signal data as a dict.

    Returns:
        The signal ID.

    Raises:
        ValueError: If signal_type is not recognized.
    """
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"Unknown signal type: {signal_type}. Valid: {SIGNAL_TYPES}")

    conn = _get_db()
    cursor = conn.execute(
        "INSERT INTO signals (timestamp, signal_type, source_agent, payload) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), signal_type, source_agent, json.dumps(payload)),
    )
    signal_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log.info("Signal published: %s from %s (id=%d)", signal_type, source_agent, signal_id)
    return signal_id


def consume(
    signal_type: str | None = None,
    source_agent: str | None = None,
    mark_consumed: bool = True,
) -> list[dict[str, Any]]:
    """Consume signals from the bus.

    Args:
        signal_type: Filter by signal type (optional).
        source_agent: Filter by source agent (optional).
        mark_consumed: Whether to mark signals as consumed after reading.

    Returns:
        List of signal dicts with id, timestamp, signal_type, source_agent, payload.
    """
    conn = _get_db()

    query = "SELECT id, timestamp, signal_type, source_agent, payload FROM signals WHERE consumed = 0"
    params: list[Any] = []

    if signal_type:
        query += " AND signal_type = ?"
        params.append(signal_type)
    if source_agent:
        query += " AND source_agent = ?"
        params.append(source_agent)

    query += " ORDER BY timestamp ASC"
    rows = conn.execute(query, params).fetchall()

    signals = []
    for row in rows:
        signals.append({
            "id": row[0],
            "timestamp": row[1],
            "signal_type": row[2],
            "source_agent": row[3],
            "payload": json.loads(row[4]),
        })

    if mark_consumed and signals:
        ids = [s["id"] for s in signals]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"UPDATE signals SET consumed = 1 WHERE id IN ({placeholders})", ids)
        conn.commit()

    conn.close()

    log.info(
        "Consumed %d signals (type=%s, source=%s)",
        len(signals),
        signal_type or "any",
        source_agent or "any",
    )
    return signals


def get_recent_signals(limit: int = 50) -> list[dict[str, Any]]:
    """Get the most recent signals regardless of consumed status."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, timestamp, signal_type, source_agent, payload, consumed FROM signals ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "signal_type": r[2],
            "source_agent": r[3],
            "payload": json.loads(r[4]),
            "consumed": bool(r[5]),
        }
        for r in rows
    ]


def clear_old_signals(days: int = 7) -> int:
    """Remove signals older than the specified number of days."""
    conn = _get_db()
    cursor = conn.execute(
        "DELETE FROM signals WHERE timestamp < datetime('now', ?)",
        (f"-{days} days",),
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    log.info("Cleared %d signals older than %d days", deleted, days)
    return deleted

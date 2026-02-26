"""Thesis and macro signal tracker for Substack Ear.

Maintains a SQLite database of extracted investment theses and macro signals.
Publishes expert signals to the agent bus.
"""

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path("data/substack_tracker.db")
AGENT_NAME = "substack_ear"


def _get_db() -> sqlite3.Connection:
    """Get or create the Substack Ear tracker database."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS theses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            source TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            affected_tickers TEXT NOT NULL DEFAULT '[]',
            conviction TEXT NOT NULL DEFAULT 'medium',
            time_horizon TEXT NOT NULL DEFAULT 'medium_term',
            contrarian INTEGER NOT NULL DEFAULT 0,
            propagation_stage TEXT NOT NULL DEFAULT 'expert'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_theses_date
        ON theses (date)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            source TEXT NOT NULL,
            indicator TEXT NOT NULL,
            implication TEXT NOT NULL,
            affected_sectors TEXT NOT NULL DEFAULT '[]'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_macro_signals_date
        ON macro_signals (date)
    """)

    conn.commit()
    return conn


def record_theses(analysis: dict[str, Any]) -> None:
    """Store extracted investment theses in the database.

    Args:
        analysis: Aggregated analysis dict from analyzer.analyze_articles().
    """
    theses = analysis.get("theses", [])
    if not theses:
        log.info("No theses to record")
        return

    today = date.today().isoformat()
    conn = _get_db()

    try:
        for thesis in theses:
            conn.execute("""
                INSERT INTO theses (date, source, author, title, summary,
                    affected_tickers, conviction, time_horizon, contrarian,
                    propagation_stage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today,
                AGENT_NAME,
                thesis.get("author", ""),
                thesis.get("title", "Untitled"),
                thesis.get("summary", ""),
                json.dumps(thesis.get("affected_tickers", [])),
                thesis.get("conviction", "medium"),
                thesis.get("time_horizon", "medium_term"),
                1 if thesis.get("contrarian", False) else 0,
                "expert",
            ))

        conn.commit()
        log.info("Recorded %d theses", len(theses))
    except sqlite3.Error as e:
        log.error("Database error recording theses: %s", e)
        conn.rollback()
    finally:
        conn.close()


def record_macro_signals(analysis: dict[str, Any]) -> None:
    """Store extracted macro signals in the database.

    Args:
        analysis: Aggregated analysis dict from analyzer.analyze_articles().
    """
    signals = analysis.get("macro_signals", [])
    if not signals:
        log.info("No macro signals to record")
        return

    today = date.today().isoformat()
    conn = _get_db()

    try:
        for signal in signals:
            conn.execute("""
                INSERT INTO macro_signals (date, source, indicator, implication, affected_sectors)
                VALUES (?, ?, ?, ?, ?)
            """, (
                today,
                AGENT_NAME,
                signal.get("indicator", ""),
                signal.get("implication", ""),
                json.dumps(signal.get("affected_sectors", [])),
            ))

        conn.commit()
        log.info("Recorded %d macro signals", len(signals))
    except sqlite3.Error as e:
        log.error("Database error recording macro signals: %s", e)
        conn.rollback()
    finally:
        conn.close()


def get_recent_theses(days: int = 7) -> list[dict[str, Any]]:
    """Return recent investment theses from the database.

    Args:
        days: Number of days to look back.

    Returns:
        List of thesis dicts.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_db()

    rows = conn.execute("""
        SELECT id, date, source, author, title, summary, affected_tickers,
               conviction, time_horizon, contrarian, propagation_stage
        FROM theses
        WHERE date >= ?
        ORDER BY date DESC
    """, (start_date,)).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "date": r[1],
            "source": r[2],
            "author": r[3],
            "title": r[4],
            "summary": r[5],
            "affected_tickers": json.loads(r[6]),
            "conviction": r[7],
            "time_horizon": r[8],
            "contrarian": bool(r[9]),
            "propagation_stage": r[10],
        }
        for r in rows
    ]


def get_recent_macro_signals(days: int = 7) -> list[dict[str, Any]]:
    """Return recent macro signals from the database.

    Args:
        days: Number of days to look back.

    Returns:
        List of macro signal dicts.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_db()

    rows = conn.execute("""
        SELECT id, date, source, indicator, implication, affected_sectors
        FROM macro_signals
        WHERE date >= ?
        ORDER BY date DESC
    """, (start_date,)).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "date": r[1],
            "source": r[2],
            "indicator": r[3],
            "implication": r[4],
            "affected_sectors": json.loads(r[5]),
        }
        for r in rows
    ]


def publish_thesis_signals(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Publish expert thesis signals to the agent bus.

    Publishes three signal types:
    - expert_thesis: For each investment thesis with high/medium conviction
    - macro_framework: For each macro signal
    - sector_rotation_call: For theses mentioning sector shifts

    Args:
        analysis: Aggregated analysis dict from analyzer.

    Returns:
        List of published signal payloads.
    """
    published: list[dict[str, Any]] = []

    # Publish expert thesis signals
    for thesis in analysis.get("theses", []):
        conviction = thesis.get("conviction", "medium")
        if conviction in ("high", "medium"):
            payload = {
                "title": thesis.get("title", ""),
                "summary": thesis.get("summary", ""),
                "affected_tickers": thesis.get("affected_tickers", []),
                "conviction": conviction,
                "time_horizon": thesis.get("time_horizon", "medium_term"),
                "contrarian": thesis.get("contrarian", False),
            }
            publish(
                signal_type="expert_thesis",
                source_agent=AGENT_NAME,
                payload=payload,
            )
            published.append({"type": "expert_thesis", **payload})
            log.info(
                "Published expert_thesis: %s (conviction=%s)",
                thesis.get("title", ""), conviction,
            )

    # Publish macro framework signals
    for signal in analysis.get("macro_signals", []):
        payload = {
            "indicator": signal.get("indicator", ""),
            "implication": signal.get("implication", ""),
            "affected_sectors": signal.get("affected_sectors", []),
        }
        publish(
            signal_type="macro_framework",
            source_agent=AGENT_NAME,
            payload=payload,
        )
        published.append({"type": "macro_framework", **payload})
        log.info("Published macro_framework: %s", signal.get("indicator", ""))

    # Publish sector rotation signals for theses with sector-level implications
    for thesis in analysis.get("theses", []):
        themes = thesis.get("themes", []) if "themes" in thesis else []
        title_lower = thesis.get("title", "").lower()
        summary_lower = thesis.get("summary", "").lower()

        sector_keywords = {"sector", "rotation", "shift", "rebalance", "cyclical", "defensive"}
        has_sector_signal = any(
            kw in title_lower or kw in summary_lower
            for kw in sector_keywords
        )

        if has_sector_signal:
            payload = {
                "title": thesis.get("title", ""),
                "affected_tickers": thesis.get("affected_tickers", []),
                "conviction": thesis.get("conviction", "medium"),
            }
            publish(
                signal_type="sector_rotation_call",
                source_agent=AGENT_NAME,
                payload=payload,
            )
            published.append({"type": "sector_rotation_call", **payload})
            log.info("Published sector_rotation_call: %s", thesis.get("title", ""))

    # Record narratives in the cross-source narrative tracker
    try:
        from src.shared.narrative_tracker import record_narrative

        for thesis in analysis.get("theses", []):
            title = thesis.get("title", "")
            tickers = thesis.get("affected_tickers", [])
            conviction = thesis.get("conviction", "medium")
            if title and tickers:
                record_narrative(
                    narrative=title,
                    source_platform="substack",
                    source_detail=AGENT_NAME,
                    affected_tickers=tickers,
                    conviction=conviction,
                )
        log.info("Recorded narratives in narrative tracker")
    except Exception as e:
        log.warning("Failed to record narratives in tracker: %s", e)

    log.info("Published %d signals total", len(published))
    return published

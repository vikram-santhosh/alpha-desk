"""Rolling mention tracker and anomaly detector for Street Ear.

Maintains a SQLite database of ticker mention history and narrative tracking.
Detects anomalies such as unusual mention spikes, sentiment reversals, and
multi-subreddit convergence. Publishes signals to the agent bus.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "street_ear_tracker.db"
AGENT_NAME = "street_ear"

# Anomaly detection thresholds
MENTION_SPIKE_MULTIPLIER = 2.0  # Flag if mentions > 2x 7-day average
CONVERGENCE_MIN_SUBS = 3  # Flag if mentioned in 3+ subreddits


def _get_db() -> sqlite3.Connection:
    """Get or create the Street Ear tracker database.

    Returns:
        SQLite connection with tables created if needed.
    """
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS mention_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            avg_sentiment REAL NOT NULL,
            subreddits TEXT NOT NULL,
            UNIQUE(ticker, date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mention_ticker_date
        ON mention_history (ticker, date)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS narratives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            narrative_text TEXT NOT NULL,
            source_posts INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_narratives_ticker_date
        ON narratives (ticker, date)
    """)

    conn.commit()
    return conn


def record_scan(results: dict[str, Any]) -> None:
    """Save current scan results to the tracker database.

    Upserts mention counts and sentiment for each ticker found in the
    analysis results. Also records narrative themes per ticker.

    Args:
        results: Aggregated analysis dict from analyzer.analyze_posts().
            Expected keys: tickers (dict), themes (list).
    """
    tickers = results.get("tickers", {})
    if not tickers:
        log.info("No tickers to record")
        return

    today = date.today().isoformat()
    conn = _get_db()

    try:
        for symbol, data in tickers.items():
            mention_count = data.get("total_mentions", 0)
            avg_sentiment = data.get("avg_sentiment", 0.0)
            subreddits = json.dumps(data.get("subreddits", []))

            # Upsert: update if exists for today, insert otherwise
            conn.execute("""
                INSERT INTO mention_history (ticker, date, mention_count, avg_sentiment, subreddits)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    mention_count = mention_count + excluded.mention_count,
                    avg_sentiment = (avg_sentiment + excluded.avg_sentiment) / 2.0,
                    subreddits = excluded.subreddits
            """, (symbol, today, mention_count, avg_sentiment, subreddits))

            # Record narrative themes for this ticker
            themes = data.get("themes", [])
            if themes:
                narrative_text = "; ".join(themes)
                conn.execute("""
                    INSERT INTO narratives (ticker, date, narrative_text, source_posts)
                    VALUES (?, ?, ?, ?)
                """, (symbol, today, narrative_text, mention_count))

        conn.commit()
        log.info("Recorded scan data for %d tickers", len(tickers))
    except sqlite3.Error as e:
        log.error("Database error recording scan: %s", e)
        conn.rollback()
    finally:
        conn.close()


def get_mention_trend(ticker: str, days: int = 7) -> list[dict[str, Any]]:
    """Return daily mention counts for a ticker over the specified period.

    Args:
        ticker: Stock ticker symbol.
        days: Number of days to look back (default 7).

    Returns:
        List of dicts with keys: date, mention_count, avg_sentiment.
        Sorted by date ascending.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_db()

    rows = conn.execute("""
        SELECT date, mention_count, avg_sentiment
        FROM mention_history
        WHERE ticker = ? AND date >= ?
        ORDER BY date ASC
    """, (ticker, start_date)).fetchall()
    conn.close()

    return [
        {"date": r[0], "mention_count": r[1], "avg_sentiment": r[2]}
        for r in rows
    ]


def _get_avg_mentions(ticker: str, days: int, conn: sqlite3.Connection) -> float:
    """Get average daily mention count for a ticker over a period.

    Args:
        ticker: Stock ticker symbol.
        days: Number of days to average over.
        conn: Active database connection.

    Returns:
        Average daily mention count, or 0.0 if no history.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()
    today = date.today().isoformat()

    row = conn.execute("""
        SELECT AVG(mention_count)
        FROM mention_history
        WHERE ticker = ? AND date >= ? AND date < ?
    """, (ticker, start_date, today)).fetchone()

    return row[0] if row and row[0] is not None else 0.0


def _get_avg_sentiment(ticker: str, days: int, conn: sqlite3.Connection) -> float | None:
    """Get average sentiment for a ticker over a period.

    Args:
        ticker: Stock ticker symbol.
        days: Number of days to average over.
        conn: Active database connection.

    Returns:
        Average sentiment score, or None if no history.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()
    today = date.today().isoformat()

    row = conn.execute("""
        SELECT AVG(avg_sentiment)
        FROM mention_history
        WHERE ticker = ? AND date >= ? AND date < ?
    """, (ticker, start_date, today)).fetchone()

    return row[0] if row and row[0] is not None else None


def detect_anomalies(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag tickers with mentions exceeding 2x their 7-day average.

    Publishes 'unusual_mentions' signals to the agent bus for flagged tickers.

    Args:
        results: Aggregated analysis dict from analyzer.

    Returns:
        List of anomaly dicts with keys: ticker, current_mentions,
        avg_mentions, multiplier.
    """
    tickers = results.get("tickers", {})
    if not tickers:
        return []

    anomalies: list[dict[str, Any]] = []
    conn = _get_db()

    try:
        for symbol, data in tickers.items():
            current_mentions = data.get("total_mentions", 0)
            avg_mentions = _get_avg_mentions(symbol, 7, conn)

            # Only flag if there's meaningful history and current spike
            if avg_mentions > 0 and current_mentions > avg_mentions * MENTION_SPIKE_MULTIPLIER:
                multiplier = round(current_mentions / avg_mentions, 1)
                anomaly = {
                    "ticker": symbol,
                    "current_mentions": current_mentions,
                    "avg_mentions": round(avg_mentions, 1),
                    "multiplier": multiplier,
                }
                anomalies.append(anomaly)

                # Publish signal
                publish(
                    signal_type="unusual_mentions",
                    source_agent=AGENT_NAME,
                    payload={
                        "ticker": symbol,
                        "current_mentions": current_mentions,
                        "avg_7d": round(avg_mentions, 1),
                        "spike_multiplier": multiplier,
                        "sentiment": data.get("avg_sentiment", 0),
                    },
                )
                log.info(
                    "Anomaly: %s mentions spike %.1fx (current=%d, avg=%.1f)",
                    symbol, multiplier, current_mentions, avg_mentions,
                )
    finally:
        conn.close()

    return anomalies


def detect_sentiment_reversals(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag tickers where sentiment has flipped sign vs their 3-day average.

    A reversal is detected when current sentiment and 3-day average have
    opposite signs (one positive, one negative).

    Publishes 'sentiment_reversal' signals to the agent bus.

    Args:
        results: Aggregated analysis dict from analyzer.

    Returns:
        List of reversal dicts with keys: ticker, current_sentiment,
        avg_sentiment, direction.
    """
    tickers = results.get("tickers", {})
    if not tickers:
        return []

    reversals: list[dict[str, Any]] = []
    conn = _get_db()

    try:
        for symbol, data in tickers.items():
            current_sentiment = data.get("avg_sentiment", 0)
            avg_sentiment = _get_avg_sentiment(symbol, 3, conn)

            if avg_sentiment is None or avg_sentiment == 0 or current_sentiment == 0:
                continue

            # Check for sign flip
            if (current_sentiment > 0 and avg_sentiment < 0) or \
               (current_sentiment < 0 and avg_sentiment > 0):
                direction = "bearish_to_bullish" if current_sentiment > 0 else "bullish_to_bearish"
                reversal = {
                    "ticker": symbol,
                    "current_sentiment": current_sentiment,
                    "avg_sentiment": round(avg_sentiment, 2),
                    "direction": direction,
                }
                reversals.append(reversal)

                # Publish signal
                publish(
                    signal_type="sentiment_reversal",
                    source_agent=AGENT_NAME,
                    payload={
                        "ticker": symbol,
                        "current_sentiment": current_sentiment,
                        "prev_3d_avg": round(avg_sentiment, 2),
                        "direction": direction,
                    },
                )
                log.info(
                    "Sentiment reversal: %s flipped to %s (current=%.2f, avg_3d=%.2f)",
                    symbol, direction, current_sentiment, avg_sentiment,
                )
    finally:
        conn.close()

    return reversals


def detect_multi_sub_convergence(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag tickers mentioned in 3+ different subreddits.

    Multi-subreddit convergence suggests broader retail investor attention.

    Publishes 'multi_sub_convergence' signals to the agent bus.

    Args:
        results: Aggregated analysis dict from analyzer.

    Returns:
        List of convergence dicts with keys: ticker, subreddit_count, subreddits.
    """
    tickers = results.get("tickers", {})
    if not tickers:
        return []

    convergences: list[dict[str, Any]] = []

    for symbol, data in tickers.items():
        subreddits = data.get("subreddits", [])
        sub_count = len(subreddits)

        if sub_count >= CONVERGENCE_MIN_SUBS:
            convergence = {
                "ticker": symbol,
                "subreddit_count": sub_count,
                "subreddits": subreddits,
            }
            convergences.append(convergence)

            # Publish signal
            publish(
                signal_type="multi_sub_convergence",
                source_agent=AGENT_NAME,
                payload={
                    "ticker": symbol,
                    "subreddit_count": sub_count,
                    "subreddits": subreddits,
                    "mentions": data.get("total_mentions", 0),
                    "sentiment": data.get("avg_sentiment", 0),
                },
            )
            log.info(
                "Multi-sub convergence: %s in %d subreddits (%s)",
                symbol, sub_count, ", ".join(subreddits),
            )

    return convergences


def publish_narrative_signals(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Publish narrative-forming signals for themes appearing across multiple tickers.

    Args:
        results: Aggregated analysis dict from analyzer.

    Returns:
        List of published narrative signal payloads.
    """
    themes = results.get("themes", [])
    if not themes:
        return []

    tickers = results.get("tickers", {})
    published: list[dict[str, Any]] = []

    # Find themes that span multiple tickers
    theme_tickers: dict[str, list[str]] = {}
    for symbol, data in tickers.items():
        for theme in data.get("themes", []):
            theme_lower = theme.lower()
            if theme_lower not in theme_tickers:
                theme_tickers[theme_lower] = []
            theme_tickers[theme_lower].append(symbol)

    for theme, related_tickers in theme_tickers.items():
        if len(related_tickers) >= 2:  # Theme spans multiple tickers
            payload = {
                "narrative": theme,
                "related_tickers": related_tickers,
                "ticker_count": len(related_tickers),
            }
            publish(
                signal_type="narrative_forming",
                source_agent=AGENT_NAME,
                payload=payload,
            )
            published.append(payload)
            log.info(
                "Narrative signal: '%s' across %d tickers (%s)",
                theme, len(related_tickers), ", ".join(related_tickers),
            )

    return published

"""Sector Scanner — SQLite tracker and agent bus publisher.

Deduplicates articles within 48h, then publishes sector_momentum and
sector_catalyst signals to the agent bus.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "sector_scanner"
DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "sector_scanner_tracker.db"
DEDUP_HOURS = 48


def _get_db() -> sqlite3.Connection:
    """Get or create the sector scanner tracker database."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sector_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT,
            sector TEXT NOT NULL,
            direction TEXT,
            catalyst_type TEXT,
            sector_relevance INTEGER,
            summary TEXT,
            tickers TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sector_articles_title
        ON sector_articles (title)
    """)
    conn.commit()
    return conn


def _is_duplicate(conn: sqlite3.Connection, title: str) -> bool:
    """Check if article title was seen in the last DEDUP_HOURS."""
    cutoff = (datetime.now() - timedelta(hours=DEDUP_HOURS)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM sector_articles WHERE title = ? AND created_at > ? LIMIT 1",
        (title, cutoff),
    ).fetchone()
    return row is not None


def track_and_publish(
    analyzed_articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate articles, persist to DB, and publish signals to agent bus.

    Publishes two signal types:
    - sector_momentum: directional moves (bullish/bearish with multiple articles)
    - sector_catalyst: specific events (individual high-relevance articles)

    Args:
        analyzed_articles: Articles that passed the analyzer relevance filter.

    Returns:
        List of published signal dicts.
    """
    if not analyzed_articles:
        return []

    conn = _get_db()
    new_articles: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    for article in analyzed_articles:
        title = article.get("title", "")
        if not title or _is_duplicate(conn, title):
            continue

        # Persist to tracker DB
        conn.execute(
            """INSERT INTO sector_articles
               (title, url, sector, direction, catalyst_type, sector_relevance, summary, tickers, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                article.get("url", ""),
                article.get("sector", "unknown"),
                article.get("direction", "neutral"),
                article.get("catalyst_type", "other"),
                article.get("sector_relevance", 0),
                article.get("sector_summary", ""),
                json.dumps(article.get("sector_tickers", [])),
                datetime.now().isoformat(),
            ),
        )
        new_articles.append(article)

    conn.commit()
    conn.close()

    if not new_articles:
        log.info("Sector tracker: no new articles after dedup")
        return []

    # Aggregate by sector for momentum signals
    sector_groups: dict[str, list[dict[str, Any]]] = {}
    for article in new_articles:
        sector = article.get("sector", "unknown")
        sector_groups.setdefault(sector, []).append(article)

    for sector, articles in sector_groups.items():
        bullish = sum(1 for a in articles if a.get("direction") == "bullish")
        bearish = sum(1 for a in articles if a.get("direction") == "bearish")

        # Publish sector_momentum if there's a directional lean
        if bullish > 0 or bearish > 0:
            direction = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "mixed"
            tickers = list(
                dict.fromkeys(
                    t for a in articles for t in a.get("sector_tickers", [])
                )
            )
            payload = {
                "sector": sector,
                "direction": direction,
                "article_count": len(articles),
                "bullish_count": bullish,
                "bearish_count": bearish,
                "tickers": tickers[:10],
                "top_summary": articles[0].get("sector_summary", ""),
            }
            try:
                signal_id = publish("sector_momentum", AGENT_NAME, payload)
                signals.append({"id": signal_id, "type": "sector_momentum", **payload})
            except Exception as e:
                log.error("Failed to publish sector_momentum for %s: %s", sector, e)

        # Publish sector_catalyst for high-relevance individual articles
        for article in articles:
            if article.get("sector_relevance", 0) >= 8:
                payload = {
                    "sector": sector,
                    "title": article.get("title", ""),
                    "direction": article.get("direction", "neutral"),
                    "catalyst_type": article.get("catalyst_type", "other"),
                    "summary": article.get("sector_summary", ""),
                    "tickers": article.get("sector_tickers", []),
                    "relevance": article.get("sector_relevance", 0),
                }
                try:
                    signal_id = publish("sector_catalyst", AGENT_NAME, payload)
                    signals.append({"id": signal_id, "type": "sector_catalyst", **payload})
                except Exception as e:
                    log.error("Failed to publish sector_catalyst: %s", e)

    log.info(
        "Sector tracker: %d new articles, %d signals published",
        len(new_articles),
        len(signals),
    )
    return signals

"""Rolling mention tracker and signal detector for YouTube Ear.

Maintains a SQLite database of ticker mention history and thesis tracking.
Detects view spikes and multi-channel convergence. Publishes signals to the
agent bus.

HYBRID approach: YouTube has real engagement metrics (views, comments) so
volume-based detection partially works, unlike pure text sources.
"""

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "youtube_tracker.db"
AGENT_NAME = "youtube_ear"

# Detection thresholds
MENTION_SPIKE_MULTIPLIER = 2.0
CONVERGENCE_MIN_CHANNELS = 2  # Flag if same ticker across 2+ channels
VIEW_SPIKE_MULTIPLIER = 3.0  # Flag videos with 3x avg views for that channel


def _get_db() -> sqlite3.Connection:
    """Get or create the YouTube Ear tracker database.

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
            channels TEXT NOT NULL,
            UNIQUE(ticker, date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mention_ticker_date
        ON mention_history (ticker, date)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS theses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            direction TEXT NOT NULL,
            thesis TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            source TEXT NOT NULL,
            themes TEXT NOT NULL DEFAULT '[]'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_theses_ticker_date
        ON theses (ticker, date)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_view_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT NOT NULL,
            date TEXT NOT NULL,
            avg_views INTEGER NOT NULL DEFAULT 0,
            video_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(channel_name, date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_channel_views
        ON channel_view_history (channel_name, date)
    """)

    conn.commit()
    return conn


def record_scan(analysis: dict[str, Any]) -> None:
    """Save current scan results to the tracker database.

    Upserts mention counts and sentiment for each ticker found in the
    analysis results.

    Args:
        analysis: Aggregated analysis dict from analyzer.analyze_videos().
    """
    tickers = analysis.get("tickers", {})
    if not tickers:
        log.info("No tickers to record")
        return

    today = date.today().isoformat()
    conn = _get_db()

    try:
        for symbol, data in tickers.items():
            mention_count = data.get("total_mentions", 0)
            avg_sentiment = data.get("avg_sentiment", 0.0)
            channels = json.dumps(data.get("channels", []))

            conn.execute("""
                INSERT INTO mention_history (ticker, date, mention_count, avg_sentiment, channels)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    mention_count = mention_count + excluded.mention_count,
                    avg_sentiment = (avg_sentiment + excluded.avg_sentiment) / 2.0,
                    channels = excluded.channels
            """, (symbol, today, mention_count, avg_sentiment, channels))

        conn.commit()
        log.info("Recorded scan data for %d tickers", len(tickers))
    except sqlite3.Error as e:
        log.error("Database error recording scan: %s", e)
        conn.rollback()
    finally:
        conn.close()


def record_theses(analysis: dict[str, Any]) -> None:
    """Save extracted theses to the tracker database.

    Args:
        analysis: Aggregated analysis dict from analyzer.analyze_videos().
    """
    theses = analysis.get("theses", [])
    if not theses:
        log.info("No theses to record")
        return

    today = date.today().isoformat()
    conn = _get_db()

    try:
        for thesis in theses:
            ticker = thesis.get("ticker", "")
            direction = thesis.get("direction", "neutral")
            thesis_text = thesis.get("thesis", "")
            confidence = thesis.get("confidence", 0.5)
            source = thesis.get("source", "unknown")
            themes = json.dumps(thesis.get("themes", []))

            if not ticker or not thesis_text:
                continue

            conn.execute("""
                INSERT INTO theses (ticker, date, direction, thesis, confidence, source, themes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ticker, today, direction, thesis_text, confidence, source, themes))

        conn.commit()
        log.info("Recorded %d theses", len(theses))
    except sqlite3.Error as e:
        log.error("Database error recording theses: %s", e)
        conn.rollback()
    finally:
        conn.close()


def _record_channel_views(videos: list[dict[str, Any]]) -> None:
    """Record per-channel view averages for spike detection.

    Args:
        videos: List of video dicts from youtube_fetcher.
    """
    if not videos:
        return

    today = date.today().isoformat()
    conn = _get_db()

    # Aggregate views per channel
    channel_stats: dict[str, dict[str, int]] = {}
    for video in videos:
        channel = video.get("subreddit", "unknown")
        views = video.get("score", 0)
        if channel not in channel_stats:
            channel_stats[channel] = {"total_views": 0, "count": 0}
        channel_stats[channel]["total_views"] += views
        channel_stats[channel]["count"] += 1

    try:
        for channel, stats in channel_stats.items():
            avg_views = stats["total_views"] // max(stats["count"], 1)
            conn.execute("""
                INSERT INTO channel_view_history (channel_name, date, avg_views, video_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_name, date) DO UPDATE SET
                    avg_views = excluded.avg_views,
                    video_count = excluded.video_count
            """, (channel, today, avg_views, stats["count"]))

        conn.commit()
    except sqlite3.Error as e:
        log.error("Database error recording channel views: %s", e)
        conn.rollback()
    finally:
        conn.close()


def _get_channel_avg_views(channel_name: str, days: int, conn: sqlite3.Connection) -> float:
    """Get average views for a channel over a period.

    Args:
        channel_name: Channel display name.
        days: Number of days to average over.
        conn: Active database connection.

    Returns:
        Average view count, or 0.0 if no history.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()
    today = date.today().isoformat()

    row = conn.execute("""
        SELECT AVG(avg_views)
        FROM channel_view_history
        WHERE channel_name = ? AND date >= ? AND date < ?
    """, (channel_name, start_date, today)).fetchone()

    return row[0] if row and row[0] is not None else 0.0


def detect_view_spikes(analysis: dict[str, Any], videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag videos with unusually high views compared to channel average.

    Publishes 'narrative_amplification' signals for spiking videos.

    Args:
        analysis: Aggregated analysis dict from analyzer.
        videos: List of video dicts from youtube_fetcher.

    Returns:
        List of spike dicts with keys: channel, title, views, avg_views, multiplier.
    """
    if not videos:
        return []

    # Record current view data
    _record_channel_views(videos)

    spikes: list[dict[str, Any]] = []
    conn = _get_db()

    try:
        for video in videos:
            channel = video.get("subreddit", "unknown")
            views = video.get("score", 0)
            title = video.get("title", "")
            url = video.get("url", "")

            avg_views = _get_channel_avg_views(channel, 14, conn)

            if avg_views > 0 and views > avg_views * VIEW_SPIKE_MULTIPLIER:
                multiplier = round(views / avg_views, 1)
                spike = {
                    "channel": channel,
                    "title": title,
                    "views": views,
                    "avg_views": round(avg_views),
                    "multiplier": multiplier,
                    "url": url,
                }
                spikes.append(spike)

                # Find tickers mentioned in videos from this channel
                related_tickers = [
                    sym for sym, data in analysis.get("tickers", {}).items()
                    if channel in data.get("channels", [])
                ]

                publish(
                    signal_type="narrative_amplification",
                    source_agent=AGENT_NAME,
                    payload={
                        "channel": channel,
                        "title": title,
                        "views": views,
                        "avg_views": round(avg_views),
                        "spike_multiplier": multiplier,
                        "url": url,
                        "related_tickers": related_tickers,
                    },
                )
                log.info(
                    "View spike: %s — '%s' %.1fx avg (%d vs %d)",
                    channel, title[:50], multiplier, views, round(avg_views),
                )
    finally:
        conn.close()

    return spikes


def detect_multi_channel_convergence(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag tickers mentioned across multiple YouTube channels.

    Multi-channel convergence suggests expert consensus forming.

    Publishes 'expert_analysis' signals to the agent bus.

    Args:
        analysis: Aggregated analysis dict from analyzer.

    Returns:
        List of convergence dicts with keys: ticker, channel_count, channels.
    """
    tickers = analysis.get("tickers", {})
    if not tickers:
        return []

    convergences: list[dict[str, Any]] = []

    for symbol, data in tickers.items():
        channels = data.get("channels", [])
        channel_count = len(channels)

        if channel_count >= CONVERGENCE_MIN_CHANNELS:
            convergence = {
                "ticker": symbol,
                "channel_count": channel_count,
                "channels": channels,
            }
            convergences.append(convergence)

            publish(
                signal_type="expert_analysis",
                source_agent=AGENT_NAME,
                payload={
                    "ticker": symbol,
                    "channel_count": channel_count,
                    "channels": channels,
                    "mentions": data.get("total_mentions", 0),
                    "sentiment": data.get("avg_sentiment", 0),
                    "themes": data.get("themes", [])[:5],
                },
            )
            log.info(
                "Multi-channel convergence: %s across %d channels (%s)",
                symbol, channel_count, ", ".join(channels),
            )

    return convergences


def publish_signals(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Publish expert analysis signals for theses with high confidence.

    Args:
        analysis: Aggregated analysis dict from analyzer.

    Returns:
        List of published signal payloads.
    """
    theses = analysis.get("theses", [])
    if not theses:
        return []

    published: list[dict[str, Any]] = []

    for thesis in theses:
        confidence = thesis.get("confidence", 0)
        if confidence < 0.6:
            continue

        payload = {
            "ticker": thesis.get("ticker", ""),
            "direction": thesis.get("direction", "neutral"),
            "thesis": thesis.get("thesis", ""),
            "confidence": confidence,
            "source": thesis.get("source", "unknown"),
            "themes": thesis.get("themes", []),
        }
        publish(
            signal_type="expert_analysis",
            source_agent=AGENT_NAME,
            payload=payload,
        )
        published.append(payload)
        log.info(
            "Expert signal: %s %s (confidence=%.2f) from %s",
            thesis.get("ticker"), thesis.get("direction"),
            confidence, thesis.get("source"),
        )

    # Record narratives in the cross-source narrative tracker
    try:
        from src.shared.narrative_tracker import record_narrative

        for thesis in theses:
            ticker = thesis.get("ticker", "")
            thesis_text = thesis.get("thesis", "")
            confidence = thesis.get("confidence", 0)
            if ticker and thesis_text and confidence >= 0.6:
                record_narrative(
                    narrative=thesis_text,
                    source_platform="youtube",
                    source_detail=thesis.get("source", AGENT_NAME),
                    affected_tickers=[ticker],
                    conviction="high" if confidence >= 0.8 else "medium",
                )
        log.info("Recorded narratives in narrative tracker")
    except Exception as e:
        log.warning("Failed to record narratives in tracker: %s", e)

    return published

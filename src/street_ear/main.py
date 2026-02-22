"""Street Ear — Reddit intelligence pipeline orchestrator.

Runs the full pipeline: fetch posts from Reddit, analyze with Claude Opus 4.6,
track mentions and detect anomalies, publish signals to the agent bus, and
format output for Telegram delivery.
"""

import asyncio
import time
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "street_ear"


async def run() -> dict[str, Any]:
    """Orchestrate the full Street Ear pipeline.

    Steps:
        1. Fetch posts from all configured subreddits
        2. Analyze posts with Claude Opus 4.6
        3. Track mentions and detect anomalies
        4. Publish signals to agent bus
        5. Format output for Telegram

    Returns:
        Dict with keys:
        - formatted: HTML-formatted string for Telegram
        - signals: list of signal dicts published to agent bus
        - stats: dict with pipeline statistics
    """
    pipeline_start = time.monotonic()
    stats: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []
    posts: list[dict[str, Any]] = []
    analysis: dict[str, Any] = {"tickers": {}, "themes": [], "market_mood": "unknown"}
    anomalies: list[dict[str, Any]] = []
    reversals: list[dict[str, Any]] = []
    convergences: list[dict[str, Any]] = []
    trends: dict[str, list[dict[str, Any]]] = {}

    # Step 1: Fetch posts from Reddit
    log.info("Step 1/5: Fetching Reddit posts")
    step_start = time.monotonic()
    try:
        from src.street_ear.reddit_fetcher import fetch_posts
        posts = await asyncio.to_thread(fetch_posts)
        stats["posts_fetched"] = len(posts)
        stats["fetch_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Fetched %d posts in %.1fs", len(posts), stats["fetch_time_s"])
    except Exception as e:
        log.error("Failed to fetch posts: %s", e, exc_info=True)
        stats["posts_fetched"] = 0
        stats["fetch_error"] = str(e)

    # Step 2: Analyze posts with Claude Opus 4.6
    log.info("Step 2/5: Analyzing posts with Claude")
    step_start = time.monotonic()
    try:
        if posts:
            from src.street_ear.analyzer import analyze_posts
            analysis = await asyncio.to_thread(analyze_posts, posts)
            stats["tickers_found"] = len(analysis.get("tickers", {}))
            stats["themes_found"] = len(analysis.get("themes", []))
        else:
            log.warning("No posts to analyze — skipping")
            stats["tickers_found"] = 0
            stats["themes_found"] = 0
        stats["analysis_time_s"] = round(time.monotonic() - step_start, 1)
        log.info(
            "Analysis complete in %.1fs: %d tickers, %d themes",
            stats["analysis_time_s"],
            stats.get("tickers_found", 0),
            stats.get("themes_found", 0),
        )
    except Exception as e:
        log.error("Failed to analyze posts: %s", e, exc_info=True)
        stats["tickers_found"] = 0
        stats["analysis_error"] = str(e)

    # Step 3: Track mentions + detect anomalies
    log.info("Step 3/5: Tracking mentions and detecting anomalies")
    step_start = time.monotonic()
    try:
        from src.street_ear.tracker import (
            detect_anomalies,
            detect_multi_sub_convergence,
            detect_sentiment_reversals,
            get_mention_trend,
            publish_narrative_signals,
            record_scan,
        )

        # Record this scan's data
        record_scan(analysis)

        # Detect anomalies
        anomalies = detect_anomalies(analysis)
        reversals = detect_sentiment_reversals(analysis)
        convergences = detect_multi_sub_convergence(analysis)

        # Get trends for formatting
        for symbol in analysis.get("tickers", {}):
            trends[symbol] = get_mention_trend(symbol, days=7)

        stats["anomalies"] = len(anomalies)
        stats["reversals"] = len(reversals)
        stats["convergences"] = len(convergences)
        stats["tracking_time_s"] = round(time.monotonic() - step_start, 1)

        log.info(
            "Tracking complete in %.1fs: %d anomalies, %d reversals, %d convergences",
            stats["tracking_time_s"],
            len(anomalies), len(reversals), len(convergences),
        )
    except Exception as e:
        log.error("Failed in tracking step: %s", e, exc_info=True)
        stats["tracking_error"] = str(e)

    # Step 4: Publish signals to agent bus
    log.info("Step 4/5: Publishing signals to agent bus")
    step_start = time.monotonic()
    try:
        from src.street_ear.tracker import publish_narrative_signals

        narrative_signals = publish_narrative_signals(analysis)

        # Collect all signals for the return value
        for a in anomalies:
            signals.append({"type": "unusual_mentions", **a})
        for r in reversals:
            signals.append({"type": "sentiment_reversal", **r})
        for c in convergences:
            signals.append({"type": "multi_sub_convergence", **c})
        for n in narrative_signals:
            signals.append({"type": "narrative_forming", **n})

        stats["signals_published"] = len(signals)
        stats["signal_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Published %d signals in %.1fs", len(signals), stats["signal_time_s"])
    except Exception as e:
        log.error("Failed to publish signals: %s", e, exc_info=True)
        stats["signal_error"] = str(e)

    # Step 5: Format output for Telegram
    log.info("Step 5/5: Formatting output")
    step_start = time.monotonic()
    formatted = ""
    try:
        from src.street_ear.formatter import format_output

        formatted = format_output(
            analysis=analysis,
            anomalies=anomalies,
            reversals=reversals,
            convergences=convergences,
            trends=trends,
        )
        stats["output_chars"] = len(formatted)
        stats["format_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Formatted output: %d chars in %.1fs", len(formatted), stats["format_time_s"])
    except Exception as e:
        log.error("Failed to format output: %s", e, exc_info=True)
        formatted = "<b>Street Ear</b>\n<i>Error formatting output</i>"
        stats["format_error"] = str(e)

    # Summary
    total_time = round(time.monotonic() - pipeline_start, 1)
    stats["total_time_s"] = total_time
    log.info(
        "Street Ear pipeline complete in %.1fs — %d posts, %d tickers, %d signals",
        total_time,
        stats.get("posts_fetched", 0),
        stats.get("tickers_found", 0),
        stats.get("signals_published", 0),
    )

    return {
        "formatted": formatted,
        "signals": signals,
        "stats": stats,
    }

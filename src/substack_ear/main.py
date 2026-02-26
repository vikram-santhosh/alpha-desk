"""Substack Ear — expert newsletter intelligence pipeline orchestrator.

Runs the full pipeline: fetch articles from Substack RSS, analyze with
Claude Haiku, track theses and macro signals, publish signals to the
agent bus, and format output for Telegram delivery.
"""

import asyncio
import time
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "substack_ear"


async def run() -> dict[str, Any]:
    """Orchestrate the full Substack Ear pipeline.

    Steps:
        1. Fetch articles from configured Substack newsletters
        2. Analyze articles with Claude Haiku
        3. Track theses and macro signals
        4. Publish signals to agent bus
        5. Format output for Telegram

    Returns:
        Dict with keys:
        - formatted: HTML-formatted string for Telegram
        - signals: list of signal dicts published to agent bus
        - stats: dict with pipeline statistics
        - analysis: summary of analysis results
    """
    pipeline_start = time.monotonic()
    stats: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []
    articles: list[dict[str, Any]] = []
    analysis: dict[str, Any] = {
        "tickers": {}, "themes": [], "theses": [],
        "macro_signals": [], "market_mood": "unknown",
    }

    # Step 1: Fetch articles from Substack
    log.info("Step 1/5: Fetching Substack articles")
    step_start = time.monotonic()
    try:
        from src.substack_ear.substack_fetcher import fetch_articles
        articles = await asyncio.to_thread(fetch_articles)
        stats["articles_fetched"] = len(articles)
        stats["fetch_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Fetched %d articles in %.1fs", len(articles), stats["fetch_time_s"])
    except Exception as e:
        log.error("Failed to fetch articles: %s", e, exc_info=True)
        stats["articles_fetched"] = 0
        stats["fetch_error"] = str(e)

    # Step 2: Analyze articles with Claude Haiku
    log.info("Step 2/5: Analyzing articles with Claude")
    step_start = time.monotonic()
    try:
        if articles:
            from src.substack_ear.analyzer import analyze_articles
            analysis = await asyncio.to_thread(analyze_articles, articles)
            stats["tickers_found"] = len(analysis.get("tickers", {}))
            stats["theses_found"] = len(analysis.get("theses", []))
            stats["macro_signals_found"] = len(analysis.get("macro_signals", []))
        else:
            log.warning("No articles to analyze -- skipping")
            stats["tickers_found"] = 0
            stats["theses_found"] = 0
            stats["macro_signals_found"] = 0
        stats["analysis_time_s"] = round(time.monotonic() - step_start, 1)
        log.info(
            "Analysis complete in %.1fs: %d tickers, %d theses, %d macro signals",
            stats["analysis_time_s"],
            stats.get("tickers_found", 0),
            stats.get("theses_found", 0),
            stats.get("macro_signals_found", 0),
        )
    except Exception as e:
        log.error("Failed to analyze articles: %s", e, exc_info=True)
        stats["tickers_found"] = 0
        stats["analysis_error"] = str(e)

    # Step 3: Track theses and macro signals
    log.info("Step 3/5: Tracking theses and macro signals")
    step_start = time.monotonic()
    try:
        from src.substack_ear.tracker import record_macro_signals, record_theses

        record_theses(analysis)
        record_macro_signals(analysis)

        stats["tracking_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Tracking complete in %.1fs", stats["tracking_time_s"])
    except Exception as e:
        log.error("Failed in tracking step: %s", e, exc_info=True)
        stats["tracking_error"] = str(e)

    # Step 4: Publish signals to agent bus
    log.info("Step 4/5: Publishing signals to agent bus")
    step_start = time.monotonic()
    try:
        from src.substack_ear.tracker import publish_thesis_signals

        signals = publish_thesis_signals(analysis)
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
        from src.substack_ear.formatter import format_output

        formatted = format_output(analysis=analysis)
        stats["output_chars"] = len(formatted)
        stats["format_time_s"] = round(time.monotonic() - step_start, 1)
        log.info("Formatted output: %d chars in %.1fs", len(formatted), stats["format_time_s"])
    except Exception as e:
        log.error("Failed to format output: %s", e, exc_info=True)
        formatted = "<b>Substack Ear</b>\n<i>Error formatting output</i>"
        stats["format_error"] = str(e)

    # Summary
    total_time = round(time.monotonic() - pipeline_start, 1)
    stats["total_time_s"] = total_time
    log.info(
        "Substack Ear pipeline complete in %.1fs -- %d articles, %d tickers, %d signals",
        total_time,
        stats.get("articles_fetched", 0),
        stats.get("tickers_found", 0),
        stats.get("signals_published", 0),
    )

    return {
        "formatted": formatted,
        "signals": signals,
        "stats": stats,
        "analysis": {
            "market_mood": analysis.get("market_mood", "unknown"),
            "tickers_found": len(analysis.get("tickers", {})),
            "themes": analysis.get("themes", []),
            "theses_count": len(analysis.get("theses", [])),
            "macro_signals_count": len(analysis.get("macro_signals", [])),
        },
    }

"""Sector Scanner — broad thematic sector intelligence pipeline.

Scans thematic sectors defined in config/advisor.yaml for news, analyzes
for sector relevance and direction, and publishes sector_momentum /
sector_catalyst signals to the agent bus.

Follows the 4-step pipeline pattern:
Fetch → Analyze → Track+Publish → Format.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "sector_scanner"


async def run(
    config: dict[str, Any] | None = None,
    exclude_tickers: set[str] | None = None,
) -> dict[str, Any]:
    """Orchestrate the full Sector Scanner pipeline.

    Args:
        config: Advisor config dict. Loaded from disk if not provided.
        exclude_tickers: Tickers to exclude (portfolio + watchlist).

    Returns:
        Dict with keys:
        - formatted: HTML-formatted string for Telegram
        - signals: list of signal dicts published to agent bus
        - stats: dict with pipeline statistics
    """
    pipeline_start = time.monotonic()
    stats: dict[str, Any] = {}
    signals: list[dict[str, Any]] = []
    analyzed_articles: list[dict[str, Any]] = []

    # Step 1: Fetch sector news
    log.info("Sector Scanner Step 1/4: Fetching sector news")
    step_start = time.monotonic()
    fetch_result: dict[str, Any] = {"articles": [], "sector_picks": {}, "stats": {}}
    try:
        from src.sector_scanner.sector_fetcher import fetch_sector_news

        fetch_result = await asyncio.to_thread(
            fetch_sector_news,
            config=config,
            exclude_tickers=exclude_tickers,
        )
        stats.update(fetch_result.get("stats", {}))
        stats["fetch_time_s"] = round(time.monotonic() - step_start, 1)
        log.info(
            "Fetched %d articles in %.1fs",
            len(fetch_result.get("articles", [])),
            stats["fetch_time_s"],
        )
    except Exception as e:
        log.error("Failed to fetch sector news: %s", e, exc_info=True)
        stats["fetch_error"] = str(e)

    # Step 2: Analyze articles with Haiku
    articles = fetch_result.get("articles", [])
    if articles:
        log.info("Sector Scanner Step 2/4: Analyzing %d articles", len(articles))
        step_start = time.monotonic()
        try:
            from src.sector_scanner.analyzer import analyze_sector_articles

            scanner_cfg = (config or {}).get("sector_scanner", {})
            min_relevance = scanner_cfg.get("min_relevance", 6)

            analyzed_articles = await asyncio.to_thread(
                analyze_sector_articles,
                articles,
                min_relevance=min_relevance,
            )
            stats["articles_analyzed"] = len(articles)
            stats["articles_relevant"] = len(analyzed_articles)
            stats["analysis_time_s"] = round(time.monotonic() - step_start, 1)
            log.info(
                "Analysis complete in %.1fs: %d/%d relevant",
                stats["analysis_time_s"],
                len(analyzed_articles),
                len(articles),
            )
        except Exception as e:
            log.error("Failed to analyze sector articles: %s", e, exc_info=True)
            stats["analysis_error"] = str(e)
    else:
        log.info("Sector Scanner: no articles to analyze")

    # Step 3: Track and publish signals
    if analyzed_articles:
        log.info("Sector Scanner Step 3/4: Tracking and publishing signals")
        step_start = time.monotonic()
        try:
            from src.sector_scanner.tracker import track_and_publish

            signals = await asyncio.to_thread(track_and_publish, analyzed_articles)
            stats["signals_published"] = len(signals)
            stats["tracking_time_s"] = round(time.monotonic() - step_start, 1)
            log.info("Published %d signals in %.1fs", len(signals), stats["tracking_time_s"])
        except Exception as e:
            log.error("Failed to track/publish sector signals: %s", e, exc_info=True)
            stats["tracking_error"] = str(e)

    # Step 4: Format output
    log.info("Sector Scanner Step 4/4: Formatting output")
    step_start = time.monotonic()
    formatted = ""
    try:
        from src.sector_scanner.formatter import format_output

        formatted = format_output(analyzed_articles, signals)
        stats["output_chars"] = len(formatted)
        stats["format_time_s"] = round(time.monotonic() - step_start, 1)
    except Exception as e:
        log.error("Failed to format sector scanner output: %s", e, exc_info=True)
        formatted = "<b>\U0001f30d Sector Scanner</b>\n<i>Error formatting output</i>"
        stats["format_error"] = str(e)

    total_time = round(time.monotonic() - pipeline_start, 1)
    stats["total_time_s"] = total_time
    log.info(
        "Sector Scanner pipeline complete in %.1fs — %d articles, %d relevant, %d signals",
        total_time,
        stats.get("articles_fetched", 0),
        stats.get("articles_relevant", 0),
        stats.get("signals_published", 0),
    )

    return {
        "formatted": formatted,
        "signals": signals,
        "stats": stats,
    }

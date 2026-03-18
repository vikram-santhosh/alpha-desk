"""News Desk main orchestrator for AlphaDesk.

Orchestrates the full news intelligence pipeline:
1. Load tickers from portfolio and watchlist configuration
2. Fetch news from Finnhub (per-ticker) and NewsAPI (headlines + market search)
3. Analyze articles with Gemini for relevance, sentiment, urgency
4. Publish signals to the agent bus for inter-agent coordination
5. Format output as Telegram HTML digest

Entry point: `run()` — an async function returning a structured result dict.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from dotenv import load_dotenv

from src.shared.config_loader import get_all_tickers, load_portfolio
from src.utils.logger import get_logger

from src.news_desk.analyzer import analyze_news, publish_signals
from src.news_desk.formatter import format_news_digest
from src.news_desk.news_fetcher import fetch_all_news

log = get_logger(__name__)

AGENT_NAME = "news_desk"


def _get_portfolio_tickers() -> list[str]:
    """Extract portfolio-only tickers for classification.

    Returns:
        List of ticker symbols from the portfolio config, or empty list
        if the config cannot be loaded.
    """
    try:
        portfolio = load_portfolio()
        return [h["ticker"] for h in portfolio.get("holdings", [])]
    except (FileNotFoundError, KeyError) as e:
        log.warning("Could not load portfolio tickers: %s", e)
        return []


def _load_api_keys() -> dict[str, str | None]:
    """Load API keys from environment variables.

    Loads the .env file and returns available API keys. Missing keys are
    returned as None so callers can gracefully degrade.

    Returns:
        Dict with keys: gemini_key, finnhub_key, newsapi_key.
    """
    load_dotenv()

    keys = {
        "gemini_key": os.getenv("ANTHROPIC_API_KEY") or os.getenv("GEMINI_API_KEY"),
        "finnhub_key": os.getenv("FINNHUB_API_KEY"),
        "newsapi_key": os.getenv("NEWSAPI_KEY"),
    }

    available = [k for k, v in keys.items() if v]
    missing = [k for k, v in keys.items() if not v]

    log.info("API keys loaded: %s available, %s missing", available, missing)

    if not keys["gemini_key"]:
        log.error("ANTHROPIC_API_KEY or GEMINI_API_KEY is required for news analysis")

    return keys


async def run(headlines_only: bool = False) -> dict[str, Any]:
    """Run the full News Desk pipeline.

    Orchestrates fetching, analysis, signal publishing, and formatting.
    The pipeline is designed to degrade gracefully: if a data source is
    unavailable, the remaining sources are still processed.

    Returns:
        Dict with keys:
        - formatted (str): Telegram HTML formatted news digest.
        - signals (list): Published signal dicts.
        - stats (dict): Pipeline statistics (timing, counts, errors).
        - top_articles (list): Top analyzed articles with full metadata.
    """
    pipeline_start = time.time()
    stats: dict[str, Any] = {
        "tickers_count": 0,
        "raw_articles": 0,
        "analyzed_articles": 0,
        "filtered_articles": 0,
        "signals_published": 0,
        "errors": [],
        "timing": {},
    }

    result: dict[str, Any] = {
        "formatted": "",
        "signals": [],
        "stats": stats,
        "top_articles": [],
    }

    # Step 1: Load tickers
    step_start = time.time()
    try:
        tickers = get_all_tickers()
        portfolio_tickers = _get_portfolio_tickers()
        stats["tickers_count"] = len(tickers)
        log.info("Loaded %d tickers (%d portfolio)", len(tickers), len(portfolio_tickers))
    except Exception as e:
        error_msg = f"Failed to load tickers: {e}"
        log.error(error_msg)
        stats["errors"].append(error_msg)
        tickers = []
        portfolio_tickers = []
    stats["timing"]["load_tickers"] = round(time.time() - step_start, 2)

    # Step 2: Load API keys
    keys = _load_api_keys()

    # Step 3: Fetch news from all sources
    step_start = time.time()
    try:
        # Run fetch in a thread pool since it involves blocking HTTP calls
        raw_articles = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: fetch_all_news(
                tickers=tickers,
                finnhub_key=keys.get("finnhub_key"),
                newsapi_key=keys.get("newsapi_key"),
                headlines_only=headlines_only,
            ),
        )
        stats["raw_articles"] = len(raw_articles)
        log.info("Fetched %d raw articles", len(raw_articles))
    except Exception as e:
        error_msg = f"Failed to fetch news: {e}"
        log.error(error_msg, exc_info=True)
        stats["errors"].append(error_msg)
        raw_articles = []
    stats["timing"]["fetch_news"] = round(time.time() - step_start, 2)

    if not raw_articles:
        log.warning("No articles fetched; returning empty result")
        result["formatted"] = format_news_digest([], portfolio_tickers)
        stats["timing"]["total"] = round(time.time() - pipeline_start, 2)
        return result

    # Step 4: Analyze with Gemini
    step_start = time.time()
    analyzed_articles: list[dict[str, Any]] = []
    if keys.get("gemini_key"):
        try:
            analyzed_articles = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: analyze_news(raw_articles, keys["gemini_key"]),
            )
            stats["analyzed_articles"] = len(raw_articles)
            stats["filtered_articles"] = len(analyzed_articles)
            log.info("Analysis complete: %d articles passed filter", len(analyzed_articles))
        except Exception as e:
            error_msg = f"Failed to analyze news: {e}"
            log.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)
    else:
        error_msg = "Skipping analysis: GEMINI_API_KEY not available"
        log.warning(error_msg)
        stats["errors"].append(error_msg)
    stats["timing"]["analyze"] = round(time.time() - step_start, 2)

    # Step 5: Publish signals to agent bus
    step_start = time.time()
    signals: list[dict[str, Any]] = []
    if analyzed_articles:
        try:
            signals = publish_signals(analyzed_articles)
            stats["signals_published"] = len(signals)
            result["signals"] = signals
            log.info("Published %d signals", len(signals))
        except Exception as e:
            error_msg = f"Failed to publish signals: {e}"
            log.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)
    stats["timing"]["publish_signals"] = round(time.time() - step_start, 2)

    # Step 6: Format output for Telegram
    step_start = time.time()
    try:
        articles_to_format = analyzed_articles if analyzed_articles else raw_articles
        formatted = format_news_digest(articles_to_format, portfolio_tickers)
        result["formatted"] = formatted
        log.info("Formatted news digest: %d characters", len(formatted))
    except Exception as e:
        error_msg = f"Failed to format news digest: {e}"
        log.error(error_msg, exc_info=True)
        stats["errors"].append(error_msg)
        result["formatted"] = "<b>News Desk</b>\n\nError formatting news digest."
    stats["timing"]["format"] = round(time.time() - step_start, 2)

    # Set top articles (up to 15)
    result["top_articles"] = (analyzed_articles if analyzed_articles else raw_articles)[:15]

    # Final timing
    stats["timing"]["total"] = round(time.time() - pipeline_start, 2)

    log.info(
        "News Desk pipeline complete in %.1fs: %d raw, %d analyzed, %d signals, %d errors",
        stats["timing"]["total"],
        stats["raw_articles"],
        stats["filtered_articles"],
        stats["signals_published"],
        len(stats["errors"]),
    )

    return result
